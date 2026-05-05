#!/usr/bin/env python3
"""Synthetic vs External-Native comparison figure.

Builds a single multi-panel figure that shows the same models scored on
two corpora:
  * Synthetic — single-file, hand-written cases
    (`full-synthetic-v1-stripped` rows from
    bench/analysis_artifacts/judge_scores.csv).
  * External-Native — multifile real-world bugs from Crashbench + Juliet,
    Tier-3 only (the ChatDBG path), from
    bench/results/external-native-ablation-20260504-merged-t3rerun.

Caveat (drawn on the figure): the two corpora were graded by different
judges (synthetic = older `judge_scores.csv` pass with mixed judges;
native = `openrouter/openai/gpt-5`) and synthetic uses an older fenced
T3 config. The figure contrasts case difficulty, not harness parity.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS))
from generate_all import load_scored_runs, MODEL_MAP, short_model  # type: ignore

ROOT = THIS.parent
EXT_DIR = ROOT / "results" / "external-native-ablation-20260504-merged-t3rerun"
JUDGE_CSV = ROOT / "analysis_artifacts" / "judge_scores.csv"
OUT = THIS / "synth_vs_external_native.png"

# Match generate_all.py's name conventions
SHARED_MODELS = ["GPT-5.5", "Gemini-FL", "Qwen-30B", "Nemotron-30B"]

# judge_scores.csv calls gemini "Gemini-3.1-Flash-Lite" — alias to "Gemini-FL"
SYNTH_MODEL_ALIAS = {"Gemini-3.1-Flash-Lite": "Gemini-FL"}


def load_synth() -> pd.DataFrame:
    df = pd.read_csv(JUDGE_CSV)
    df = df[df.suite == "full-synthetic-v1-stripped"].copy()
    df["model"] = df["model"].replace(SYNTH_MODEL_ALIAS)
    df = df[df["model"].isin(SHARED_MODELS)]
    return df


def load_native_t3() -> pd.DataFrame:
    runs = [r for r in load_scored_runs(EXT_DIR) if r["tier"] == 3]
    df = pd.DataFrame(runs)
    if df.empty:
        return df
    df = df[df["model"].isin(SHARED_MODELS)].copy()
    df = df.rename(columns={"rc": "root_cause", "lf": "local_fix", "gf": "global_fix"})
    return df


def mean_axis(df: pd.DataFrame, model: str, axis: str) -> float:
    sub = df[df["model"] == model]
    return float(sub[axis].mean()) if len(sub) else 0.0


def main() -> int:
    syn = load_synth()
    nat = load_native_t3()
    if syn.empty or nat.empty:
        print(f"need both synth + native data; got synth={len(syn)} nat={len(nat)}")
        return 1

    # Per-model panel: total score (0–3) bar pair
    # Per-axis panel: 3 sub-bars (RC/LF/GF) × 2 corpora

    fig = plt.figure(figsize=(14, 8))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1], width_ratios=[1.2, 1])

    # ---- (1) Headline total-score: synth vs native, per shared model ----
    ax = fig.add_subplot(gs[0, :])
    x = np.arange(len(SHARED_MODELS))
    w = 0.36
    syn_totals = [mean_axis(syn, m, "total") for m in SHARED_MODELS]
    nat_totals = [mean_axis(nat, m, "total") for m in SHARED_MODELS]
    b1 = ax.bar(x - w/2, syn_totals, w, label="Synthetic (single-file, hand-written)",
                color="#1976d2", alpha=0.85)
    b2 = ax.bar(x + w/2, nat_totals, w, label="External-Native (multifile, real bugs)",
                color="#d32f2f", alpha=0.85, hatch="//", edgecolor="black", linewidth=0.5)
    for bars, vals in [(b1, syn_totals), (b2, nat_totals)]:
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, v + 0.06, f"{v:.2f}",
                    ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels(SHARED_MODELS, fontsize=11)
    ax.set_ylabel("Mean Total Score (0–3)")
    ax.set_ylim(0, 3.4)
    ax.axhline(3, ls="--", lw=0.5, color="gray", alpha=0.6)
    ax.set_title("Synthetic vs External-Native (Tier 3) — Total Score by Model",
                 fontsize=13, fontweight="bold")
    ax.legend(loc="upper right", fontsize=10)

    syn_n = len(syn); nat_n = len(nat)
    ax.text(0.01, 0.97,
            f"Synthetic: 8 single-file cases × {len(SHARED_MODELS)} models, n={syn_n} runs.\n"
            f"External-Native (T3): 11 multifile cases × {len(SHARED_MODELS)} models, n={nat_n} runs.",
            transform=ax.transAxes, va="top", fontsize=8.5,
            bbox=dict(facecolor="white", edgecolor="lightgray", alpha=0.9))

    # ---- (2) Per-axis breakdown: RC / LF / GF ----
    ax = fig.add_subplot(gs[1, 0])
    axes_keys = [("root_cause", "Root Cause"),
                 ("local_fix",  "Local Fix"),
                 ("global_fix", "Global Fix")]
    axis_x = np.arange(len(axes_keys))
    bw = 0.18
    cmap = plt.cm.Blues(np.linspace(0.55, 0.95, len(SHARED_MODELS)))
    cmap2 = plt.cm.Reds(np.linspace(0.55, 0.95, len(SHARED_MODELS)))
    for i, m in enumerate(SHARED_MODELS):
        offs = (i - (len(SHARED_MODELS) - 1)/2) * bw
        syn_vals = [mean_axis(syn, m, k) for k, _ in axes_keys]
        nat_vals = [mean_axis(nat, m, k) for k, _ in axes_keys]
        ax.bar(axis_x + offs - bw*0.05, syn_vals, bw*0.45,
               color=cmap[i], label=f"{m} (syn)" if i == 0 else None)
        ax.bar(axis_x + offs + bw*0.5, nat_vals, bw*0.45,
               color=cmap2[i], hatch="//", edgecolor="black", linewidth=0.3,
               label=f"{m} (nat)" if i == 0 else None)
    ax.set_xticks(axis_x)
    ax.set_xticklabels([lbl for _, lbl in axes_keys])
    ax.set_ylabel("Mean Score (0–1)")
    ax.set_ylim(0, 1.15)
    ax.set_title("Per-Axis Breakdown (each pair: syn / nat per model, left→right by model order)",
                 fontsize=10)

    # Legend explaining the encoding
    handles = [
        plt.Rectangle((0,0),1,1, facecolor="#1976d2", label="Synthetic (solid)"),
        plt.Rectangle((0,0),1,1, facecolor="#d32f2f", hatch="//", edgecolor="black", label="Native (hatched)"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=8.5)

    # ---- (3) Drop-off scatter: per-model synth-vs-native ----
    ax = fig.add_subplot(gs[1, 1])
    for m, color in zip(SHARED_MODELS,
                        plt.cm.tab10(np.linspace(0, 1, len(SHARED_MODELS)))):
        sx = mean_axis(syn, m, "total")
        nx = mean_axis(nat, m, "total")
        ax.scatter(sx, nx, s=140, color=color, edgecolor="black", linewidth=0.6,
                   zorder=3, label=m)
        ax.annotate(m, (sx, nx), xytext=(6, 6), textcoords="offset points",
                    fontsize=9)
    ax.plot([0, 3], [0, 3], "--", color="gray", lw=0.7, alpha=0.7,
            label="parity (synth = native)")
    ax.set_xlim(-0.1, 3.1); ax.set_ylim(-0.1, 3.1)
    ax.set_xlabel("Synthetic — mean total"); ax.set_ylabel("Native (T3) — mean total")
    ax.set_title("Generalization gap (below diagonal = harder on real bugs)",
                 fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")

    fig.suptitle("Same models, two corpora: hand-written single-file synthetics vs multifile real-world bugs",
                 fontsize=14, fontweight="bold")
    fig.text(0.5, 0.005,
             "Caveats: synthetic suite uses older fenced T3 config and a different judge "
             "(see bench/analysis_artifacts/judge_scores.csv); native uses unfenced+CMW T3 + GPT-5 judge. "
             "Read the figure as case-difficulty contrast, not harness parity.",
             ha="center", fontsize=8.5, color="dimgray", style="italic", wrap=True)
    plt.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(OUT, dpi=160)
    plt.close(fig)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
