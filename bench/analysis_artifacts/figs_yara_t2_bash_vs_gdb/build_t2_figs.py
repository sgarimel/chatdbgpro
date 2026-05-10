"""Tier 2 yara analysis: does adding gdb on top of bash actually help?

T2 = mini-swe-agent with TWO tools: `bash` and `gdb` (persistent gdb session).
For each (case, model) cell we count how many of each tool the agent issued,
and we know the judge score. The question: do high-scoring runs lean on gdb,
on bash, or on both?

T2 yara data sources:
  - merged-yara-pilot                         (gpt-4o)
  - adroit-yara-after-fix-20260503-223021     (sonnet-4.6, grok-4.3)
  - adroit-yara-gemini-gpt5-20260503-235331   (gemini-2.5-flash, gpt-5.1)

Outputs go to bench/analysis_artifacts/figs_yara_t2_bash_vs_gdb/.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(r"C:\Users\Owner\OneDrive\Documents\Classes\COS\COS484\chatdbgpro\bench\results")
FIGS = Path(__file__).parent

def short_model(s: str) -> str:
    s = s.replace("openrouter_", "")
    s = s.replace("anthropic_claude-", "claude-")
    s = s.replace("openai_", "")
    s = s.replace("google_", "")
    s = s.replace("x-ai_", "")
    s = s.replace("nvidia_", "")
    s = s.replace("meta-llama_", "")
    s = s.replace("qwen_", "")
    return s


def parse_t2_runs(case_prefix: str = "yara-"):
    """Walk every collect.json under bench/results whose run dir uses
    a T2 tool config (tier2_bash_plus_gdb or tier2_gdb_plus_bash).

    By default restricted to yara cases. Pass case_prefix='' to widen.
    The dir name template is `{case}__tier{N}__{model}__{tool_config}__...`.
    Some dirs use tier-name "tier3" but tool_config "tier2_bash_plus_gdb"
    (early-iter dispatch oddity); we key off the tool_config field, not
    the tier field, since that's what determines the actual tool surface
    the agent had."""
    rows = []
    for cp in ROOT.rglob("collect.json"):
        parent_name = cp.parent.name
        if not parent_name.startswith(case_prefix):
            continue
        if not (
            "tier2_bash_plus_gdb" in parent_name
            or "tier2_gdb_plus_bash" in parent_name
        ):
            continue
        parts = parent_name.split("__")
        if len(parts) < 3:
            continue
        case, _tier, model = parts[0], parts[1], parts[2]
        try:
            c = json.load(open(cp, encoding="utf-8"))
            q = c["queries"][0]
            tool_calls = q.get("tool_calls", [])
        except Exception:
            continue
        if not tool_calls:
            continue
        n_bash = sum(1 for t in tool_calls if t.get("tool_name") == "bash")
        n_gdb = sum(1 for t in tool_calls if t.get("tool_name") == "gdb")
        sp = cp.parent / "score.json"
        scores = {}
        if sp.exists():
            try:
                scores = json.load(open(sp, encoding="utf-8")).get("scores", {})
            except Exception:
                pass
        rc = scores.get("root_cause", 0)
        lf = scores.get("local_fix", 0)
        gf = scores.get("global_fix", 0)
        total = rc + lf + gf
        rows.append({
            "sweep": cp.parent.parent.name, "case": case, "model": model,
            "model_short": short_model(model),
            "bash": n_bash, "gdb": n_gdb,
            "rc": rc, "lf": lf, "gf": gf, "total": total,
        })
    return rows


def main():
    FIGS.mkdir(parents=True, exist_ok=True)
    rows = parse_t2_runs()
    if not rows:
        print("No T2 runs found")
        return

    print(f"Found {len(rows)} T2 yara runs")
    models = sorted({r["model_short"] for r in rows})
    print("Models:", models)

    # Filter out models that produced zero tool calls in every run —
    # those models don't engage mini's tool protocol so they're not
    # informative for a "did gdb help?" comparison. We keep their row
    # count for transparency in the summary.
    nonzero_models = [
        m for m in models
        if any(r["bash"] + r["gdb"] > 0 for r in rows if r["model_short"] == m)
    ]
    flatlined = sorted(set(models) - set(nonzero_models))
    print("Models with non-zero tool calls:", nonzero_models)
    print("Flatlined (0 tools every run):", flatlined)
    rows_eff = [r for r in rows if r["model_short"] in nonzero_models]
    models = nonzero_models

    # ---------- Figure 1: scatter — bash vs gdb, colored by total score ----------
    fig, ax = plt.subplots(figsize=(9, 6.5))
    score_colors = {0: "#999999", 1: "#ffe082", 2: "#ffb74d", 3: "#43a047"}
    score_labels = {0: "0/3", 1: "1/3", 2: "2/3", 3: "3/3"}
    for r in rows_eff:
        ax.scatter(r["bash"], r["gdb"],
                   color=score_colors.get(r["total"], "#999"),
                   s=110, edgecolor="black", linewidth=0.6, alpha=0.85)
        ax.annotate(r["case"],
                    (r["bash"], r["gdb"]),
                    fontsize=7, alpha=0.8,
                    xytext=(5, 4), textcoords="offset points")
    # Legend by score
    handles = [plt.Line2D([0], [0], marker="o", linestyle="",
                          color=score_colors[s], markersize=10,
                          markeredgecolor="black", label=score_labels[s])
               for s in [0, 1, 2, 3]]
    ax.legend(handles=handles, title="judge total", loc="upper right")
    # Diagonal y=x
    lim = max(max(r["bash"] for r in rows_eff),
              max(r["gdb"] for r in rows_eff)) + 2
    ax.plot([0, lim], [0, lim], "k--", alpha=0.25, linewidth=0.7)
    ax.set_xlabel("# bash tool calls")
    ax.set_ylabel("# gdb tool calls")
    title = ("T2 yara — bash vs gdb usage per run, coloured by score\n"
             f"models charted: {', '.join(nonzero_models)}")
    if flatlined:
        title += (f"\n(flatlined / 0 tool calls everywhere: {', '.join(flatlined)})")
    ax.set_title(title, fontsize=10)
    ax.set_xlim(-1, lim)
    ax.set_ylim(-1, lim)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "01_bash_vs_gdb_scatter.png", dpi=140)
    plt.close(fig)

    # ---------- Figure 2: per-case stacked bar of bash vs gdb (gpt-4o is the only model with calls) ----------
    fig, ax = plt.subplots(figsize=(10, 5.5))
    # Aggregate by case across all rows_eff (effectively gpt-4o here).
    cases_seen = sorted({r["case"] for r in rows_eff})
    bash_per_case = []
    gdb_per_case = []
    score_per_case = []
    for c in cases_seen:
        rs = [r for r in rows_eff if r["case"] == c]
        bash_per_case.append(np.mean([r["bash"] for r in rs]))
        gdb_per_case.append(np.mean([r["gdb"] for r in rs]))
        score_per_case.append(np.mean([r["total"] for r in rs]))
    x = np.arange(len(cases_seen))
    ax.bar(x, bash_per_case, label="bash", color="#1f77b4")
    ax.bar(x, gdb_per_case, bottom=bash_per_case, label="gdb", color="#d62728")
    ax.set_xticks(x)
    ax.set_xticklabels(cases_seen)
    ax.set_ylabel("mean # tool calls per run")
    title2 = "T2 yara — bash vs gdb per case (mean across runs)"
    if len(nonzero_models) == 1:
        title2 += f"\nmodel: {nonzero_models[0]}"
    ax.set_title(title2)
    ax.legend(loc="upper left")
    ax.grid(axis="y", alpha=0.3)
    # Score annotations
    for xi, ms in zip(x, score_per_case):
        ax.text(xi, bash_per_case[int(xi)] + gdb_per_case[int(xi)] + 0.1,
                f"score {ms:.1f}/3", ha="center", fontsize=9, color="green")
    fig.tight_layout()
    fig.savefig(FIGS / "02_per_case_bash_vs_gdb.png", dpi=140)
    plt.close(fig)

    # ---------- Figure 2b: per-model summary including flatlined ----------
    fig, ax1 = plt.subplots(figsize=(10, 5.5))
    all_models_for_summary = sorted({r["model_short"] for r in rows})
    by_model = {m: [r for r in rows if r["model_short"] == m]
                for m in all_models_for_summary}
    models_summary = all_models_for_summary
    mean_bash = [np.mean([r["bash"] for r in by_model[m]]) for m in models_summary]
    mean_gdb = [np.mean([r["gdb"] for r in by_model[m]]) for m in models_summary]
    mean_score = [np.mean([r["total"] for r in by_model[m]]) for m in models_summary]
    n_per = [len(by_model[m]) for m in models_summary]
    x = np.arange(len(models_summary))
    models = models_summary  # so the rest of the body uses all models
    ax1.bar(x, mean_bash, label="bash", color="#1f77b4")
    ax1.bar(x, mean_gdb, bottom=mean_bash, label="gdb", color="#d62728")
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"{m}\n(n={n})" for m, n in zip(models, n_per)],
                        rotation=15, ha="right", fontsize=9)
    ax1.set_ylabel("mean # tool calls per run", color="#333")
    ax1.set_title("T2 yara — mean bash vs gdb usage per model + mean score")
    ax1.legend(loc="upper left")
    ax1.grid(axis="y", alpha=0.3)
    # Twin axis for mean score
    ax2 = ax1.twinx()
    ax2.plot(x, mean_score, "go-", linewidth=2, markersize=10,
             label="mean total score (/3)")
    ax2.set_ylabel("mean total score (out of 3)", color="green")
    ax2.set_ylim(0, 3.1)
    for xi, ms in zip(x, mean_score):
        ax2.annotate(f"{ms:.1f}", (xi, ms), textcoords="offset points",
                     xytext=(0, 8), ha="center", color="green", fontsize=10)
    ax2.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(FIGS / "02b_per_model_bash_vs_gdb_with_score.png", dpi=140)
    plt.close(fig)

    # ---------- Figure 3: gdb fraction vs score correlation ----------
    fig, ax = plt.subplots(figsize=(7.5, 5))
    fracs = []
    scores = []
    for r in rows_eff:
        tot = r["bash"] + r["gdb"]
        if tot == 0:
            continue
        fracs.append(r["gdb"] / tot)
        scores.append(r["total"])
    # bin by score
    by_score = {s: [] for s in [0, 1, 2, 3]}
    for f, s in zip(fracs, scores):
        by_score[s].append(f)
    means = [np.mean(by_score[s]) if by_score[s] else 0 for s in [0, 1, 2, 3]]
    ns = [len(by_score[s]) for s in [0, 1, 2, 3]]
    bars = ax.bar([0, 1, 2, 3], means,
                  color=["#cccccc", "#ffe082", "#ffb74d", "#43a047"],
                  edgecolor="black")
    for b, m, n in zip(bars, means, ns):
        if n == 0:
            ax.text(b.get_x() + b.get_width() / 2, 0.02,
                    "no runs", ha="center", color="#999")
        else:
            ax.text(b.get_x() + b.get_width() / 2, m + 0.02,
                    f"{m:.2f}\n(n={n})", ha="center", fontsize=9)
    ax.set_xticks([0, 1, 2, 3])
    ax.set_xticklabels(["0/3", "1/3", "2/3", "3/3"])
    ax.set_xlabel("judge total score")
    ax.set_ylabel("mean fraction of tool calls that are gdb")
    ax.set_title("T2 yara — does gdb-leaning correlate with success?")
    ax.set_ylim(0, max(means + [0.5]) * 1.3 if means else 1)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "03_gdb_fraction_by_score.png", dpi=140)
    plt.close(fig)

    # ---------- CSV ----------
    import csv
    with open(FIGS / "data.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sweep", "case", "model", "bash", "gdb", "rc", "lf", "gf", "total"])
        for r in rows:
            w.writerow([r["sweep"], r["case"], r["model"], r["bash"], r["gdb"],
                        r["rc"], r["lf"], r["gf"], r["total"]])

    # ---------- Summary table ----------
    print()
    print(f"{'model':35s} {'n':>3} {'mean bash':>10} {'mean gdb':>10} {'mean score':>12}")
    for m in models:
        d = by_model[m]
        n = len(d)
        mb = np.mean([r["bash"] for r in d])
        mg = np.mean([r["gdb"] for r in d])
        ms = np.mean([r["total"] for r in d])
        print(f"  {m:33s} {n:>3} {mb:>10.1f} {mg:>10.1f} {ms:>12.2f}")

    print()
    print("By score bin (gdb fraction of tool calls):")
    for s in [0, 1, 2, 3]:
        d = by_score[s]
        if d:
            print(f"  score={s}/3  n={len(d):3d}  mean_gdb_frac={np.mean(d):.2f}")
        else:
            print(f"  score={s}/3  no runs")

    print()
    print("Wrote:")
    for p in sorted(FIGS.glob("*")):
        print(" ", p)


if __name__ == "__main__":
    main()
