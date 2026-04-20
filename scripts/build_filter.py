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
import sys
from tqdm import tqdm

from utils import DB_PATH, BUGSCPP_REPO, DATA_DIR, get_db_connection, run_bugscpp

WORKSPACES_DIR = DATA_DIR / "workspaces"


def workspace_path(project: str, bug_index: int) -> str:
    """Return the path bugscpp checks out to for a given bug."""
    return str(WORKSPACES_DIR / f"{project}-{bug_index}" / project / f"buggy-{bug_index}")


def build_bug(project: str, bug_index: int):
    """
    1. Checkout the buggy version into a local workspace.
    2. Build it inside the Docker container.
    Returns (success: bool, error_msg: str | None).
    """
    target = str(WORKSPACES_DIR / f"{project}-{bug_index}")

    # Step 1: checkout (idempotent — skips if already checked out)
    co = run_bugscpp(
        ["checkout", project, str(bug_index), "--buggy", "--target", target],
        timeout=120,
    )
    if co.returncode != 0:
        err = (co.stderr or co.stdout or "checkout failed")[:2000]
        return False, f"checkout: {err}"

    # Step 2: build from the checked-out workspace
    result = run_bugscpp(
        ["build", workspace_path(project, bug_index)],
        timeout=600,
    )

    if result.returncode == 0:
        return True, None
    else:
        err = (result.stderr or result.stdout or "unknown error")[:2000]
        return False, err


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

    success_count = fail_count = 0

    for row in tqdm(candidates, desc="Building", unit="bug"):
        bug_id, project, bug_index = row["bug_id"], row["project"], row["bug_index"]

        try:
            success, error_msg = build_bug(project, bug_index)
        except Exception as e:
            success, error_msg = False, f"exception: {e}"

        cur.execute(
            "INSERT INTO build_log (bug_id, success, error_msg) VALUES (?, ?, ?)",
            (bug_id, 1 if success else 0, error_msg),
        )
        con.commit()  # commit per-row so progress survives interruptions

        if success:
            success_count += 1
        else:
            fail_count += 1
            tqdm.write(f"  BUILD FAILED: {bug_id}: {error_msg[:120]}")

    con.close()
    print(f"[build_filter] Done: {success_count} built, {fail_count} failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true",
                        help="Skip bugs already recorded in build_log")
    parser.add_argument("--project", default=None,
                        help="Only build bugs from this project (e.g. libtiff)")
    args = parser.parse_args()
    run(resume=args.resume, project_filter=args.project)
