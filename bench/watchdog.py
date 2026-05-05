"""Sweep watchdog — kills a running parallel_run if API credit/quota
errors are repeatedly observed in fresh result.json/stderr.log files.

Why this exists:
- bench.orchestrator does not abort on OpenRouter 402 / insufficient_credits;
  it records the cell as "ok" with an empty transcript and moves on.
- parallel_run.py with --skip-existing then treats those empty cells as
  "done", so a re-run does not retry them.
- Without a watchdog, a credit exhaustion silently burns through thousands
  of cells producing zero data.

What it does, every POLL_INTERVAL seconds:
- Walk the sweep dir, look at the N most recently-modified result.json files.
- Count how many show credit/quota indicators (see CREDIT_PATTERNS) in
  result.json, stderr.log, or a near-empty stdout.log paired with a very
  short elapsed_s.
- If >= THRESHOLD of the last N indicate credit failure, send SIGTERM
  to the parallel_run PID and exit nonzero.
- Otherwise, print a heartbeat: cells done, cells suspect, elapsed mins.

Usage:
    python -m bench.watchdog --sweep-dir bench/results/<name> --pid <parallel_pid>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from pathlib import Path

CREDIT_PATTERNS = [
    re.compile(r"\binsufficient[_ ]credits?\b", re.IGNORECASE),
    re.compile(r"\b402\b"),
    re.compile(r"quota[_ ]exceeded", re.IGNORECASE),
    re.compile(r"rate[_ ]limit[_ ]exceeded", re.IGNORECASE),
    re.compile(r"insufficient[_ ]quota", re.IGNORECASE),
    re.compile(r"out of credits", re.IGNORECASE),
    re.compile(r"payment.required", re.IGNORECASE),
]

POLL_INTERVAL = 60          # seconds between checks
WINDOW = 20                 # how many recent cells to inspect
THRESHOLD = 5               # this many credit-suspect cells in WINDOW → halt
HEARTBEAT_EVERY = 5         # heartbeat every 5 polls (~5 min)


def _looks_credit_blocked(run_dir: Path) -> bool:
    """Return True if this finished cell looks like a credit/quota failure."""
    result_json = run_dir / "result.json"
    stderr_log = run_dir / "stderr.log"
    stdout_log = run_dir / "stdout.log"

    blobs: list[str] = []
    elapsed_s = None
    status = None

    if result_json.exists():
        try:
            obj = json.loads(result_json.read_text(encoding="utf-8", errors="replace"))
            elapsed_s = obj.get("elapsed_s")
            status = obj.get("status")
            blobs.append(json.dumps(obj))
        except Exception:
            pass
    for p in (stderr_log, stdout_log):
        if p.exists():
            try:
                blobs.append(p.read_text(encoding="utf-8", errors="replace")[-8000:])
            except Exception:
                pass

    text = "\n".join(blobs)
    for pat in CREDIT_PATTERNS:
        if pat.search(text):
            return True

    # Heuristic: a "successful" ok cell that finished in <5s with an empty
    # stdout log is almost certainly a model that returned nothing because
    # of an upstream API error the harness ate.
    if status == "ok" and elapsed_s is not None and elapsed_s < 5.0:
        try:
            if stdout_log.exists() and stdout_log.stat().st_size < 200:
                return True
        except Exception:
            pass
    return False


def _recent_cells(sweep_dir: Path, n: int) -> list[Path]:
    candidates = []
    for run_dir in sweep_dir.iterdir():
        if not run_dir.is_dir():
            continue
        rj = run_dir / "result.json"
        if rj.exists():
            candidates.append((rj.stat().st_mtime, run_dir))
    candidates.sort(reverse=True)
    return [d for _, d in candidates[:n]]


def _terminate(pid: int) -> None:
    if pid <= 0:
        return
    try:
        if sys.platform == "win32":
            # On Windows there is no SIGTERM for arbitrary PIDs; use taskkill.
            os.system(f'taskkill /F /T /PID {pid}')
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception as e:
        print(f"[watchdog] failed to terminate PID {pid}: {e}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sweep-dir", required=True, type=Path)
    ap.add_argument("--pid", type=int, default=0,
                    help="PID of the parallel_run process to kill on alert")
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--poll-interval", type=int, default=POLL_INTERVAL)
    ap.add_argument("--target-cells", type=int, default=0,
                    help="If >0, watchdog exits cleanly when this many cells have result.json")
    args = ap.parse_args()

    sweep_dir: Path = args.sweep_dir
    sweep_dir.mkdir(parents=True, exist_ok=True)

    print(f"[watchdog] watching {sweep_dir} (pid={args.pid}, "
          f"window={args.window}, threshold={args.threshold}, "
          f"poll={args.poll_interval}s)", flush=True)

    t0 = time.time()
    poll = 0
    while True:
        poll += 1
        time.sleep(args.poll_interval)

        cells = _recent_cells(sweep_dir, args.window)
        n_total = sum(1 for _ in sweep_dir.glob("*/result.json"))
        suspect = [d for d in cells if _looks_credit_blocked(d)]
        n_suspect_recent = len(suspect)

        if poll % HEARTBEAT_EVERY == 0 or n_suspect_recent >= args.threshold:
            mins = (time.time() - t0) / 60.0
            print(
                f"[watchdog] heartbeat: total_done={n_total} "
                f"recent_suspect={n_suspect_recent}/{len(cells)} "
                f"elapsed_min={mins:.1f}",
                flush=True,
            )

        if n_suspect_recent >= args.threshold and len(cells) >= args.threshold:
            print(
                f"[watchdog] ALERT: {n_suspect_recent}/{len(cells)} recent cells "
                f"look credit/quota-blocked. Halting sweep.",
                flush=True,
            )
            for d in suspect[:5]:
                print(f"[watchdog]   suspect: {d.name}", flush=True)
            _terminate(args.pid)
            return 2

        if args.target_cells and n_total >= args.target_cells:
            print(f"[watchdog] target reached ({n_total} >= {args.target_cells}), exiting clean", flush=True)
            return 0


if __name__ == "__main__":
    sys.exit(main())
