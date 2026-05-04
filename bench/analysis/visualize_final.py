#!/usr/bin/env python3
"""
Final paper-ready visualizations for T1-T3 ablations.

Outputs (bench/analysis/figs/):
  1. full_heatmap_t1t2t3.png     — 9-column heatmap: RC/LF/GF × T1/T2/T3
  2. mean_scores_t1t2t3.png      — grouped bar: mean total score per model
  3. mean_tokens_t1t2t3.png      — grouped bar: mean tokens per model
  4. tool_use_t1t2t3.png         — stacked bar: bash vs gdb/debug tool calls
  5. scores_table.md             — markdown table with all T1-T4 scores
"""
import json
import glob
from pathlib import Path
from collections import defaultdict, Counter

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
    "sonnet": "Sonnet-4.5",
}

MODEL_ORDER = ["GPT-5.5", "GPT-4o", "Grok-4", "Sonnet-4.5", "Gemini-2.5",
               "Qwen-30B", "Nemotron-30B", "Llama-8B"]

TIER_LABELS = {1: "T1: bash", 2: "T2: bash+gdb", 3: "T3: ChatDBG", 4: "T4: Claude Code"}
TIER_COLORS = {1: "#1976d2", 2: "#f57c00", 3: "#388e3c"}
AXES = ["root_cause", "local_fix", "global_fix"]
AXIS_SHORT = {"root_cause": "RC", "local_fix": "LF", "global_fix": "GF"}


def _model_name(run_dir_name, result=None):
    for k, v in MODEL_MAP.items():
        if k in run_dir_name:
            return v
    if result:
        m = result.get("model", "").replace("/", "_")
        for k, v in MODEL_MAP.items():
            if k in m:
                return v
        short = result.get("model", "").split("/")[-1]
        if short in MODEL_MAP:
            return MODEL_MAP[short]
    return "?"


def load_all():
    """Load scored runs with tool/token metadata."""
    data = []
    sources = [
        (Path("bench/results/synth-8model-sweep"), [1, 2]),
        (Path("bench/results/synth-t3-unfenced"), [3]),
        (Path("bench/results/synth-t4-sweep"), [4]),
    ]
    for results_dir, tiers in sources:
        for f in sorted(glob.glob(str(results_dir / "*/score.json"))):
            rd = Path(f).parent
            result = json.load(open(rd / "result.json"))
            if result.get("tier") not in tiers or result.get("status") != "ok":
                continue
            score = json.load(open(f))
            sc = score.get("scores", {})
            model = _model_name(rd.name, result)

            tokens, tool_calls, bash_calls, gdb_calls = 0, 0, 0, 0
            cj = rd / "collect.json"
            if cj.exists():
                c = json.load(open(cj))
                q = (c.get("queries") or [{}])[0]
                stats = q.get("stats", {})
                tokens = stats.get("tokens", 0) or 0
                tool_calls = q.get("num_tool_calls", 0)
                for tc in q.get("tool_calls", []):
                    tn = tc.get("tool_name", "")
                    if tn == "bash" or tn in ("ls", "cat", "grep", "find", "echo",
                                               "head", "tail", "nl", "printf",
                                               "python3", "prog", "file", "wc"):
                        bash_calls += 1
                    elif tn == "gdb" or tn in ("debug", "frame", "bt", "p", "code",
                                                "definition", "b", "run", "breakpoint",
                                                "continue", "next", "step", "expr",
                                                "memory", "register", "target",
                                                "disassemble", "image", "thread",
                                                "process", "x/s", "x/8cb", "x/20bx",
                                                "finish", "info", "c", "r", "br",
                                                "v", "attach", "kill", "settings",
                                                "platform", "x"):
                        gdb_calls += 1
                    else:
                        # Fallback: check verb field (T2 has it)
                        verb = tc.get("verb", "")
                        if verb in ("bash",):
                            bash_calls += 1
                        else:
                            gdb_calls += 1

            data.append({
                "case": result.get("case_id", "?"),
                "model": model,
                "tier": result.get("tier", 0),
                "rc": sc.get("root_cause", 0),
                "lf": sc.get("local_fix", 0),
                "gf": sc.get("global_fix", 0),
                "total": sum(sc.values()),
                "tokens": tokens,
                "tool_calls": tool_calls,
                "bash_calls": bash_calls,
                "gdb_calls": gdb_calls,
            })
    return data


# ── Fig 1: 9-column heatmap (T1-T3 only) ────────────────────────────

def fig_heatmap(data):
    tiers = [1, 2, 3]
    td = [d for d in data if d["tier"] in tiers]
    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in td)]

    # Build means
    means = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for d in td:
        for axis in AXES:
            key = "rc" if axis == "root_cause" else ("lf" if axis == "local_fix" else "gf")
            means[d["model"]][d["tier"]][axis].append(d[key])

    col_headers = []
    for t in tiers:
        for axis in AXES:
            col_headers.append(f"{TIER_LABELS[t]}\n{AXIS_SHORT[axis]}")

    matrix = np.full((len(models), len(col_headers)), np.nan)
    for mi, model in enumerate(models):
        ci = 0
        for t in tiers:
            for axis in AXES:
                vals = means[model][t][axis]
                if vals:
                    matrix[mi, ci] = sum(vals) / len(vals)
                ci += 1

    fig, ax = plt.subplots(figsize=(14, 5.5))
    cmap = plt.cm.RdYlGn.copy()
    cmap.set_bad(color='#f0f0f0')
    im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=1, aspect='auto')

    ax.set_xticks(range(len(col_headers)))
    ax.set_xticklabels(col_headers, fontsize=8, ha='center')
    ax.set_yticks(range(len(models)))
    ax.set_yticklabels(models, fontsize=11)

    for i in range(len(models)):
        for j in range(len(col_headers)):
            val = matrix[i, j]
            if np.isnan(val):
                ax.text(j, i, "–", ha="center", va="center", fontsize=9, color="gray")
            else:
                color = "white" if val < 0.4 else "black"
                ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                        fontsize=9, fontweight="bold", color=color)

    for sep in [3, 6]:
        ax.axvline(x=sep - 0.5, color="black", linewidth=1.5)

    ax.set_title("Per-Axis Mean Scores by Model x Tier", fontsize=14, pad=12)
    plt.colorbar(im, ax=ax, label="Score (0-1)", shrink=0.7, pad=0.02)
    plt.tight_layout()
    fname = FIGS_DIR / "full_heatmap_t1t2t3.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"Saved: {fname}")
    plt.close()


# ── Fig 2: mean total score bar chart ────────────────────────────────

def fig_mean_scores(data):
    tiers = [1, 2, 3]
    td = [d for d in data if d["tier"] in tiers]
    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in td)]

    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(len(models))
    width = 0.25

    for ti, tier in enumerate(tiers):
        avgs = []
        for m in models:
            vals = [d["total"] for d in td if d["model"] == m and d["tier"] == tier]
            avgs.append(sum(vals) / len(vals) if vals else 0)
        bars = ax.bar(x + ti * width, avgs, width,
                      label=TIER_LABELS[tier], color=TIER_COLORS[tier], alpha=0.85)
        for bar, val in zip(bars, avgs):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.04,
                        f"{val:.2f}", ha="center", va="bottom", fontsize=7)

    ax.set_ylabel("Mean Total Score (0-3)")
    ax.set_title("Mean Debugging Score by Model x Tier")
    ax.set_xticks(x + width)
    ax.set_xticklabels(models, fontsize=9)
    ax.legend(fontsize=9, loc="upper right")
    ax.set_ylim(0, 3.5)
    ax.axhline(y=3, color="gray", ls="--", lw=0.5, alpha=0.5)
    plt.tight_layout()
    fname = FIGS_DIR / "mean_scores_t1t2t3.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"Saved: {fname}")
    plt.close()


# ── Fig 3: mean tokens bar chart ─────────────────────────────────────

def fig_mean_tokens(data):
    tiers = [1, 2, 3]
    td = [d for d in data if d["tier"] in tiers]
    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in td)]

    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(len(models))
    width = 0.25

    for ti, tier in enumerate(tiers):
        avgs = []
        for m in models:
            vals = [d["tokens"] for d in td if d["model"] == m and d["tier"] == tier and d["tokens"] > 0]
            avgs.append(sum(vals) / len(vals) if vals else 0)
        bars = ax.bar(x + ti * width, avgs, width,
                      label=TIER_LABELS[tier], color=TIER_COLORS[tier], alpha=0.85)

    ax.set_ylabel("Mean Total Tokens")
    ax.set_title("Mean Token Usage by Model x Tier")
    ax.set_xticks(x + width)
    ax.set_xticklabels(models, fontsize=9)
    ax.legend(fontsize=9, loc="upper right")
    # Format y-axis with K suffix
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v/1000:.0f}K"))
    plt.tight_layout()
    fname = FIGS_DIR / "mean_tokens_t1t2t3.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"Saved: {fname}")
    plt.close()


# ── Fig 4: tool use — bash vs gdb/debug ──────────────────────────────

def fig_tool_use(data):
    tiers = [1, 2, 3]
    td = [d for d in data if d["tier"] in tiers]
    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in td)]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)

    for ax, tier in zip(axes, tiers):
        tier_data = [d for d in td if d["tier"] == tier]
        bash_avgs = []
        gdb_avgs = []
        for m in models:
            mdata = [d for d in tier_data if d["model"] == m]
            if mdata:
                bash_avgs.append(sum(d["bash_calls"] for d in mdata) / len(mdata))
                gdb_avgs.append(sum(d["gdb_calls"] for d in mdata) / len(mdata))
            else:
                bash_avgs.append(0)
                gdb_avgs.append(0)

        x = np.arange(len(models))
        width = 0.6
        ax.bar(x, bash_avgs, width, label="bash/shell", color="#1976d2", alpha=0.8)
        ax.bar(x, gdb_avgs, width, bottom=bash_avgs, label="gdb/debug", color="#d32f2f", alpha=0.8)

        ax.set_title(TIER_LABELS[tier], fontsize=12)
        ax.set_xticks(x)
        ax.set_xticklabels(models, fontsize=7, rotation=35, ha="right")
        if tier == 1:
            ax.set_ylabel("Avg Tool Calls per Case")
        if tier == 3:
            ax.legend(fontsize=8, loc="upper right")

    fig.suptitle("Tool Usage: Bash vs GDB/Debug Calls by Model x Tier", fontsize=14, y=1.02)
    plt.tight_layout()
    fname = FIGS_DIR / "tool_use_t1t2t3.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"Saved: {fname}")
    plt.close()


# ── Markdown table (T1-T4) ───────────────────────────────────────────

def write_markdown_table(data):
    tiers = [1, 2, 3, 4]
    models = [m for m in MODEL_ORDER if m in set(d["model"] for d in data)]

    # Build means
    means = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    token_means = defaultdict(lambda: defaultdict(list))
    for d in data:
        for axis in AXES:
            key = "rc" if axis == "root_cause" else ("lf" if axis == "local_fix" else "gf")
            means[d["model"]][d["tier"]][axis].append(d[key])
        if d["tokens"] > 0:
            token_means[d["model"]][d["tier"]].append(d["tokens"])

    lines = ["# T1-T4 Ablation Scores\n"]
    lines.append("## Per-Axis Scores (mean, 0-1)\n")

    # Header
    header = "| Model |"
    sep = "|-------|"
    for t in tiers:
        for axis in AXES:
            header += f" {TIER_LABELS[t]} {AXIS_SHORT[axis]} |"
            sep += ":---:|"
    lines.append(header)
    lines.append(sep)

    for model in models:
        row = f"| {model} |"
        for t in tiers:
            for axis in AXES:
                vals = means[model][t][axis]
                if vals:
                    row += f" {sum(vals)/len(vals):.2f} |"
                else:
                    row += " - |"
        lines.append(row)

    lines.append("\n## Total Scores (mean, 0-3)\n")
    header2 = "| Model |"
    sep2 = "|-------|"
    for t in tiers:
        header2 += f" {TIER_LABELS[t]} |"
        sep2 += ":---:|"
    header2 += " Best Tier |"
    sep2 += ":---:|"
    lines.append(header2)
    lines.append(sep2)

    for model in models:
        row = f"| {model} |"
        best_tier = None
        best_val = -1
        for t in tiers:
            axis_vals = []
            for axis in AXES:
                vals = means[model][t][axis]
                if vals:
                    axis_vals.append(sum(vals) / len(vals))
            if axis_vals:
                total = sum(axis_vals)
                row += f" {total:.2f} |"
                if total > best_val:
                    best_val = total
                    best_tier = t
            else:
                row += " - |"
        row += f" {TIER_LABELS.get(best_tier, '-')} |" if best_tier else " - |"
        lines.append(row)

    lines.append("\n## Mean Tokens\n")
    header3 = "| Model |"
    sep3 = "|-------|"
    for t in tiers:
        header3 += f" {TIER_LABELS[t]} |"
        sep3 += ":---:|"
    lines.append(header3)
    lines.append(sep3)

    for model in models:
        row = f"| {model} |"
        for t in tiers:
            vals = token_means[model][t]
            if vals:
                avg = sum(vals) / len(vals)
                row += f" {avg:,.0f} |"
            else:
                row += " - |"
        lines.append(row)

    md = "\n".join(lines)
    fname = FIGS_DIR / "scores_table.md"
    fname.write_text(md)
    print(f"Saved: {fname}")
    return md


def main():
    print("Loading data...")
    data = load_all()

    for tier in [1, 2, 3, 4]:
        td = [d for d in data if d["tier"] == tier]
        print(f"  T{tier}: {len(td)} scored runs")

    print("\nGenerating figures (T1-T3)...")
    fig_heatmap(data)
    fig_mean_scores(data)
    fig_mean_tokens(data)
    fig_tool_use(data)

    print("\nGenerating markdown table (T1-T4)...")
    md = write_markdown_table(data)
    print("\n" + md)


if __name__ == "__main__":
    main()
