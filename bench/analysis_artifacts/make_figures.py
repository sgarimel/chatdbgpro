"""Generate figures for the bench analysis.

Heuristic signals (no judge has run yet):
- valid_target: gdb attached to a non-system binary
- line_mentioned: response mentions truth_line ± 3 (proxy for root_cause hit)
- file_mentioned / any_truth_file_mentioned: response cites truth filename
  (mostly useful on BugsCPP — synthetic cases all use 'program.c')

Figures land in bench/analysis_artifacts/figs/.
"""
from __future__ import annotations
import json, re
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
FIG = OUT / "figs"; FIG.mkdir(exist_ok=True)
df = pd.read_csv(OUT / "all_runs.csv")

# Short model labels
def short_model(m):
    if not isinstance(m, str): return "?"
    if "nemotron-nano-9b" in m: return "nemotron-9B"
    if "nemotron-3-nano-30b" in m: return "nemotron-30B"
    if "qwen3-30b" in m: return "qwen-30B"
    return m.split("/")[-1]
df["model_s"] = df["model"].map(short_model)

# Promote the "best" line proxy: line within ±3 OR function match
df["near_root"] = df["line_mentioned"].fillna(False) | df["func_mentioned"].fillna(False)

plt.rcParams.update({"figure.dpi": 130, "savefig.bbox": "tight",
                     "axes.spines.top": False, "axes.spines.right": False})

# ==== Fig 1: Harness validity by suite ====
def fig_harness():
    suites = ["nemotron-full", "full-synthetic-v1-stripped",
              "smoke-v3-nemotron-qwen", "step4-pilot-v2"]
    sub = df[df.suite.isin(suites)]
    g = sub.groupby("suite").agg(
        total=("run_id","count"),
        valid=("valid_target","sum"),
    ).loc[suites]
    g["invalid"] = g["total"] - g["valid"]
    fig, ax = plt.subplots(figsize=(7,3.4))
    y = np.arange(len(g))
    ax.barh(y, g["valid"], color="#2a9d8f", label="valid target")
    ax.barh(y, g["invalid"], left=g["valid"], color="#e76f51",
            label="wrong binary (bash/sed/find/make)")
    ax.set_yticks(y); ax.set_yticklabels(g.index)
    ax.set_xlabel("# runs")
    ax.set_title("Harness validity: how often gdb actually attaches to the buggy binary")
    for i, (v, t) in enumerate(zip(g["valid"], g["total"])):
        ax.text(t+1, i, f"{v}/{t} valid ({100*v/t:.0f}%)", va="center", fontsize=9)
    ax.legend(loc="lower right", fontsize=8)
    fig.savefig(FIG/"01_harness_validity.png")
    plt.close(fig)

# ==== Fig 2: BugsCPP debugged-binary distribution ====
def fig_bugscpp_binaries():
    s = df[df.suite=="nemotron-full"]
    counts = s["debugged_binary"].fillna("(none)").value_counts()
    fig, ax = plt.subplots(figsize=(7,4))
    bars = ax.barh(counts.index[::-1], counts.values[::-1],
                   color=["#e76f51" if b in {"/bin/bash","/usr/bin/bash","/bin/sed",
                                              "/usr/bin/find","/usr/bin/make"}
                          else "#2a9d8f" for b in counts.index[::-1]])
    ax.set_xlabel("# runs")
    ax.set_title("nemotron-full (BugsC++): which binary gdb is actually debugging")
    for b, v in zip(bars, counts.values[::-1]):
        ax.text(v+0.5, b.get_y()+b.get_height()/2, str(v), va="center", fontsize=8)
    fig.savefig(FIG/"02_bugscpp_binaries.png")
    plt.close(fig)

# ==== Fig 3: Tool-call distribution synthetic vs BugsCPP ====
def fig_tool_calls():
    syn = df[(df.suite=="full-synthetic-v1-stripped") & df.valid_target]
    bugs = df[(df.suite=="nemotron-full") & df.valid_target]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    for ax, sub, title in [(axes[0], syn, "Synthetic (valid runs, n=14)"),
                           (axes[1], bugs, "BugsC++ valid runs (n=5)")]:
        for m, color in zip(sorted(sub.model_s.unique()),
                            ["#264653","#e9c46a","#e76f51"]):
            x = sub[sub.model_s==m]["n_tool_calls"]
            ax.scatter([m]*len(x), x, color=color, s=40, alpha=0.7)
        ax.set_title(title)
        ax.set_ylabel("# tool calls per run")
        ax.set_ylim(-0.5, max(20, sub["n_tool_calls"].max() if len(sub) else 1)+1)
        ax.tick_params(axis='x', rotation=20)
    fig.suptitle("Tool-call engagement varies enormously by model (Qwen explores; Nemotron rarely tools)")
    fig.savefig(FIG/"03_tool_calls.png")
    plt.close(fig)

# ==== Fig 4: Per-case line-mention heuristic on synthetic ====
def fig_per_case_synth():
    syn = df[(df.suite=="full-synthetic-v1-stripped") & df.valid_target].copy()
    g = syn.pivot_table(index="case_id", columns="model_s",
                        values="near_root", aggfunc="mean")
    fig, ax = plt.subplots(figsize=(8,4.5))
    im = ax.imshow(g.fillna(0).values, vmin=0, vmax=1, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(g.columns))); ax.set_xticklabels(g.columns)
    ax.set_yticks(range(len(g.index))); ax.set_yticklabels(g.index)
    for i in range(g.shape[0]):
        for j in range(g.shape[1]):
            v = g.values[i,j]
            ax.text(j,i, "—" if pd.isna(v) else f"{v:.0f}",
                    ha="center", va="center", fontsize=10,
                    color="black" if 0.3<v<0.7 else "white")
    ax.set_title("Synthetic: response mentions truth line (±3) or function — by case × model")
    plt.colorbar(im, ax=ax, fraction=0.04)
    fig.savefig(FIG/"04_per_case_synth.png")
    plt.close(fig)

# ==== Fig 5: Tool calls vs near_root (synthetic) ====
def fig_engagement_vs_hit():
    syn = df[(df.suite=="full-synthetic-v1-stripped") & df.valid_target].copy()
    fig, ax = plt.subplots(figsize=(6,3.8))
    for m, color in zip(sorted(syn.model_s.unique()),
                        ["#264653","#e76f51"]):
        sub = syn[syn.model_s==m]
        jitter = np.random.uniform(-0.15, 0.15, len(sub))
        ax.scatter(sub["n_tool_calls"], sub["near_root"].astype(int)+jitter,
                   color=color, s=60, alpha=0.7, label=m)
    ax.set_xlabel("# tool calls in run")
    ax.set_ylabel("near_root  (0=miss, 1=line/func mentioned)")
    ax.set_yticks([0,1])
    ax.set_title("Synthetic: more tool engagement weakly correlates with hitting the bug line")
    ax.legend()
    fig.savefig(FIG/"05_engagement_vs_hit.png")
    plt.close(fig)

# ==== Fig 6: BugsCPP nemotron-full -- still produces 'fixes' from useless backtraces ====
def fig_bugscpp_overconfidence():
    s = df[df.suite=="nemotron-full"].copy()
    s["bin_class"] = np.where(s["valid_target"], "valid bug binary", "system tool (bash/sed/find/make)")
    g = s.groupby("bin_class").agg(
        n=("run_id","count"),
        emits_recommendation=("has_recommendation_section","mean"),
        mean_resp_len=("resp_len","mean"),
        mean_tool_calls=("n_tool_calls","mean"),
    )
    fig, ax = plt.subplots(figsize=(7,3))
    rows = ["valid bug binary","system tool (bash/sed/find/make)"]
    rows = [r for r in rows if r in g.index]
    metrics = ["emits_recommendation","mean_tool_calls"]
    bw = 0.35
    x = np.arange(len(metrics))
    for i, r in enumerate(rows):
        vals = [g.loc[r, m] for m in metrics]
        # normalize tool calls to 0-1 scale by dividing by 5 for visual parity
        vals_disp = [vals[0], vals[1]/5]
        ax.bar(x + (i-0.5)*bw, vals_disp, bw, label=f"{r}  (n={int(g.loc[r,'n'])})",
               color=["#2a9d8f","#e76f51"][i])
    ax.set_xticks(x)
    ax.set_xticklabels(["P(emits 'Recommendation')", "mean tool calls /5"])
    ax.set_ylim(0, 1.1)
    ax.set_title("BugsC++: model emits a 'fix' even when shown a wrong-binary backtrace")
    ax.legend(fontsize=8)
    fig.savefig(FIG/"06_bugscpp_overconfidence.png")
    plt.close(fig)

# ==== Fig 7: Tokens vs response length ====
def fig_tokens():
    syn = df[(df.suite=="full-synthetic-v1-stripped") & df.valid_target]
    fig, ax = plt.subplots(figsize=(6.5,3.8))
    for m, color in zip(sorted(syn.model_s.unique()),
                        ["#264653","#e76f51"]):
        sub = syn[syn.model_s==m]
        ax.scatter(sub["prompt_tokens"], sub["completion_tokens"],
                   s=60, alpha=0.7, label=m, color=color)
    ax.set_xlabel("prompt tokens")
    ax.set_ylabel("completion tokens")
    ax.set_title("Synthetic: completion verbosity (Qwen explores → larger prompts)")
    ax.legend()
    fig.savefig(FIG/"07_tokens.png")
    plt.close(fig)

for fn in [fig_harness, fig_bugscpp_binaries, fig_tool_calls,
           fig_per_case_synth, fig_engagement_vs_hit,
           fig_bugscpp_overconfidence, fig_tokens]:
    fn()
    print("ok:", fn.__name__)

# ==== Hard-cases table ====
syn = df[(df.suite=="full-synthetic-v1-stripped") & df.valid_target].copy()
hard = (syn.groupby("case_id")
            .agg(runs=("run_id","count"),
                 near_root_rate=("near_root","mean"),
                 mean_tools=("n_tool_calls","mean"),
                 mean_resp_len=("resp_len","mean"))
            .sort_values("near_root_rate"))
hard.to_csv(OUT/"hard_cases_synthetic.csv")
print("\nHardest synthetic cases (lowest near_root rate):")
print(hard.head(10).to_string())

# Promising cases for ½-SOTA: cases with ≥1 hit on small models
promising = hard[hard["near_root_rate"]>0]
promising.to_csv(OUT/"promising_cases.csv")
print("\nPromising cases (worth retrying on ½-SOTA):")
print(promising.to_string())
