# Anika — synthetic panel runner handoff

> **2026-05-10 — partially superseded.** Steps 1–4 below were executed
> and key parts deviated from this doc:
>
> 1. Synthetic case ids aren't in `corpus.db`, so the `--docker --bug-ids`
>    path through `parallel_run.py` returns nothing. Patched: when
>    `--panel synthetic`, `run_runset_shard.py` now passes `--no-docker`
>    to `parallel_run.py`, which routes orchestrator through `--cases`
>    (on-disk discovery). No Docker needed for synthetic at all.
> 2. Native Windows lacks a C compiler and the bash sandbox mini-swe-agent
>    expects, so the runs happen inside **WSL2 Ubuntu** instead.
> 3. `mini-swe-agent>=2.2.8` requires `litellm>=1.75.5`, conflicting
>    with chatdbg's `litellm==1.55.9` pin. Two venvs are used:
>    `$HOME/.venvs/chatdbg-bench` (orch) + `$HOME/.venvs/chatdbg-mini`
>    (mini-swe-agent runner), bridged by `CHATDBG_MINI_PY`.
> 4. Build via `bench/setup_wsl_venv.sh`; run via
>    `bench/run_synthetic_with_venv.sh`.
>
> The full reproducible record (commands, outputs, failure→fix chain) is
> in **`bench/SETUP_LOG_anika_synthetic.md`** — read that first.

This file is the entry point for any Claude Code session running on Anika's
machine. Read this end-to-end first, then start at "Step-by-step run".

## Your slice

You own the **synthetic panel only**, **all tiers** (codebase T1 = bash-only
and codebase T3 = gdb-only). Ibraheem owns the realworld panel.

Your output sweep dirs will all be named:
```
bench/results/anika-paper-final-synthetic-<YYYYMMDD>-T<tier>-<modelslug>/
```
Each (tier, model) gets its own sweep dir. They never collide with Ibraheem's.

Cell counts (from `bench/results/final_paper_bench/_missing_synthetic.txt`):
- 209 missing cells across 8 models × {T1, T3}
- Plus a small bound-parity set produced by `bench/audit_bound_cells.py`

## Environment

You are on Windows, but you must run inside **WSL2** (Ubuntu).
- The persistent gdb session used by codebase tier 3 (gdb-only) calls
  `select.select` over POSIX pipe FDs and **does not work on native Windows**
  (see auto-memory: `project_windows_bench_blockers.md`).
- WSL2 makes everything behave like Linux. Docker Desktop's WSL backend
  exposes `docker` inside WSL.
- Repo path inside WSL: `/mnt/c/Users/Owner/OneDrive/Documents/Classes/COS/COS484/chatdbgpro`
  (or clone fresh into your WSL home for better disk I/O).

Required tools inside WSL:
- Python 3.11+ in a venv named `.venv-bench` (matches existing convention).
  If missing: `python3 -m venv .venv-bench && source .venv-bench/bin/activate &&
  pip install -e . && pip install pyyaml gitpython tqdm litellm`.
- Docker Desktop (Windows) with WSL2 integration enabled, OR apptainer.
- A populated `.env` at the repo root with `OPENROUTER_API_KEY=sk-or-...`.
  (`bench/orchestrator.py` loads dotenv automatically.)

## Branch convention

You commit and push to **`push/local-runs-anika`**. Do not push to Ibraheem's
branch. To pull his data when you need it, run
`git fetch origin && git merge origin/push/runs-ibraheem --no-edit`.

## Step-by-step run

```bash
cd ~/chatdbgpro                           # or /mnt/c/... if not cloned to home
git checkout push/local-runs-anika
git pull --rebase
source .venv-bench/bin/activate

# 1. Build the bound-cell parity list (one-shot, fast).
python -m bench.audit_bound_cells \
    --provenance bench/results/final_paper_bench/_provenance.json \
    --archive    bench/results/archive \
    --out        bench/results/final_paper_bench/_bound_cells.csv

# 2. Lock the runset.
python -m bench.build_runset \
    --missing-synthetic bench/results/final_paper_bench/_missing_synthetic.txt \
    --missing-realworld bench/results/final_paper_bench/_missing_realworld.txt \
    --bound-csv         bench/results/final_paper_bench/_bound_cells.csv \
    --out               bench/results/final_paper_bench/_runset_locked.tsv

# 3. Commit + push the locked runset so Ibraheem works from the same list.
bash bench/sync_results_to_repo.sh bench/results/final_paper_bench/_runset_locked.tsv \
                                   bench/results/final_paper_bench/_bound_cells.csv

# 4. Smoke-test exactly one synthetic cell (~5 min, sanity check).
python -m bench.run_runset_shard \
    --runset bench/results/final_paper_bench/_runset_locked.tsv \
    --panel synthetic \
    --tiers 1 \
    --models openrouter/openai/gpt-5.5 \
    --owner anika \
    --runtime docker \
    --workers 1 \
    --timeout 600

# Inspect the resulting sweep dir; confirm collect.json + result.json land:
ls bench/results/anika-paper-final-synthetic-*-T1-*/

# 5. Run the full synthetic shard. This is the long one — overnight at worst.
python -m bench.run_runset_shard \
    --runset bench/results/final_paper_bench/_runset_locked.tsv \
    --panel synthetic \
    --owner anika \
    --runtime docker \
    --workers 8 \
    --timeout 600

# 6. Periodically (every ~10-30 min during long sweeps), push fresh data:
bash bench/sync_results_to_repo.sh bench/results/anika-paper-final-synthetic-*

# 7. After the shard finishes, merge cells into the curated dir + push:
python -m bench.copy_to_final_bench \
    $(for d in bench/results/anika-paper-final-synthetic-*; do printf -- "--sweep %s " "$d"; done) \
    --runset bench/results/final_paper_bench/_runset_locked.tsv \
    --final  bench/results/final_paper_bench

bash bench/sync_results_to_repo.sh bench/results/final_paper_bench
```

## If anything breaks

- `--skip-existing` (already on by default in `run_runset_shard.py` via
  `parallel_run.py`) means re-running step 5 picks up where a crashed run left
  off. Just re-issue the command.
- If a particular (tier, model) group fails repeatedly, isolate it:
  `--tiers <N> --models <ID>` and re-run with `--workers 1` to see clean logs.
- If docker chokes inside WSL: restart Docker Desktop, then check
  `docker info` from WSL. Apptainer is a fallback (`--runtime apptainer`)
  but you'd need `module load singularity` equivalent on WSL — not standard.
- For long-running sweeps, run inside `tmux` or `screen` so the sweep survives
  SSH disconnects.

## When to stop running and hand off to the team

Once `find bench/results/final_paper_bench/synthetic -name collect.json | wc -l`
equals 320 (the synthetic panel target), you're done with the agent runs.
Tell the team in chat; whoever has bandwidth will run `bench/judge.py
--overwrite` over the merged dir.

## Reference

- Project plan: `bench_execution_plan.md` at repo root
- Tier label scheme: see "Tier-label scheme" section of the plan
- Existing memory notes that apply to this work:
  `project_windows_bench_blockers.md`, `reference_local_windows_setup.md`,
  `project_t3_unfence_fix_partial.md`
