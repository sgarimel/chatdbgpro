"""
scripts/crash_filter.py  —  Pipeline Step 3
For each successfully-built bug, runs the crash-trigger command under GDB
three times inside the BugsC++ container. A bug passes the crash filter if
it crashes with the SAME catchable signal (SIGSEGV / SIGABRT / SIGFPE / SIGBUS)
on all three runs.

GDB is run in batch mode so it does not wait for user input.
Raw output per run is saved to data/filter_runs/<bug_id>_run<N>.txt
(these are NOT committed — add filter_runs/ to .gitignore).

Usage:
    python scripts/crash_filter.py            # process all build-successful bugs
    python scripts/crash_filter.py --resume   # skip bugs already in filter_log

Estimated time: 2–4 hours. Run in tmux.

NOTE on bugscpp exec:
    bugscpp exec <project> <index> -- <cmd>  runs <cmd> inside the bug's
    container with the correct working directory already set.
    If your bugscpp version does not have `exec`, see the TODO below and
    replace with `docker exec` against the running container.
"""

import argparse
import os
import re
import subprocess
from pathlib import Path

from tqdm import tqdm

from utils import (
    CATCHABLE_SIGNALS,
    DB_PATH,
    FILTER_RUNS_DIR,
    get_db_connection,
    run_bugscpp,
)

# GDB commands executed in batch mode for each run.
# `run` starts the program (bugscpp sets up argv via container env).
# `bt` prints backtrace after the crash.
GDB_BATCH_ARGS = [
    "-batch",
    "-ex", "set pagination off",
    "-ex", "set confirm off",
    "-ex", "run",
    "-ex", "bt",
    "-ex", "quit",
]


def parse_signal(gdb_output: str) -> str | None:
    """
    Extract the signal name from GDB batch output.
    GDB prints:
        Program received signal SIGSEGV, Segmentation fault.
        Program terminated with signal SIGABRT, Aborted.
    """
    for pattern in [
        r"Program received signal (\w+)",
        r"Program terminated with signal (\w+)",
    ]:
        m = re.search(pattern, gdb_output)
        if m:
            return m.group(1)
    return None


def run_gdb_in_container(bug_id: str, project: str, bug_index: int, run_number: int):
    """
    Run GDB inside the bugscpp container for this bug.
    Returns (crashed: bool, signal: str | None, exit_code: int, raw_path: str).

    bugscpp exec sets the working directory and trigger args automatically.
    The special token `@@` in the trigger command is replaced with the input
    file path by bugscpp (AFL-style fuzzing convention).
    """
    raw_path = FILTER_RUNS_DIR / f"{bug_id}_run{run_number}.txt"
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    # TODO: Verify that your bugscpp version supports `exec`.
    # If it does not, replace this block with:
    #   docker exec -it <container_name> gdb ...
    # You'll need to start the container first with `bugscpp start <project> <index>`.
    try:
        result = subprocess.run(
            ["bugscpp", "exec", project, str(bug_index), "--buggy",
             "--", "gdb"] + GDB_BATCH_ARGS,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raw_path.write_text("TIMEOUT")
        return False, "TIMEOUT", -1, str(raw_path)
    except Exception as e:
        raw_path.write_text(f"ERROR: {e}")
        return False, f"ERROR", -1, str(raw_path)

    output = result.stdout + result.stderr
    raw_path.write_text(output)

    signal = parse_signal(output)
    crashed = signal in CATCHABLE_SIGNALS
    return crashed, signal, result.returncode, str(raw_path)


def run(db_path=DB_PATH, resume=False):
    con = get_db_connection(db_path)
    cur = con.cursor()

    if resume:
        # Skip bugs that already have filter_log entries (all 3 runs)
        built = cur.execute("""
            SELECT t.bug_id, t.project, t.bug_index
            FROM test_cases t
            JOIN build_log b ON t.bug_id = b.bug_id
            WHERE b.success = 1
              AND (SELECT COUNT(*) FROM filter_log f WHERE f.bug_id = t.bug_id) < 3
        """).fetchall()
    else:
        built = cur.execute("""
            SELECT t.bug_id, t.project, t.bug_index
            FROM test_cases t
            JOIN build_log b ON t.bug_id = b.bug_id
            WHERE b.success = 1
        """).fetchall()

    if not built:
        print("[crash_filter] No bugs to process.")
        return

    eligible_count = 0

    for row in tqdm(built, desc="Crash filter", unit="bug"):
        bug_id, project, bug_index = row["bug_id"], row["project"], row["bug_index"]
        signals_seen = []

        for run_num in range(1, 4):
            crashed, signal, exit_code, raw_path = run_gdb_in_container(
                bug_id, project, bug_index, run_num
            )

            cur.execute(
                """
                INSERT INTO filter_log
                    (bug_id, run_number, crashed, signal, gdb_exit_code, raw_output_path)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (bug_id, run_num, 1 if crashed else 0, signal, exit_code, raw_path),
            )

            if crashed:
                signals_seen.append(signal)

        # Reproducible = same catchable signal on all 3 runs
        reproducible = (
            len(signals_seen) == 3
            and len(set(signals_seen)) == 1
            and signals_seen[0] in CATCHABLE_SIGNALS
        )

        if reproducible:
            cur.execute(
                """
                UPDATE test_cases
                SET crash_signal = ?, crash_reproducible = 1
                WHERE bug_id = ?
                """,
                (signals_seen[0], bug_id),
            )
            eligible_count += 1
        else:
            cur.execute(
                "UPDATE test_cases SET crash_reproducible = 0 WHERE bug_id = ?",
                (bug_id,),
            )

        con.commit()  # commit per-bug so progress survives interruptions

    con.close()
    print(f"[crash_filter] Done: {eligible_count} bugs crash reproducibly")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true",
                        help="Skip bugs already partially processed in filter_log")
    args = parser.parse_args()
    run(resume=args.resume)
