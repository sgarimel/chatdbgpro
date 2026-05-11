#!/usr/bin/env bash
# SLURM batch script for Adroit (Princeton HPC) — runs one (panel, tier, model)
# group from the locked runset. Submit one of these per group, OR submit one
# job that loops over all of Ibraheem's groups (synthetic vs realworld picked
# at submit time).
#
# Submit examples:
#   # Real-world panel, T1 (bash only), single model:
#   sbatch --export=ALL,PANEL=realworld,TIERS=1,MODEL=openrouter/openai/gpt-5.5 \
#       bench/sbatch_paper_final.sh
#
#   # Real-world panel, T3 (gdb only), single model, 8h wall:
#   sbatch --time=08:00:00 \
#       --export=ALL,PANEL=realworld,TIERS=3,MODEL=openrouter/anthropic/claude-sonnet-4.5 \
#       bench/sbatch_paper_final.sh
#
# Required env (passed via --export):
#   PANEL    synthetic | realworld
#   TIERS    space-separated codebase tier digits (1 3)
#   MODEL    one model id (loop over models with multiple sbatch submits)
#
# Optional env:
#   OWNER         tag for sweep dir name (default: $USER)
#   RUNSET        path to runset TSV (default: bench/results/final_paper_bench/_runset_locked.tsv)
#   WORKERS       parallel_run worker count (default: 8)
#   TIMEOUT       per-cell wall in seconds (default: 600)
#   AUTO_SYNC     if "1", run bench/sync_results_to_repo.sh after the sweep
#
#SBATCH --job-name=chatdbg-paper
#SBATCH --time=06:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=8
#SBATCH --output=logs/chatdbg-paper-%j.log
#SBATCH --error=logs/chatdbg-paper-%j.err

set -euo pipefail

mkdir -p logs

: "${PANEL:?PANEL env var required (synthetic|realworld)}"
: "${TIERS:?TIERS env var required (e.g. \"1 3\")}"
: "${MODEL:?MODEL env var required (e.g. openrouter/openai/gpt-5.5)}"
OWNER="${OWNER:-${USER}}"
RUNSET="${RUNSET:-bench/results/final_paper_bench/_runset_locked.tsv}"
WORKERS="${WORKERS:-2}"
TIMEOUT="${TIMEOUT:-600}"

cd "$SLURM_SUBMIT_DIR"

# Load Python (Adroit module names per ADROIT.md).
module load anaconda3 || true
module load singularity || true
module load intel-llvm/2024.2 || true
export PATH=$HOME/.conda/envs/clang-bench/bin:$PATH
export BENCH_APPTAINER_SIF_DIR=$HOME/.apptainer/cache
export LIBRARY_PATH=$HOME/.conda/envs/clang-bench/lib:${LIBRARY_PATH:-}

# Activate the project venv. Two paths supported: .venv (ADROIT.md style) and
# .venv-bench (Mac/dev style).
if [ -d .venv-bench ]; then
    # shellcheck disable=SC1091
    source .venv-bench/bin/activate
elif [ -d .venv ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
else
    echo "[sbatch] no venv found (.venv or .venv-bench). Aborting." >&2
    exit 2
fi

# OpenRouter / model API key.
if [ -f .env ]; then
    set -a; source .env; set +a
fi
: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY required (set in .env)}"

echo "[sbatch] PANEL=$PANEL TIERS=$TIERS MODEL=$MODEL OWNER=$OWNER WORKERS=$WORKERS"
echo "[sbatch] runset=$RUNSET timeout=$TIMEOUT runtime=apptainer"

python -m bench.run_runset_shard \
    --runset "$RUNSET" \
    --panel "$PANEL" \
    --tiers $TIERS \
    --models "$MODEL" \
    --owner "$OWNER" \
    --runtime apptainer \
    --workers "$WORKERS" \
    --timeout "$TIMEOUT"

if [ "${AUTO_SYNC:-0}" = "1" ]; then
    # Push every sweep dir matching this owner-panel-date prefix.
    DATE_TAG="$(date -u +%Y%m%d)"
    PATTERN="bench/results/${OWNER}-paper-final-${PANEL}-${DATE_TAG}-*"
    # shellcheck disable=SC2086
    bash bench/sync_results_to_repo.sh $(ls -d $PATTERN 2>/dev/null || true)
fi
