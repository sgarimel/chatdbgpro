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
from pathlib import Path

from tqdm import tqdm

from utils import BACKTRACES_DIR, DB_PATH, get_db_connection

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


def get_backtrace(project: str, bug_index: int) -> str:
    """Run GDB `bt full` inside the bugscpp container and return output."""
    result = subprocess.run(
        [
            "bugscpp", "exec", project, str(bug_index), "--buggy",
            "--", "gdb",
            "-batch",
            "-ex", "set pagination off",
            "-ex", "set confirm off",
            "-ex", "run",
            "-ex", "bt full",
            "-ex", "quit",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout + result.stderr


def run(db_path=DB_PATH, resume=False):
    con = get_db_connection(db_path)
    cur = con.cursor()
    BACKTRACES_DIR.mkdir(parents=True, exist_ok=True)

    if resume:
        eligible = cur.execute("""
            SELECT bug_id, project, bug_index FROM test_cases
            WHERE crash_reproducible = 1 AND backtrace_path IS NULL
        """).fetchall()
    else:
        eligible = cur.execute("""
            SELECT bug_id, project, bug_index FROM test_cases
            WHERE crash_reproducible = 1
        """).fetchall()

    if not eligible:
        print("[extract_crash_location] No crash-reproducible bugs to process.")
        return

    parsed = failed = 0

    for row in tqdm(eligible, desc="Extracting frames", unit="bug"):
        bug_id, project, bug_index = row["bug_id"], row["project"], row["bug_index"]
        bt_path = BACKTRACES_DIR / f"{bug_id}.txt"

        try:
            output = get_backtrace(project, bug_index)
        except subprocess.TimeoutExpired:
            tqdm.write(f"  TIMEOUT: {bug_id}")
            failed += 1
            continue
        except Exception as e:
            tqdm.write(f"  ERROR {bug_id}: {e}")
            failed += 1
            continue

        bt_path.write_text(output)
        frames = parse_backtrace(output)

        if not frames:
            tqdm.write(f"  WARNING: no parseable frames for {bug_id}")
            failed += 1
            continue

        frame0     = frames[0]
        user_frame = find_user_frame(frames) or frame0

        # Store relative path from data/ for portability
        rel_bt = bt_path.relative_to(db_path.parent)

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

    con.close()
    print(f"[extract_crash_location] Done: {parsed} frames extracted, {failed} failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true",
                        help="Skip bugs that already have backtrace_path set")
    args = parser.parse_args()
    run(resume=args.resume)
