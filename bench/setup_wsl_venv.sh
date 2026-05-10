#!/usr/bin/env bash
# Build the two Linux Python venvs used by the synthetic-panel sweep.
#
# Two venvs, by design (see bench/drivers/tier1_minisweagent.py:8-19):
#   1. orchestrator venv  — chatdbg core; pyproject.toml pins litellm==1.55.9.
#   2. mini-swe-agent venv — used as a tool-call sandbox via $CHATDBG_MINI_PY.
#      mini-swe-agent>=2.2.8 requires litellm>=1.75.5, which conflicts with
#      chatdbg's pin. Keeping them separate is cleaner than forking either.
#
# Both venvs default to $HOME/.venvs (native ext4 — fast). On Anika's
# WSL2 host the repo lives on /mnt/c (OneDrive proxy) which is unusably
# slow for site-packages; on Adroit (native Linux) the same default is
# already what you want.
#
# Override paths via env:
#   CHATDBG_VENV       (default: $HOME/.venvs/chatdbg-bench) — orchestrator
#   CHATDBG_MINI_VENV  (default: $HOME/.venvs/chatdbg-mini)  — mini-swe-agent
#
# Idempotent. Safe to re-run.
#
# Usage (Linux shell, repo root):
#   bash bench/setup_wsl_venv.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_ORCH="${CHATDBG_VENV:-$HOME/.venvs/chatdbg-bench}"
VENV_MINI="${CHATDBG_MINI_VENV:-$HOME/.venvs/chatdbg-mini}"

echo "[setup] repo:       $REPO"
echo "[setup] orch venv:  $VENV_ORCH"
echo "[setup] mini venv:  $VENV_MINI"
echo "[setup] uname:      $(uname -a)"
echo "[setup] python:     $(command -v python3) — $(python3 --version)"

for tool in gcc clang python3 bash; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "[setup] FATAL: $tool not on PATH." >&2
        exit 1
    }
done

mkdir -p "$(dirname "$VENV_ORCH")" "$(dirname "$VENV_MINI")"

# --- Orchestrator venv ----------------------------------------------------
if [ ! -d "$VENV_ORCH" ]; then
    echo "[setup] creating orch venv at $VENV_ORCH"
    python3 -m venv "$VENV_ORCH"
fi
# shellcheck disable=SC1091
source "$VENV_ORCH/bin/activate"
python -m pip install --upgrade pip wheel

echo "[setup] orch: pip install -e $REPO  (pulls litellm==1.55.9)"
pip install -e "$REPO"
pip install \
    "PyYAML>=6.0.1" \
    "python-dotenv>=1.0.0" \
    "tqdm>=4.66.0" \
    "GitPython>=3.1.40"
deactivate

# --- mini-swe-agent venv --------------------------------------------------
if [ ! -d "$VENV_MINI" ]; then
    echo "[setup] creating mini venv at $VENV_MINI"
    python3 -m venv "$VENV_MINI"
fi
# shellcheck disable=SC1091
source "$VENV_MINI/bin/activate"
python -m pip install --upgrade pip wheel

echo "[setup] mini: pip install mini-swe-agent>=2.2.8 (pulls newer litellm)"
pip install "mini-swe-agent>=2.2.8"
deactivate

# --- Smoke check ----------------------------------------------------------
# Activate orch and verify it can resolve the mini Python via env var.
# shellcheck disable=SC1091
source "$VENV_ORCH/bin/activate"
export CHATDBG_MINI_PY="$VENV_MINI/bin/python3"

python - <<PY
import os, sys
sys.path.insert(0, "$REPO")
from bench.drivers import tier1_minisweagent as t1
print("[setup] CHATDBG_MINI_PY:", os.environ.get("CHATDBG_MINI_PY"))
print("[setup] t1._resolve_mini_py():", t1._resolve_mini_py())
print("[setup] mini Python exists:", t1._resolve_mini_py().exists())
PY

# Sanity-check mini venv too, by importing minisweagent from it directly.
"$VENV_MINI/bin/python3" -c "import minisweagent; print('[setup] minisweagent ok in mini venv')"

cat <<EOF

[setup] done.

[setup] Orchestrator venv:    $VENV_ORCH
[setup] mini-swe-agent venv:  $VENV_MINI

[setup] Per-invocation: bench/run_synthetic_with_venv.sh handles the
[setup] activation + CHATDBG_MINI_PY export. Use it instead of activating
[setup] manually.
EOF
