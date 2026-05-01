"""Heatmap from REAL judge scores (score.json under each run dir)."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

ROOT = Path(__file__).resolve().parents[2]
SUITES = [
    # First-seen wins; put paper-cases-fix before paper-cases so the rerun
    # of the 4 nullptr-broken cases overrides the original compile_failed runs.
    ROOT / "bench" / "results" / "paper-cases-fix",
    ROOT / "bench" / "results" / "paper-cases",
    ROOT / "bench" / "results" / "full-synthetic-v1-stripped",
    ROOT / "bench" / "results" / "injected-cases",
]
OUT = ROOT / "bench" / "analysis_artifacts"
FIG = OUT / "figs"

def short(m: str) -> str:
    if "nemotron-3-nano-30b" in m: return "Nemotron-30B"
    if "qwen3-30b" in m: return "Qwen-30B"
    if "nemotron-nano-9b" in m: return "Nemotron-9B"
    if "gemini-3.1-flash-lite" in m: return "Gemini-3.1-Flash-Lite"
    if "gpt-5.5" in m: return "GPT-5.5"
    return m.split("/")[-1]

rows = []
seen = set()  # de-dupe (case, model) — prefer paper-cases-fix over paper-cases
for suite in SUITES:
    if not suite.exists(): continue
    for run_dir in sorted(suite.iterdir()):
        if not run_dir.is_dir(): continue
        sj = run_dir / "score.json"
        rj = run_dir / "result.json"
        if not (sj.exists() and rj.exists()): continue
        score = json.loads(sj.read_text())
        res = json.loads(rj.read_text())
        # Skip runs that never produced a real session (compile_failed,
        # skipped_platform, no_collect, timeout) — judge scored 0/0/0 on
        # empty input, which would render as a misleading all-red row.
        if res.get("status") not in ("ok",):
            continue
        key = (res["case_id"], short(res["model"]))
        if key in seen: continue
        seen.add(key)
        s = score["scores"]
        rows.append({
            "suite": suite.name,
            "case_id": res["case_id"],
            "model": short(res["model"]),
            "root_cause": s["root_cause"],
            "local_fix": s["local_fix"],
            "global_fix": s["global_fix"],
            "total": s["root_cause"] + s["local_fix"] + s["global_fix"],
        })
df = pd.DataFrame(rows)
df.to_csv(OUT/"judge_scores.csv", index=False)
print(df.to_string())

pivot = df.pivot_table(index="model", columns="case_id", values="total", aggfunc="mean")
order = [m for m in ["GPT-5.5","Gemini-3.1-Flash-Lite","Nemotron-30B","Qwen-30B"] if m in pivot.index]
pivot = pivot.loc[order]

cmap = LinearSegmentedColormap.from_list(
    "rdylgn", ["#a4161a","#e76f51","#f4a261","#ffe66d","#90be6d","#2a9d8f","#1b4332"])
fig, ax = plt.subplots(figsize=(max(11, 1.0 + 0.95*pivot.shape[1]), 1.4 + 0.7*len(pivot)))
data = pivot.values.astype(float)
im = ax.imshow(data, vmin=0, vmax=3, cmap=cmap, aspect="auto")
ax.set_xticks(range(pivot.shape[1])); ax.set_xticklabels(pivot.columns, rotation=25, ha="right")
ax.set_yticks(range(pivot.shape[0])); ax.set_yticklabels(pivot.index)
for i in range(pivot.shape[0]):
    for j in range(pivot.shape[1]):
        v = data[i, j]
        ax.text(j, i, "—" if pd.isna(v) else f"{int(round(v))}", ha="center", va="center",
                fontsize=14, fontweight="bold",
                color="white" if (v < 1.0 or v > 2.2) else "black")
cbar = plt.colorbar(im, ax=ax, fraction=0.025); cbar.set_label("Score (0-3)")
ax.set_title("Total Score (root_cause + local_fix + global_fix) by Model × Case\n"
             "judge=openrouter/openai/gpt-4o, suite=full-synthetic-v1-stripped (16 runs)",
             fontsize=11)
fig.tight_layout()
out_png = FIG/"09_heatmap_real_judge.png"
fig.savefig(out_png, dpi=140, bbox_inches="tight")
print("wrote", out_png)

# also per-axis breakout
fig2, axes = plt.subplots(1, 3, figsize=(max(18, 1.0 + 0.95*pivot.shape[1]*3), 1.4 + 0.7*len(pivot)), sharey=True)
for ax, col, vmax in zip(axes, ["root_cause","local_fix","global_fix"], [1,1,1]):
    pv = df.pivot_table(index="model", columns="case_id", values=col, aggfunc="mean").loc[order]
    im = ax.imshow(pv.values.astype(float), vmin=0, vmax=1, cmap=cmap, aspect="auto")
    ax.set_xticks(range(pv.shape[1])); ax.set_xticklabels(pv.columns, rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(pv.shape[0])); ax.set_yticklabels(pv.index)
    for i in range(pv.shape[0]):
        for j in range(pv.shape[1]):
            v = pv.values[i,j]
            ax.text(j, i, "—" if pd.isna(v) else f"{int(round(v))}", ha="center", va="center",
                    fontsize=11, fontweight="bold",
                    color="white" if (v < 0.4 or v > 0.7) else "black")
    ax.set_title(col)
fig2.suptitle("Per-axis judge scores  (judge=gpt-4o)", y=1.02)
fig2.tight_layout()
out2 = FIG/"10_per_axis_real_judge.png"
fig2.savefig(out2, dpi=140, bbox_inches="tight")
print("wrote", out2)
