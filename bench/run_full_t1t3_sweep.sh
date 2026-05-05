#!/usr/bin/env bash
# Launch the full BugsCPP T1+T3 sweep across the 6 confirmed model slugs,
# under bench/parallel_run.py with --workers 8, plus the credit watchdog
# and the live judge+analyze refresh loop.
#
# This script does NOT block — it backgrounds three processes and prints
# their PIDs + log paths so the user can tail or kill them independently.
#
# Usage:
#   bash bench/run_full_t1t3_sweep.sh [--name NAME] [--workers N] [--judge-model M]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

NAME=""
WORKERS=8
JUDGE_MODEL="openrouter/openai/gpt-4o"
TIMEOUT=540
TIERS=(1 3)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --workers) WORKERS="$2"; shift 2 ;;
    --judge-model) JUDGE_MODEL="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -z "$NAME" ]] && NAME="full-bugscpp-t1t3-$(date +%Y%m%d-%H%M%S)"
SWEEP_DIR="bench/results/$NAME"
mkdir -p "$SWEEP_DIR/_logs"

# Source .env so OPENROUTER/OPENAI keys are visible to subprocesses.
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

# Pull all included BugsCPP bug ids.
mapfile -t BUG_IDS < <(python -c "
import sqlite3
c = sqlite3.connect('data/corpus.db')
for (b,) in c.execute('SELECT bug_id FROM bugs WHERE included_in_corpus=1 ORDER BY project, bug_index'):
    print(b)
")
if [[ "${#BUG_IDS[@]}" -lt 50 ]]; then
  echo "Only ${#BUG_IDS[@]} bug ids found in corpus.db — aborting (expected ~148)" >&2
  exit 1
fi

MODELS=(
  openrouter/openai/gpt-5.5
  openrouter/openai/gpt-4o
  openrouter/google/gemini-2.5-flash
  openrouter/nvidia/nemotron-3-nano-30b-a3b
  openrouter/qwen/qwen3-30b-a3b-instruct-2507
  openrouter/meta-llama/llama-3.1-8b-instruct
)

N_CELLS=$(( ${#BUG_IDS[@]} * ${#MODELS[@]} * ${#TIERS[@]} ))

echo "[full-sweep] name:    $NAME"
echo "[full-sweep] bugs:    ${#BUG_IDS[@]}"
echo "[full-sweep] models:  ${#MODELS[@]}"
echo "[full-sweep] tiers:   ${TIERS[*]}"
echo "[full-sweep] cells:   $N_CELLS"
echo "[full-sweep] workers: $WORKERS"
echo "[full-sweep] timeout: ${TIMEOUT}s/cell"
echo "[full-sweep] sweep dir: $SWEEP_DIR"

# 1. Sweep (background)
nohup python -m bench.parallel_run \
  --bug-ids "${BUG_IDS[@]}" \
  --tiers "${TIERS[@]}" \
  --models "${MODELS[@]}" \
  --runtime docker \
  --workers "$WORKERS" \
  --timeout "$TIMEOUT" \
  --name "$NAME" \
  > "$SWEEP_DIR/_logs/sweep.log" 2>&1 &
SWEEP_PID=$!
echo "[full-sweep] sweep pid: $SWEEP_PID  (log: $SWEEP_DIR/_logs/sweep.log)"

# 2. Watchdog (background) — kills sweep on credit/quota exhaustion
nohup python -m bench.watchdog \
  --sweep-dir "$SWEEP_DIR" \
  --pid "$SWEEP_PID" \
  --target-cells "$N_CELLS" \
  --window 20 --threshold 5 --poll-interval 60 \
  > "$SWEEP_DIR/_logs/watchdog.log" 2>&1 &
WD_PID=$!
echo "[full-sweep] watchdog pid: $WD_PID  (log: $SWEEP_DIR/_logs/watchdog.log)"

# 3. Live refresh (background) — periodic judge + analyze + PDF rebuild
nohup python -m bench.live_refresh \
  --sweep-dir "$SWEEP_DIR" \
  --judge-model "$JUDGE_MODEL" \
  --interval 600 \
  > "$SWEEP_DIR/_logs/live_refresh.log" 2>&1 &
LR_PID=$!
echo "[full-sweep] live-refresh pid: $LR_PID  (log: $SWEEP_DIR/_logs/live_refresh.log)"

# Pin pids for the closeout step.
cat > "$SWEEP_DIR/_logs/pids.txt" <<EOF
sweep=$SWEEP_PID
watchdog=$WD_PID
live_refresh=$LR_PID
sweep_name=$NAME
EOF

echo "[full-sweep] all 3 background processes launched. monitor with:"
echo "  tail -f $SWEEP_DIR/_logs/sweep.log"
echo "  tail -f $SWEEP_DIR/_logs/watchdog.log"
echo "  tail -f $SWEEP_DIR/_logs/live_refresh.log"
