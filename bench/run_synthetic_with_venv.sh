#!/usr/bin/env bash
# Helper: source the Linux venv set up by bench/setup_wsl_venv.sh and
# export the orchestrator hooks (CHATDBG_MINI_PY) before forwarding all
# remaining args to bench.run_runset_shard.
#
# Why this exists: the synthetic panel needs orchestrator+tier1 to find
# mini-swe-agent's Python. We deliberately install the venv outside the
# repo dir on Anika's host (OneDrive/NTFS proxy is too slow). This
# wrapper is the single place that knows where the venv lives, so the
# rest of the workflow doesn't have to.
#
# Usage:
#   bash bench/run_synthetic_with_venv.sh \
#        --runset bench/results/final_paper_bench/_runset_locked.tsv \
#        --panel synthetic --tiers 1 --models openrouter/openai/gpt-4o \
#        --owner anika --runtime docker --workers 1 --timeout 600
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${CHATDBG_VENV:-$HOME/.venvs/chatdbg-bench}"

if [ ! -x "$VENV/bin/python3" ]; then
    echo "[run] venv not found at $VENV. Run bench/setup_wsl_venv.sh first." >&2
    exit 1
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
export CHATDBG_MINI_PY="$VENV/bin/python3"
export PYTHONUNBUFFERED=1

cd "$REPO"
exec python -m bench.run_runset_shard "$@"
