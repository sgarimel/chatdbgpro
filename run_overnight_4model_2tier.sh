#!/usr/bin/env bash
# Overnight 4-model × 2-tier ablation on the full BugsCPP corpus.
#
# Step 1: Tier 1 (gdb only) — all 158 bugs × 4 models.
# Step 2: Judge step 1 outputs with gpt-4o.
# Step 3: Tier 2 (gdb + bash) — all 158 bugs × 4 models.
# Step 4: Judge step 3 outputs with gpt-4o.
#
# Both run-trees and their score.json files are preserved under
# bench/results/<name>/<run>/. The bash script is fully unattended;
# no prompts or approvals after launch.
#
# Resume: if a step is interrupted, re-running this script will skip
# any already-completed step (detected by the presence of index.json
# with the expected number of entries — 632 = 4 models * 158 bugs).
# Partial step indexes are NOT considered done; restart that step from
# scratch by deleting the partial run dir.

set -uo pipefail

cd "$(dirname "$0")"

mkdir -p logs
TS="${OVERNIGHT_TS:-$(date +%Y%m%d_%H%M%S)}"
LOG="logs/overnight_4m2t_${TS}.log"
exec > >(tee -a "$LOG") 2>&1

banner() { echo; echo "============================================================"; echo "$@"; echo "============================================================"; }

banner "Overnight 4-model × 2-tier ablation"
echo "started:    $(date)"
echo "log:        $LOG"
echo "session ts: $TS"

# ---------- API keys ------------------------------------------------------
banner "[0/5] Load API keys from .env"
if [ ! -f .env ]; then
  echo "FATAL: .env missing"; exit 1
fi
export OPENROUTER_API_KEY="$(grep -E '^OPENROUTER_API_KEY' .env | sed -E 's/^[^=]*=[[:space:]]*//' | tr -d ' \r\n')"
export OPENAI_API_KEY="$(grep -E '^OPENAI_API_KEY' .env | sed -E 's/^[^=]*=[[:space:]]*//' | tr -d ' \r\n')"
if [ -z "$OPENROUTER_API_KEY" ]; then echo "FATAL: OPENROUTER_API_KEY not parsed"; exit 1; fi
echo "OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:0:12}... (len=${#OPENROUTER_API_KEY})"
echo "OPENAI_API_KEY:     ${OPENAI_API_KEY:0:12}... (len=${#OPENAI_API_KEY})"

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'
export PYTHONIOENCODING=utf-8

# ---------- Pre-flight: kill orphan containers ---------------------------
banner "[1/5] Pre-flight cleanup"
ORPHANS=$(docker ps -q --filter 'name=-dpp' 2>/dev/null | grep -v '^$' || true)
if [ -n "$ORPHANS" ]; then
  echo "Killing $(echo "$ORPHANS" | wc -l) orphaned dpp containers..."
  for c in $ORPHANS; do docker kill "$c" >/dev/null 2>&1 || true; done
fi

# Kill any non-dpp containers from a previous interrupted ablation run
# (these are the per-bug gdb-image containers — naming pattern is random).
LEFTOVER=$(docker ps --format "{{.ID}}" --filter "ancestor=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^chatdbgpro/gdb-' | head -1)" 2>/dev/null || true)
if [ -n "$LEFTOVER" ]; then
  for c in $LEFTOVER; do docker kill "$c" >/dev/null 2>&1 || true; done
  echo "Killed $(echo "$LEFTOVER" | wc -l) leftover gdb containers"
fi

# ---------- Confirm corpus ready ------------------------------------------
INCLUDED=$(python -c "import sqlite3; print(sqlite3.connect('data/corpus.db').execute('SELECT COUNT(*) FROM bugs WHERE included_in_corpus=1').fetchone()[0])")
echo "corpus included bugs: $INCLUDED"
EXPECTED_RUNS=$((INCLUDED * 4))
echo "expected runs per tier: $EXPECTED_RUNS (= $INCLUDED * 4 models)"

# ---------- Models we sweep -----------------------------------------------
MODELS=(
  "openrouter/meta-llama/llama-3.1-8b-instruct"
  "openrouter/nvidia/nemotron-3-nano-30b-a3b"
  "openrouter/qwen/qwen3-30b-a3b-instruct-2507"
  "openrouter/openai/gpt-4o"
)

# Helper: did a tier already complete? Returns 0 if all $EXPECTED_RUNS
# entries are present in index.json.
tier_complete() {
  local rd="$1"
  local idx="$rd/index.json"
  [ -f "$idx" ] || return 1
  local n
  n=$(python -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "$idx" 2>/dev/null || echo 0)
  [ "$n" = "$EXPECTED_RUNS" ]
}

# Helper: did a tier already get judged? Returns 0 if every run dir has
# a score.json.
tier_judged() {
  local rd="$1"
  local total scored
  total=$(find "$rd" -name result.json 2>/dev/null | wc -l)
  scored=$(find "$rd" -name score.json 2>/dev/null | wc -l)
  [ "$total" -gt 0 ] && [ "$scored" = "$total" ]
}

run_tier() {
  local label="$1"        # "tier1" or "tier2"
  local config="$2"       # tool-config name
  local rd_name="overnight-${label}-${TS}"
  local rd="bench/results/${rd_name}"

  banner "[$3] ${label} sweep — config=${config}"
  echo "started: $(date)"
  if tier_complete "$rd"; then
    echo "tier already complete (index.json has $EXPECTED_RUNS entries) — skipping"
  else
    python bench/orchestrator.py --docker \
      --models "${MODELS[@]}" \
      --tool-configs "$config" \
      --tiers 3 --trials 1 --timeout 360 \
      --name "$rd_name" \
      || echo "[warn] orchestrator exited non-zero; continuing"
  fi
  echo "${label} run finished: $(date)"

  banner "[$4] ${label} judging — gpt-4o"
  echo "started: $(date)"
  if tier_judged "$rd"; then
    echo "tier already fully judged — skipping"
  else
    python -m bench.judge "$rd" \
      --judge-model openrouter/openai/gpt-4o \
      --temperature 0 \
      || echo "[warn] judge exited non-zero; continuing"
  fi
  echo "${label} judging finished: $(date)"

  # Per-tier summary
  python - <<PY
import json, collections
from pathlib import Path
rd = Path("$rd")
idx_path = rd / "index.json"
runs = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else []
print(f"=== ${label} summary ===")
print(f"runs in index: {len(runs)}")
status_c = collections.Counter(r.get("status") for r in runs)
for s, n in status_c.most_common():
    print(f"  status {s}: {n}")
# Score breakdown
by_model = collections.defaultdict(lambda: {"n":0, "rc":0, "lf":0, "gf":0, "any":0})
for r in runs:
    rid = r["run_id"]
    score_p = rd / rid / "score.json"
    if not score_p.exists(): continue
    try:
        s = json.loads(score_p.read_text(encoding="utf-8")).get("scores", {})
    except Exception:
        continue
    m = r["model"].split("/")[-1]
    by_model[m]["n"] += 1
    rc = int(s.get("root_cause", 0))
    lf = int(s.get("local_fix", 0))
    gf = int(s.get("global_fix", 0))
    by_model[m]["rc"] += rc
    by_model[m]["lf"] += lf
    by_model[m]["gf"] += gf
    if rc or lf or gf: by_model[m]["any"] += 1
print(f"{'model':35} {'judged':6} {'rc':>5} {'lf':>5} {'gf':>5} {'any>0':>7}")
for m, c in sorted(by_model.items()):
    print(f"  {m:33} {c['n']:>6} {c['rc']:>5} {c['lf']:>5} {c['gf']:>5} {c['any']:>7}")
PY
}

# ---------- Step 1+2: Tier 1 (gdb only) ----------------------------------
run_tier "tier1" "tier3_gdb_only" "2/5" "3/5"

# Cleanup any orphans before the heavier tier 2 sweep
ORPHANS=$(docker ps -q --filter 'name=-dpp' 2>/dev/null | grep -v '^$' || true)
if [ -n "$ORPHANS" ]; then for c in $ORPHANS; do docker kill "$c" >/dev/null 2>&1 || true; done; fi

# ---------- Step 3+4: Tier 2 (gdb + bash) --------------------------------
run_tier "tier2" "tier2_bash_plus_gdb" "4/5" "5/5"

# ---------- Final report --------------------------------------------------
banner "All steps complete"
echo "finished: $(date)"
echo "tier1 results: bench/results/overnight-tier1-${TS}/"
echo "tier2 results: bench/results/overnight-tier2-${TS}/"
echo "log:           $LOG"
