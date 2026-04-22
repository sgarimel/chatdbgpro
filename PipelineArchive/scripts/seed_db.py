"""
scripts/seed_db.py  —  Pipeline Step 1
Reads BugsC++ metadata and inserts one row per bug into test_cases
with included_in_corpus = 0 (everything starts as a candidate).

Does NOT build or run anything — just populates the DB as a starting point.

Usage:
    python scripts/seed_db.py
    python scripts/seed_db.py --resolve-case-triggers

Strategy:
    1. Try `bugscpp list --json` (CLI may or may not support this flag).
    2. Fall back to reading taxonomy JSON files from the cloned BugsC++ repo.
       Set BUGSCPP_REPO env var if the repo isn't at ../bugscpp/.

When --resolve-case-triggers is set, every bug whose meta.json uses the
case[N] convention (instead of literal extra_tests) is also passed
through the trigger resolver in utils.resolve_case_trigger; one row per
attempted resolution is appended to trigger_resolution_log so the
operator can audit fidelity (resolved vs. wrapped vs. unsupported).
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from utils import (
    DB_PATH,
    PROJECT_ROOT,
    ensure_dirs,
    get_db_connection,
    load_bugscpp_metadata_from_taxonomy,
    run_bugscpp,
)


def ensure_schema(con):
    """Create required tables if the DB is fresh.

    seed_db is the first script to touch corpus.db, so it owns
    schema bootstrap. Schema is idempotent (CREATE TABLE IF NOT EXISTS).
    """
    schema_path = PROJECT_ROOT / "schema.sql"
    if not schema_path.exists():
        return
    con.executescript(schema_path.read_text())


def get_all_bugs():
    """
    Attempt CLI-first, then taxonomy-file fallback.
    Returns a list of bug dicts (see utils.load_bugscpp_metadata_from_taxonomy for keys).
    """
    return get_all_bugs_with_options()


def get_all_bugs_with_options(resolve_case_triggers: bool = False):
    """
    Attempt CLI-first, then taxonomy-file fallback.
    When resolve_case_triggers=True, read taxonomy directly so case-format
    trigger extraction can inspect test harness metadata.
    """
    if not resolve_case_triggers:
        # --- Try the CLI first ---
        try:
            result = run_bugscpp(["list", "--json"], timeout=30, check=True)
            bugs = json.loads(result.stdout)
            # Normalize: CLI may return different key names
            normalized = []
            for b in bugs:
                idx_raw = b.get("index") if b.get("index") is not None else b.get("id")
                if idx_raw is None or b.get("project") is None:
                    print(f"[seed_db] Skipping malformed CLI entry: {b}", file=sys.stderr)
                    continue
                idx = int(idx_raw)
                normalized.append({
                    "project":         b["project"],
                    "index":           idx,
                    "bug_type":        b.get("type") or b.get("bug_type"),
                    "cve_id":          b.get("cve") or b.get("cve_id"),
                    "trigger_command": b.get("trigger") or b.get("trigger_command"),
                    "docker_image":    f"bugscpp/{b['project']}:{idx}",
                })
            print(f"[seed_db] CLI returned {len(normalized)} bugs")
            return normalized

        except Exception as e:
            print(f"[seed_db] CLI fallback triggered ({e}); reading taxonomy files directly…")
    else:
        print("[seed_db] --resolve-case-triggers set; reading taxonomy metadata directly.")

    # --- Fallback: read taxonomy JSON files from the cloned repo ---
    bugs = load_bugscpp_metadata_from_taxonomy(resolve_case_triggers=resolve_case_triggers)
    print(f"[seed_db] Taxonomy files returned {len(bugs)} bugs")
    return bugs


def seed(db_path=DB_PATH, resolve_case_triggers: bool = False):
    ensure_dirs()
    con = get_db_connection(db_path)
    ensure_schema(con)
    cur = con.cursor()

    bugs = get_all_bugs_with_options(resolve_case_triggers=resolve_case_triggers)
    if not bugs:
        print("[seed_db] ERROR: no bug metadata found. Aborting.", file=sys.stderr)
        sys.exit(1)

    print(f"[seed_db] Inserting {len(bugs)} bug(s) into {db_path}")
    inserted = skipped = errored = 0
    trigger_filled = 0
    missing_trigger = 0
    resolution_breakdown: dict[str, int] = {}
    for bug in bugs:
        bug_id = f"{bug['project']}-{bug['index']}"
        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO test_cases
                    (bug_id, project, bug_index, docker_image, bug_type, cve_id, trigger_command)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bug_id,
                    bug["project"],
                    bug["index"],
                    bug["docker_image"],
                    bug.get("bug_type"),
                    bug.get("cve_id"),
                    bug.get("trigger_command"),
                ),
            )
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1  # already in DB from a previous run
                if bug.get("trigger_command"):
                    cur.execute(
                        "UPDATE test_cases "
                        "SET trigger_command = ? "
                        "WHERE bug_id = ? AND trigger_command IS NULL",
                        (bug["trigger_command"], bug_id),
                    )
                    if cur.rowcount:
                        trigger_filled += 1

            if not bug.get("trigger_command"):
                missing_trigger += 1

            resolution = bug.get("trigger_resolution")
            if resolution is not None:
                cur.execute(
                    """
                    INSERT INTO trigger_resolution_log
                        (bug_id, harness, case_index, status, reason)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        bug_id,
                        resolution.harness,
                        resolution.case_index,
                        resolution.status,
                        resolution.reason,
                    ),
                )
                key = f"{resolution.harness}:{resolution.status}"
                resolution_breakdown[key] = resolution_breakdown.get(key, 0) + 1

        except Exception as e:
            errored += 1
            print(f"  ERROR inserting {bug_id}: {e}", file=sys.stderr)

    con.commit()
    con.close()
    print(f"[seed_db] Done: {inserted} inserted, {skipped} already present, "
          f"{trigger_filled} trigger(s) backfilled, {errored} errored -> {db_path}")
    if resolution_breakdown:
        print("[seed_db] Trigger resolution breakdown (harness:status):")
        for key, n in sorted(resolution_breakdown.items(), key=lambda kv: -kv[1]):
            print(f"  {key:30s} {n:4d}")
    if missing_trigger:
        # Trigger command is the crash-inducing argv; without it crash_filter
        # launches GDB with no args and most bugs will not actually crash.
        print(f"[seed_db] WARNING: {missing_trigger}/{len(bugs)} bugs have no "
              f"trigger_command. crash_filter will be unable to reproduce crashes "
              f"for these. Inspect utils._extract_trigger and the BugsC++ "
              f"meta.json format for missing projects. For case[N] projects, "
              f"re-run with --resolve-case-triggers (you may need to build "
              f"workspaces first to get high-fidelity ctest argv).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH),
                        help="Path to sqlite DB (default: data/corpus.db)")
    parser.add_argument("--resolve-case-triggers", action="store_true",
                        help="Attempt to resolve case[N] triggers (currently ctest) "
                             "using already-built workspaces in data/workspaces.")
    args = parser.parse_args()
    seed(db_path=args.db, resolve_case_triggers=args.resolve_case_triggers)
