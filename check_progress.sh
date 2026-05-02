#!/usr/bin/env bash
# Print a quick progress report on the overnight 4-model x 2-tier ablation.
# Prints status for each tier that has been started (tier1, tier2).

set -uo pipefail

cd "$(dirname "$0")"

EXPECTED=632  # 158 included bugs * 4 models

print_tier() {
  local label="$1"
  local pattern="$2"
  local rd
  rd=$(ls -dt bench/results/${pattern} 2>/dev/null | head -1)
  if [ -z "$rd" ] || [ ! -f "$rd/index.json" ]; then
    return 1
  fi

  PYTHONIOENCODING=utf-8 python - "$rd" "$label" "$EXPECTED" <<'PY'
import sys, json, collections
from pathlib import Path

rd, label, expected = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
idx = json.loads((rd / "index.json").read_text(encoding="utf-8"))
n = len(idx)
pct = (n * 100) // expected if expected else 0

# How far along did we get on the judge step too?
scored = sum(1 for r in idx if (rd / r["run_id"] / "score.json").exists())

# Pretty model names
PRETTY = {
    "llama-3.1-8b-instruct":         "Llama-8B",
    "nemotron-3-nano-30b-a3b":       "Nemotron-30B",
    "qwen3-30b-a3b-instruct-2507":   "Qwen-30B",
    "gpt-4o":                        "GPT-4o",
}

# Per-model counts
counts = collections.defaultdict(lambda: {"ok": 0, "timeout": 0, "other": 0,
                                           "rc": 0, "lf": 0, "gf": 0, "any": 0,
                                           "judged": 0})
for r in idx:
    raw = r["model"].split("/")[-1]
    m = PRETTY.get(raw, raw)
    s = r.get("status", "")
    if s == "ok":
        counts[m]["ok"] += 1
    elif s == "timeout":
        counts[m]["timeout"] += 1
    else:
        counts[m]["other"] += 1
    sp = rd / r["run_id"] / "score.json"
    if sp.exists():
        try:
            ss = json.loads(sp.read_text(encoding="utf-8")).get("scores", {})
        except Exception:
            ss = {}
        rc = int(ss.get("root_cause", 0))
        lf = int(ss.get("local_fix", 0))
        gf = int(ss.get("global_fix", 0))
        counts[m]["judged"] += 1
        counts[m]["rc"] += rc
        counts[m]["lf"] += lf
        counts[m]["gf"] += gf
        if rc or lf or gf:
            counts[m]["any"] += 1

# Headline
print(f"\n{label}: {n}/{expected} ({pct}%) runs done", end="")
if scored:
    print(f"  |  judged: {scored}/{n}", end="")
print()

# Run table
print()
print(f"{'model':<14} {'ok':>4} {'timeout':>10}")
order = ["Llama-8B", "Qwen-30B", "GPT-4o", "Nemotron-30B"]
for m in order:
    c = counts.get(m)
    if not c: continue
    total = c["ok"] + c["timeout"] + c["other"]
    pct_to = (c["timeout"] * 100 // total) if total else 0
    to_str = f"{c['timeout']}"
    if c["timeout"]:
        to_str = f"{c['timeout']} ({pct_to}% timeout rate)"
    print(f"{m:<14} {c['ok']:>4} {to_str:>10}")

# Judge table (only if any judged)
if scored:
    print()
    print(f"judged so far: {scored}")
    print(f"{'model':<14} {'judged':>6} {'rc':>4} {'lf':>4} {'gf':>4} {'any>0':>6}")
    for m in order:
        c = counts.get(m)
        if not c or c["judged"] == 0: continue
        print(f"{m:<14} {c['judged']:>6} {c['rc']:>4} {c['lf']:>4} {c['gf']:>4} {c['any']:>6}")
PY
}

# Print whichever tiers we have data for
print_tier "tier 1 (gdb only)"      "overnight-tier1-*" || true
print_tier "tier 2 (gdb + bash)"    "overnight-tier2-*" || true

# Last log line is useful for showing what's currently running
LASTLOG=$(ls -t logs/overnight_4m2t_*.log 2>/dev/null | head -1)
if [ -n "$LASTLOG" ]; then
  LAST=$(tail -1 "$LASTLOG" 2>/dev/null)
  if [ -n "$LAST" ]; then
    echo
    echo "log tail: $LAST"
  fi
fi
