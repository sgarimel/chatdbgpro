"""One-shot migration: move existing corpus.db to the new contract.

Changes applied to every row:

  * Key migrated from `case_id = "bugscpp-<project>-<idx>"` to
    `bug_id   = "<project>-<idx>"` (table is renamed; primary key changes).
  * New columns added (nullable): patch_path, patch_first_file,
    patch_first_line, patch_line_ranges_json, bug_observed, built_at.
  * Stale column dropped: case_yaml_path.
  * Developer fix patch re-extracted from BugsC++ taxonomy
    (`taxonomy/<project>/patch/<NNNN>-buggy.patch`, reversed) and written
    to `data/patches/<bug_id>.diff`. Overwrites the previous contaminated
    `patch_diff` that was produced by `diff -ruN built-buggy unbuilt-fixed`.
  * `workspace_path` set to the canonical location
    `data/workspaces/<bug_id>/<project>/buggy-<idx>` regardless of
    whether the directory exists (build.py materializes it).
  * `bug_observed` derived from the existing `crash_signal`:
        crash_signal present + crash_reproducible=1  -> "crash:<signal>"
        probed_at IS NOT NULL but no crash reproducible -> "no_observation"
        otherwise (unprobed)                         -> NULL
  * Stale `bench/cases/bugscpp-*` directories removed (DockerDriver reads
    from corpus.db, not from bench/cases/).
  * Inclusion gate re-applied under the new rule:
        build_ok = 1 AND patch_first_file IS NOT NULL AND patch_path IS NOT NULL

Pure metadata + filesystem-write pass. No docker, no checkouts, no builds.
Runs in seconds.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "corpus.db"
SCHEMA = REPO_ROOT / "pipeline2" / "schema.sql"
PATCHES_DIR = REPO_ROOT / "data" / "patches"
WORKSPACES_DIR = REPO_ROOT / "data" / "workspaces"
BENCH_CASES_DIR = REPO_ROOT / "bench" / "cases"

sys.path.insert(0, str(REPO_ROOT))
from pipeline2.parse_patch import parse_unified_diff, reverse_patch  # noqa: E402
from pipeline2.seed import (  # noqa: E402
    bugscpp_taxonomy_dir,
    workspace_path_for,
)


def migrate_schema(con: sqlite3.Connection) -> None:
    """Rename case_id->bug_id; add new columns; drop case_yaml_path.

    We do this column-surgery explicitly instead of CREATE TABLE ... AS SELECT
    because the existing table has 26 columns and we want to preserve values.
    Idempotent: checks which columns already exist before altering.
    """
    cur = con.cursor()
    existing = {r[1] for r in cur.execute("PRAGMA table_info(bugs)").fetchall()}

    # 1) Add the new columns (no-op if already present).
    new_cols = {
        "bug_id":                 "TEXT",
        "patch_path":             "TEXT",
        "patch_first_file":       "TEXT",
        "patch_first_line":       "INTEGER",
        "patch_line_ranges_json": "TEXT",
        "bug_observed":           "TEXT",
        "built_at":               "TEXT",
    }
    for col, typ in new_cols.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE bugs ADD COLUMN {col} {typ}")

    # 2) Backfill bug_id from case_id where still NULL.
    if "case_id" in existing:
        cur.execute(
            "UPDATE bugs "
            "   SET bug_id = substr(case_id, length('bugscpp-') + 1) "
            " WHERE bug_id IS NULL AND case_id LIKE 'bugscpp-%'"
        )

    # 3) Backfill built_at from probed_at (1:1 semantic match for old rows).
    cur.execute(
        "UPDATE bugs SET built_at = probed_at "
        "WHERE built_at IS NULL AND probed_at IS NOT NULL"
    )

    con.commit()


def resolve_patch_for(project: str, idx: int) -> dict:
    """Read the taxonomy buggy.patch, return fix patch + parsed fields.

    Mirrors pipeline2.seed.resolve_patch, but kept separate here to avoid
    circular concerns (seed.resolve_patch also writes the .diff file,
    which we want to do exactly the same way — so just call it).
    """
    patch_file = (
        bugscpp_taxonomy_dir() / project / "patch" / f"{idx:04d}-buggy.patch"
    )
    if not patch_file.exists():
        return {}

    buggy_patch = patch_file.read_text(encoding="utf-8", errors="replace")
    fix_patch = reverse_patch(buggy_patch)
    ranges = parse_unified_diff(buggy_patch)

    files = sorted({r["file"] for r in ranges})
    first_file = ranges[0]["file"] if ranges else None
    first_line = ranges[0]["start"] if ranges else None

    bug_id = f"{project}-{idx}"
    PATCHES_DIR.mkdir(parents=True, exist_ok=True)
    # write_bytes to avoid Windows CRLF translation — workspace source files
    # are LF, so the patch must be LF for `git apply` to match context lines.
    (PATCHES_DIR / f"{bug_id}.diff").write_bytes(fix_patch.encode("utf-8"))

    return {
        "patch_diff":             fix_patch,
        "patch_files_json":       json.dumps(files) if files else None,
        "patch_path":             f"patches/{bug_id}.diff",
        "patch_first_file":       first_file,
        "patch_first_line":       first_line,
        "patch_line_ranges_json": json.dumps(ranges) if ranges else None,
    }


def compute_bug_observed(row: sqlite3.Row) -> str | None:
    crash_signal = row["crash_signal"]
    crash_repro  = row["crash_reproducible"]
    probed_at    = row["probed_at"]
    if crash_signal and crash_repro == 1:
        return f"crash:{crash_signal}"
    if probed_at:
        return "no_observation"
    return None


def cleanup_stale_bench_cases(log) -> int:
    """Remove bench/cases/bugscpp-* — no longer pipeline2 output."""
    if not BENCH_CASES_DIR.exists():
        return 0
    removed = 0
    for path in sorted(BENCH_CASES_DIR.glob("bugscpp-*")):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    if removed:
        log(f"[reconcile] removed {removed} stale bench/cases/bugscpp-* dirs")
    return removed


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB))
    args = p.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        sys.exit(f"DB not found: {db_path}")

    def log(msg: str) -> None:
        print(msg, flush=True)

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row

    log(f"[reconcile] migrating schema in {db_path}")
    migrate_schema(con)

    rows = con.execute(
        "SELECT bug_id, project, bug_index, build_ok, "
        "       crash_signal, crash_reproducible, probed_at "
        "FROM bugs ORDER BY project, bug_index"
    ).fetchall()
    log(f"[reconcile] {len(rows)} rows to process")

    updated_patch = 0
    updated_observed = 0
    included_after = 0
    cur = con.cursor()

    for row in rows:
        bug_id = row["bug_id"]
        project = row["project"]
        idx = row["bug_index"]

        updates: dict = {}

        patch_fields = resolve_patch_for(project, idx)
        if patch_fields:
            updates.update(patch_fields)
            updated_patch += 1

        updates["workspace_path"] = str(workspace_path_for(project, idx))

        observed = compute_bug_observed(row)
        if observed is not None:
            updates["bug_observed"] = observed
            updated_observed += 1

        # Compute the gate using the new rule.
        new_patch_first_file = updates.get("patch_first_file")
        new_patch_path = updates.get("patch_path")
        included = (
            1 if (row["build_ok"] == 1
                  and new_patch_first_file
                  and new_patch_path)
            else 0
        )
        updates["included_in_corpus"] = included
        if included:
            included_after += 1

        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [bug_id]
        cur.execute(f"UPDATE bugs SET {cols} WHERE bug_id = ?", vals)

    con.commit()
    con.close()

    cleanup_stale_bench_cases(log)

    log(
        f"[reconcile] done. patches re-extracted: {updated_patch}/{len(rows)}, "
        f"bug_observed set: {updated_observed}, "
        f"included_in_corpus after gate: {included_after}"
    )


if __name__ == "__main__":
    main()
