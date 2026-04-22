"""
scripts/extract_crash_location.py  —  Pipeline Step 4
For each crash-reproducible bug, runs GDB one final time with `bt full`
to get a rich backtrace, then:
  1. Saves the raw backtrace to data/backtraces/<bug_id>.txt
  2. Parses frame 0 (where execution stopped, may be in libc)
  3. Finds the first "user frame" — the shallowest frame in project source code
  4. Updates frame columns in test_cases

The user_frame is the ground truth for evaluation scoring:
a model's diagnosis is correct if it names the right function/file/line
in the user_frame (not necessarily frame 0).

Usage:
    python scripts/extract_crash_location.py
    python scripts/extract_crash_location.py --resume
    python scripts/extract_crash_location.py --workers 4
"""

import argparse
import re
import subprocess

from _parallel import BugResult, run_pipeline_step
from utils import (
    BACKTRACES_DIR,
    DATA_DIR,
    DB_PATH,
    IssueTracker,
    checkout_bug,
    gdb_image_for,
    get_db_connection,
    get_workspace_dir,
    tokenize_trigger,
)

SYSTEM_PREFIXES = [
    "/usr/",
    "/lib/",
    "/build/",
    "??",
]

FRAME_RE = re.compile(
    r"#(\d+)\s+"
    r"(?:0x[0-9a-f]+\s+in\s+)?"
    r"(\S+)\s+"
    r"\(.*?\)"
    r"(?:\s+at\s+([^:]+):(\d+))?"
)


def parse_backtrace(gdb_output: str) -> list[dict]:
    frames = []
    for line in gdb_output.splitlines():
        m = FRAME_RE.search(line)
        if m:
            frames.append({
                "index":    int(m.group(1)),
                "function": m.group(2),
                "file":     m.group(3).strip() if m.group(3) else None,
                "line":     int(m.group(4)) if m.group(4) else None,
            })
    return frames


def is_system_frame(file_path: str | None) -> bool:
    if not file_path:
        return True
    for prefix in SYSTEM_PREFIXES:
        if file_path.startswith(prefix):
            return True
    return False


def find_user_frame(frames: list[dict]) -> dict | None:
    for frame in sorted(frames, key=lambda f: f["index"]):
        if not is_system_frame(frame.get("file")):
            return frame
    return None


DOCKER_BT_SCRIPT = r"""
export LD_LIBRARY_PATH="$(find /work -type d -name .libs -printf '%p:')${LD_LIBRARY_PATH:-}"
exec gdb -batch \
    -ex 'set pagination off' \
    -ex 'set confirm off' \
    -ex 'set follow-fork-mode child' \
    -ex 'set detach-on-fork on' \
    -ex 'run' \
    -ex 'bt full' \
    -ex 'quit' \
    --args "$@"
"""


def _resolve_libtool_argv(workspace_dir, argv):
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


def get_backtrace(
    project: str, bug_index: int, trigger_command: str | None,
    docker_image: str | None = None,
) -> str:
    workspace_dir = get_workspace_dir(project, bug_index, buggy=True)
    if not workspace_dir.exists():
        raise FileNotFoundError(f"workspace missing: {workspace_dir}")

    trigger_argv = tokenize_trigger(trigger_command)
    trigger_argv = _resolve_libtool_argv(workspace_dir, trigger_argv)

    if docker_image:
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{workspace_dir.resolve()}:/work",
            "-w", "/work",
            docker_image,
            "bash", "-c", DOCKER_BT_SCRIPT, "bash",
        ] + trigger_argv
        run_cwd = None
    else:
        gdb_args = [
            "-batch",
            "-ex", "set pagination off",
            "-ex", "set confirm off",
            "-ex", "set follow-fork-mode child",
            "-ex", "set detach-on-fork on",
            "-ex", "run",
            "-ex", "bt full",
            "-ex", "quit",
        ]
        if trigger_argv:
            gdb_args += ["--args"] + trigger_argv
        cmd = ["gdb"] + gdb_args
        run_cwd = str(workspace_dir)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=180 if docker_image else 120,
        cwd=run_cwd,
    )
    return result.stdout + result.stderr


def process_one(row: dict, ctx: dict) -> BugResult:
    bug_id = row["bug_id"]
    project = row["project"]
    bug_index = row["bug_index"]
    trigger = row["trigger_command"]
    if ctx.get("no_docker"):
        docker_image = None
    else:
        docker_image = ctx.get("docker_image_override") or gdb_image_for(project)

    bt_path = BACKTRACES_DIR / f"{bug_id}.txt"
    res = BugResult(bug_id=bug_id)

    try:
        workspace_dir = get_workspace_dir(project, bug_index, buggy=True)
        if not workspace_dir.exists():
            co = checkout_bug(project, bug_index, buggy=True, timeout=180)
            if co.returncode != 0:
                err = (co.stderr or co.stdout or "checkout failed")[:120]
                res.log_lines.append(f"  [CHECKOUT FAIL] {bug_id}: {err}")
                res.issue_records.append(("bugscpp_error", bug_id, f"checkout: {err}"))
                res.counters["failed"] = 1
                return res
        output = get_backtrace(project, bug_index, trigger, docker_image=docker_image)
    except subprocess.TimeoutExpired:
        res.log_lines.append(f"  [TIMEOUT] {bug_id}")
        res.issue_records.append(("timeout", bug_id, "gdb bt full > 120s"))
        res.counters["failed"] = 1
        return res
    except Exception as e:
        res.log_lines.append(f"  [ERROR] {bug_id}: {e}")
        res.issue_records.append(("bugscpp_error", bug_id, str(e)[:120]))
        res.counters["failed"] = 1
        return res

    bt_path.write_text(output)

    if not output.strip():
        res.log_lines.append(f"  [EMPTY] {bug_id}: gdb produced no output")
        res.issue_records.append(("empty_output", bug_id, ""))
        res.counters["failed"] = 1
        return res

    frames = parse_backtrace(output)
    if not frames:
        res.log_lines.append(
            f"  [PARSE FAIL] {bug_id}: {len(output)} bytes, no frames matched")
        res.issue_records.append(("parse_failed", bug_id, f"{len(output)}B output"))
        res.counters["failed"] = 1
        return res

    frame0 = frames[0]
    user_frame_raw = find_user_frame(frames)
    if user_frame_raw is None:
        res.issue_records.append(
            ("only_system_frames", bug_id, f"frame0={frame0.get('file')}"))
        res.log_lines.append(f"  [SYSTEM ONLY] {bug_id}: all frames in system paths")
    user_frame = user_frame_raw or frame0

    rel_bt = bt_path.relative_to(DATA_DIR)

    res.db_updates.append((
        """
        UPDATE test_cases SET
            frame0_function     = ?,
            frame0_file         = ?,
            frame0_line         = ?,
            user_frame_function = ?,
            user_frame_file     = ?,
            user_frame_line     = ?,
            backtrace_path      = ?
        WHERE bug_id = ?
        """,
        (
            frame0["function"],     frame0.get("file"),     frame0.get("line"),
            user_frame["function"], user_frame.get("file"), user_frame.get("line"),
            rel_bt.as_posix(),
            bug_id,
        ),
    ))
    res.counters["parsed"] = 1
    res.log_lines.append(
        f"  [OK] {bug_id}: user_frame={user_frame['function']} "
        f"@ {user_frame.get('file')}:{user_frame.get('line')}")
    return res


def run(db_path=DB_PATH, resume=False, bug_id=None,
        docker_image_override=None, no_docker=False, workers=1):
    con = get_db_connection(db_path)
    cur = con.cursor()
    BACKTRACES_DIR.mkdir(parents=True, exist_ok=True)

    base_sql = (
        "SELECT bug_id, project, bug_index, trigger_command FROM test_cases "
        "WHERE crash_reproducible = 1"
    )
    params: tuple = ()
    if bug_id:
        base_sql += " AND bug_id = ?"
        params = (bug_id,)
    if resume:
        base_sql += " AND backtrace_path IS NULL"
    eligible = cur.execute(base_sql, params).fetchall()

    if not eligible:
        print("[extract_crash_location] No crash-reproducible bugs to process.")
        con.close()
        return

    rows = [dict(r) for r in eligible]
    print(f"[extract_crash_location] Extracting frames for {len(rows)} bug(s) "
          f"(workers={workers})")

    issues = IssueTracker("extract_crash_location")
    counters = run_pipeline_step(
        bug_rows=rows,
        work_fn=process_one,
        ctx={"docker_image_override": docker_image_override,
             "no_docker": no_docker},
        workers=workers,
        desc="Extracting frames",
        con=con,
        issue_tracker=issues,
    )
    con.close()

    parsed = counters.get("parsed", 0)
    failed = counters.get("failed", 0)
    print(f"[extract_crash_location] Done: {parsed} frames extracted, {failed} failed")
    issues.print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true",
                        help="Skip bugs that already have backtrace_path set")
    parser.add_argument("--bug-id", default=None,
                        help="Process only this bug_id")
    parser.add_argument("--db", default=str(DB_PATH),
                        help="Path to sqlite DB (default: data/corpus.db)")
    parser.add_argument("--docker-image", default=None,
                        help="Override the per-project chatdbgpro/gdb-<project>:latest "
                             "image for ALL bugs in this run. Default: each bug uses "
                             "its own project image.")
    parser.add_argument("--no-docker", action="store_true",
                        help="Run gdb natively on the host instead of in docker")
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of parallel workers (default: 1 = serial)")
    args = parser.parse_args()
    run(db_path=args.db, resume=args.resume,
        bug_id=args.bug_id, docker_image_override=args.docker_image,
        no_docker=args.no_docker, workers=args.workers)
