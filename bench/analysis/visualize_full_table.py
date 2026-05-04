#!/usr/bin/env python3
"""
Generate a full cross-tier table/heatmap: 8 models × 4 tiers × 3 axes.
Each cell shows the mean score (0-1) for that (model, tier, axis) combo.

Data sources:
  T1/T2: bench/results/synth-8model-sweep (scored)
  T3:    bench/results/synth-t3-unfenced (scored, unfenced debugger)
  T4:    bench/results/synth-t4-sweep (scored, Claude/Sonnet only)
"""
import json
import glob
from pathlib import Path
from collections import defaultdict

import matplotlib.pyplot as plt
import matplotlib
import numpy as np

matplotlib.rcParams['font.size'] = 10
matplotlib.rcParams['font.family'] = 'sans-serif'

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
    "sonnet": "Sonnet-4.5",  # T4 uses bare model name
}

MODEL_ORDER = ["GPT-5.5", "GPT-4o", "Grok-4", "Sonnet-4.5", "Gemini-2.5",
               "Qwen-30B", "Nemotron-30B", "Llama-8B"]

TIER_LABELS = {1: "T1:bash", 2: "T2:bash+gdb", 3: "T3:ChatDBG", 4: "T4:ClaudeCode"}
AXES = ["root_cause", "local_fix", "global_fix"]
AXIS_SHORT = {"root_cause": "RC", "local_fix": "LF", "global_fix": "GF"}


def _model_name(run_dir_name, result=None):
    for k, v in MODEL_MAP.items():
        if k in run_dir_name:
            return v
    # Fallback: check result.json model field
    if result:
        m = result.get("model", "")
        for k, v in MODEL_MAP.items():
            if k in m.replace("/", "_"):
                return v
        # Direct match for T4
        short = m.split("/")[-1] if "/" in m else m
        if short in MODEL_MAP:
            return MODEL_MAP[short]
    return "?"


def load_tier_scores(results_dir, tier_filter=None):
    """Load scored runs, return list of dicts."""
    data = []
    for f in sorted(glob.glob(str(results_dir / "*/score.json"))):
        rd = Path(f).parent
        result = json.load(open(rd / "result.json"))
        if tier_filter and result.get("tier") != tier_filter:
            continue
        if result.get("status") not in ("ok",):
            continue
        score = json.load(open(f))
        sc = score.get("scores", {})
        model = _model_name(rd.name, result)
        data.append({
            "case": result.get("case_id", "?"),
            "model": model,
            "tier": result.get("tier", 0),
            "root_cause": sc.get("root_cause", 0),
            "local_fix": sc.get("local_fix", 0),
            "global_fix": sc.get("global_fix", 0),
            "total": sum(sc.values()),
        })
    return data


def build_table(all_data):
    """Build {model -> {tier -> {axis -> mean_score}}}."""
    # Collect per (model, tier, axis)
    raw = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for d in all_data:
        for axis in AXES:
            raw[d["model"]][d["tier"]][axis].append(d[axis])

    table = {}
    for model in raw:
        table[model] = {}
        for tier in raw[model]:
            table[model][tier] = {}
            for axis in AXES:
                vals = raw[model][tier][axis]
                table[model][tier][axis] = sum(vals) / len(vals) if vals else None
    return table


def fig_full_heatmap(table):
    """12-column heatmap: models × (T1-RC, T1-LF, T1-GF, T2-RC, ...)."""
    tiers = [1, 2, 3, 4]
    models = [m for m in MODEL_ORDER if m in table]

    # Build column headers and data matrix
    col_headers = []
    for t in tiers:
        for axis in AXES:
            col_headers.append(f"{TIER_LABELS[t]}\n{AXIS_SHORT[axis]}")

    matrix = np.full((len(models), len(col_headers)), np.nan)
    for mi, model in enumerate(models):
        ci = 0
        for t in tiers:
            for axis in AXES:
                if t in table.get(model, {}) and axis in table[model][t]:
                    val = table[model][t][axis]
                    if val is not None:
                        matrix[mi, ci] = val
                ci += 1

    fig, ax = plt.subplots(figsize=(16, 6))
    cmap = plt.cm.RdYlGn.copy()
    cmap.set_bad(color='#f0f0f0')
    im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=1, aspect='auto')

    ax.set_xticks(range(len(col_headers)))
    ax.set_xticklabels(col_headers, fontsize=8, ha='center')
    ax.set_yticks(range(len(models)))
    ax.set_yticklabels(models, fontsize=11)

    # Annotate cells
    for i in range(len(models)):
        for j in range(len(col_headers)):
            val = matrix[i, j]
            if np.isnan(val):
                ax.text(j, i, "–", ha="center", va="center", fontsize=9, color="gray")
            else:
                color = "white" if val < 0.4 else "black"
                ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                        fontsize=9, fontweight="bold", color=color)

    # Vertical separators between tiers
    for sep in [3, 6, 9]:
        ax.axvline(x=sep - 0.5, color="black", linewidth=1.5)

    ax.set_title("Per-Axis Scores by Model × Tier (0 = fail, 1 = pass)", fontsize=14, pad=12)
    plt.colorbar(im, ax=ax, label="Score", shrink=0.7, pad=0.02)
    plt.tight_layout()
    fname = FIGS_DIR / "full_tier_axis_heatmap.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"Saved: {fname}")
    plt.close()


def fig_total_score_heatmap(table):
    """4-column heatmap: models × total score per tier."""
    tiers = [1, 2, 3, 4]
    models = [m for m in MODEL_ORDER if m in table]

    matrix = np.full((len(models), len(tiers)), np.nan)
    for mi, model in enumerate(models):
        for ti, t in enumerate(tiers):
            if t in table.get(model, {}):
                vals = [table[model][t].get(a) for a in AXES]
                if all(v is not None for v in vals):
                    matrix[mi, ti] = sum(vals)

    fig, ax = plt.subplots(figsize=(8, 6))
    cmap = plt.cm.RdYlGn.copy()
    cmap.set_bad(color='#f0f0f0')
    im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=3, aspect='auto')

    ax.set_xticks(range(len(tiers)))
    ax.set_xticklabels([TIER_LABELS[t] for t in tiers], fontsize=10)
    ax.set_yticks(range(len(models)))
    ax.set_yticklabels(models, fontsize=11)

    for i in range(len(models)):
        for j in range(len(tiers)):
            val = matrix[i, j]
            if np.isnan(val):
                ax.text(j, i, "–", ha="center", va="center", fontsize=10, color="gray")
            else:
                color = "white" if val < 1.5 else "black"
                ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                        fontsize=12, fontweight="bold", color=color)

    ax.set_title("Mean Total Score (RC+LF+GF, 0–3) by Model × Tier", fontsize=14, pad=12)
    plt.colorbar(im, ax=ax, label="Score (0–3)", shrink=0.8)
    plt.tight_layout()
    fname = FIGS_DIR / "full_tier_total_heatmap.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"Saved: {fname}")
    plt.close()


def print_table_text(table):
    """Print a clean text table for pasting."""
    tiers = [1, 2, 3, 4]
    models = [m for m in MODEL_ORDER if m in table]

    header = f"{'Model':15s}"
    for t in tiers:
        header += f" | {TIER_LABELS[t]:>14s} RC  LF  GF"
    print(header)
    print("=" * len(header))

    for model in models:
        row = f"{model:15s}"
        for t in tiers:
            if t in table.get(model, {}):
                rc = table[model][t].get("root_cause")
                lf = table[model][t].get("local_fix")
                gf = table[model][t].get("global_fix")
                rc_s = f"{rc:.2f}" if rc is not None else "  – "
                lf_s = f"{lf:.2f}" if lf is not None else "  – "
                gf_s = f"{gf:.2f}" if gf is not None else "  – "
                row += f" | {' ':>14s}{rc_s} {lf_s} {gf_s}"
            else:
                row += f" | {' ':>14s}  –    –    – "
        print(row)


def main():
    print("Loading data...")

    all_data = []

    # T1/T2 from synth-8model-sweep
    sweep_dir = Path("bench/results/synth-8model-sweep")
    for tier in [1, 2]:
        d = load_tier_scores(sweep_dir, tier_filter=tier)
        all_data.extend(d)
        print(f"  T{tier}: {len(d)} scored runs")

    # T3 unfenced
    d = load_tier_scores(Path("bench/results/synth-t3-unfenced"), tier_filter=3)
    all_data.extend(d)
    print(f"  T3 (unfenced): {len(d)} scored runs")

    # T4
    d = load_tier_scores(Path("bench/results/synth-t4-sweep"), tier_filter=4)
    all_data.extend(d)
    print(f"  T4: {len(d)} scored runs")

    table = build_table(all_data)

    print("\n--- TEXT TABLE ---\n")
    print_table_text(table)

    print("\nGenerating figures...")
    fig_full_heatmap(table)
    fig_total_score_heatmap(table)
    print("Done!")


if __name__ == "__main__":
    main()
