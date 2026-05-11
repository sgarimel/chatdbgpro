# Realworld panel rerun — status note (2026-05-11)

## Where things stand

The realworld panel is being rerun on the **adroit login node** (not SLURM)
because:

1. The first 16-job SLURM round produced `status=ok` cells that all had
   `exit_status: APIError`, `tokens: 0`, `response: ""` in `collect.json`.
   The orchestrator misread "agent exited cleanly" as success even when the
   model never responded.

2. Root cause: **adroit compute nodes cannot reach openrouter.ai**. The
   Princeton proxy (`module load proxy/default`, `http://adroit-proxy:8080`)
   whitelists `api.openai.com` and `api.anthropic.com` (both reachable, 401
   without a key) but **403s on `openrouter.ai`** and on `github.com`/`pypi.org`.

3. The login node has full internet (HTTP 200 to openrouter.ai), so we run
   from there. Single nohup process iterates 16 (tier, model) groups with
   workers=2 inside each `bench.parallel_run` call.

## Fixes landed this session

| Commit | Fix |
|---|---|
| c4907050 | run_runset_shard splits mixed corpus+synth groups by source |
| b719938e | sbatch uses $HOME/.conda/envs/clang-bench/bin for clang (compute lacks intel-llvm) |
| 8dd34aba | sbatch `workers=2` default, `BENCH_APPTAINER_SIF_DIR` for cached SIFs |
| c32c0443 | gitignore whitelist for per-owner paper-final sweep dirs |
| c03ed57d | bench/common.py strips ALL shell-quote chars from trigger (PR #22 was incomplete); container_session redacts `sk-*` from error logs; sbatch loads `proxy/default` |

## What the login-node sweep should produce

Output sweeps named `ibraheem-paper-final-realworld-20260511-T{1,3}-<model-slug>/`.
161 cells across 8 models × 2 tiers. Wall-time estimate 3–5 hours.

After it finishes:
1. Pull data: `git pull push/runs-ibraheem`
2. Re-judge: `python -m bench.judge bench/results/ibraheem-paper-final-realworld-20260511-*`
3. Merge into final_paper_bench: `python -m bench.copy_to_final_bench ...`

## Known remaining limits

- **bugbench cases (bc/man/ncompress/polymorph)**: `bugbench-src/` has bc-1.06
  symlinked and configured, but ncompress/polymorph weren't pre-configured for
  this round. Their cells will likely still `build_failed`. ~27 cells.
- **T3 native gdb chatdbg plugin** (crashbench/juliet T3 on native path):
  adroit's system gdb uses Python 3.9; chatdbg requires Python 3.11+. The
  container path (used for BugsCPP) is fine; the native path (used for synth
  T3) cannot easily load chatdbg. ~33 cells.

After this run finishes, we'll have a clear measurement of: which T1 cells
get real model output (everything not bugbench), and which T3 berry cells
get through with the new trigger-quote fix. Together that's an expected
~80–100 of 161 cells truly run end-to-end.
