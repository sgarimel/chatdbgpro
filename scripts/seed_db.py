"""
scripts/seed_db.py  —  Pipeline Step 1
Reads BugsC++ metadata and inserts one row per bug into test_cases
with included_in_corpus = 0 (everything starts as a candidate).

Does NOT build or run anything — just populates the DB as a starting point.

Usage:
    python scripts/seed_db.py

Strategy:
    1. Try `bugscpp list --json` (CLI may or may not support this flag).
    2. Fall back to reading taxonomy JSON files from the cloned BugsC++ repo.
       Set BUGSCPP_REPO env var if the repo isn't at ../bugscpp/.
"""

import json
import sys

from utils import (
    DB_PATH,
    ensure_dirs,
    get_db_connection,
    load_bugscpp_metadata_from_taxonomy,
    run_bugscpp,
)


def get_all_bugs():
    """
    Attempt CLI-first, then taxonomy-file fallback.
    Returns a list of bug dicts (see utils.load_bugscpp_metadata_from_taxonomy for keys).
    """
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

    # --- Fallback: read taxonomy JSON files from the cloned repo ---
    bugs = load_bugscpp_metadata_from_taxonomy()
    print(f"[seed_db] Taxonomy files returned {len(bugs)} bugs")
    return bugs


def seed(db_path=DB_PATH):
    ensure_dirs()
    con = get_db_connection(db_path)
    cur = con.cursor()

    bugs = get_all_bugs()
    if not bugs:
        print("[seed_db] ERROR: no bug metadata found. Aborting.", file=sys.stderr)
        sys.exit(1)

    print(f"[seed_db] Inserting {len(bugs)} bug(s) into {db_path}")
    inserted = skipped = errored = 0
    missing_trigger = 0
    for bug in bugs:
        try:
            cur.execute(
                """
                INSERT OR IGNORE INTO test_cases
                    (bug_id, project, bug_index, docker_image, bug_type, cve_id, trigger_command)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{bug['project']}-{bug['index']}",
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

            if not bug.get("trigger_command"):
                missing_trigger += 1

        except Exception as e:
            errored += 1
            print(f"  ERROR inserting {bug}: {e}", file=sys.stderr)

    con.commit()
    con.close()
    print(f"[seed_db] Done: {inserted} inserted, {skipped} already present, "
          f"{errored} errored -> {db_path}")
    if missing_trigger:
        # Trigger command is the crash-inducing argv; without it crash_filter
        # launches GDB with no args and most bugs will not actually crash.
        print(f"[seed_db] WARNING: {missing_trigger}/{len(bugs)} bugs have no "
              f"trigger_command. crash_filter will be unable to reproduce crashes "
              f"for these. Inspect utils._extract_trigger and the BugsC++ "
              f"meta.json format for missing projects.")


if __name__ == "__main__":
    seed()
