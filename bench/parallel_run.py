"""Case-level parallel runner over bench.orchestrator.

Runs N (case, tier, model) tuples concurrently as separate orchestrator
processes, each managing its own apptainer/docker instance.

Why this and not SWE-Rex:
  - SWE-Rex is a sandbox/runtime *abstraction* (FastAPI server inside
    a container, RemoteRuntime client). It does NOT ship a parallel
    batch runner — you write asyncio.gather over deployments yourself.
  - SWE-Rex backends: docker, modal, fargate, daytona, local, remote.
    No apptainer/singularity backend — you'd write one. Adroit is
    apptainer-only.
  - Mini-swe-agent has swerex_docker / swerex_modal env classes, but
    no swerex_apptainer. T3 (ChatDBG-in-gdb) and T4 (Claude Code)
    have no SWE-Rex integration at all.
  - Adopting SWE-Rex on adroit ≈ multi-day refactor (write
    ApptainerDeployment, bake their FastAPI server into our images,
    rewrite all four tier drivers) for a feature SWE-Rex doesn't
    even provide.

What we ship instead, in ~60 lines:
  - ProcessPoolExecutor over (bug_id, tier, model) tuples.
  - Each worker shells out to `python -m bench.orchestrator
    --bug-ids ONE --tiers ONE --models ONE --name SWEEP
    --skip-existing`.
  - All bookkeeping (case discovery, case.yaml, finalize_result)
    handled by the existing orchestrator.
  - --skip-existing makes it idempotent — re-launches pick up
    where a crash/kill left off.
  - Workers don't collide: each (bug, tier, model) writes to a
    distinct run-dir under the shared sweep dir, and apptainer
    instance names are random per orchestrator process.

Tunable knob: --workers. Cap by:
  - Apptainer image-extract concurrency (SIF is cached, fine to ~16).
  - LLM provider rate limits (OpenRouter free tier ~10 RPM/key;
    paid is much higher; 8-12 is a safe default).
  - Per-worker memory: each apptainer instance + agent venv is
    ~200-500 MB; 8 workers ≈ 4 GB.

Usage:
    python -m bench.parallel_run \\
        --bug-ids yara-1 yara-2 yara-3 yara-4 yara-5 \\
        --tiers 1 2 3 \\
        --models openrouter/google/gemini-2.5-flash \\
                 openrouter/openai/gpt-5.1 \\
        --runtime apptainer \\
        --workers 8 \\
        --name yara-parallel-pilot
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

TIER_CONFIG = {
    1: REPO_ROOT / "bench/configs/tier1_bash_only.json",
    2: REPO_ROOT / "bench/configs/tier2_gdb_plus_bash.json",
    3: REPO_ROOT / "bench/configs/tier3_gdb_only.json",
    4: REPO_ROOT / "bench/configs/tier4_claude_code.json",
}


def run_one(
    bug_id: str,
    tier: int,
    model: str,
    name: str,
    runtime: str,
    timeout: int,
    trials: int,
    dry: bool,
    no_docker: bool = False,
) -> str:
    """Worker: run a single (bug, tier, model) via bench.orchestrator.

    When ``no_docker`` is True the cell is dispatched through the on-disk
    case-discovery path (``--cases`` against ``bench/cases``), which is
    required for the synthetic panel because those case ids do not exist
    in ``corpus.db``.
    """
    cmd = [
        sys.executable, "-m", "bench.orchestrator",
        "--models", model,
        "--tool-configs", str(TIER_CONFIG[tier]),
        "--tiers", str(tier),
        "--trials", str(trials),
        "--timeout", str(timeout),
        "--name", name,
        "--skip-existing",
    ]
    if no_docker:
        cmd += ["--cases", bug_id]
    else:
        cmd += ["--docker", "--bug-ids", bug_id, "--runtime", runtime]
    label = f"{bug_id}/T{tier}/{model.split('/')[-1]}"
    if dry:
        return f"[DRY] {label}: {' '.join(cmd)}"
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    dt = time.time() - t0
    tail = (r.stdout + r.stderr).splitlines()[-1] if (r.stdout or r.stderr) else ""
    return f"[done] {label} rc={r.returncode} {dt:.0f}s :: {tail[:120]}"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bug-ids", nargs="+", required=True,
                   help="Bug ids from corpus.db (e.g. yara-1 yara-2 ...)")
    p.add_argument("--tiers", nargs="+", type=int, required=True,
                   choices=(1, 2, 3, 4))
    p.add_argument("--models", nargs="+", required=True,
                   help="Full model IDs (e.g. openrouter/anthropic/claude-sonnet-4.6)")
    p.add_argument("--name", required=True,
                   help="Sweep dir name under bench/results/")
    p.add_argument("--runtime", default="apptainer",
                   choices=("docker", "apptainer"))
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--trials", type=int, default=1)
    p.add_argument("--workers", type=int, default=8,
                   help="Max concurrent orchestrator processes")
    p.add_argument("--no-docker", action="store_true",
                   help="Dispatch through orchestrator's on-disk --cases "
                        "path. Required for the synthetic panel because those "
                        "case ids are not in corpus.db.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    specs = [
        (b, t, m)
        for b in args.bug_ids
        for t in args.tiers
        for m in args.models
    ] * args.trials  # trials handled by orchestrator's --trials in each call,
    # so we deduplicate here and rely on orchestrator to multiply. Reset:
    specs = [(b, t, m) for b in args.bug_ids for t in args.tiers for m in args.models]

    print(f"[parallel] {len(specs)} cells × workers={args.workers} "
          f"(sweep={args.name}, runtime={args.runtime})", flush=True)

    t0 = time.time()
    completed = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                run_one, b, t, m, args.name,
                args.runtime, args.timeout, args.trials, args.dry_run,
                args.no_docker,
            ): (b, t, m)
            for b, t, m in specs
        }
        for f in as_completed(futures):
            try:
                msg = f.result()
            except Exception as e:
                b, t, m = futures[f]
                msg = f"[ERR ] {b}/T{t}/{m.split('/')[-1]}: {e}"
            completed += 1
            print(f"[{completed}/{len(specs)}] {msg}", flush=True)

    elapsed = time.time() - t0
    print(f"[parallel] all {len(specs)} cells done in {elapsed:.0f}s "
          f"({elapsed / max(len(specs), 1):.1f}s/cell amortized)", flush=True)


if __name__ == "__main__":
    main()
