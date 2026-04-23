"""Seed corpus.db with one row per BugsC++ defect.

Reads metadata from $BUGSCPP_REPO/bugscpp/taxonomy/<project>/meta.json
(no CLI list command exists). Per bug:

  1. Resolve trigger_argv:
       Tier A — extra_tests literal command (high fidelity, no shell wrapper)
       Tier B — common.test.commands template, rendered per case index
                (kept as `bash -c "..."`; lower fidelity)
  2. Read taxonomy/<project>/patch/<NNNN>-buggy.patch, reverse it to
     produce the developer fix patch (buggy -> fixed), and write it to
     data/patches/<bug_id>.diff where bug_id = "<project>-<index>".
  3. Parse hunks to derive patch_first_file / patch_first_line /
     patch_line_ranges_json (line numbers are in BUGGY-tree coordinates).

All ground-truth data is populated here, before any docker / build work.
Idempotent: rows are upserted by bug_id.
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

from pipeline2.parse_patch import parse_unified_diff, reverse_patch

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "corpus.db"
SCHEMA = REPO_ROOT / "pipeline2" / "schema.sql"
PATCHES_DIR = REPO_ROOT / "data" / "patches"
WORKSPACES_DIR = REPO_ROOT / "data" / "workspaces"

SKIP_PROJECTS = {"example"}
CPP_PROJECTS = {"cpp_peglib", "cppcheck", "exiv2", "yaml_cpp"}

_SHELL_METACHARS = set("$`\\&|;<>()*?[]{}~!#")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def bugscpp_repo_dir() -> Path:
    repo = os.environ.get("BUGSCPP_REPO")
    if repo:
        return Path(repo)
    return REPO_ROOT.parent / "bugscpp"


def bugscpp_taxonomy_dir() -> Path:
    return bugscpp_repo_dir() / "bugscpp" / "taxonomy"


def language_for(project: str) -> str:
    return "cpp" if project in CPP_PROJECTS or "cpp" in project else "c"


def gdb_image_for(project: str) -> str:
    return f"chatdbgpro/gdb-{project}:latest"


def bug_id_for(project: str, idx: int) -> str:
    return f"{project}-{idx}"


def workspace_path_for(project: str, idx: int) -> Path:
    """Canonical buggy workspace. Matches PipelineArchive/scripts/utils.py::get_workspace_dir."""
    return WORKSPACES_DIR / f"{project}-{idx}" / project / f"buggy-{idx}"


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
    for variants in defect.get("extra_tests") or []:
        for test in variants:
            if not test.get("is_pass", True):
                lines = test.get("lines") or []
                if lines:
                    return tokenize_trigger(lines[0])

    for case_raw in defect.get("case") or []:
        try:
            case_index = int(case_raw)
        except (TypeError, ValueError):
            continue
        rendered = render_template(common_test_commands, case_index)
        if rendered:
            return tokenize_trigger(rendered)

    return []


def resolve_patch(project: str, idx: int) -> dict:
    """Read taxonomy buggy.patch, return fix patch + parsed location fields.

    Returns dict with: patch_diff, patch_files_json, patch_path,
    patch_first_file, patch_first_line, patch_line_ranges_json. Any field
    may be None if the patch is missing or yields no hunks.
    """
    patch_file = (
        bugscpp_taxonomy_dir() / project / "patch" / f"{idx:04d}-buggy.patch"
    )
    if not patch_file.exists():
        return {
            "patch_diff": None,
            "patch_files_json": None,
            "patch_path": None,
            "patch_first_file": None,
            "patch_first_line": None,
            "patch_line_ranges_json": None,
        }

    buggy_patch = patch_file.read_text(encoding="utf-8", errors="replace")
    fix_patch = reverse_patch(buggy_patch)
    ranges = parse_unified_diff(buggy_patch)  # line numbers in BUGGY tree

    files = sorted({r["file"] for r in ranges})
    first_file = ranges[0]["file"] if ranges else None
    first_line = ranges[0]["start"] if ranges else None

    bug_id = bug_id_for(project, idx)
    PATCHES_DIR.mkdir(parents=True, exist_ok=True)
    out_file = PATCHES_DIR / f"{bug_id}.diff"
    # write_bytes to avoid Windows CRLF translation — workspace source files
    # are LF, so the patch must be LF for `git apply` to match context lines.
    out_file.write_bytes(fix_patch.encode("utf-8"))

    return {
        "patch_diff": fix_patch,
        "patch_files_json": json.dumps(files) if files else None,
        "patch_path": f"patches/{bug_id}.diff",
        "patch_first_file": first_file,
        "patch_first_line": first_line,
        "patch_line_ranges_json": json.dumps(ranges) if ranges else None,
    }


def load_taxonomy() -> list[dict]:
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
            patch_fields = resolve_patch(project, idx)
            row = {
                "bug_id":            bug_id_for(project, idx),
                "project":           project,
                "bug_index":         idx,
                "language":          language_for(project),
                "bug_type":          extract_bug_type(defect.get("tags") or []),
                "cve_id":            extract_cve(defect.get("description")),
                "gdb_image":         gdb_image_for(project),
                "trigger_argv_json": json.dumps(argv) if argv else None,
                "workspace_path":    str(workspace_path_for(project, idx)),
                **patch_fields,
            }
            bugs.append(row)
    return bugs


_SEED_COLUMNS = (
    "project", "bug_index", "language", "bug_type", "cve_id",
    "gdb_image", "trigger_argv_json",
    "workspace_path",
    "patch_diff", "patch_files_json", "patch_path",
    "patch_first_file", "patch_first_line", "patch_line_ranges_json",
)


def upsert(con: sqlite3.Connection, rows: list[dict]) -> tuple[int, int]:
    cur = con.cursor()
    inserted = updated = 0
    assignments = ", ".join(f"{c} = ?" for c in _SEED_COLUMNS)
    insert_cols = "bug_id, " + ", ".join(_SEED_COLUMNS)
    insert_placeholders = ", ".join(["?"] * (len(_SEED_COLUMNS) + 1))

    for r in rows:
        existing = cur.execute(
            "SELECT 1 FROM bugs WHERE bug_id = ?", (r["bug_id"],),
        ).fetchone()
        values = tuple(r[c] for c in _SEED_COLUMNS)
        if existing:
            cur.execute(
                f"UPDATE bugs SET {assignments} WHERE bug_id = ?",
                values + (r["bug_id"],),
            )
            updated += 1
        else:
            cur.execute(
                f"INSERT INTO bugs ({insert_cols}) VALUES ({insert_placeholders})",
                (r["bug_id"],) + values,
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
    with_patch = con.execute(
        "SELECT COUNT(*) FROM bugs WHERE patch_first_file IS NOT NULL",
    ).fetchone()[0]
    con.close()

    print(
        f"[seed] {inserted} inserted, {updated} updated; "
        f"{total} total, {with_trigger} with trigger_argv, "
        f"{with_patch} with parsed patch"
    )


if __name__ == "__main__":
    main()
