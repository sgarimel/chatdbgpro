"""
scripts/build_filter.py  —  Pipeline Step 2
Builds each candidate bug with debug symbols (-g -O0) inside its BugsC++
Docker container, logs results to build_log.

Bugs that fail to build are NOT deleted from test_cases; they just stay
with included_in_corpus = 0. Later steps skip bugs with no successful build.

Usage:
    python scripts/build_filter.py                     # serial, all candidates
    python scripts/build_filter.py --resume            # skip bugs already in build_log
    python scripts/build_filter.py --workers 4         # 4 parallel workers
    python scripts/build_filter.py --project libtiff   # one project only

Estimated time: 30–60 min serial, ~10–20 min with 4 workers. Run in tmux.
"""

import argparse
import subprocess

from _parallel import BugResult, run_pipeline_step
from utils import (
    DATA_DIR, DB_PATH, IssueTracker,
    get_db_connection, run_bugscpp,
)

WORKSPACES_DIR = DATA_DIR / "workspaces"


def workspace_path(project: str, bug_index: int) -> str:
    return str(WORKSPACES_DIR / f"{project}-{bug_index}" / project / f"buggy-{bug_index}")


def build_bug(project: str, bug_index: int):
    """
    Returns (success, error_msg, failure_kind). failure_kind is one of
    None / "checkout_failed" / "build_timeout" / "build_failed".
    """
    target = str(WORKSPACES_DIR / f"{project}-{bug_index}")

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


def process_one(row: dict, ctx: dict) -> BugResult:
    bug_id = row["bug_id"]
    project = row["project"]
    bug_index = row["bug_index"]
    resume = ctx["resume"]

    try:
        success, error_msg, kind = build_bug(project, bug_index)
    except Exception as e:
        success, error_msg, kind = False, f"exception: {e}", "exception"

    res = BugResult(bug_id=bug_id)
    res.db_updates.append((
        "INSERT INTO build_log (bug_id, success, error_msg) VALUES (?, ?, ?)",
        (bug_id, 1 if success else 0, error_msg),
    ))
    if not resume:
        res.db_updates.append((
            "DELETE FROM build_log WHERE bug_id = ? "
            "AND id NOT IN (SELECT MAX(id) FROM build_log WHERE bug_id = ?)",
            (bug_id, bug_id),
        ))

    if success:
        res.counters["success"] = 1
        res.log_lines.append(f"  [OK]   {bug_id}")
    else:
        res.counters["fail"] = 1
        res.issue_records.append(
            (kind or "build_failed", bug_id, (error_msg or "")[:120])
        )
        res.log_lines.append(f"  [FAIL:{kind}] {bug_id}: {(error_msg or '')[:120]}")

    return res


def run(db_path=DB_PATH, resume=False, project_filter=None, workers=1):
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

    rows = [dict(r) for r in candidates]
    if project_filter:
        rows = [r for r in rows if r["project"] == project_filter]

    if not rows:
        print("[build_filter] Nothing to build.")
        con.close()
        return

    print(f"[build_filter] Building {len(rows)} bug(s) "
          f"(resume={resume}, project_filter={project_filter}, workers={workers})")

    issues = IssueTracker("build_filter")
    counters = run_pipeline_step(
        bug_rows=rows,
        work_fn=process_one,
        ctx={"resume": resume},
        workers=workers,
        desc="Building",
        con=con,
        issue_tracker=issues,
    )
    con.close()

    success_count = counters.get("success", 0)
    fail_count = counters.get("fail", 0)
    print(f"[build_filter] Done: {success_count} built, {fail_count} failed "
          f"({100*success_count/max(1,len(rows)):.1f}% success)")
    issues.print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true",
                        help="Skip bugs already recorded in build_log")
    parser.add_argument("--project", default=None,
                        help="Only build bugs from this project (e.g. libtiff)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of parallel workers (default: 1 = serial)")
    args = parser.parse_args()
    run(resume=args.resume, project_filter=args.project, workers=args.workers)
