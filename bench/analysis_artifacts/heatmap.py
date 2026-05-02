"""Heatmap: Total proxy score (root_cause + local_fix + global_fix) by Model x Case.

Until the LLM judge runs, each axis is a heuristic proxy:
  root_cause : 1 if response mentions truth_line ±3 OR truth function name
  local_fix  : 1 if response contains >= 2 per-case fix anchors
  global_fix : 1 if response mentions the bug-category keyword (heap_overflow,
               use_after_free, off_by_one, ...) AND has a 'Recommendation' block

These are correlated and lenient; treat the values as 'best case'.
"""
from __future__ import annotations
import json, re
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

ROOT = Path(__file__).resolve().parents[2]
OUT  = ROOT / "bench" / "analysis_artifacts"
FIG  = OUT / "figs"

# Per-case anchor tokens (re-used from strong_score.py)
ANCHORS = {
    "heap-overflow-csv":      ["n + 1", "n+1", "malloc(n + 1", "malloc(n+1"],
    "off-by-one-crc":         ["<=", "i < ", "len - 1", "off-by-one"],
    "double-free-errpath":    ["= NULL", "double free", "after free"],
    "uaf-linked-list":        ["use-after-free", "after free", "freed"],
    "intoverflow-alloc":      ["overflow", "SIZE_MAX", "n * sizeof"],
    "null-deref-env":         ["getenv", "null check", "NULL"],
    "signed-unsigned-loop":   ["unsigned", "underflow", "i--"],
    "uninit-stack-accumulator":["uninitialized", "= 0", "init"],
}
BUGGY_FUNCS = {
    "heap-overflow-csv": "first_field",
    "off-by-one-crc":    "crc",
    "double-free-errpath":"cleanup",
}
CATEGORY_KEYWORDS = {
    "heap-overflow-csv":      ["heap overflow", "out of bound", "overflow", "buffer overflow"],
    "off-by-one-crc":         ["off-by-one", "off by one"],
    "double-free-errpath":    ["double free", "double-free"],
    "uaf-linked-list":        ["use-after-free", "use after free", "dangling"],
    "intoverflow-alloc":      ["integer overflow", "size overflow", "overflow"],
    "null-deref-env":         ["null pointer", "null deref", "null"],
    "signed-unsigned-loop":   ["unsigned underflow", "underflow", "signed"],
    "uninit-stack-accumulator":["uninitialized"],
}

df = pd.read_csv(OUT / "all_runs.csv")
syn = df[(df.suite=="full-synthetic-v1-stripped") & df.valid_target].copy()

def short(m):
    if "nemotron-3-nano-30b" in m: return "Nemotron-30B"
    if "qwen3-30b" in m: return "Qwen-30B"
    return m
syn["model_s"] = syn["model"].map(short)

def score_run(row):
    rd = Path(row["run_dir"])
    cj = rd/"collect.json"
    try:
        q = json.loads(cj.read_text())["queries"][0]
    except Exception:
        return pd.Series({"root_cause":0,"local_fix":0,"global_fix":0})
    resp = (q.get("response","") or "").lower()
    case = row["case_id"]

    # root_cause: line ±3 OR function name
    rc = 0
    L = row.get("truth_line")
    if pd.notna(L):
        L = int(L)
        nums = set(int(x) for x in re.findall(r"\b(\d{2,5})\b", resp))
        if any((L+d) in nums for d in range(-3,4)): rc = 1
    fn = BUGGY_FUNCS.get(case)
    if fn and fn.lower() in resp: rc = 1

    # local_fix: >= 2 anchor matches
    n_anchor = sum(1 for a in ANCHORS.get(case,[]) if a.lower() in resp)
    lf = 1 if n_anchor >= 2 else 0

    # global_fix: category keyword AND response has 'recommendation'
    cats = CATEGORY_KEYWORDS.get(case, [])
    cat_hit = any(k.lower() in resp for k in cats)
    has_rec = "recommendation" in resp
    gf = 1 if (cat_hit and has_rec) else 0

    return pd.Series({"root_cause":rc, "local_fix":lf, "global_fix":gf})

syn[["root_cause","local_fix","global_fix"]] = syn.apply(score_run, axis=1)
syn["total"] = syn[["root_cause","local_fix","global_fix"]].sum(axis=1)

pivot = syn.pivot_table(index="model_s", columns="case_id",
                        values="total", aggfunc="mean")
# fixed model order
order = [m for m in ["Nemotron-30B","Qwen-30B"] if m in pivot.index]
pivot = pivot.loc[order]

print("Heuristic-proxy total score (root_cause+local_fix+global_fix):")
print(pivot.to_string())
syn[["case_id","model_s","root_cause","local_fix","global_fix","total"]].to_csv(
    OUT/"heuristic_axis_scores.csv", index=False)

# --- plot ---
cmap = LinearSegmentedColormap.from_list(
    "rdylgn", ["#a4161a", "#e76f51", "#f4a261", "#ffe66d", "#90be6d", "#2a9d8f", "#1b4332"])
fig, ax = plt.subplots(figsize=(11, 2 + 0.6*len(pivot)))
data = pivot.values.astype(float)
im = ax.imshow(data, vmin=0, vmax=3, cmap=cmap, aspect="auto")
ax.set_xticks(range(pivot.shape[1])); ax.set_xticklabels(pivot.columns, rotation=25, ha="right")
ax.set_yticks(range(pivot.shape[0])); ax.set_yticklabels(pivot.index)
for i in range(pivot.shape[0]):
    for j in range(pivot.shape[1]):
        v = data[i,j]
        ax.text(j, i, f"{int(round(v))}", ha="center", va="center",
                fontsize=13, color="white" if (v < 1.0 or v > 2.2) else "black",
                fontweight="bold")
cbar = plt.colorbar(im, ax=ax, fraction=0.025)
cbar.set_label("Score (0-3)")
ax.set_title("Heuristic-proxy Total Score (root_cause + local_fix + global_fix) by Model × Case\n"
             "(synthetic suite; LLM judge has not run — values are mention-based proxies)",
             fontsize=11)
fig.tight_layout()
fig.savefig(FIG/"08_heatmap_total_score.png", dpi=140, bbox_inches="tight")
print("wrote", FIG/"08_heatmap_total_score.png")
