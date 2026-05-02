#!/usr/bin/env bash
# Full overnight preprocessing + ablation pipeline. Designed to run unattended.
#
# Stages:
#   1. Load OPENROUTER/OPENAI keys from .env
#   2. Kill any orphaned bugscpp dpp containers from prior runs
#   3. Audit + reset zombie corpus rows (build_ok=1 but binary not on disk)
#   4. Run pipeline2/build.py --resume --workers 2 to (re)build the queue
#   5. Print final corpus state
#   6. Run bench/orchestrator.py --docker on every included bug
#   7. Print ablation summary
#
# Logs everything to logs/run_overnight_<timestamp>.log (and stdout via tee).
# Resumable: if interrupted, re-running picks up where build.py left off.

set -uo pipefail

cd "$(dirname "$0")"

mkdir -p logs
TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/run_overnight_${TS}.log"
exec > >(tee -a "$LOG") 2>&1

banner() {
  echo
  echo "============================================================"
  echo "$@"
  echo "============================================================"
}

banner "ChatDBG Pro: full preprocessing + ablation pipeline"
echo "started: $(date)"
echo "log:     $LOG"

# ---------- 1. API keys ----------------------------------------------------
banner "[1/7] Load API keys from .env"
if [ ! -f .env ]; then
  echo "ERROR: .env file missing"; exit 1
fi
# .env uses 'KEY = value' format with spaces; strip the prefix and trim.
export OPENROUTER_API_KEY="$(grep -E '^OPENROUTER_API_KEY' .env \
  | sed -E 's/^[^=]*=[[:space:]]*//' | tr -d ' \r\n')"
export OPENAI_API_KEY="$(grep -E '^OPENAI_API_KEY' .env \
  | sed -E 's/^[^=]*=[[:space:]]*//' | tr -d ' \r\n')"
if [ -z "$OPENROUTER_API_KEY" ]; then
  echo "ERROR: OPENROUTER_API_KEY not parsed from .env"; exit 1
fi
echo "OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:0:12}... (len=${#OPENROUTER_API_KEY})"
echo "OPENAI_API_KEY:     ${OPENAI_API_KEY:0:12}... (len=${#OPENAI_API_KEY})"

# Bind-mount paths must not be MSYS-rewritten on Windows.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

# ---------- 2. Pre-flight container cleanup --------------------------------
banner "[2/7] Pre-flight cleanup of orphaned dpp containers"
ORPHANS=$(docker ps -q --filter 'name=-dpp' 2>/dev/null || true)
if [ -n "$ORPHANS" ]; then
  echo "killing $(echo "$ORPHANS" | wc -l) orphaned containers"
  for c in $ORPHANS; do docker kill "$c" 2>&1 | head -1 || true; done
else
  echo "no orphans"
fi

# ---------- 3. Audit + reset zombie rows -----------------------------------
banner "[3/7] Audit corpus, reset zombie rows"
python pipeline2/audit_and_reset.py
echo
python pipeline2/progress.py | head -28

# ---------- 4. Build retry --------------------------------------------------
banner "[4/7] Build retry (workers=2)"
echo "started: $(date)"
BUGSCPP_REPO=../bugscpp python pipeline2/build.py --resume --workers 2 \
  || echo "[warn] build.py exited non-zero; continuing"
echo "finished: $(date)"

# ---------- 5. Post-build corpus state -------------------------------------
banner "[5/7] Final corpus state"
python pipeline2/progress.py

# ---------- 6. Ablations ----------------------------------------------------
banner "[6/7] Ablations via DockerDriver"
echo "started: $(date)"
INCLUDED=$(python -c "
import sqlite3
print(sqlite3.connect('data/corpus.db').execute(
    'SELECT COUNT(*) FROM bugs WHERE included_in_corpus=1'
).fetchone()[0])
")
echo "running ablations on $INCLUDED included bugs"

# Use a single free model + the gdb-only tool config for the unattended pass.
# Re-run later with different --models / --tool-configs as needed.
python bench/orchestrator.py --docker \
  --models openrouter/meta-llama/llama-3.1-8b-instruct:free \
  --tool-configs tier3_gdb_only \
  --tiers 3 --trials 1 --timeout 240 \
  --name "full-${TS}" \
  || echo "[warn] orchestrator exited non-zero; continuing"
echo "finished: $(date)"

# ---------- 7. Ablation summary --------------------------------------------
banner "[7/7] Ablation summary"
RUN_DIR="bench/results/full-${TS}"
if [ -d "$RUN_DIR" ]; then
  echo "results dir: $RUN_DIR"
  python -c "
import json, pathlib
idx = json.loads((pathlib.Path('$RUN_DIR') / 'index.json').read_text())
from collections import Counter
c = Counter(r.get('status', 'unknown') for r in idx)
print(f'total runs: {len(idx)}')
for status, n in sorted(c.items(), key=lambda x: -x[1]):
    print(f'  {status:20} {n}')
"
else
  echo "no results dir at $RUN_DIR"
fi

banner "Pipeline complete"
echo "finished: $(date)"
echo "log:      $LOG"
