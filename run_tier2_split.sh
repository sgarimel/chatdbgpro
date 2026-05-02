#!/usr/bin/env bash
# Run tier 2 (gdb + bash) with the 3 fast models first, judge them, then
# run tier 2 with Nemotron alone, judge it. Nemotron is split out because
# its per-run wall time (~190s ok / 360s timeout) is ~10x the others, so
# isolating it lets the fast models complete + get scored quickly while
# Nemotron grinds in the background.
#
# Run dirs:
#   bench/results/overnight-tier2-<TS>-3models/    Llama, Qwen, GPT-4o
#   bench/results/overnight-tier2-<TS>-nemotron/   Nemotron only
#
# TS is taken from $OVERNIGHT_TS if set, else newly minted.

set -uo pipefail

cd "$(dirname "$0")"

mkdir -p logs
TS="${OVERNIGHT_TS:-$(date +%Y%m%d_%H%M%S)}"
LOG="logs/tier2_split_${TS}.log"
exec > >(tee -a "$LOG") 2>&1

banner() { echo; echo "============================================================"; echo "$@"; echo "============================================================"; }

banner "Tier 2 split — 3 fast models first, Nemotron after"
echo "started:    $(date)"
echo "log:        $LOG"
echo "session ts: $TS"

# ---------- API keys ------------------------------------------------------
banner "[0/4] Load API keys from .env"
if [ ! -f .env ]; then echo "FATAL: .env missing"; exit 1; fi
export OPENROUTER_API_KEY="$(grep -E '^OPENROUTER_API_KEY' .env | sed -E 's/^[^=]*=[[:space:]]*//' | tr -d ' \r\n')"
export OPENAI_API_KEY="$(grep -E '^OPENAI_API_KEY' .env | sed -E 's/^[^=]*=[[:space:]]*//' | tr -d ' \r\n')"
if [ -z "$OPENROUTER_API_KEY" ]; then echo "FATAL: OPENROUTER_API_KEY not parsed"; exit 1; fi
echo "OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:0:12}... (len=${#OPENROUTER_API_KEY})"

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'
export PYTHONIOENCODING=utf-8

INCLUDED=$(python -c "import sqlite3; print(sqlite3.connect('data/corpus.db').execute('SELECT COUNT(*) FROM bugs WHERE included_in_corpus=1').fetchone()[0])")
echo "corpus included bugs: $INCLUDED"

THREE_MODELS=(
  "openrouter/meta-llama/llama-3.1-8b-instruct"
  "openrouter/qwen/qwen3-30b-a3b-instruct-2507"
  "openrouter/openai/gpt-4o"
)
NEMOTRON_MODEL="openrouter/nvidia/nemotron-3-nano-30b-a3b"

EXPECT_3M=$((INCLUDED * 3))
EXPECT_1M=$((INCLUDED))

# Clean up any orphan dpp containers before starting
ORPHANS=$(docker ps -q --filter 'name=-dpp' 2>/dev/null | grep -v '^$' || true)
if [ -n "$ORPHANS" ]; then
  for c in $ORPHANS; do docker kill "$c" >/dev/null 2>&1 || true; done
fi

tier_complete() {
  local rd="$1"; local expect="$2"
  local idx="$rd/index.json"
  [ -f "$idx" ] || return 1
  local n
  n=$(python -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "$idx" 2>/dev/null || echo 0)
  [ "$n" = "$expect" ]
}

tier_judged() {
  local rd="$1"
  local total scored
  total=$(find "$rd" -name result.json 2>/dev/null | wc -l)
  scored=$(find "$rd" -name score.json 2>/dev/null | wc -l)
  [ "$total" -gt 0 ] && [ "$scored" = "$total" ]
}

per_tier_summary() {
  local rd="$1"; local label="$2"
  python - "$rd" "$label" <<'PY'
import sys, json, collections
from pathlib import Path
rd, label = Path(sys.argv[1]), sys.argv[2]
idx = json.loads((rd / "index.json").read_text(encoding="utf-8"))
status_c = collections.Counter(r.get("status") for r in idx)
print(f"\n=== {label} summary ===")
print(f"runs: {len(idx)}")
for s, n in status_c.most_common():
    print(f"  {s}: {n}")
by_model = collections.defaultdict(lambda: {"n":0,"rc":0,"lf":0,"gf":0,"any":0})
for r in idx:
    sp = rd / r["run_id"] / "score.json"
    if not sp.exists(): continue
    try:
        ss = json.loads(sp.read_text(encoding="utf-8")).get("scores", {})
    except Exception:
        continue
    m = r["model"].split("/")[-1]
    by_model[m]["n"] += 1
    rc = int(ss.get("root_cause", 0)); lf = int(ss.get("local_fix", 0)); gf = int(ss.get("global_fix", 0))
    by_model[m]["rc"] += rc; by_model[m]["lf"] += lf; by_model[m]["gf"] += gf
    if rc or lf or gf: by_model[m]["any"] += 1
print(f"{'model':40} {'n':>4} {'rc':>4} {'lf':>4} {'gf':>4} {'any':>4}")
for m, c in sorted(by_model.items()):
    print(f"  {m:38} {c['n']:>4} {c['rc']:>4} {c['lf']:>4} {c['gf']:>4} {c['any']:>4}")
PY
}

run_chunk() {
  local rd_name="$1"; shift
  local expect="$1"; shift
  local label="$1"; shift
  # remaining args are the model URIs

  local rd="bench/results/${rd_name}"

  banner "${label}: orchestrator (config=tier2_bash_plus_gdb)"
  echo "started: $(date)"
  if tier_complete "$rd" "$expect"; then
    echo "already complete (index.json has $expect entries) — skipping"
  else
    python bench/orchestrator.py --docker \
      --models "$@" \
      --tool-configs tier2_bash_plus_gdb \
      --tiers 3 --trials 1 --timeout 360 \
      --name "$rd_name" \
      || echo "[warn] orchestrator exited non-zero; continuing"
  fi
  echo "${label} sweep finished: $(date)"

  banner "${label}: judge (gpt-4o via openrouter)"
  echo "started: $(date)"
  if tier_judged "$rd"; then
    echo "already fully judged — skipping"
  else
    python -m bench.judge "$rd" \
      --judge-model openrouter/openai/gpt-4o \
      --temperature 0 \
      || echo "[warn] judge exited non-zero; continuing"
  fi
  echo "${label} judge finished: $(date)"

  per_tier_summary "$rd" "$label"
}

# ---------- Step 1+2: Tier 2 / 3 fast models -----------------------------
run_chunk "overnight-tier2-${TS}-3models" \
          "$EXPECT_3M" "[1+2/4] tier2-3models" \
          "${THREE_MODELS[@]}"

# Cleanup orphans before nemotron's slower sweep
ORPHANS=$(docker ps -q --filter 'name=-dpp' 2>/dev/null | grep -v '^$' || true)
if [ -n "$ORPHANS" ]; then for c in $ORPHANS; do docker kill "$c" >/dev/null 2>&1 || true; done; fi

# ---------- Step 3+4: Tier 2 / Nemotron only ------------------------------
run_chunk "overnight-tier2-${TS}-nemotron" \
          "$EXPECT_1M" "[3+4/4] tier2-nemotron" \
          "$NEMOTRON_MODEL"

banner "Tier 2 split complete"
echo "finished: $(date)"
echo "tier2 3-models results: bench/results/overnight-tier2-${TS}-3models/"
echo "tier2 nemotron results: bench/results/overnight-tier2-${TS}-nemotron/"
echo "log:                    $LOG"
