"""
scripts/crash_filter.py  —  Pipeline Step 3
For each successfully-built bug, runs the crash-trigger command under GDB
three times from the local BugsC++ checkout workspace. A bug passes the crash filter if
it crashes with the SAME catchable signal (SIGSEGV / SIGABRT / SIGFPE / SIGBUS)
on all three runs.

GDB is run in batch mode so it does not wait for user input.
Raw output per run is saved to data/filter_runs/<bug_id>_run<N>.txt
(these are NOT committed — add filter_runs/ to .gitignore).

Usage:
    python scripts/crash_filter.py            # process all build-successful bugs
    python scripts/crash_filter.py --resume   # skip bugs already in filter_log

Estimated time: 2–4 hours. Run in tmux.

This script intentionally does NOT use `bugscpp exec` because it is not part
of the documented CLI surface.
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
    checkout_bug,
    get_db_connection,
    get_workspace_dir,
    tokenize_trigger,
)

# Bash snippet run inside the docker container. Populates LD_LIBRARY_PATH from
# every .libs directory under the workspace (handles autotools/libtool builds
# where the real ELF lives under tools/.libs/ and depends on ../.libs/libX.so).
# Then invokes gdb in batch mode against the (possibly rewritten) argv.
DOCKER_GDB_SCRIPT = r"""
export LD_LIBRARY_PATH="$(find /work -type d -name .libs -printf '%p:')${LD_LIBRARY_PATH:-}"
exec gdb -batch \
    -ex 'set pagination off' \
    -ex 'set confirm off' \
    -ex 'run' \
    -ex 'bt' \
    -ex 'quit' \
    --args "$@"
"""


def resolve_libtool_argv(workspace_dir: Path, argv: list[str]) -> list[str]:
    """
    If argv[0] inside the workspace is a libtool shell-wrapper script, rewrite
    it to the real ELF under sibling .libs/. Leaves argv unchanged otherwise.
    Safe because we only rewrite when the .libs/ variant actually exists.
    """
    if not argv:
        return argv
    exe = argv[0]
    exe_abs = workspace_dir / exe
    if not exe_abs.is_file():
        return argv
    try:
        head = exe_abs.read_bytes()[:4096]
    except Exception:
        return argv
    if b"libtool" not in head:
        return argv
    dirname, _, base = exe.rpartition("/")
    alt = f"{dirname}/.libs/{base}" if dirname else f".libs/{base}"
    if (workspace_dir / alt).is_file():
        return [alt] + argv[1:]
    return argv

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


def run_gdb_in_workspace(
    bug_id: str, project: str, bug_index: int, run_number: int,
    trigger_command: str | None,
    docker_image: str | None = None,
):
    """
    Run GDB in the local checked-out buggy workspace for this bug.
    When docker_image is set, dispatch gdb inside that container with the
    workspace bind-mounted at /work. Otherwise invoke host gdb directly.
    Returns (crashed, signal, exit_code, raw_path, error_kind).
    """
    raw_path = FILTER_RUNS_DIR / f"{bug_id}_run{run_number}.txt"
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    workspace_dir = get_workspace_dir(project, bug_index, buggy=True)
    if not workspace_dir.exists():
        raw_path.write_text(f"WORKSPACE_NOT_FOUND: {workspace_dir}")
        return False, None, -1, str(raw_path), "bugscpp_error"

    trigger_argv = tokenize_trigger(trigger_command)
    trigger_argv = resolve_libtool_argv(workspace_dir, trigger_argv)

    if docker_image:
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{workspace_dir.resolve()}:/work",
            "-w", "/work",
            docker_image,
            "bash", "-c", DOCKER_GDB_SCRIPT, "bash",
        ] + trigger_argv
        run_cwd = None
    else:
        cmd = ["gdb"] + list(GDB_BATCH_ARGS)
        if trigger_argv:
            cmd += ["--args"] + trigger_argv
        run_cwd = str(workspace_dir)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180 if docker_image else 120,
            cwd=run_cwd,
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


def run(db_path=DB_PATH, resume=False, bug_id=None, docker_image=None):
    con = get_db_connection(db_path)
    cur = con.cursor()

    base_sql = """
        SELECT t.bug_id, t.project, t.bug_index, t.trigger_command
        FROM test_cases t
        JOIN build_log b ON t.bug_id = b.bug_id
        WHERE b.success = 1
    """
    params: tuple = ()
    if bug_id:
        base_sql += " AND t.bug_id = ?"
        params = (bug_id,)
    if resume:
        base_sql += (
            " AND (SELECT COUNT(*) FROM filter_log f WHERE f.bug_id = t.bug_id) < 3"
        )
    built = cur.execute(base_sql, params).fetchall()

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

        # When running against an already-checked-out workspace (e.g. the
        # smoke sandbox) re-running checkout is wasted work. Skip if present.
        workspace_dir = get_workspace_dir(project, bug_index, buggy=True)
        if workspace_dir.exists():
            class _OK: returncode = 0; stderr = ""; stdout = ""
            co = _OK()
        else:
            co = checkout_bug(project, bug_index, buggy=True, timeout=180)
        if co.returncode != 0:
            err = (co.stderr or co.stdout or "checkout failed")[:2000]
            for run_num in range(1, 4):
                raw_path = FILTER_RUNS_DIR / f"{bug_id}_run{run_num}.txt"
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(f"CHECKOUT_FAILED: {err}")
                cur.execute(
                    """
                    INSERT INTO filter_log
                        (bug_id, run_number, crashed, signal, gdb_exit_code, raw_output_path)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (bug_id, run_num, 0, None, -1, str(raw_path)),
                )
            issues.record("bugscpp_error", bug_id, "checkout_failed")
            cur.execute(
                "UPDATE test_cases SET crash_reproducible = 0 WHERE bug_id = ?",
                (bug_id,),
            )
            con.commit()
            continue

        for run_num in range(1, 4):

            crashed, signal, exit_code, raw_path, err_kind = run_gdb_in_workspace(
                bug_id, project, bug_index, run_num, trigger,
                docker_image=docker_image,
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
    parser.add_argument("--bug-id", default=None,
                        help="Run only this bug_id (e.g. libtiff-2)")
    parser.add_argument("--db", default=str(DB_PATH),
                        help="Path to sqlite DB (default: data/corpus.db)")
    parser.add_argument("--docker-image", default=None,
                        help="Run gdb inside this docker image with workspace "
                             "mounted at /work (e.g. chatdbgpro/gdb-libtiff:latest)")
    args = parser.parse_args()
    run(db_path=args.db, resume=args.resume,
        bug_id=args.bug_id, docker_image=args.docker_image)
