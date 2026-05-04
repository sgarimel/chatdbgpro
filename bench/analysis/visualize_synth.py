#!/usr/bin/env python3
"""
Visualize synthetic case results across models and tiers.
Generates heatmaps, bar charts, and tool breakdown charts.
Output: bench/analysis/figs/
"""
import json
import glob
import os
from pathlib import Path
from collections import defaultdict

import matplotlib.pyplot as plt
import matplotlib
import numpy as np

matplotlib.rcParams['font.size'] = 11

RESULTS_DIR = Path("bench/results/synth-8model-sweep")
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
               "Llama-8B", "Nemotron-30B", "Qwen-30B"]

TIER_MAP = {
    1: "T1: bash",
    2: "T2: bash+gdb",
    3: "T3: ChatDBG",
    4: "T4: Claude Code",
}


def load_data():
    data = []
    for f in sorted(glob.glob(str(RESULTS_DIR / "*/score.json"))):
        run_dir = Path(f).parent
        with open(f) as fh:
            score = json.load(fh)
        result_f = run_dir / "result.json"
        collect_f = run_dir / "collect.json"
        if not result_f.exists():
            continue
        with open(result_f) as fh:
            result = json.load(fh)

        # Parse model name
        model_raw = result.get("model", "?").replace("/", "_")
        model = "?"
        for k, v in MODEL_MAP.items():
            if k in run_dir.name:
                model = v
                break

        sc = score.get("scores", {})
        tc = 0
        tf = {}
        tokens = 0
        if collect_f.exists():
            with open(collect_f) as fh:
                c = json.load(fh)
            q = c.get("queries", [{}])[0]
            tc = q.get("num_tool_calls", 0)
            tf = q.get("tool_frequency", {})
            tokens = q.get("stats", {}).get("total_tokens", 0)

        data.append({
            "case": result.get("case_id", "?"),
            "model": model,
            "tier": result.get("tier", 0),
            "tier_label": TIER_MAP.get(result.get("tier", 0), f"T{result.get('tier', '?')}"),
            "rc": sc.get("root_cause", 0),
            "lf": sc.get("local_fix", 0),
            "gf": sc.get("global_fix", 0),
            "total": sc.get("root_cause", 0) + sc.get("local_fix", 0) + sc.get("global_fix", 0),
            "tool_calls": tc,
            "tool_freq": tf,
            "tokens": tokens,
            "elapsed_s": result.get("elapsed_s", 0),
            "status": result.get("status", "?"),
        })
    return data


def plot_tier_heatmap(data, tier, suffix=""):
    """Heatmap: Total Score by Model × Case for a single tier."""
    tier_data = [d for d in data if d["tier"] == tier]
    if not tier_data:
        print(f"  No data for tier {tier}")
        return

    cases = sorted(set(d["case"] for d in tier_data))
    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in tier_data)]

    matrix = np.full((len(models), len(cases)), np.nan)
    for d in tier_data:
        if d["model"] in models and d["case"] in cases:
            mi = models.index(d["model"])
            ci = cases.index(d["case"])
            matrix[mi, ci] = d["total"]

    fig, ax = plt.subplots(figsize=(max(12, len(cases) * 0.7), max(4, len(models) * 0.6)))
    cmap = plt.cm.RdYlGn
    cmap.set_bad(color='lightgray')
    im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=3, aspect='auto')

    ax.set_xticks(range(len(cases)))
    ax.set_xticklabels(cases, rotation=45, ha='right', fontsize=8)
    ax.set_yticks(range(len(models)))
    ax.set_yticklabels(models, fontsize=10)

    for i in range(len(models)):
        for j in range(len(cases)):
            val = matrix[i, j]
            if np.isnan(val):
                ax.text(j, i, "-", ha="center", va="center", fontsize=9, color="gray")
            else:
                color = "white" if val <= 1 else "black"
                ax.text(j, i, str(int(val)), ha="center", va="center",
                        fontsize=11, fontweight="bold", color=color)

    tier_label = TIER_MAP.get(tier, f"Tier {tier}")
    ax.set_title(f"Total Score (RC+LF+GF, 0-3) — {tier_label}\nby Model × Case", fontsize=13)
    plt.colorbar(im, ax=ax, label="Score (0-3)", shrink=0.8)
    plt.tight_layout()
    fname = FIGS_DIR / f"synth_t{tier}_heatmap{suffix}.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"  Saved: {fname}")
    plt.close()


def plot_model_averages(data, tiers=None, suffix=""):
    """Bar chart: average score per model across cases."""
    if tiers is None:
        tiers = sorted(set(d["tier"] for d in data))

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(MODEL_ORDER))
    width = 0.8 / len(tiers)
    colors = ["#388e3c", "#1976d2", "#f57c00", "#7b1fa2"]

    for ti, tier in enumerate(tiers):
        tier_data = [d for d in data if d["tier"] == tier]
        avgs = []
        for model in MODEL_ORDER:
            vals = [d["total"] for d in tier_data if d["model"] == model]
            avgs.append(np.mean(vals) if vals else 0)
        bars = ax.bar(x + ti * width, avgs, width,
                      label=TIER_MAP.get(tier, f"T{tier}"),
                      color=colors[ti % len(colors)])
        for bar, val in zip(bars, avgs):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                        f"{val:.1f}", ha="center", va="bottom", fontsize=8)

    ax.set_xlabel("Model")
    ax.set_ylabel("Mean Total Score (0-3)")
    ax.set_title("Mean Debugging Score by Model × Tier")
    ax.set_xticks(x + width * (len(tiers) - 1) / 2)
    ax.set_xticklabels(MODEL_ORDER, fontsize=9)
    ax.legend(fontsize=9)
    ax.set_ylim(0, 3.5)
    plt.tight_layout()
    fname = FIGS_DIR / f"synth_mean_scores{suffix}.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"  Saved: {fname}")
    plt.close()


def plot_per_axis(data, tier, suffix=""):
    """Grouped bar: RC/LF/GF per model for a tier."""
    tier_data = [d for d in data if d["tier"] == tier]
    if not tier_data:
        return

    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in tier_data)]
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(models))
    width = 0.25

    for ai, (axis, color, label) in enumerate([
        ("rc", "#1976d2", "Root Cause"),
        ("lf", "#388e3c", "Local Fix"),
        ("gf", "#f57c00", "Global Fix"),
    ]):
        avgs = []
        for model in models:
            vals = [d[axis] for d in tier_data if d["model"] == model]
            avgs.append(np.mean(vals) if vals else 0)
        bars = ax.bar(x + ai * width, avgs, width, label=label, color=color)
        for bar, val in zip(bars, avgs):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                        f"{val:.2f}", ha="center", va="bottom", fontsize=7)

    tier_label = TIER_MAP.get(tier, f"T{tier}")
    ax.set_title(f"Per-Axis Scores — {tier_label}")
    ax.set_xticks(x + width)
    ax.set_xticklabels(models, fontsize=9)
    ax.set_ylabel("Score (0-1)")
    ax.set_ylim(0, 1.2)
    ax.legend()
    plt.tight_layout()
    fname = FIGS_DIR / f"synth_t{tier}_per_axis{suffix}.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"  Saved: {fname}")
    plt.close()


def plot_tool_usage(data, tier, suffix=""):
    """Bar chart: tool calls per model for a tier."""
    tier_data = [d for d in data if d["tier"] == tier]
    if not tier_data:
        return

    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in tier_data)]
    fig, ax = plt.subplots(figsize=(10, 5))

    avgs = []
    for model in models:
        vals = [d["tool_calls"] for d in tier_data if d["model"] == model]
        avgs.append(np.mean(vals) if vals else 0)

    bars = ax.bar(range(len(models)), avgs, color="#7b1fa2")
    for bar, val in zip(bars, avgs):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2,
                f"{val:.1f}", ha="center", fontsize=9)

    tier_label = TIER_MAP.get(tier, f"T{tier}")
    ax.set_title(f"Avg Tool Calls per Case — {tier_label}")
    ax.set_xticks(range(len(models)))
    ax.set_xticklabels(models, fontsize=9)
    ax.set_ylabel("Avg Tool Calls")
    plt.tight_layout()
    fname = FIGS_DIR / f"synth_t{tier}_tool_calls{suffix}.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"  Saved: {fname}")
    plt.close()


def print_table(data):
    """Print summary table."""
    tiers = sorted(set(d["tier"] for d in data))
    for tier in tiers:
        tier_data = [d for d in data if d["tier"] == tier]
        tier_label = TIER_MAP.get(tier, f"T{tier}")
        models = [m for m in MODEL_ORDER if m in set(d["model"] for d in tier_data)]
        cases = sorted(set(d["case"] for d in tier_data))

        print(f"\n{'=' * 80}")
        print(f"  {tier_label} — {len(cases)} cases × {len(models)} models")
        print(f"{'=' * 80}")

        for model in models:
            mdata = [d for d in tier_data if d["model"] == model]
            avg = np.mean([d["total"] for d in mdata]) if mdata else 0
            perfect = sum(1 for d in mdata if d["total"] == 3)
            nonzero = sum(1 for d in mdata if d["total"] > 0)
            avg_tc = np.mean([d["tool_calls"] for d in mdata]) if mdata else 0
            print(f"  {model:<14} avg={avg:.2f}/3  perfect={perfect}/{len(mdata)}  "
                  f"nonzero={nonzero}/{len(mdata)}  avg_tools={avg_tc:.1f}")


def main():
    data = load_data()
    print(f"Loaded {len(data)} scored runs")

    print_table(data)

    tiers = sorted(set(d["tier"] for d in data))
    for tier in tiers:
        print(f"\nGenerating {TIER_MAP.get(tier, f'T{tier}')} visualizations...")
        plot_tier_heatmap(data, tier)
        plot_per_axis(data, tier)
        plot_tool_usage(data, tier)

    if len(tiers) > 1:
        print("\nGenerating cross-tier comparison...")
        plot_model_averages(data, tiers)

    # Save raw data as JSON
    report_path = FIGS_DIR / "synth_report.json"
    with open(report_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"\nSaved: {report_path}")


if __name__ == "__main__":
    main()
