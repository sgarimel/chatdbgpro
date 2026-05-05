"""Live judge + analyze refresh loop.

While bench.parallel_run is sweeping, this loop periodically scores any
new cells and rebuilds CSVs/PDF so the user can inspect partial results
at any time without waiting for the sweep to finish.

bench.judge is incremental — it skips runs that already have a score.json
unless --overwrite is set. bench.analyze always rewrites its analysis/
dir but is cheap. So calling them on a loop is safe and idempotent.

Usage:
    python -m bench.live_refresh --sweep-dir bench/results/<name> \
        --judge-model openrouter/openai/gpt-4o --interval 300
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], log_prefix: str) -> int:
    """Run a subprocess; return its returncode. Tolerate non-zero exits."""
    print(f"[live] {log_prefix}: {' '.join(cmd)}", flush=True)
    try:
        r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30 * 60)
        tail = (r.stdout + r.stderr).splitlines()[-3:]
        for line in tail:
            print(f"[live] {log_prefix}/out: {line[:160]}", flush=True)
        return r.returncode
    except subprocess.TimeoutExpired:
        print(f"[live] {log_prefix}: timeout (30 min)", flush=True)
        return 124
    except Exception as e:
        print(f"[live] {log_prefix}: error {e}", flush=True)
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sweep-dir", required=True, type=Path)
    ap.add_argument("--judge-model", default="openrouter/openai/gpt-4o")
    ap.add_argument("--interval", type=int, default=300, help="Seconds between refresh passes")
    ap.add_argument("--once", action="store_true", help="Run one pass and exit")
    ap.add_argument("--skip-pdf", action="store_true",
                    help="Don't try to build the cross-tier PDF (saves ~30s/pass)")
    args = ap.parse_args()

    sweep_dir: Path = args.sweep_dir
    sweep_name = sweep_dir.name

    print(f"[live] refresh loop on {sweep_dir} (every {args.interval}s, judge={args.judge_model})", flush=True)

    pass_n = 0
    while True:
        pass_n += 1
        t0 = time.time()
        n_done = sum(1 for _ in sweep_dir.glob("*/result.json")) if sweep_dir.exists() else 0
        n_scored = sum(1 for _ in sweep_dir.glob("*/score.json")) if sweep_dir.exists() else 0
        print(f"[live] pass={pass_n} done={n_done} scored={n_scored}", flush=True)

        if n_done > 0:
            _run(
                [sys.executable, "-m", "bench.judge",
                 "--judge-model", args.judge_model,
                 str(sweep_dir)],
                "judge",
            )
            _run(
                [sys.executable, "-m", "bench.analyze", str(sweep_dir)],
                "analyze",
            )
            if not args.skip_pdf:
                pdf_out = REPO_ROOT / "bench" / "analysis_artifacts" / "figs" / f"{sweep_name}.pdf"
                pdf_out.parent.mkdir(parents=True, exist_ok=True)
                _run(
                    [sys.executable, "bench/analysis_artifacts/build_cross_tier_pdf.py",
                     "--suite", str(sweep_dir),
                     "--out", str(pdf_out)],
                    "pdf",
                )

        if args.once:
            return 0

        elapsed = time.time() - t0
        sleep_for = max(args.interval - elapsed, 30)
        print(f"[live] pass={pass_n} took {elapsed:.0f}s; sleeping {sleep_for:.0f}s", flush=True)
        time.sleep(sleep_for)


if __name__ == "__main__":
    sys.exit(main())
