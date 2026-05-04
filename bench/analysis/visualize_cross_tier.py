#!/usr/bin/env python3
"""
Cross-tier (T1-T3) visualizations for the synthetic 8-model sweep.
Also generates per-tier heatmaps and a CMW comparison figure.

Output: bench/analysis/figs/
"""
import json
import glob
from pathlib import Path
from collections import defaultdict

import matplotlib.pyplot as plt
import matplotlib
import numpy as np

matplotlib.rcParams['font.size'] = 11
matplotlib.rcParams['font.family'] = 'sans-serif'

RESULTS_DIR = Path("bench/results/synth-8model-sweep")
CMW_DIR = Path("bench/results/synth-cmw-t3-sweep")
FIGS_DIR = Path("bench/analysis/figs")
FIGS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_MAP = {
    "openrouter_openai_gpt-4o": "GPT-4o",
    "openrouter_openai_gpt-5.5": "GPT-5.5",
    "openrouter_x-ai_grok-4": "Grok-4",
    "openrouter_anthropic_claude-sonnet-4-5-20250514": "Sonnet-4.5",
    "openrouter_anthropic_claude-sonnet-4-5": "Sonnet-4.5",
    "openrouter_google_gemini-2.5-flash": "Gemini-2.5",
    "openrouter_meta-llama_llama-3.1-8b-instruct": "Llama-8B",
    "openrouter_nvidia_nemotron-3-nano-30b-a3b": "Nemotron-30B",
    "openrouter_qwen_qwen3-30b-a3b-instruct-2507": "Qwen-30B",
}

MODEL_ORDER = ["GPT-5.5", "GPT-4o", "Grok-4", "Sonnet-4.5", "Gemini-2.5",
               "Qwen-30B", "Nemotron-30B", "Llama-8B"]

TIER_LABELS = {1: "T1: bash", 2: "T2: bash+gdb", 3: "T3: ChatDBG"}
TIER_COLORS = {1: "#1976d2", 2: "#f57c00", 3: "#388e3c"}


def _model_name(run_dir_name):
    for k, v in MODEL_MAP.items():
        if k in run_dir_name:
            return v
    return "?"


def load_scored_data(results_dir):
    data = []
    for f in sorted(glob.glob(str(results_dir / "*/score.json"))):
        rd = Path(f).parent
        score = json.load(open(f))
        result = json.load(open(rd / "result.json"))
        if result.get("status") not in ("ok",):
            continue

        sc = score.get("scores", {})
        model = _model_name(rd.name)

        tc, tf, tokens = 0, {}, 0
        collect_f = rd / "collect.json"
        if collect_f.exists():
            c = json.load(open(collect_f))
            q = (c.get("queries") or [{}])[0]
            tc = q.get("num_tool_calls", 0)
            tf = q.get("tool_frequency", {})
            tokens = q.get("stats", {}).get("tokens", 0) or 0

        data.append({
            "case": result.get("case_id", "?"),
            "model": model,
            "tier": result.get("tier", 0),
            "rc": sc.get("root_cause", 0),
            "lf": sc.get("local_fix", 0),
            "gf": sc.get("global_fix", 0),
            "total": sc.get("root_cause", 0) + sc.get("local_fix", 0) + sc.get("global_fix", 0),
            "tool_calls": tc,
            "tokens": tokens,
            "elapsed_s": result.get("elapsed_s", 0),
        })
    return data


def load_cmw_data():
    """Load CMW sweep results from collect.json check_my_work field."""
    data = []
    for f in sorted(glob.glob(str(CMW_DIR / "*/result.json"))):
        rd = Path(f)
        result = json.load(open(f))
        if result.get("status") != "ok":
            continue

        collect_f = rd.parent / "collect.json"
        if not collect_f.exists():
            continue
        c = json.load(open(collect_f))
        cmw = c.get("check_my_work")
        if not cmw:
            continue

        model = _model_name(rd.parent.name)
        fs = cmw["final_scores"]
        data.append({
            "case": result.get("case_id", "?"),
            "model": model,
            "num_checks": cmw["num_checks"],
            "rc": fs.get("root_cause", 0),
            "lf": fs.get("local_fix", 0),
            "gf": fs.get("global_fix", 0),
            "total": sum(fs.values()),
            "stale": cmw["stale_exit"],
            "checks_to_rc": cmw.get("checks_to_root_cause"),
            "checks_to_lf": cmw.get("checks_to_local_fix"),
            "checks_to_gf": cmw.get("checks_to_global_fix"),
        })
    return data


# ── Figure 1: Cross-tier mean score bar chart ────────────────────────

def fig_cross_tier_means(data):
    tiers = [1, 2, 3]
    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in data)]

    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(len(models))
    width = 0.25

    for ti, tier in enumerate(tiers):
        td = [d for d in data if d["tier"] == tier]
        avgs = []
        for m in models:
            vals = [d["total"] for d in td if d["model"] == m]
            avgs.append(np.mean(vals) if vals else 0)
        bars = ax.bar(x + ti * width, avgs, width,
                      label=TIER_LABELS[tier], color=TIER_COLORS[tier], alpha=0.85)
        for bar, val in zip(bars, avgs):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.04,
                        f"{val:.2f}", ha="center", va="bottom", fontsize=7)

    ax.set_ylabel("Mean Total Score (0–3)")
    ax.set_title("Mean Debugging Score by Model × Tier (Synthetic Cases)")
    ax.set_xticks(x + width)
    ax.set_xticklabels(models, fontsize=9)
    ax.legend(fontsize=9, loc="upper right")
    ax.set_ylim(0, 3.5)
    ax.axhline(y=3, color="gray", ls="--", lw=0.5, alpha=0.5)
    plt.tight_layout()
    fname = FIGS_DIR / "cross_tier_mean_scores.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"  Saved: {fname}")
    plt.close()


# ── Figure 2: Per-tier heatmaps (one per tier) ──────────────────────

def fig_tier_heatmap(data, tier):
    td = [d for d in data if d["tier"] == tier]
    if not td:
        return
    cases = sorted(set(d["case"] for d in td))
    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in td)]

    matrix = np.full((len(models), len(cases)), np.nan)
    for d in td:
        if d["model"] in models and d["case"] in cases:
            matrix[models.index(d["model"]), cases.index(d["case"])] = d["total"]

    fig, ax = plt.subplots(figsize=(max(12, len(cases) * 0.65), max(4, len(models) * 0.55)))
    cmap = plt.cm.RdYlGn.copy()
    cmap.set_bad(color='lightgray')
    im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=3, aspect='auto')

    ax.set_xticks(range(len(cases)))
    ax.set_xticklabels(cases, rotation=50, ha='right', fontsize=7)
    ax.set_yticks(range(len(models)))
    ax.set_yticklabels(models, fontsize=10)

    for i in range(len(models)):
        for j in range(len(cases)):
            val = matrix[i, j]
            if np.isnan(val):
                ax.text(j, i, "–", ha="center", va="center", fontsize=8, color="gray")
            else:
                color = "white" if val <= 1 else "black"
                ax.text(j, i, str(int(val)), ha="center", va="center",
                        fontsize=10, fontweight="bold", color=color)

    ax.set_title(f"Total Score (0–3) — {TIER_LABELS[tier]}", fontsize=13)
    plt.colorbar(im, ax=ax, label="Score", shrink=0.8)
    plt.tight_layout()
    fname = FIGS_DIR / f"heatmap_t{tier}.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"  Saved: {fname}")
    plt.close()


# ── Figure 3: Per-axis breakdown per tier ────────────────────────────

def fig_per_axis_all_tiers(data):
    tiers = [1, 2, 3]
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)

    for ax, tier in zip(axes, tiers):
        td = [d for d in data if d["tier"] == tier]
        models = [m for m in MODEL_ORDER if m in set(d["model"] for d in td)]
        x = np.arange(len(models))
        width = 0.25

        for ai, (axis, color, label) in enumerate([
            ("rc", "#1976d2", "Root Cause"),
            ("lf", "#388e3c", "Local Fix"),
            ("gf", "#f57c00", "Global Fix"),
        ]):
            avgs = [np.mean([d[axis] for d in td if d["model"] == m]) if
                    [d[axis] for d in td if d["model"] == m] else 0 for m in models]
            ax.bar(x + ai * width, avgs, width, label=label, color=color, alpha=0.85)

        ax.set_title(TIER_LABELS[tier], fontsize=12)
        ax.set_xticks(x + width)
        ax.set_xticklabels(models, fontsize=7, rotation=30, ha="right")
        ax.set_ylim(0, 1.15)
        if tier == 1:
            ax.set_ylabel("Score (0–1)")
        if tier == 3:
            ax.legend(fontsize=8, loc="upper right")

    fig.suptitle("Per-Axis Scores by Model × Tier", fontsize=14, y=1.02)
    plt.tight_layout()
    fname = FIGS_DIR / "per_axis_all_tiers.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"  Saved: {fname}")
    plt.close()


# ── Figure 4: Tool usage comparison across tiers ─────────────────────

def fig_tool_usage(data):
    tiers = [1, 2, 3]
    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in data)]

    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(len(models))
    width = 0.25

    for ti, tier in enumerate(tiers):
        td = [d for d in data if d["tier"] == tier]
        avgs = [np.mean([d["tool_calls"] for d in td if d["model"] == m]) if
                [d for d in td if d["model"] == m] else 0 for m in models]
        ax.bar(x + ti * width, avgs, width,
               label=TIER_LABELS[tier], color=TIER_COLORS[tier], alpha=0.85)

    ax.set_ylabel("Avg Tool Calls per Case")
    ax.set_title("Tool Usage by Model × Tier")
    ax.set_xticks(x + width)
    ax.set_xticklabels(models, fontsize=9)
    ax.legend(fontsize=9)
    plt.tight_layout()
    fname = FIGS_DIR / "tool_usage_cross_tier.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"  Saved: {fname}")
    plt.close()


# ── Figure 5: CMW impact — T3 baseline vs T3+CMW ────────────────────

def fig_cmw_comparison(baseline_data, cmw_data):
    if not cmw_data:
        print("  No CMW data — skipping")
        return

    # Get T3 baseline
    t3 = [d for d in baseline_data if d["tier"] == 3]
    # Only compare cases that exist in both
    cmw_cases = set(d["case"] for d in cmw_data)
    t3 = [d for d in t3 if d["case"] in cmw_cases]

    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in cmw_data)]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Panel A: Mean score comparison
    ax = axes[0]
    x = np.arange(len(models))
    width = 0.35
    baseline_avgs = [np.mean([d["total"] for d in t3 if d["model"] == m]) if
                     [d for d in t3 if d["model"] == m] else 0 for m in models]
    cmw_avgs = [np.mean([d["total"] for d in cmw_data if d["model"] == m]) if
                [d for d in cmw_data if d["model"] == m] else 0 for m in models]

    ax.bar(x - width / 2, baseline_avgs, width, label="T3 (one-shot)", color="#7b1fa2", alpha=0.75)
    ax.bar(x + width / 2, cmw_avgs, width, label="T3 + CMW", color="#388e3c", alpha=0.75)

    for i, (b, c) in enumerate(zip(baseline_avgs, cmw_avgs)):
        delta = c - b
        if abs(delta) > 0.01:
            color = "#388e3c" if delta > 0 else "#d32f2f"
            ax.annotate(f"+{delta:.2f}" if delta > 0 else f"{delta:.2f}",
                        xy=(i + width / 2, c + 0.05), fontsize=7, ha="center", color=color)

    ax.set_ylabel("Mean Total Score (0–3)")
    ax.set_title("(a) One-Shot vs Check-My-Work")
    ax.set_xticks(x)
    ax.set_xticklabels(models, fontsize=8, rotation=20, ha="right")
    ax.legend(fontsize=8)
    ax.set_ylim(0, 3.5)

    # Panel B: Avg checks to perfect + stale rate
    ax = axes[1]
    avg_checks = [np.mean([d["num_checks"] for d in cmw_data if d["model"] == m])
                  for m in models]
    stale_pct = [100 * sum(1 for d in cmw_data if d["model"] == m and d["stale"])
                 / max(1, sum(1 for d in cmw_data if d["model"] == m))
                 for m in models]

    color_checks = "#1976d2"
    color_stale = "#d32f2f"
    bars = ax.bar(x - width / 2, avg_checks, width, label="Avg Checks", color=color_checks, alpha=0.75)
    ax2 = ax.twinx()
    ax2.bar(x + width / 2, stale_pct, width, label="Stale %", color=color_stale, alpha=0.5)

    ax.set_ylabel("Avg Checks", color=color_checks)
    ax2.set_ylabel("Stale Exit %", color=color_stale)
    ax.set_title("(b) Convergence Effort")
    ax.set_xticks(x)
    ax.set_xticklabels(models, fontsize=8, rotation=20, ha="right")
    ax.set_ylim(0, 5)
    ax2.set_ylim(0, 100)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="upper left")

    fig.suptitle("Check-My-Work: Iterative Feedback Impact on T3", fontsize=14, y=1.02)
    plt.tight_layout()
    fname = FIGS_DIR / "cmw_comparison.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"  Saved: {fname}")
    plt.close()


# ── Figure 6: CMW checks-to-axis (how many rounds per axis) ─────────

def fig_cmw_checks_to_axis(cmw_data):
    if not cmw_data:
        return

    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in cmw_data)]
    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(len(models))
    width = 0.25

    for ai, (field, color, label) in enumerate([
        ("checks_to_rc", "#1976d2", "Root Cause"),
        ("checks_to_lf", "#388e3c", "Local Fix"),
        ("checks_to_gf", "#f57c00", "Global Fix"),
    ]):
        avgs = []
        for m in models:
            vals = [d[field] for d in cmw_data if d["model"] == m and d[field] is not None]
            avgs.append(np.mean(vals) if vals else 0)
        ax.bar(x + ai * width, avgs, width, label=label, color=color, alpha=0.85)

    ax.set_ylabel("Avg Check # When Axis First Achieved")
    ax.set_title("Check-My-Work: Checks Needed per Axis")
    ax.set_xticks(x + width)
    ax.set_xticklabels(models, fontsize=9)
    ax.legend(fontsize=9)
    ax.set_ylim(0, 4.5)
    plt.tight_layout()
    fname = FIGS_DIR / "cmw_checks_to_axis.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"  Saved: {fname}")
    plt.close()


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("Loading baseline data...")
    data = load_scored_data(RESULTS_DIR)
    print(f"  {len(data)} scored runs")

    for tier in [1, 2, 3]:
        td = [d for d in data if d["tier"] == tier]
        print(f"  T{tier}: {len(td)} runs, {len(set(d['case'] for d in td))} cases")

    print("\nLoading CMW data...")
    cmw = load_cmw_data()
    print(f"  {len(cmw)} CMW runs")

    print("\nGenerating figures...")

    print("  Fig 1: Cross-tier mean scores")
    fig_cross_tier_means(data)

    for tier in [1, 2, 3]:
        print(f"  Fig 2: T{tier} heatmap")
        fig_tier_heatmap(data, tier)

    print("  Fig 3: Per-axis all tiers")
    fig_per_axis_all_tiers(data)

    print("  Fig 4: Tool usage")
    fig_tool_usage(data)

    print("  Fig 5: CMW comparison")
    fig_cmw_comparison(data, cmw)

    print("  Fig 6: CMW checks-to-axis")
    fig_cmw_checks_to_axis(cmw)

    print("\nDone!")


if __name__ == "__main__":
    main()
