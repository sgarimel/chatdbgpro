"""
scripts/build_filter.py  —  Pipeline Step 2
Builds each candidate bug with debug symbols (-g -O0) inside its BugsC++
Docker container, logs results to build_log.

Bugs that fail to build are NOT deleted from test_cases; they just stay
with included_in_corpus = 0. Later steps skip bugs with no successful build.

Usage:
    python scripts/build_filter.py             # build all candidates
    python scripts/build_filter.py --resume    # skip bugs already in build_log

Estimated time: 30–60 min for all 209 bugs. Run in tmux.
"""

import argparse
import subprocess
import sys
from tqdm import tqdm

from utils import (
    DB_PATH, BUGSCPP_REPO, DATA_DIR, IssueTracker,
    get_db_connection, run_bugscpp,
)

WORKSPACES_DIR = DATA_DIR / "workspaces"


def workspace_path(project: str, bug_index: int) -> str:
    """Return the path bugscpp checks out to for a given bug."""
    return str(WORKSPACES_DIR / f"{project}-{bug_index}" / project / f"buggy-{bug_index}")


def build_bug(project: str, bug_index: int):
    """
    1. Checkout the buggy version into a local workspace.
    2. Build it inside the Docker container.
    Returns (success, error_msg, failure_kind). failure_kind is one of
    None / "checkout_failed" / "build_timeout" / "build_failed".
    """
    target = str(WORKSPACES_DIR / f"{project}-{bug_index}")

    # Step 1: checkout (idempotent — skips if already checked out)
    try:
        co = run_bugscpp(
            ["checkout", project, str(bug_index), "--buggy", "--target", target],
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, "checkout timed out after 120s", "checkout_failed"

    if co.returncode != 0:
        err = (co.stderr or co.stdout or "checkout failed")[:2000]
        return False, f"checkout: {err}", "checkout_failed"

    # Step 2: build from the checked-out workspace
    try:
        result = run_bugscpp(
            ["build", workspace_path(project, bug_index)],
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return False, "build timed out after 600s", "build_timeout"

    if result.returncode == 0:
        return True, None, None
    err = (result.stderr or result.stdout or "unknown error")[:2000]
    return False, err, "build_failed"


def run(db_path=DB_PATH, resume=False, project_filter=None):
    con = get_db_connection(db_path)
    cur = con.cursor()

    if resume:
        candidates = cur.execute("""
            SELECT t.bug_id, t.project, t.bug_index
            FROM test_cases t
            WHERE t.bug_id NOT IN (SELECT bug_id FROM build_log)
        """).fetchall()
    else:
        candidates = cur.execute(
            "SELECT bug_id, project, bug_index FROM test_cases"
        ).fetchall()

    if project_filter:
        candidates = [r for r in candidates if r["project"] == project_filter]

    if not candidates:
        print("[build_filter] Nothing to build.")
        return

    print(f"[build_filter] Building {len(candidates)} bug(s) "
          f"(resume={resume}, project_filter={project_filter})")

    issues = IssueTracker("build_filter")
    success_count = fail_count = 0

    for row in tqdm(candidates, desc="Building", unit="bug"):
        bug_id, project, bug_index = row["bug_id"], row["project"], row["bug_index"]

        try:
            success, error_msg, kind = build_bug(project, bug_index)
        except Exception as e:
            success, error_msg, kind = False, f"exception: {e}", "exception"

        cur.execute(
            "INSERT INTO build_log (bug_id, success, error_msg) VALUES (?, ?, ?)",
            (bug_id, 1 if success else 0, error_msg),
        )
        con.commit()  # commit per-row so progress survives interruptions

        # In non-resume mode, prune any prior build_log rows for this bug
        # so queries joining on build_log.success don't see stale duplicates.
        if not resume:
            cur.execute("DELETE FROM build_log WHERE bug_id = ? AND id NOT IN (SELECT MAX(id) FROM build_log WHERE bug_id = ?)", (bug_id, bug_id))

        if success:
            success_count += 1
            tqdm.write(f"  [OK]   {bug_id}")
        else:
            fail_count += 1
            issues.record(kind or "build_failed", bug_id, (error_msg or "")[:120])
            tqdm.write(f"  [FAIL:{kind}] {bug_id}: {(error_msg or '')[:120]}")

    con.close()
    print(f"[build_filter] Done: {success_count} built, {fail_count} failed "
          f"({100*success_count/max(1,len(candidates)):.1f}% success)")
    issues.print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true",
                        help="Skip bugs already recorded in build_log")
    parser.add_argument("--project", default=None,
                        help="Only build bugs from this project (e.g. libtiff)")
    args = parser.parse_args()
    run(resume=args.resume, project_filter=args.project)
