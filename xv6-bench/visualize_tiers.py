#!/usr/bin/env python3
"""
Visualize xv6-bench tier ablation results.
Produces heatmaps and bar charts for the paper/poster.
"""
import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib
import numpy as np

matplotlib.rcParams['font.size'] = 12

RESULTS_DIR = Path("results/xv6-4tier-20260503_185537")

MODELS = {
    "openrouter_openai_gpt-4o": "GPT-4o",
    "openrouter_openai_gpt-5.5": "GPT-5.5",
    "openrouter_x-ai_grok-4": "Grok-4",
    "openrouter_anthropic_claude-sonnet-4-5-20250514": "Sonnet-4.5",
    "openrouter_google_gemini-2.5-flash": "Gemini-2.5",
    "openrouter_meta-llama_llama-3.1-8b-instruct": "Llama-8B",
    "openrouter_nvidia_nemotron-3-nano-30b-a3b": "Nemotron-30B",
    "openrouter_qwen_qwen3-30b-a3b-instruct-2507": "Qwen-30B",
}

TIERS = {
    "tier0_garbage_all_tools": "Tier 0\nGarbage prompt\nLLDB + bash",
    "tier1_enriched_all_tools": "Tier 1\nEnriched prompt\nLLDB + bash",
    "tier2_enriched_lldb_only": "Tier 2\nEnriched prompt\nLLDB only",
    "tier3_enriched_all_tools": "Tier 3\nEnriched prompt\nLLDB + bash",
}

TIER_SHORT = {
    "tier0_garbage_all_tools": "T0: Garbage+All",
    "tier1_enriched_all_tools": "T1: Enriched+All",
    "tier2_enriched_lldb_only": "T2: Enriched+LLDB",
    "tier3_enriched_all_tools": "T3: Enriched+All",
}


def load_all_data():
    """Load scores, tool calls, tokens, and responses for all runs."""
    data = []
    for d in sorted(RESULTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        score_f = d / "score.json"
        collect_f = d / "collect.json"
        result_f = d / "result.json"
        if not score_f.exists():
            continue

        parts = d.name.split("__")
        # bug_id__model_slug__tier
        model_slug = "__".join(parts[1:-1])
        tier = parts[-1]

        with open(score_f) as f:
            scores = json.load(f).get("scores", {})
        with open(score_f) as f:
            rationale = json.load(f).get("rationale", {})

        tool_calls = 0
        tool_freq = {}
        tokens = 0
        response = ""
        prompt = ""
        if collect_f.exists():
            with open(collect_f) as f:
                c = json.load(f)
            q = c.get("queries", [{}])[0]
            tool_calls = q.get("num_tool_calls", 0)
            tool_freq = q.get("tool_frequency", {})
            tokens = q.get("stats", {}).get("total_tokens", 0)
            response = q.get("response", "")
            prompt = q.get("prompt", "")

        elapsed = 0
        if result_f.exists():
            with open(result_f) as f:
                elapsed = json.load(f).get("elapsed_s", 0)

        data.append({
            "model": model_slug,
            "model_short": MODELS.get(model_slug, model_slug),
            "tier": tier,
            "tier_short": TIER_SHORT.get(tier, tier),
            "rc": scores.get("root_cause", 0),
            "lf": scores.get("local_fix", 0),
            "gf": scores.get("global_fix", 0),
            "total": scores.get("root_cause", 0) + scores.get("local_fix", 0) + scores.get("global_fix", 0),
            "tool_calls": tool_calls,
            "tool_freq": tool_freq,
            "tokens": tokens,
            "elapsed_s": elapsed,
            "response": response,
            "prompt": prompt,
            "rationale": rationale,
        })
    return data


def plot_heatmap(data):
    """Heatmap: Total Score (0-3) by Model × Tier."""
    model_order = ["GPT-4o", "GPT-5.5", "Grok-4", "Sonnet-4.5", "Gemini-2.5", "Llama-8B", "Nemotron-30B", "Qwen-30B"]
    tier_order = list(TIER_SHORT.values())

    matrix = np.zeros((len(model_order), len(tier_order)))
    for d in data:
        mi = model_order.index(d["model_short"]) if d["model_short"] in model_order else -1
        ti = tier_order.index(d["tier_short"]) if d["tier_short"] in tier_order else -1
        if mi >= 0 and ti >= 0:
            matrix[mi, ti] = d["total"]

    fig, ax = plt.subplots(figsize=(10, 5))
    cmap = plt.cm.RdYlGn
    im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=3, aspect='auto')

    ax.set_xticks(range(len(tier_order)))
    ax.set_xticklabels(tier_order, fontsize=10)
    ax.set_yticks(range(len(model_order)))
    ax.set_yticklabels(model_order, fontsize=12)

    for i in range(len(model_order)):
        for j in range(len(tier_order)):
            val = int(matrix[i, j])
            color = "white" if val <= 1 else "black"
            ax.text(j, i, str(val), ha="center", va="center",
                    fontsize=16, fontweight="bold", color=color)

    ax.set_title("xv6 Kernel Debugging: Total Score (root_cause + local_fix + global_fix)\nby Model × Tier", fontsize=13)
    plt.colorbar(im, ax=ax, label="Score (0-3)")
    plt.tight_layout()
    plt.savefig("results/xv6_tier_heatmap.png", dpi=150, bbox_inches="tight")
    print("Saved: results/xv6_tier_heatmap.png")
    plt.close()


def plot_tool_calls(data):
    """Bar chart: Tool calls per tier per model."""
    model_order = ["GPT-4o", "GPT-5.5", "Grok-4", "Sonnet-4.5", "Gemini-2.5", "Llama-8B", "Nemotron-30B", "Qwen-30B"]
    tier_order = list(TIER_SHORT.values())
    colors = ["#d32f2f", "#f57c00", "#1976d2", "#388e3c"]

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(model_order))
    width = 0.2

    for ti, tier in enumerate(tier_order):
        vals = []
        for model in model_order:
            match = [d for d in data if d["model_short"] == model and d["tier_short"] == tier]
            vals.append(match[0]["tool_calls"] if match else 0)
        bars = ax.bar(x + ti * width, vals, width, label=tier, color=colors[ti])
        for bar, val in zip(bars, vals):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                        str(val), ha="center", va="bottom", fontsize=9)

    ax.set_xlabel("Model")
    ax.set_ylabel("Tool Calls")
    ax.set_title("Debugger Tool Calls by Model × Tier")
    ax.set_xticks(x + 1.5 * width)
    ax.set_xticklabels(model_order)
    ax.legend(fontsize=8, loc="upper left")
    ax.set_ylim(0, max(d["tool_calls"] for d in data) + 3)
    plt.tight_layout()
    plt.savefig("results/xv6_tier_tool_calls.png", dpi=150, bbox_inches="tight")
    print("Saved: results/xv6_tier_tool_calls.png")
    plt.close()


def plot_tool_breakdown(data):
    """Stacked bar: Tool type breakdown for tiers 2 and 3."""
    model_order = ["GPT-4o", "GPT-5.5", "Grok-4", "Sonnet-4.5", "Gemini-2.5", "Llama-8B", "Nemotron-30B", "Qwen-30B"]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    for ax, tier_key, title in [
        (axes[0], "T2: LLDB", "Tier 2: LLDB Only"),
        (axes[1], "T3: LLDB+bash", "Tier 3: LLDB + Bash"),
    ]:
        # Categorize tools
        categories = {"LLDB debug": 0, "code/definition": 0, "bash": 0, "other": 0}
        model_cats = {m: dict(categories) for m in model_order}

        for d in data:
            if d["tier_short"] != tier_key:
                continue
            m = d["model_short"]
            if m not in model_cats:
                continue
            for tool, count in d["tool_freq"].items():
                tl = tool.lower()
                if tl.startswith("bash"):
                    model_cats[m]["bash"] += count
                elif tl in ("code", "definition"):
                    model_cats[m]["code/definition"] += count
                elif tl in ("bt", "frame", "register", "thread", "info",
                            "image", "list", "source", "disassemble",
                            "breakpoint", "expr", "expression", "up", "down",
                            "next", "step", "print", "p", "x/10i",
                            "target", "lldb", "break", "run", "symbol", "dx"):
                    model_cats[m]["LLDB debug"] += count
                else:
                    model_cats[m]["other"] += count

        x = np.arange(len(model_order))
        bottom = np.zeros(len(model_order))
        cat_colors = {"LLDB debug": "#1976d2", "code/definition": "#7b1fa2",
                      "bash": "#388e3c", "other": "#9e9e9e"}

        for cat in ["LLDB debug", "code/definition", "bash", "other"]:
            vals = [model_cats[m][cat] for m in model_order]
            ax.bar(x, vals, 0.6, bottom=bottom, label=cat, color=cat_colors[cat])
            bottom += np.array(vals)

        ax.set_title(title, fontsize=12)
        ax.set_xticks(x)
        ax.set_xticklabels(model_order, fontsize=10)
        ax.set_ylabel("Tool Calls")
        ax.legend(fontsize=8)

    plt.suptitle("Tool Type Breakdown: What Models Actually Use", fontsize=13, y=1.02)
    plt.tight_layout()
    plt.savefig("results/xv6_tier_tool_breakdown.png", dpi=150, bbox_inches="tight")
    print("Saved: results/xv6_tier_tool_breakdown.png")
    plt.close()


def print_summary_table(data):
    """Print a detailed text table with all data."""
    model_order = ["GPT-4o", "GPT-5.5", "Grok-4", "Sonnet-4.5", "Gemini-2.5", "Llama-8B", "Nemotron-30B", "Qwen-30B"]
    tier_order = list(TIER_SHORT.values())

    print("\n" + "=" * 90)
    print("xv6 Kernel Debugging Ablation: bug1-uvmcopy-perm")
    print("=" * 90)
    print(f"{'Model':<14} {'Tier':<18} {'RC':>3} {'LF':>3} {'GF':>3} {'Tot':>4} {'Tools':>6} {'Tokens':>7} {'Time':>7}  Tool Types")
    print("-" * 90)

    for model in model_order:
        for tier in tier_order:
            match = [d for d in data if d["model_short"] == model and d["tier_short"] == tier]
            if not match:
                continue
            d = match[0]
            tools_str = ", ".join(f"{k}:{v}" for k, v in sorted(d["tool_freq"].items(), key=lambda x: -x[1])[:4])
            print(f"{model:<14} {tier:<18} {d['rc']:>3} {d['lf']:>3} {d['gf']:>3} {d['total']:>4} {d['tool_calls']:>6} {d['tokens']:>7} {d['elapsed_s']:>6.1f}s  {tools_str}")
        print()

    # Save detailed JSON report
    report = []
    for d in data:
        report.append({
            "model": d["model_short"],
            "tier": d["tier_short"],
            "scores": {"root_cause": d["rc"], "local_fix": d["lf"], "global_fix": d["gf"]},
            "tool_calls": d["tool_calls"],
            "tool_frequency": d["tool_freq"],
            "tokens": d["tokens"],
            "elapsed_s": d["elapsed_s"],
            "response_preview": d["response"][:300],
            "rationale": d["rationale"],
        })
    with open("results/xv6_tier_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Saved: results/xv6_tier_report.json")


def main():
    data = load_all_data()
    print(f"Loaded {len(data)} runs")

    print_summary_table(data)
    plot_heatmap(data)
    plot_tool_calls(data)
    plot_tool_breakdown(data)


if __name__ == "__main__":
    main()
