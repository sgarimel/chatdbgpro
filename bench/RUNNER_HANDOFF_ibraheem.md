# Ibraheem — realworld panel runner handoff (Adroit / Princeton HPC)

This file is the entry point for any Claude Code session running on Ibraheem's
Adroit account. Read this end-to-end first, then start at "Step-by-step run".

## Your slice

You own the **realworld panel only**, **all tiers** (codebase T1 = bash-only
and codebase T3 = gdb-only). Anika owns the synthetic panel.

Your output sweep dirs will all be named:
```
bench/results/ibraheem-paper-final-realworld-<YYYYMMDD>-T<tier>-<modelslug>/
```
Each (tier, model) gets its own sweep dir. They never collide with Anika's.

Cell counts (from `bench/results/final_paper_bench/_missing_realworld.txt`):
- 156 missing cells across 8 models × {T1, T3}
- Plus a small bound-parity set from `bench/audit_bound_cells.py`

## Environment (Adroit)

Reference: `ADROIT.md` at repo root. Summary:

```bash
ssh <netid>@adroit.princeton.edu
git clone https://github.com/sgarimel/chatdbgpro.git
cd chatdbgpro

module load anaconda3
module load singularity            # apptainer is the runtime on Adroit
python3 -m venv .venv-bench
source .venv-bench/bin/activate
pip install -e . && pip install pyyaml gitpython tqdm litellm

# API key
cat > .env <<'EOF'
OPENROUTER_API_KEY=sk-or-...
ANTHROPIC_API_KEY=...        # only if you also plan to run T4
EOF
```

Adroit does **not** allow Docker. Use `--runtime apptainer` everywhere. The
BugsCPP images live on GHCR; pull them once:
```bash
bash scripts/pull_gdb_images.sh        # one-time; takes ~10 min
```

## Branch convention

You commit and push to **`push/runs-ibraheem`**. Create it if it doesn't
exist:
```bash
git checkout -b push/runs-ibraheem origin/main 2>/dev/null || git checkout push/runs-ibraheem
git push -u origin push/runs-ibraheem
```
Do not push to Anika's branch. To pull her data when you need it:
```bash
git fetch origin && git merge origin/push/local-runs-anika --no-edit
```

## Step-by-step run

There are two ways to run: **interactive** (small smoke runs) and **sbatch**
(everything else). Always sbatch for the full sweep.

### Phase 1 — prep (interactive)

```bash
cd ~/chatdbgpro
git pull --rebase
source .venv-bench/bin/activate

# 1. Confirm the locked runset already exists. Anika is supposed to push it
# first. If missing, build it yourself (idempotent — same output either way).
ls bench/results/final_paper_bench/_runset_locked.tsv 2>/dev/null || \
python -m bench.audit_bound_cells \
    --provenance bench/results/final_paper_bench/_provenance.json \
    --archive    bench/results/archive \
    --out        bench/results/final_paper_bench/_bound_cells.csv && \
python -m bench.build_runset \
    --missing-synthetic bench/results/final_paper_bench/_missing_synthetic.txt \
    --missing-realworld bench/results/final_paper_bench/_missing_realworld.txt \
    --bound-csv         bench/results/final_paper_bench/_bound_cells.csv \
    --out               bench/results/final_paper_bench/_runset_locked.tsv

# 2. Smoke-test one realworld cell interactively (~5 min). Pick a small case.
python -m bench.run_runset_shard \
    --runset bench/results/final_paper_bench/_runset_locked.tsv \
    --panel realworld \
    --tiers 1 \
    --models openrouter/openai/gpt-5.5 \
    --owner ibraheem \
    --runtime apptainer \
    --workers 1 \
    --timeout 600
```

If the smoke run produced `bench/results/ibraheem-paper-final-realworld-*-T1-*/
<case>__tier1__*/collect.json`, you're good.

### Phase 2 — full sweep (sbatch)

Submit one job per (tier, model) group, OR submit one job that iterates over
groups. The simpler pattern is one-per-model:

```bash
mkdir -p logs

# Realworld T1 across all 8 models:
for m in \
    openrouter/anthropic/claude-sonnet-4.5 \
    openrouter/google/gemini-2.5-flash \
    openrouter/google/gemini-3.1-flash-lite-preview \
    openrouter/meta-llama/llama-3.1-8b-instruct \
    openrouter/nvidia/nemotron-3-nano-30b-a3b \
    openrouter/openai/gpt-4o \
    openrouter/openai/gpt-5.5 \
    openrouter/qwen/qwen3-30b-a3b-instruct-2507 \
    openrouter/x-ai/grok-4
do
    sbatch --time=04:00:00 \
        --export=ALL,PANEL=realworld,TIERS=1,MODEL="$m",OWNER=ibraheem,AUTO_SYNC=1 \
        bench/sbatch_paper_final.sh
done

# Realworld T3 (gdb only) across all 8 models:
for m in \
    openrouter/anthropic/claude-sonnet-4.5 \
    openrouter/google/gemini-2.5-flash \
    openrouter/google/gemini-3.1-flash-lite-preview \
    openrouter/meta-llama/llama-3.1-8b-instruct \
    openrouter/nvidia/nemotron-3-nano-30b-a3b \
    openrouter/openai/gpt-4o \
    openrouter/openai/gpt-5.5 \
    openrouter/qwen/qwen3-30b-a3b-instruct-2507 \
    openrouter/x-ai/grok-4
do
    sbatch --time=06:00:00 \
        --export=ALL,PANEL=realworld,TIERS=3,MODEL="$m",OWNER=ibraheem,AUTO_SYNC=1 \
        bench/sbatch_paper_final.sh
done

squeue -u "$USER"
tail -f logs/chatdbg-paper-*.log
```

`AUTO_SYNC=1` makes each job commit + push its own sweep dirs to
`push/runs-ibraheem` as soon as it finishes. If you'd rather batch the syncs
manually, drop that env and run `bench/sync_results_to_repo.sh` yourself.

### Phase 3 — merge into final_paper_bench/

After all jobs finish:
```bash
python -m bench.copy_to_final_bench \
    $(for d in bench/results/ibraheem-paper-final-realworld-*; do printf -- "--sweep %s " "$d"; done) \
    --runset bench/results/final_paper_bench/_runset_locked.tsv \
    --final  bench/results/final_paper_bench

bash bench/sync_results_to_repo.sh bench/results/final_paper_bench
```

## If anything breaks

- A SLURM job dying mid-sweep doesn't lose data: `--skip-existing` (built into
  the orchestrator path used by `parallel_run.py`) makes resubmission
  idempotent. Just resubmit the same sbatch.
- If apptainer can't find an image, run `bash scripts/pull_gdb_images.sh`
  again. The image name embedded in the BugsCPP case YAMLs is the source of
  truth.
- If an entire model produces 0/N successful cells, it's almost always an API
  key / rate-limit issue, not a code issue. Check `logs/*.err` for HTTP 401
  / 429.
- For long debugging sessions outside sbatch, use `tmux` so the run survives
  SSH disconnect.

## When to stop running and hand off

Once `find bench/results/final_paper_bench/realworld -name collect.json | wc -l`
equals 320 (the realworld panel target), you're done. Tell the team; whoever
has bandwidth will run `bench/judge.py --overwrite` on the merged dir.

## Reference

- Project plan: `bench_execution_plan.md` at repo root
- Adroit setup notes: `ADROIT.md`
- Tier label scheme: see "Tier-label scheme" section of the plan
