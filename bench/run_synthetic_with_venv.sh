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
# Two venvs (see bench/setup_wsl_venv.sh and bench/SETUP_LOG_anika_synthetic.md):
#   ORCH = chatdbg core (litellm 1.55.9)        — runs the orchestrator.
#   MINI = mini-swe-agent runner (litellm 1.83) — bridged via $CHATDBG_MINI_PY.
VENV_ORCH="${CHATDBG_VENV:-$HOME/.venvs/chatdbg-bench}"
VENV_MINI="${CHATDBG_MINI_VENV:-$HOME/.venvs/chatdbg-mini}"

for v in "$VENV_ORCH" "$VENV_MINI"; do
    if [ ! -x "$v/bin/python3" ]; then
        echo "[run] venv missing at $v. Run bench/setup_wsl_venv.sh first." >&2
        exit 1
    fi
done

# shellcheck disable=SC1091
source "$VENV_ORCH/bin/activate"
# Export both venv hooks for the orchestrator subprocesses:
#   CHATDBG_MINI_PY — tier1 driver's mini-swe-agent venv lookup
#   CHATDBG_VENV    — tier3 driver's PYTHONPATH lookup for the embedded
#                     gdb/lldb Python (resolves the orch venv's
#                     site-packages so chatdbg + llm_utils + litellm
#                     are importable from inside gdb)
export CHATDBG_MINI_PY="$VENV_MINI/bin/python3"
export CHATDBG_VENV="$VENV_ORCH"
export PYTHONUNBUFFERED=1

cd "$REPO"
exec python -m bench.run_runset_shard "$@"
