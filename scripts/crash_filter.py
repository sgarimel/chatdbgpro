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
    python scripts/crash_filter.py                         # serial, all built bugs
    python scripts/crash_filter.py --resume                # skip bugs already in filter_log
    python scripts/crash_filter.py --workers 4             # 4 parallel workers
    python scripts/crash_filter.py --bug-id libtiff-2      # one bug only

Estimated time: 2–4 hours serial, ~30–45 min with 4 workers. Run in tmux.
"""

import argparse
import re
import subprocess
from pathlib import Path

from _parallel import BugResult, run_pipeline_step
from utils import (
    CATCHABLE_SIGNALS,
    DB_PATH,
    FILTER_RUNS_DIR,
    IssueTracker,
    checkout_bug,
    gdb_image_for,
    get_db_connection,
    get_workspace_dir,
    tokenize_trigger,
)

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


GDB_BATCH_ARGS = [
    "-batch",
    "-ex", "set pagination off",
    "-ex", "set confirm off",
    "-ex", "run",
    "-ex", "bt",
    "-ex", "quit",
]


def parse_signal(gdb_output: str) -> str | None:
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
    """Returns (crashed, signal, exit_code, raw_path, error_kind)."""
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


def process_one(row: dict, ctx: dict) -> BugResult:
    bug_id = row["bug_id"]
    project = row["project"]
    bug_index = row["bug_index"]
    trigger = row["trigger_command"]
    if ctx.get("no_docker"):
        docker_image = None
    else:
        docker_image = ctx.get("docker_image_override") or gdb_image_for(project)

    res = BugResult(bug_id=bug_id)

    if not trigger:
        res.counters["missing_trigger"] = 1
        res.issue_records.append(("missing_trigger", bug_id, "no trigger_command in DB"))

    workspace_dir = get_workspace_dir(project, bug_index, buggy=True)
    if not workspace_dir.exists():
        co = checkout_bug(project, bug_index, buggy=True, timeout=180)
        if co.returncode != 0:
            err = (co.stderr or co.stdout or "checkout failed")[:2000]
            for run_num in range(1, 4):
                raw_path = FILTER_RUNS_DIR / f"{bug_id}_run{run_num}.txt"
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(f"CHECKOUT_FAILED: {err}")
                res.db_updates.append((
                    "INSERT INTO filter_log "
                    "(bug_id, run_number, crashed, signal, gdb_exit_code, raw_output_path) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (bug_id, run_num, 0, None, -1, str(raw_path)),
                ))
            res.issue_records.append(("bugscpp_error", bug_id, "checkout_failed"))
            res.db_updates.append((
                "UPDATE test_cases SET crash_reproducible = 0 WHERE bug_id = ?",
                (bug_id,),
            ))
            return res

    signals_seen: list[str] = []
    for run_num in range(1, 4):
        crashed, signal, exit_code, raw_path, err_kind = run_gdb_in_workspace(
            bug_id, project, bug_index, run_num, trigger,
            docker_image=docker_image,
        )
        res.db_updates.append((
            "INSERT INTO filter_log "
            "(bug_id, run_number, crashed, signal, gdb_exit_code, raw_output_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (bug_id, run_num, 1 if crashed else 0, signal, exit_code, raw_path),
        ))
        if err_kind:
            res.issue_records.append((err_kind, bug_id, f"run{run_num}"))
        if crashed:
            signals_seen.append(signal)

    reproducible = (
        len(signals_seen) == 3
        and len(set(signals_seen)) == 1
        and signals_seen[0] in CATCHABLE_SIGNALS
    )

    if reproducible:
        res.db_updates.append((
            "UPDATE test_cases SET crash_signal = ?, crash_reproducible = 1 "
            "WHERE bug_id = ?",
            (signals_seen[0], bug_id),
        ))
        res.counters["eligible"] = 1
        res.log_lines.append(f"  [REPRO:{signals_seen[0]}] {bug_id}")
    else:
        res.db_updates.append((
            "UPDATE test_cases SET crash_reproducible = 0 WHERE bug_id = ?",
            (bug_id,),
        ))
        if not signals_seen:
            res.issue_records.append(("no_signal", bug_id, "no crash in any run"))
            res.log_lines.append(f"  [NO CRASH] {bug_id}")
        elif len(set(signals_seen)) > 1:
            res.issue_records.append(
                ("inconsistent_signal", bug_id, f"signals={signals_seen}"))
            res.log_lines.append(f"  [INCONSISTENT] {bug_id}: {signals_seen}")
        elif signals_seen[0] not in CATCHABLE_SIGNALS:
            res.issue_records.append(("non_catchable", bug_id, signals_seen[0]))
            res.log_lines.append(f"  [NON-CATCHABLE] {bug_id}: {signals_seen[0]}")
        else:
            res.issue_records.append(
                ("flaky_crash", bug_id, f"crashed {len(signals_seen)}/3 runs"))
            res.log_lines.append(f"  [FLAKY] {bug_id}: {len(signals_seen)}/3 runs")

    return res


def run(db_path=DB_PATH, resume=False, bug_id=None,
        docker_image_override=None, no_docker=False, workers=1):
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
        con.close()
        return

    rows = [dict(r) for r in built]
    print(f"[crash_filter] Running GDB on {len(rows)} bug(s), 3 runs each "
          f"(resume={resume}, workers={workers})")

    issues = IssueTracker("crash_filter")
    counters = run_pipeline_step(
        bug_rows=rows,
        work_fn=process_one,
        ctx={"docker_image_override": docker_image_override,
             "no_docker": no_docker},
        workers=workers,
        desc="Crash filter",
        con=con,
        issue_tracker=issues,
    )
    con.close()

    eligible_count = counters.get("eligible", 0)
    missing_trigger = counters.get("missing_trigger", 0)
    print(f"[crash_filter] Done: {eligible_count}/{len(rows)} bugs crash reproducibly")
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
                        help="Override the per-project chatdbgpro/gdb-<project>:latest "
                             "image for ALL bugs in this run (useful for debugging). "
                             "Default: each bug uses its own project image.")
    parser.add_argument("--no-docker", action="store_true",
                        help="Run gdb natively on the host instead of in docker "
                             "(only use if gdb + project build env are installed locally)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of parallel workers (default: 1 = serial)")
    args = parser.parse_args()
    run(db_path=args.db, resume=args.resume,
        bug_id=args.bug_id, docker_image_override=args.docker_image,
        no_docker=args.no_docker, workers=args.workers)
