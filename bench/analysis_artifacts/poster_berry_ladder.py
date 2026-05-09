"""Berry tier-ladder figure: how harness choice changes outcomes on real-world bugs.

Single panel: T1 (bash) → T2 (bash+gdb) → T3 (gdb-only) → T4 (Claude Code).
Three grouped bars per tier (RC, LF, GF), means over all (model × bug) cells.
Whiskers show min/max across models; annotation labels best model per tier.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "bench/results/berry_consolidated"
OUT = ROOT / "bench/analysis_artifacts/figs/poster/08_berry_tier_ladder.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

MODEL_LABEL = {
    "openrouter_openai_gpt-5.5": "GPT-5.5",
    "openrouter_openai_gpt-4o": "GPT-4o",
    "openrouter_google_gemini-2.5-flash": "Gemini-2.5-FL",
    "openrouter_meta-llama_llama-3.1-8b-instruct": "Llama-8B",
    "openrouter_nvidia_nemotron-3-nano-30b-a3b": "Nemotron-30B",
    "openrouter_qwen_qwen3-30b-a3b-instruct-2507": "Qwen-30B",
    "openrouter_anthropic_claude-haiku-4.5": "Haiku-4.5",
    "openrouter_anthropic_claude-sonnet-4.6": "Sonnet-4.6",
    "openrouter_anthropic_claude-opus-4.7": "Opus-4.7",
}

TIER_TOOLS = {
    1: "bash only",
    2: "bash + gdb",
    3: "gdb only",
    4: "Claude Code\n(agentic shell + FS)",
}

mpl.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
})


def load():
    rows = []
    for d in sorted(DATA.iterdir()):
        if not d.is_dir():
            continue
        parts = d.name.split("__")
        if len(parts) < 3 or not parts[1].startswith("tier"):
            continue
        sp = d / "score.json"
        if not sp.exists():
            continue
        s = json.loads(sp.read_text()).get("scores", {})
        rows.append({
            "bug": parts[0],
            "tier": int(parts[1][4:]),
            "model": parts[2],
            "rc": int(s.get("root_cause") or 0),
            "lf": int(s.get("local_fix") or 0),
            "gf": int(s.get("global_fix") or 0),
        })
    return rows


def main():
    rows = load()
    tiers = [1, 2, 3, 4]
    axes = ["rc", "lf", "gf"]
    axis_label = {"rc": "Root cause", "lf": "Local fix", "gf": "Global fix"}
    axis_color = {"rc": "#264653", "lf": "#2a9d8f", "gf": "#e76f51"}

    # per-tier × per-axis: mean over cells, plus per-model means for whiskers + best
    means = {a: [] for a in axes}
    per_model = {t: defaultdict(lambda: {"rc": [], "lf": [], "gf": []}) for t in tiers}
    n_per_tier = {}
    for r in rows:
        for a in axes:
            per_model[r["tier"]][r["model"]][a].append(r[a])
    for t in tiers:
        flat = {a: [v for m_scores in per_model[t].values() for v in m_scores[a]] for a in axes}
        n_per_tier[t] = len(flat["rc"])
        for a in axes:
            means[a].append(np.mean(flat[a]) if flat[a] else 0.0)

    # best model per tier (by RC mean)
    best = {}
    for t in tiers:
        best_m, best_rc = None, -1.0
        for m, sc in per_model[t].items():
            rc = np.mean(sc["rc"]) if sc["rc"] else 0
            if rc > best_rc:
                best_m, best_rc = m, rc
        best[t] = (MODEL_LABEL.get(best_m, best_m), best_rc)

    # whiskers: min/max model mean RC per tier (use rc as the reference axis)
    whiskers = {a: ([], []) for a in axes}
    for t in tiers:
        for a in axes:
            ms = [np.mean(sc[a]) for sc in per_model[t].values() if sc[a]]
            whiskers[a][0].append(min(ms) if ms else 0)
            whiskers[a][1].append(max(ms) if ms else 0)

    # ===== plot =====
    fig, ax = plt.subplots(figsize=(11, 5.8))
    x = np.arange(len(tiers))
    width = 0.25

    for k, a in enumerate(axes):
        ys = means[a]
        offsets = (k - 1) * width
        bars = ax.bar(x + offsets, ys, width, color=axis_color[a],
                      label=axis_label[a], edgecolor="white", linewidth=0.6)
        # whiskers (min/max across models)
        lo = whiskers[a][0]
        hi = whiskers[a][1]
        for xi, y, l, h in zip(x, ys, lo, hi):
            ax.vlines(xi + offsets, l, h, color="#333", linewidth=1.2, alpha=0.7)
            ax.hlines(l, xi + offsets - 0.05, xi + offsets + 0.05, color="#333", linewidth=1.2, alpha=0.7)
            ax.hlines(h, xi + offsets - 0.05, xi + offsets + 0.05, color="#333", linewidth=1.2, alpha=0.7)
        # numeric labels on top of bars
        for xi, y in zip(x, ys):
            ax.text(xi + offsets, y + 0.025, f"{y:.2f}", ha="center", va="bottom",
                    fontsize=8.5, color=axis_color[a], fontweight="bold")

    # x-axis
    ax.set_xticks(x)
    xlabels = [f"T{t}\n{TIER_TOOLS[t]}" for t in tiers]
    ax.set_xticklabels(xlabels, fontsize=10)
    ax.set_ylabel("Mean pass rate over (model × bug) cells", fontsize=11)
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", alpha=0.25, linestyle="--")
    ax.legend(loc="upper left", frameon=False, fontsize=10)

    # annotation strip above bars: best model + n
    for xi, t in zip(x, tiers):
        bm, brc = best[t]
        ax.annotate(f"best: {bm}\nrc={brc:.2f}  (n={n_per_tier[t]})",
                    xy=(xi, 0.92), xycoords=("data", "axes fraction"),
                    ha="center", va="top", fontsize=8.5, color="#333",
                    bbox=dict(facecolor="#f4f1de", edgecolor="#cfc7a8",
                              boxstyle="round,pad=0.3", linewidth=0.6))

    # tier transition arrows below x labels
    ax.annotate("", xy=(2.5, -0.20), xytext=(0.5, -0.20),
                xycoords=("data", "axes fraction"),
                arrowprops=dict(arrowstyle="->", color="#cc4422", linewidth=1.5))
    ax.text(1.5, -0.27, "more debugger structure → ↓ pass rate",
            ha="center", fontsize=9, color="#cc4422",
            transform=ax.get_xaxis_transform())
    ax.annotate("", xy=(3.5, -0.20), xytext=(2.6, -0.20),
                xycoords=("data", "axes fraction"),
                arrowprops=dict(arrowstyle="->", color="#117733", linewidth=1.5))
    ax.text(3.05, -0.27, "agentic FS access → ↑↑",
            ha="center", fontsize=9, color="#117733",
            transform=ax.get_xaxis_transform())

    fig.suptitle("Berry (real-world multi-file bugs): more gdb hurts, agentic file access helps",
                 fontsize=13, fontweight="bold", y=0.99)
    fig.tight_layout(rect=[0, 0.05, 1, 0.96])
    fig.savefig(OUT, dpi=200, bbox_inches="tight")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
