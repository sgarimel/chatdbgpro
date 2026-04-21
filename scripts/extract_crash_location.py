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
"""

import argparse
import re
import subprocess

from tqdm import tqdm

from utils import (
    BACKTRACES_DIR,
    DATA_DIR,
    DB_PATH,
    IssueTracker,
    checkout_bug,
    get_db_connection,
    get_workspace_dir,
    tokenize_trigger,
)

# Path prefixes that indicate a system / library frame (not user project code).
# We walk up the stack skipping these until we find project source.
SYSTEM_PREFIXES = [
    "/usr/",
    "/lib/",
    "/build/",     # common Docker build staging area
    "??",          # GDB uses "??" when it has no source info
]

# Regex for GDB backtrace lines. Examples:
#   #0  TIFFReadDirectory (tif=0x...) at tif_dirread.c:3973
#   #1  0x00007f6a in main (argc=2, argv=...) at tiff2pdf.c:121
#   #3  0x00007f6a in __libc_start_main () from /lib/x86_64-linux-gnu/libc.so.6
FRAME_RE = re.compile(
    r"#(\d+)\s+"               # frame index
    r"(?:0x[0-9a-f]+\s+in\s+)?" # optional address
    r"(\S+)\s+"                # function name
    r"\(.*?\)"                 # arguments (lazy)
    r"(?:\s+at\s+([^:]+):(\d+))?"  # optional " at file:line"
)


def parse_backtrace(gdb_output: str) -> list[dict]:
    """
    Parse GDB `bt full` output into a list of frame dicts with keys:
      index (int), function (str), file (str | None), line (int | None)
    """
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
    """Return True if this frame is in a system library, not project source."""
    if not file_path:
        return True
    for prefix in SYSTEM_PREFIXES:
        if file_path.startswith(prefix):
            return True
    return False


def find_user_frame(frames: list[dict]) -> dict | None:
    """
    Walk frames from 0 upward, return the first frame in project source.
    Falls back to frame 0 if every frame looks like a system path.
    """
    for frame in sorted(frames, key=lambda f: f["index"]):
        if not is_system_frame(frame.get("file")):
            return frame
    return None


DOCKER_BT_SCRIPT = r"""
export LD_LIBRARY_PATH="$(find /work -type d -name .libs -printf '%p:')${LD_LIBRARY_PATH:-}"
exec gdb -batch \
    -ex 'set pagination off' \
    -ex 'set confirm off' \
    -ex 'run' \
    -ex 'bt full' \
    -ex 'quit' \
    --args "$@"
"""


def _resolve_libtool_argv(workspace_dir, argv):
    """Rewrite libtool wrapper -> .libs/ real ELF (same logic as crash_filter)."""
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
    """Run GDB `bt full` in the local workspace. If docker_image set, dispatch
    inside that container with workspace bind-mounted at /work."""
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


def run(db_path=DB_PATH, resume=False, bug_id=None, docker_image=None):
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
        return

    print(f"[extract_crash_location] Extracting frames for {len(eligible)} bug(s)")

    issues = IssueTracker("extract_crash_location")
    parsed = failed = 0

    for row in tqdm(eligible, desc="Extracting frames", unit="bug"):
        bug_id    = row["bug_id"]
        project   = row["project"]
        bug_index = row["bug_index"]
        trigger   = row["trigger_command"]
        bt_path = BACKTRACES_DIR / f"{bug_id}.txt"

        try:
            workspace_dir = get_workspace_dir(project, bug_index, buggy=True)
            if not workspace_dir.exists():
                co = checkout_bug(project, bug_index, buggy=True, timeout=180)
                if co.returncode != 0:
                    err = (co.stderr or co.stdout or "checkout failed")[:120]
                    tqdm.write(f"  [CHECKOUT FAIL] {bug_id}: {err}")
                    issues.record("bugscpp_error", bug_id, f"checkout: {err}")
                    failed += 1
                    continue
            output = get_backtrace(project, bug_index, trigger, docker_image=docker_image)
        except subprocess.TimeoutExpired:
            tqdm.write(f"  [TIMEOUT] {bug_id}")
            issues.record("timeout", bug_id, "gdb bt full > 120s")
            failed += 1
            continue
        except Exception as e:
            tqdm.write(f"  [ERROR] {bug_id}: {e}")
            issues.record("bugscpp_error", bug_id, str(e)[:120])
            failed += 1
            continue

        bt_path.write_text(output)

        if not output.strip():
            tqdm.write(f"  [EMPTY] {bug_id}: gdb produced no output")
            issues.record("empty_output", bug_id)
            failed += 1
            continue

        frames = parse_backtrace(output)

        if not frames:
            tqdm.write(f"  [PARSE FAIL] {bug_id}: {len(output)} bytes, no frames matched")
            issues.record("parse_failed", bug_id, f"{len(output)}B output")
            failed += 1
            continue

        frame0     = frames[0]
        user_frame_raw = find_user_frame(frames)
        if user_frame_raw is None:
            # All frames look like system paths — corpus ground truth would
            # point into libc. Flag so finalize can exclude if we choose.
            issues.record("only_system_frames", bug_id,
                          f"frame0={frame0.get('file')}")
            tqdm.write(f"  [SYSTEM ONLY] {bug_id}: all frames in system paths")
        user_frame = user_frame_raw or frame0

        # Store relative path from data/ for portability (DATA_DIR, not db_path
        # parent — db_path may be a string in some call sites).
        rel_bt = bt_path.relative_to(DATA_DIR)

        cur.execute(
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
                str(rel_bt),
                bug_id,
            ),
        )
        con.commit()
        parsed += 1
        tqdm.write(f"  [OK] {bug_id}: user_frame={user_frame['function']} "
                   f"@ {user_frame.get('file')}:{user_frame.get('line')}")

    con.close()
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
                        help="Run gdb inside this docker image")
    args = parser.parse_args()
    run(db_path=args.db, resume=args.resume,
        bug_id=args.bug_id, docker_image=args.docker_image)
