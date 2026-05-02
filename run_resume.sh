#!/usr/bin/env bash
# Resume after credit top-up. Runs:
#   1. Tier 1 judge (632 score.json files)
#   2. Tier 2 split (3 fast models + judge, then Nemotron + judge)
#
# Reuses the original session timestamp so all tier1/tier2 dirs share it.

set -uo pipefail

cd "$(dirname "$0")"

mkdir -p logs
TS="${OVERNIGHT_TS:-20260501_011643}"
LOG="logs/resume_${TS}.log"
exec > >(tee -a "$LOG") 2>&1

banner() { echo; echo "============================================================"; echo "$@"; echo "============================================================"; }

banner "Resume after credit top-up"
echo "started: $(date)"
echo "log:     $LOG"
echo "ts:      $TS"

# ---------- API keys ------------------------------------------------------
export OPENROUTER_API_KEY="$(grep -E '^OPENROUTER_API_KEY' .env | sed -E 's/^[^=]*=[[:space:]]*//' | tr -d ' \r\n')"
export OPENAI_API_KEY="$(grep -E '^OPENAI_API_KEY' .env | sed -E 's/^[^=]*=[[:space:]]*//' | tr -d ' \r\n')"
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'
export PYTHONIOENCODING=utf-8

# ---------- Step 1: Tier 1 judge -----------------------------------------
banner "[1/2] Tier 1 judge — gpt-4o via openrouter"
TIER1_RD="bench/results/overnight-tier1-${TS}"
echo "started: $(date)"
python -m bench.judge "$TIER1_RD" \
  --judge-model openrouter/openai/gpt-4o \
  --temperature 0 \
  || echo "[warn] judge exited non-zero; continuing"
echo "tier 1 judge finished: $(date)"

# Quick summary
python - "$TIER1_RD" <<'PY'
import sys, json, collections
from pathlib import Path
rd = Path(sys.argv[1])
idx = json.loads((rd / "index.json").read_text(encoding="utf-8"))
print(f"\n=== tier1 judge summary ===")
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

# ---------- Step 2: Tier 2 split (delegates to existing script) ----------
banner "[2/2] Tier 2 split (3 fast models, then Nemotron)"
echo "started: $(date)"
OVERNIGHT_TS="$TS" bash run_tier2_split.sh

banner "Resume complete"
echo "finished: $(date)"
echo "tier 1: bench/results/overnight-tier1-${TS}/"
echo "tier 2 (3 models): bench/results/overnight-tier2-${TS}-3models/"
echo "tier 2 (nemotron): bench/results/overnight-tier2-${TS}-nemotron/"
echo "log: $LOG"
