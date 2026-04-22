"""Seed corpus.db with one row per BugsC++ defect.

Reads metadata from $BUGSCPP_REPO/bugscpp/taxonomy/<project>/meta.json
(no CLI list command exists). Resolves an initial trigger argv per defect:

  Tier A — extra_tests literal command (high fidelity, no shell wrapper)
  Tier B — common.test.commands template, rendered per case index
           (kept as `bash -c "..."`; lower fidelity)

ctest-json resolution requires a built workspace and is deferred to
build_and_probe.py.

Idempotent: rows are upserted by case_id.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "corpus.db"
SCHEMA = REPO_ROOT / "pipeline2" / "schema.sql"

SKIP_PROJECTS = {"example"}
CPP_PROJECTS = {"cpp_peglib", "cppcheck", "exiv2", "yaml_cpp"}

_SHELL_METACHARS = set("$`\\&|;<>()*?[]{}~!#")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def bugscpp_taxonomy_dir() -> Path:
    repo = os.environ.get("BUGSCPP_REPO")
    if repo:
        return Path(repo) / "bugscpp" / "taxonomy"
    return REPO_ROOT.parent / "bugscpp" / "bugscpp" / "taxonomy"


def language_for(project: str) -> str:
    return "cpp" if project in CPP_PROJECTS or "cpp" in project else "c"


def gdb_image_for(project: str) -> str:
    return f"chatdbgpro/gdb-{project}:latest"


def case_id_for(project: str, idx: int) -> str:
    return f"bugscpp-{project}-{idx}"


def extract_bug_type(tags: list[str]) -> str:
    s = set(tags or [])
    if "use-after-free" in s:    return "use_after_free"
    if "null-deref" in s:        return "null_deref"
    if "stack-overflow" in s:    return "stack_overflow"
    if "buffer-overflow" in s:   return "buffer_overflow"
    if "memory-error" in s:      return "memory_error"
    return "other"


def extract_cve(description: str | None) -> str | None:
    if not description:
        return None
    m = re.search(r"CVE-\d{4}-\d+", description)
    return m.group(0) if m else None


def unwrap_bash_c(argv: list[str]) -> list[str]:
    """Unwrap ['bash','-c','<safe inner>'] so gdb can attach directly."""
    if len(argv) != 3 or argv[0] != "bash" or argv[1] != "-c":
        return argv
    inner = argv[2]
    if any(c in _SHELL_METACHARS for c in inner):
        return argv
    try:
        inner_argv = shlex.split(inner)
    except ValueError:
        return argv
    if not inner_argv or _ENV_ASSIGN_RE.match(inner_argv[0]):
        return argv
    return inner_argv


def tokenize_trigger(cmd: str | None) -> list[str]:
    if not cmd:
        return []
    try:
        return unwrap_bash_c(shlex.split(cmd))
    except ValueError:
        return []


def render_template(commands: list[dict] | None, case_index: int) -> str | None:
    """Render common.test.commands with $(cat DPP_TEST_INDEX) substitution."""
    if not commands:
        return None
    lines: list[str] = []
    for cmd in commands:
        for line in cmd.get("lines", []) or []:
            if line.strip():
                lines.append(line)
    if not lines:
        return None
    rendered = " && ".join(lines)
    rendered = rendered.replace("$(cat DPP_TEST_INDEX)", str(case_index))
    rendered = rendered.replace("$(cat ../DPP_TEST_INDEX)", str(case_index))
    rendered = rendered.replace("@DPP_PARALLEL_BUILD@", "1")
    return f"bash -c {shlex.quote(rendered)}"


def resolve_trigger_argv(
    defect: dict,
    common_test_commands: list[dict] | None,
) -> list[str]:
    """Tier A: extra_tests; Tier B: templated. Returns argv (possibly empty)."""
    # Tier A: literal failing test command
    for variants in defect.get("extra_tests") or []:
        for test in variants:
            if not test.get("is_pass", True):
                lines = test.get("lines") or []
                if lines:
                    return tokenize_trigger(lines[0])

    # Tier B: render template per case index, take first that renders
    for case_raw in defect.get("case") or []:
        try:
            case_index = int(case_raw)
        except (TypeError, ValueError):
            continue
        rendered = render_template(common_test_commands, case_index)
        if rendered:
            # Keep wrapped — has shell metachars (&&, $(...))
            return tokenize_trigger(rendered)

    return []


def load_taxonomy() -> list[dict]:
    """Walk the taxonomy tree, return flat list of seed-row dicts."""
    tax = bugscpp_taxonomy_dir()
    if not tax.exists():
        sys.exit(
            f"BugsC++ taxonomy not found: {tax}\n"
            "Set BUGSCPP_REPO to the path of the cloned bugscpp repo."
        )

    bugs = []
    for proj_dir in sorted(tax.iterdir()):
        if not proj_dir.is_dir() or proj_dir.name in SKIP_PROJECTS:
            continue
        meta_file = proj_dir / "meta.json"
        if not meta_file.exists():
            continue

        project = proj_dir.name
        with open(meta_file, encoding="utf-8") as f:
            meta = json.load(f)
        common = meta.get("common") or {}
        common_test_commands = ((common.get("test") or {}).get("commands"))

        for defect in meta.get("defects") or []:
            try:
                idx = int(defect["id"])
            except (KeyError, TypeError, ValueError):
                continue

            argv = resolve_trigger_argv(defect, common_test_commands)
            bugs.append({
                "case_id":           case_id_for(project, idx),
                "project":           project,
                "bug_index":         idx,
                "language":          language_for(project),
                "bug_type":          extract_bug_type(defect.get("tags") or []),
                "cve_id":            extract_cve(defect.get("description")),
                "gdb_image":         gdb_image_for(project),
                "trigger_argv_json": json.dumps(argv) if argv else None,
            })
    return bugs


def upsert(con: sqlite3.Connection, rows: list[dict]) -> tuple[int, int]:
    cur = con.cursor()
    inserted = updated = 0
    for r in rows:
        existing = cur.execute(
            "SELECT 1 FROM bugs WHERE case_id = ?", (r["case_id"],),
        ).fetchone()
        if existing:
            cur.execute(
                """UPDATE bugs SET
                       project           = ?,
                       bug_index         = ?,
                       language          = ?,
                       bug_type          = ?,
                       cve_id            = ?,
                       gdb_image         = ?,
                       trigger_argv_json = ?
                   WHERE case_id = ?""",
                (r["project"], r["bug_index"], r["language"], r["bug_type"],
                 r["cve_id"], r["gdb_image"], r["trigger_argv_json"],
                 r["case_id"]),
            )
            updated += 1
        else:
            cur.execute(
                """INSERT INTO bugs
                   (case_id, project, bug_index, language, bug_type, cve_id,
                    gdb_image, trigger_argv_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["case_id"], r["project"], r["bug_index"], r["language"],
                 r["bug_type"], r["cve_id"], r["gdb_image"],
                 r["trigger_argv_json"]),
            )
            inserted += 1
    con.commit()
    return inserted, updated


def ensure_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.executescript(SCHEMA.read_text())
    con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB))
    args = p.parse_args()

    db_path = Path(args.db)
    ensure_schema(db_path)
    bugs = load_taxonomy()

    con = sqlite3.connect(str(db_path))
    inserted, updated = upsert(con, bugs)
    total = con.execute("SELECT COUNT(*) FROM bugs").fetchone()[0]
    with_trigger = con.execute(
        "SELECT COUNT(*) FROM bugs WHERE trigger_argv_json IS NOT NULL",
    ).fetchone()[0]
    con.close()

    print(f"[seed] {inserted} inserted, {updated} updated; "
          f"{total} total, {with_trigger} with trigger_argv")


if __name__ == "__main__":
    main()
