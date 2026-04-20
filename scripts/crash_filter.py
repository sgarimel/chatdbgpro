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
    IssueTracker,
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


def run_gdb_in_container(
    bug_id: str, project: str, bug_index: int, run_number: int,
    trigger_command: str | None,
):
    """
    Run GDB inside the bugscpp container for this bug.
    Returns (crashed, signal, exit_code, raw_path, error_kind).
    error_kind is None on non-error paths, else: "timeout" | "bugscpp_error".

    The trigger_command comes from BugsC++ metadata (seed_db.py populates it).
    GDB's `run` reads args from `--args` on the gdb invocation; we append the
    tokenised trigger so the program actually executes with the crash-inducing
    input. Without this, `run` launches the program with no args and most bugs
    will silently exit 0 instead of crashing.
    """
    raw_path = FILTER_RUNS_DIR / f"{bug_id}_run{run_number}.txt"
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    gdb_cmd = list(GDB_BATCH_ARGS)
    if trigger_command:
        # Pass trigger tokens after `--args PROGRAM [ARGV...]`. bugscpp `exec`
        # runs the command inside the container's working directory, so the
        # trigger string (e.g. "./tiff2pdf input.tif /dev/null") is split on
        # whitespace and handed to GDB as the inferior's argv.
        import shlex
        gdb_cmd += ["--args"] + shlex.split(trigger_command)

    try:
        result = subprocess.run(
            ["bugscpp", "exec", project, str(bug_index), "--buggy",
             "--", "gdb"] + gdb_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raw_path.write_text("TIMEOUT")
        return False, "TIMEOUT", -1, str(raw_path), "timeout"
    except FileNotFoundError as e:
        raw_path.write_text(f"FileNotFoundError: {e}")
        return False, None, -1, str(raw_path), "bugscpp_error"
    except Exception as e:
        raw_path.write_text(f"ERROR: {e}")
        return False, None, -1, str(raw_path), "bugscpp_error"

    output = result.stdout + result.stderr
    raw_path.write_text(output)

    signal = parse_signal(output)
    crashed = signal in CATCHABLE_SIGNALS
    return crashed, signal, result.returncode, str(raw_path), None


def run(db_path=DB_PATH, resume=False):
    con = get_db_connection(db_path)
    cur = con.cursor()

    if resume:
        # Skip bugs that already have filter_log entries (all 3 runs)
        built = cur.execute("""
            SELECT t.bug_id, t.project, t.bug_index, t.trigger_command
            FROM test_cases t
            JOIN build_log b ON t.bug_id = b.bug_id
            WHERE b.success = 1
              AND (SELECT COUNT(*) FROM filter_log f WHERE f.bug_id = t.bug_id) < 3
        """).fetchall()
    else:
        built = cur.execute("""
            SELECT t.bug_id, t.project, t.bug_index, t.trigger_command
            FROM test_cases t
            JOIN build_log b ON t.bug_id = b.bug_id
            WHERE b.success = 1
        """).fetchall()

    if not built:
        print("[crash_filter] No bugs to process.")
        return

    print(f"[crash_filter] Running GDB on {len(built)} bug(s), 3 runs each "
          f"(resume={resume})")

    issues = IssueTracker("crash_filter")
    eligible_count = 0
    missing_trigger = 0

    for row in tqdm(built, desc="Crash filter", unit="bug"):
        bug_id     = row["bug_id"]
        project    = row["project"]
        bug_index  = row["bug_index"]
        trigger    = row["trigger_command"]
        signals_seen = []

        if not trigger:
            missing_trigger += 1
            issues.record("missing_trigger", bug_id, "no trigger_command in DB")

        for run_num in range(1, 4):
            crashed, signal, exit_code, raw_path, err_kind = run_gdb_in_container(
                bug_id, project, bug_index, run_num, trigger
            )

            cur.execute(
                """
                INSERT INTO filter_log
                    (bug_id, run_number, crashed, signal, gdb_exit_code, raw_output_path)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (bug_id, run_num, 1 if crashed else 0, signal, exit_code, raw_path),
            )

            if err_kind:
                issues.record(err_kind, bug_id, f"run{run_num}")
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
            tqdm.write(f"  [REPRO:{signals_seen[0]}] {bug_id}")
        else:
            cur.execute(
                "UPDATE test_cases SET crash_reproducible = 0 WHERE bug_id = ?",
                (bug_id,),
            )
            # Categorize why it failed the crash filter
            if not signals_seen:
                issues.record("no_signal", bug_id, "no crash in any run")
                tqdm.write(f"  [NO CRASH] {bug_id}")
            elif len(set(signals_seen)) > 1:
                issues.record("inconsistent_signal", bug_id,
                              f"signals={signals_seen}")
                tqdm.write(f"  [INCONSISTENT] {bug_id}: {signals_seen}")
            elif signals_seen[0] not in CATCHABLE_SIGNALS:
                issues.record("non_catchable", bug_id, signals_seen[0])
                tqdm.write(f"  [NON-CATCHABLE] {bug_id}: {signals_seen[0]}")
            else:
                issues.record("flaky_crash", bug_id,
                              f"crashed {len(signals_seen)}/3 runs")
                tqdm.write(f"  [FLAKY] {bug_id}: {len(signals_seen)}/3 runs")

        con.commit()  # commit per-bug so progress survives interruptions

    con.close()
    print(f"[crash_filter] Done: {eligible_count}/{len(built)} bugs crash reproducibly")
    if missing_trigger:
        print(f"[crash_filter] WARNING: {missing_trigger} bugs had no trigger_command "
              f"in test_cases — GDB launched with no argv, which usually means "
              f"no crash. Re-run seed_db.py against a BugsC++ version that exposes "
              f"trigger metadata, or patch utils._extract_trigger.")
    issues.print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true",
                        help="Skip bugs already partially processed in filter_log")
    args = parser.parse_args()
    run(resume=args.resume)
