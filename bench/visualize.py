#!/usr/bin/env python3
"""Visualize ChatDBG ablation results from scored runs.

Reads score.json + result.json + collect.json from each run directory
and produces comparison charts.

Usage:
    python bench/visualize.py --results-dir bench/results/ablation-synthetic-4models
    python bench/visualize.py --results-dir bench/results/ablation-synthetic-4models --output bench/figures
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    sys.exit("matplotlib and numpy required: pip install matplotlib numpy")


MODEL_SHORT = {
    "openrouter/openai/gpt-4": "GPT-4",
    "openrouter/nvidia/nemotron-3-nano-30b-a3b": "Nemotron-30B",
    "openrouter/qwen/qwen3-30b-a3b-instruct-2507": "Qwen-30B",
    "openrouter/ai21/jamba-1.5-mini": "Jamba-Mini",
    "openrouter/meta-llama/llama-3.1-8b-instruct": "Llama-8B",
}


def short_model(name: str) -> str:
    return MODEL_SHORT.get(name, name.split("/")[-1][:20])


def load_runs(results_dir: Path) -> list[dict]:
    """Load all scored runs from a results directory."""
    runs = []
    for run_dir in sorted(results_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        result_path = run_dir / "result.json"
        score_path = run_dir / "score.json"
        collect_path = run_dir / "collect.json"
        if not result_path.exists():
            continue

        result = json.loads(result_path.read_text())
        score = json.loads(score_path.read_text()) if score_path.exists() else None
        collect = json.loads(collect_path.read_text()) if collect_path.exists() else None

        entry = {
            "run_id": result.get("run_id", run_dir.name),
            "case_id": result.get("case_id", "?"),
            "model": result.get("model", "?"),
            "tier": result.get("tier", 3),
            "status": result.get("status", "?"),
            "elapsed_s": result.get("elapsed_s", 0),
        }

        if score:
            scores = score.get("scores", {})
            entry["root_cause"] = scores.get("root_cause", 0)
            entry["local_fix"] = scores.get("local_fix", 0)
            entry["global_fix"] = scores.get("global_fix", 0)
            entry["rationale"] = score.get("rationale", {})

        if collect:
            queries = collect.get("queries", [])
            if queries:
                q = queries[0]
                entry["num_tool_calls"] = q.get("num_tool_calls", 0)
                entry["tool_frequency"] = q.get("tool_frequency", {})
                stats = q.get("stats", {})
                entry["tokens"] = stats.get("tokens", 0)
                entry["prompt_tokens"] = stats.get("prompt_tokens", 0)
                entry["completion_tokens"] = stats.get("completion_tokens", 0)
                entry["cost"] = stats.get("cost", 0)

        runs.append(entry)
    return runs


def group_by_model(runs: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for r in runs:
        groups.setdefault(r["model"], []).append(r)
    return groups


def plot_scores_by_model(runs: list[dict], output: Path):
    """Grouped bar chart: score axes by model."""
    by_model = group_by_model(runs)
    models = sorted(by_model.keys(), key=lambda m: short_model(m))
    axes = ["root_cause", "local_fix", "global_fix"]

    means = {ax: [] for ax in axes}
    for model in models:
        mr = [r for r in by_model[model] if "root_cause" in r]
        n = len(mr) or 1
        for ax in axes:
            means[ax].append(sum(r.get(ax, 0) for r in mr) / n)

    x = np.arange(len(models))
    width = 0.25
    fig, ax = plt.subplots(figsize=(10, 5))

    colors = ["#2196F3", "#4CAF50", "#FF9800"]
    for i, (axis, color) in enumerate(zip(axes, colors)):
        bars = ax.bar(x + i * width, means[axis], width, label=axis.replace("_", " ").title(),
                      color=color, edgecolor="white")
        for bar, val in zip(bars, means[axis]):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                    f"{val:.2f}", ha="center", va="bottom", fontsize=8)

    ax.set_ylabel("Score (0-1)")
    ax.set_title("Debugging Scores by Model")
    ax.set_xticks(x + width)
    ax.set_xticklabels([short_model(m) for m in models], rotation=15, ha="right")
    ax.set_ylim(0, 1.15)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output / "scores_by_model.png", dpi=150)
    plt.close(fig)
    print(f"  -> {output / 'scores_by_model.png'}")


def plot_tool_calls_by_model(runs: list[dict], output: Path):
    """Bar chart: average tool calls per model."""
    by_model = group_by_model(runs)
    models = sorted(by_model.keys(), key=lambda m: short_model(m))

    avg_tools = []
    for model in models:
        mr = by_model[model]
        n = len(mr) or 1
        avg_tools.append(sum(r.get("num_tool_calls", 0) for r in mr) / n)

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar([short_model(m) for m in models], avg_tools,
                  color=["#2196F3", "#4CAF50", "#FF9800", "#9C27B0"][:len(models)],
                  edgecolor="white")
    for bar, val in zip(bars, avg_tools):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                f"{val:.1f}", ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("Avg Tool Calls per Case")
    ax.set_title("Debugger Tool Usage by Model")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output / "tool_calls_by_model.png", dpi=150)
    plt.close(fig)
    print(f"  -> {output / 'tool_calls_by_model.png'}")


def plot_time_by_model(runs: list[dict], output: Path):
    """Bar chart: average elapsed time per model."""
    by_model = group_by_model(runs)
    models = sorted(by_model.keys(), key=lambda m: short_model(m))

    avg_time = []
    for model in models:
        mr = by_model[model]
        n = len(mr) or 1
        avg_time.append(sum(r.get("elapsed_s", 0) for r in mr) / n)

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar([short_model(m) for m in models], avg_time,
                  color=["#2196F3", "#4CAF50", "#FF9800", "#9C27B0"][:len(models)],
                  edgecolor="white")
    for bar, val in zip(bars, avg_time):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f"{val:.1f}s", ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("Avg Elapsed Time (s)")
    ax.set_title("Debugging Time by Model")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output / "time_by_model.png", dpi=150)
    plt.close(fig)
    print(f"  -> {output / 'time_by_model.png'}")


def plot_heatmap(runs: list[dict], output: Path):
    """Heatmap: model × case, colored by total score (rc + lf + gf)."""
    by_model = group_by_model(runs)
    models = sorted(by_model.keys(), key=lambda m: short_model(m))
    cases = sorted(set(r["case_id"] for r in runs))

    matrix = np.zeros((len(models), len(cases)))
    for i, model in enumerate(models):
        case_map = {r["case_id"]: r for r in by_model[model]}
        for j, case in enumerate(cases):
            r = case_map.get(case, {})
            matrix[i, j] = r.get("root_cause", 0) + r.get("local_fix", 0) + r.get("global_fix", 0)

    fig, ax = plt.subplots(figsize=(12, 4))
    im = ax.imshow(matrix, cmap="RdYlGn", vmin=0, vmax=3, aspect="auto")
    ax.set_xticks(range(len(cases)))
    ax.set_xticklabels(cases, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(models)))
    ax.set_yticklabels([short_model(m) for m in models])
    for i in range(len(models)):
        for j in range(len(cases)):
            ax.text(j, i, f"{int(matrix[i, j])}", ha="center", va="center",
                    fontsize=10, fontweight="bold",
                    color="white" if matrix[i, j] < 1.5 else "black")
    ax.set_title("Total Score (root_cause + local_fix + global_fix) by Model x Case")
    fig.colorbar(im, ax=ax, label="Score (0-3)")
    fig.tight_layout()
    fig.savefig(output / "heatmap_model_case.png", dpi=150)
    plt.close(fig)
    print(f"  -> {output / 'heatmap_model_case.png'}")


def plot_tokens_vs_score(runs: list[dict], output: Path):
    """Scatter plot: total tokens vs total score, colored by model."""
    fig, ax = plt.subplots(figsize=(8, 5))
    by_model = group_by_model(runs)
    colors = ["#2196F3", "#4CAF50", "#FF9800", "#9C27B0", "#F44336"]
    for i, (model, mr) in enumerate(sorted(by_model.items(), key=lambda x: short_model(x[0]))):
        tokens = [r.get("tokens", 0) for r in mr]
        scores = [r.get("root_cause", 0) + r.get("local_fix", 0) + r.get("global_fix", 0) for r in mr]
        ax.scatter(tokens, scores, label=short_model(model),
                   color=colors[i % len(colors)], s=60, alpha=0.8, edgecolors="white")
    ax.set_xlabel("Total Tokens")
    ax.set_ylabel("Total Score (0-3)")
    ax.set_title("Token Usage vs Debugging Score")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output / "tokens_vs_score.png", dpi=150)
    plt.close(fig)
    print(f"  -> {output / 'tokens_vs_score.png'}")


def print_summary_table(runs: list[dict]):
    """Print a text summary table."""
    by_model = group_by_model(runs)
    print("\n" + "=" * 90)
    print(f"{'Model':<20} {'N':>3} {'RC':>5} {'LF':>5} {'GF':>5} "
          f"{'Tools':>6} {'Tokens':>7} {'Time':>6} {'Cost':>6}")
    print("-" * 90)
    for model in sorted(by_model.keys(), key=lambda m: short_model(m)):
        mr = [r for r in by_model[model] if "root_cause" in r]
        n = len(mr) or 1
        rc = sum(r.get("root_cause", 0) for r in mr) / n
        lf = sum(r.get("local_fix", 0) for r in mr) / n
        gf = sum(r.get("global_fix", 0) for r in mr) / n
        tools = sum(r.get("num_tool_calls", 0) for r in mr) / n
        tokens = sum(r.get("tokens", 0) for r in mr) / n
        time_s = sum(r.get("elapsed_s", 0) for r in mr) / n
        cost = sum(r.get("cost", 0) for r in mr)
        print(f"{short_model(model):<20} {n:>3} {rc:>5.2f} {lf:>5.2f} {gf:>5.2f} "
              f"{tools:>6.1f} {tokens:>7.0f} {time_s:>5.1f}s ${cost:>5.3f}")
    print("=" * 90)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results-dir", required=True,
                   help="Path to scored results directory")
    p.add_argument("--output", default=None,
                   help="Output directory for figures. Default: <results-dir>/figures/")
    args = p.parse_args()

    results_dir = Path(args.results_dir)
    output = Path(args.output) if args.output else results_dir / "figures"
    output.mkdir(parents=True, exist_ok=True)

    runs = load_runs(results_dir)
    scored = [r for r in runs if "root_cause" in r]

    if not scored:
        sys.exit(f"No scored runs found in {results_dir}. Run bench/judge.py first.")

    print(f"[visualize] {len(scored)} scored runs from {results_dir}")

    plot_scores_by_model(scored, output)
    plot_tool_calls_by_model(scored, output)
    plot_time_by_model(scored, output)
    plot_heatmap(scored, output)
    plot_tokens_vs_score(scored, output)
    print_summary_table(scored)

    print(f"\n[visualize] Figures saved to {output}/")


if __name__ == "__main__":
    main()
