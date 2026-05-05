#!/usr/bin/env python3
"""
Unified figure generator for ChatDBG-Pro paper.

Generates all visualizations for both synthetic and BugBench corpora,
plus tool-command analysis. Outputs to bench/figures/.

Usage:
    python bench/figures/generate_all.py                  # all figures
    python bench/figures/generate_all.py --only synth     # synthetic only
    python bench/figures/generate_all.py --only bugbench  # bugbench only
    python bench/figures/generate_all.py --only tools     # tool-cmd only
"""
from __future__ import annotations
import argparse, json, glob, os, sys
from pathlib import Path
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

try:
    from scipy.stats import spearmanr
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# ── Paths ─────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent  # bench/
SYNTH_DIR    = ROOT / "results" / "synth-8model-sweep"
T3UNF_DIR    = ROOT / "results" / "synth-t3-unfenced"
CMW_DIR      = ROOT / "results" / "synth-t3-unfenced-cmw"
T4_DIR       = ROOT / "results" / "synth-t4-sweep"
BB_DIRS      = {t: ROOT / "results" / f"bugbench-t{t}" for t in [1, 2, 3]}
FIGS         = Path(__file__).resolve().parent
FIGS.mkdir(exist_ok=True)

# ── Model helpers ─────────────────────────────────────────────────────

MODEL_MAP = {
    "gpt-5.5": "GPT-5.5", "gpt-4o": "GPT-4o", "grok-4": "Grok-4",
    "claude-sonnet-4-5": "Sonnet-4.5", "claude-sonnet-4-5-20250514": "Sonnet-4.5",
    "gemini-2.5-flash": "Gemini-FL", "llama-3.1-8b-instruct": "Llama-8B",
    "nemotron-3-nano-30b-a3b": "Nemotron-30B",
    "qwen3-30b-a3b-instruct-2507": "Qwen-30B", "qwen3-30b-a3b-instruct": "Qwen-30B",
}
MODEL_ORDER = ["GPT-5.5", "GPT-4o", "Grok-4", "Sonnet-4.5", "Gemini-FL",
               "Qwen-30B", "Nemotron-30B", "Llama-8B"]
BB_MODEL_ORDER = ["GPT-4o", "Qwen-30B", "Nemotron-30B", "Llama-8B"]
TIER_LABELS = {1: "T1: bash", 2: "T2: bash+gdb", 3: "T3: ChatDBG"}
TIER_COLORS = {1: "#1976d2", 2: "#f57c00", 3: "#388e3c"}

plt.rcParams.update({"figure.dpi": 150, "savefig.bbox": "tight",
                     "axes.spines.top": False, "axes.spines.right": False,
                     "font.size": 11, "font.family": "sans-serif"})


def short_model(m: str) -> str:
    for k, v in MODEL_MAP.items():
        if k in m:
            return v
    return m.split("/")[-1]


def _model_from_dirname(name: str) -> str:
    for k, v in MODEL_MAP.items():
        if k in name:
            return v
    return "?"


# ── Data loaders ──────────────────────────────────────────────────────

def load_scored_runs(results_dir: Path, *, use_collect=True) -> list[dict]:
    """Load scored runs from a results directory."""
    data = []
    for sd in sorted(results_dir.iterdir()):
        if not sd.is_dir():
            continue
        rp, sp = sd / "result.json", sd / "score.json"
        if not rp.exists():
            continue
        result = json.loads(rp.read_text())
        # Skip multi-model combo runs (harness artifact)
        model_raw = result.get("model", "?")
        if model_raw.count("openrouter") > 1:
            continue
        if result.get("status") not in ("ok",):
            continue

        model = short_model(model_raw)
        sc = {}
        if sp.exists():
            score = json.loads(sp.read_text())
            sc = score.get("scores", {})

        tc, tf = 0, {}
        cp = sd / "collect.json"
        if use_collect and cp.exists():
            try:
                c = json.loads(cp.read_text())
                q = (c.get("queries") or [{}])[0]
                tc = q.get("num_tool_calls", 0)
                tf = q.get("tool_frequency", {})
            except Exception:
                pass
        # Fallback: score.json mut field
        if tc == 0 and sp.exists():
            score = json.loads(sp.read_text())
            mut = score.get("mut", {})
            tc = mut.get("num_tool_calls", 0)
            tf = mut.get("tool_frequency", {})

        tier = result.get("tier", 0)
        if "tier1" in sd.name: tier = 1
        elif "tier2" in sd.name: tier = 2
        elif "tier3" in sd.name: tier = 3

        data.append({
            "case": result.get("case_id", "?"),
            "model": model,
            "tier": tier,
            "rc": sc.get("root_cause", 0),
            "lf": sc.get("local_fix", 0),
            "gf": sc.get("global_fix", 0),
            "total": sc.get("root_cause", 0) + sc.get("local_fix", 0) + sc.get("global_fix", 0),
            "tool_calls": tc,
            "tool_freq": tf,
            "elapsed_s": result.get("elapsed_s", 0),
            "status": result.get("status", "?"),
        })
    return data


def load_cmw_data() -> list[dict]:
    data = []
    for sd in sorted(CMW_DIR.iterdir()):
        if not sd.is_dir():
            continue
        rp, cp = sd / "result.json", sd / "collect.json"
        if not (rp.exists() and cp.exists()):
            continue
        result = json.loads(rp.read_text())
        if result.get("status") != "ok":
            continue
        model_raw = result.get("model", "?")
        if model_raw.count("openrouter") > 1:
            continue
        c = json.loads(cp.read_text())
        cmw = c.get("check_my_work")
        if not cmw:
            continue
        fs = cmw.get("final_scores", {})
        data.append({
            "case": result.get("case_id", "?"),
            "model": short_model(model_raw),
            "num_checks": cmw.get("num_checks", 0),
            "rc": fs.get("root_cause", 0),
            "lf": fs.get("local_fix", 0),
            "gf": fs.get("global_fix", 0),
            "total": sum(fs.values()),
            "stale": cmw.get("stale_exit", False),
        })
    return data


# ── Heatmap helper ────────────────────────────────────────────────────

def _heatmap(data, models, tier, title, fname, *, vmax=3):
    td = [d for d in data if d["tier"] == tier]
    if not td:
        return
    cases = sorted(set(d["case"] for d in td))
    ms = [m for m in models if m in set(d["model"] for d in td)]

    matrix = np.full((len(ms), len(cases)), np.nan)
    for d in td:
        if d["model"] in ms and d["case"] in cases:
            matrix[ms.index(d["model"]), cases.index(d["case"])] = d["total"]

    fig, ax = plt.subplots(figsize=(max(10, len(cases) * 0.65), max(3.5, len(ms) * 0.55)))
    cmap = plt.cm.RdYlGn.copy()
    cmap.set_bad(color="lightgray")
    im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(cases)))
    ax.set_xticklabels(cases, rotation=50, ha="right", fontsize=7)
    ax.set_yticks(range(len(ms)))
    ax.set_yticklabels(ms, fontsize=10)
    for i in range(len(ms)):
        for j in range(len(cases)):
            val = matrix[i, j]
            if np.isnan(val):
                ax.text(j, i, "–", ha="center", va="center", fontsize=8, color="gray")
            else:
                color = "white" if val <= 1 else "black"
                ax.text(j, i, str(int(val)), ha="center", va="center",
                        fontsize=10, fontweight="bold", color=color)
    ax.set_title(title, fontsize=13)
    plt.colorbar(im, ax=ax, label="Score", shrink=0.8)
    plt.tight_layout()
    plt.savefig(FIGS / fname, dpi=150)
    print(f"  Saved: {fname}")
    plt.close()


# ── Cross-tier bar chart helper ───────────────────────────────────────

def _cross_tier_bars(data, models, title, fname):
    tiers = sorted(set(d["tier"] for d in data))
    ms = [m for m in models if m in set(d["model"] for d in data)]
    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(len(ms))
    width = 0.8 / len(tiers)
    for ti, tier in enumerate(tiers):
        td = [d for d in data if d["tier"] == tier]
        avgs = [np.mean([d["total"] for d in td if d["model"] == m]) if
                [d for d in td if d["model"] == m] else 0 for m in ms]
        bars = ax.bar(x + ti * width, avgs, width,
                      label=TIER_LABELS.get(tier, f"T{tier}"),
                      color=TIER_COLORS.get(tier, "#999"), alpha=0.85)
        for bar, val in zip(bars, avgs):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.04,
                        f"{val:.2f}", ha="center", va="bottom", fontsize=7)
    ax.set_ylabel("Mean Total Score (0–3)")
    ax.set_title(title)
    ax.set_xticks(x + width * (len(tiers) - 1) / 2)
    ax.set_xticklabels(ms, fontsize=9)
    ax.legend(fontsize=9, loc="upper right")
    ax.set_ylim(0, 3.5)
    ax.axhline(y=3, color="gray", ls="--", lw=0.5, alpha=0.5)
    plt.tight_layout()
    plt.savefig(FIGS / fname, dpi=150)
    print(f"  Saved: {fname}")
    plt.close()


# ── Per-axis bar chart helper ─────────────────────────────────────────

def _per_axis_bars(data, models, title, fname):
    tiers = sorted(set(d["tier"] for d in data))
    fig, axes = plt.subplots(1, len(tiers), figsize=(5.5 * len(tiers), 5), sharey=True)
    if len(tiers) == 1:
        axes = [axes]
    for ax, tier in zip(axes, tiers):
        td = [d for d in data if d["tier"] == tier]
        ms = [m for m in models if m in set(d["model"] for d in td)]
        x = np.arange(len(ms))
        width = 0.25
        for ai, (axis, color, label) in enumerate([
            ("rc", "#1976d2", "Root Cause"),
            ("lf", "#388e3c", "Local Fix"),
            ("gf", "#f57c00", "Global Fix"),
        ]):
            avgs = [np.mean([d[axis] for d in td if d["model"] == m]) if
                    [d for d in td if d["model"] == m] else 0 for m in ms]
            ax.bar(x + ai * width, avgs, width, label=label, color=color, alpha=0.85)
        ax.set_title(TIER_LABELS.get(tier, f"T{tier}"), fontsize=12)
        ax.set_xticks(x + width)
        ax.set_xticklabels(ms, fontsize=7, rotation=30, ha="right")
        ax.set_ylim(0, 1.15)
        if tier == tiers[0]:
            ax.set_ylabel("Score (0–1)")
        if tier == tiers[-1]:
            ax.legend(fontsize=8, loc="upper right")
    fig.suptitle(title, fontsize=14, y=1.02)
    plt.tight_layout()
    plt.savefig(FIGS / fname, dpi=150)
    print(f"  Saved: {fname}")
    plt.close()


# ── Tool-command analysis helpers ─────────────────────────────────────

SYNONYMS = {
    "p": ["p", "print"], "frame": ["frame", "fr"],
    "breakpoint": ["breakpoint", "b", "br", "break"],
    "run": ["run", "r"], "continue": ["continue", "c"],
    "expr": ["expr", "expression"], "next": ["next", "n"],
    "step": ["step", "s", "si"],
}

def _merge_tool_freq(tf: dict) -> dict:
    merged = defaultdict(int)
    remap = {}
    for canonical, aliases in SYNONYMS.items():
        for a in aliases:
            remap[a] = canonical
    for cmd, cnt in tf.items():
        merged[remap.get(cmd, cmd)] += cnt
    return dict(merged)


def _tool_cmd_vs_score(data, title_suffix, fname):
    """Heatmap: mean command usage by total score, with Spearman r."""
    import pandas as pd
    rows = []
    for d in data:
        mtf = _merge_tool_freq(d["tool_freq"])
        rows.append({"total_score": d["total"], **mtf})
    df = pd.DataFrame(rows).fillna(0)

    cmd_cols = [c for c in df.columns if c != "total_score"]
    totals = {c: df[c].sum() for c in cmd_cols}
    top = sorted(totals, key=totals.get, reverse=True)[:10]
    for force in ["next", "step", "continue"]:
        if force not in top and force in cmd_cols:
            top.append(force)
    top = sorted(top, key=lambda c: totals.get(c, 0), reverse=True)
    if not top:
        print(f"  Skipped {fname} (no tool data)")
        return

    score_levels = sorted(df["total_score"].unique())
    heat = np.zeros((len(score_levels), len(top)))
    counts = []
    for i, s in enumerate(score_levels):
        sub = df[df["total_score"] == s]
        counts.append(len(sub))
        for j, cmd in enumerate(top):
            heat[i, j] = sub[cmd].mean() if cmd in sub.columns else 0

    corrs = {}
    if HAS_SCIPY:
        for cmd in top:
            if cmd in df.columns:
                rho, pval = spearmanr(df[cmd], df["total_score"])
                corrs[cmd] = (rho, pval)

    fig, ax = plt.subplots(figsize=(min(15, len(top) * 1.2 + 2), 6.5))
    im = ax.imshow(heat, cmap="YlOrRd", aspect="auto")

    xlabels = []
    for cmd in top:
        if cmd in corrs:
            rho, pval = corrs[cmd]
            star = "***" if pval < 0.001 else "**" if pval < 0.01 else "*" if pval < 0.05 else ""
            xlabels.append(f"{cmd}\n(r={rho:.2f}{star})")
        else:
            xlabels.append(cmd)
    ax.set_xticks(range(len(top)))
    ax.set_xticklabels(xlabels, fontsize=10, fontweight="bold")
    ax.set_yticks(range(len(score_levels)))
    ax.set_yticklabels([f"Score {int(s)}  (n={counts[i]})" for i, s in enumerate(score_levels)], fontsize=11)

    for i in range(len(score_levels)):
        for j in range(len(top)):
            v = heat[i, j]
            color = "white" if v > heat.max() * 0.55 else "black"
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=10, color=color, fontweight="bold")

    cb = plt.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label("Mean calls per run", fontsize=11)
    ax.set_title(f"LLDB command usage vs total score — {title_suffix}\n"
                 f"(merged synonyms, {len(df)} runs, * p<.05  ** p<.01  *** p<.001)",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("LLDB command (merged synonyms)", fontsize=12)
    plt.tight_layout()
    plt.savefig(FIGS / fname, dpi=150)
    print(f"  Saved: {fname}")
    plt.close()


def _tool_cmd_by_model(data, models, title_suffix, fname):
    """Stacked bar: top commands by model."""
    import pandas as pd
    rows = []
    for d in data:
        mtf = _merge_tool_freq(d["tool_freq"])
        rows.append({"model": d["model"], **mtf})
    df = pd.DataFrame(rows).fillna(0)

    cmd_cols = [c for c in df.columns if c != "model"]
    totals = {c: df[c].sum() for c in cmd_cols}
    top = sorted(totals, key=totals.get, reverse=True)[:10]
    ms = [m for m in models if m in df["model"].values]
    if not ms or not top:
        print(f"  Skipped {fname} (no data)")
        return

    colors = plt.cm.tab10(np.linspace(0, 1, len(top)))
    fig, ax = plt.subplots(figsize=(14, 5))
    x = np.arange(len(ms))
    bottom = np.zeros(len(ms))
    for ci, cmd in enumerate(top):
        vals = []
        for m in ms:
            sub = df[df["model"] == m]
            vals.append(sub[cmd].mean() if cmd in sub.columns else 0)
        ax.bar(x, vals, bottom=bottom, label=cmd, color=colors[ci], width=0.7)
        bottom += np.array(vals)
    # "other" bucket
    other_vals = []
    for m in ms:
        sub = df[df["model"] == m]
        other = sum(sub[c].mean() for c in cmd_cols if c not in top and c in sub.columns)
        other_vals.append(other)
    ax.bar(x, other_vals, bottom=bottom, label="other", color="lightgray", width=0.7)

    ax.set_xticks(x)
    ax.set_xticklabels(ms, fontsize=11)
    ax.set_ylabel("Mean tool calls per run")
    ax.set_title(f"Top 10 debugger commands by model — {title_suffix}", fontsize=13)
    ax.legend(ncol=4, fontsize=8, loc="upper right")
    plt.tight_layout()
    plt.savefig(FIGS / fname, dpi=150)
    print(f"  Saved: {fname}")
    plt.close()


def _tool_cmd_win_vs_fail(data, title_suffix, fname):
    """Side-by-side bar: mean commands for perfect vs failed runs."""
    import pandas as pd
    perfect = [d for d in data if d["total"] == 3]
    failed = [d for d in data if d["total"] == 0]
    if not perfect or not failed:
        print(f"  Skipped {fname} (need both perfect and failed runs)")
        return

    def _profile(runs):
        merged = defaultdict(float)
        for d in runs:
            mtf = _merge_tool_freq(d["tool_freq"])
            for cmd, cnt in mtf.items():
                merged[cmd] += cnt
        return {k: v / len(runs) for k, v in merged.items()}

    pp, fp = _profile(perfect), _profile(failed)
    all_cmds = set(list(pp.keys()) + list(fp.keys()))
    top_p = sorted(all_cmds, key=lambda c: pp.get(c, 0), reverse=True)[:12]
    top_f = sorted(all_cmds, key=lambda c: fp.get(c, 0), reverse=True)[:12]

    colors = ["#4285F4", "#34A853", "#FBBC05", "#EA4335"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 5))

    y = np.arange(len(top_p))
    vals = [pp.get(c, 0) for c in top_p]
    cs = [colors[i % len(colors)] for i in range(len(top_p))]
    ax1.barh(y, vals, color=cs, height=0.7)
    ax1.set_yticks(y); ax1.set_yticklabels(top_p, fontsize=10)
    ax1.set_xlabel("Mean calls per run"); ax1.invert_yaxis()
    ax1.set_title(f"Perfect (3/3) (n={len(perfect)})")

    y = np.arange(len(top_f))
    vals = [fp.get(c, 0) for c in top_f]
    cs = [colors[i % len(colors)] for i in range(len(top_f))]
    ax2.barh(y, vals, color=cs, height=0.7)
    ax2.set_yticks(y); ax2.set_yticklabels(top_f, fontsize=10)
    ax2.set_xlabel("Mean calls per run"); ax2.invert_yaxis()
    ax2.set_title(f"Failed (0/3) (n={len(failed)})")

    fig.suptitle(f"Command profiles: winning vs failing runs — {title_suffix}", fontsize=14)
    plt.tight_layout()
    plt.savefig(FIGS / fname, dpi=150)
    print(f"  Saved: {fname}")
    plt.close()


# ══════════════════════════════════════════════════════════════════════
#  SYNTHETIC FIGURES
# ══════════════════════════════════════════════════════════════════════

def generate_synth():
    print("\n── Synthetic Figures ──")
    # T1/T2 from synth-8model-sweep, T3 from synth-t3-unfenced
    data12 = load_scored_runs(SYNTH_DIR)
    data12 = [d for d in data12 if d["tier"] in (1, 2)]
    data3 = load_scored_runs(T3UNF_DIR)
    for d in data3:
        d["tier"] = 3
    data = data12 + data3
    print(f"  Loaded {len(data12)} T1/T2 + {len(data3)} T3 = {len(data)} runs")

    # Heatmaps
    for tier in [1, 2, 3]:
        _heatmap(data, MODEL_ORDER, tier,
                 f"Synthetic — Total Score (0–3) — {TIER_LABELS[tier]}",
                 f"synth_heatmap_t{tier}.png")

    # Cross-tier bars
    _cross_tier_bars(data, MODEL_ORDER,
                     "Synthetic: Mean Score by Model × Tier",
                     "synth_cross_tier_bars.png")

    # Per-axis
    _per_axis_bars(data, MODEL_ORDER,
                   "Synthetic: Per-Axis Scores by Model × Tier",
                   "synth_per_axis_bars.png")

    # Tool cmd analysis (T3 unfenced only)
    _tool_cmd_vs_score(data3, "Synthetic T3 unfenced",
                       "synth_tool_cmd_vs_score.png")
    _tool_cmd_by_model(data3, MODEL_ORDER, "Synthetic T3 unfenced",
                       "synth_tool_cmd_by_model.png")
    _tool_cmd_win_vs_fail(data3, "Synthetic T3 unfenced",
                          "synth_tool_cmd_win_vs_fail.png")

    # CMW comparison
    cmw = load_cmw_data()
    if cmw:
        t3 = [d for d in data3]
        cmw_cases = set(d["case"] for d in cmw)
        t3_matched = [d for d in t3 if d["case"] in cmw_cases]
        models = [m for m in MODEL_ORDER if m in set(d["model"] for d in cmw)]

        fig, ax = plt.subplots(figsize=(12, 5))
        x = np.arange(len(models))
        width = 0.35
        baseline = [np.mean([d["total"] for d in t3_matched if d["model"] == m]) if
                    [d for d in t3_matched if d["model"] == m] else 0 for m in models]
        cmw_avg = [np.mean([d["total"] for d in cmw if d["model"] == m]) if
                   [d for d in cmw if d["model"] == m] else 0 for m in models]
        ax.bar(x - width/2, baseline, width, label="T3 (one-shot)", color="#7b1fa2", alpha=0.75)
        ax.bar(x + width/2, cmw_avg, width, label="T3 + CMW", color="#388e3c", alpha=0.75)
        for i, (b, c) in enumerate(zip(baseline, cmw_avg)):
            delta = c - b
            if abs(delta) > 0.01:
                color = "#388e3c" if delta > 0 else "#d32f2f"
                ax.annotate(f"{delta:+.2f}", xy=(i + width/2, c + 0.05),
                            fontsize=8, ha="center", color=color, fontweight="bold")
        ax.set_ylabel("Mean Total Score (0–3)")
        ax.set_title("Synthetic: One-Shot vs Check-My-Work (T3 unfenced)")
        ax.set_xticks(x); ax.set_xticklabels(models, fontsize=9)
        ax.legend(fontsize=9); ax.set_ylim(0, 3.5)
        plt.tight_layout()
        plt.savefig(FIGS / "synth_cmw_comparison.png", dpi=150)
        print(f"  Saved: synth_cmw_comparison.png")
        plt.close()


# ══════════════════════════════════════════════════════════════════════
#  BUGBENCH FIGURES
# ══════════════════════════════════════════════════════════════════════

def generate_bugbench():
    print("\n── BugBench Figures ──")
    all_data = []
    for tier, bdir in BB_DIRS.items():
        if not bdir.exists():
            print(f"  Warning: {bdir} not found, skipping T{tier}")
            continue
        td = load_scored_runs(bdir)
        for d in td:
            d["tier"] = tier
        all_data.extend(td)
    print(f"  Loaded {len(all_data)} BugBench runs")
    if not all_data:
        return

    # Heatmaps
    for tier in [1, 2, 3]:
        _heatmap(all_data, BB_MODEL_ORDER, tier,
                 f"BugBench — Total Score (0–3) — {TIER_LABELS[tier]}",
                 f"bugbench_heatmap_t{tier}.png")

    # Cross-tier bars
    _cross_tier_bars(all_data, BB_MODEL_ORDER,
                     "BugBench: Mean Score by Model × Tier (4 real C bugs)",
                     "bugbench_cross_tier_bars.png")

    # Per-axis
    _per_axis_bars(all_data, BB_MODEL_ORDER,
                   "BugBench: Per-Axis Scores by Model × Tier",
                   "bugbench_per_axis_bars.png")

    # Tool cmd analysis (T3 only)
    t3 = [d for d in all_data if d["tier"] == 3]
    if t3 and any(d["tool_calls"] > 0 for d in t3):
        _tool_cmd_vs_score(t3, "BugBench T3",
                           "bugbench_tool_cmd_vs_score.png")
        _tool_cmd_by_model(t3, BB_MODEL_ORDER, "BugBench T3",
                           "bugbench_tool_cmd_by_model.png")
        _tool_cmd_win_vs_fail(t3, "BugBench T3",
                              "bugbench_tool_cmd_win_vs_fail.png")


# ══════════════════════════════════════════════════════════════════════
#  TOOL-ONLY (regenerate tool figures without full sweep)
# ══════════════════════════════════════════════════════════════════════

def generate_tools_only():
    print("\n── Tool-Command Figures (standalone) ──")
    data3 = load_scored_runs(T3UNF_DIR)
    for d in data3:
        d["tier"] = 3
    _tool_cmd_vs_score(data3, "Synthetic T3 unfenced", "synth_tool_cmd_vs_score.png")
    _tool_cmd_by_model(data3, MODEL_ORDER, "Synthetic T3 unfenced", "synth_tool_cmd_by_model.png")
    _tool_cmd_win_vs_fail(data3, "Synthetic T3 unfenced", "synth_tool_cmd_win_vs_fail.png")

    bb3 = []
    if BB_DIRS[3].exists():
        bb3 = load_scored_runs(BB_DIRS[3])
        for d in bb3:
            d["tier"] = 3
    if bb3 and any(d["tool_calls"] > 0 for d in bb3):
        _tool_cmd_vs_score(bb3, "BugBench T3", "bugbench_tool_cmd_vs_score.png")
        _tool_cmd_by_model(bb3, BB_MODEL_ORDER, "BugBench T3", "bugbench_tool_cmd_by_model.png")
        _tool_cmd_win_vs_fail(bb3, "BugBench T3", "bugbench_tool_cmd_win_vs_fail.png")


# ══════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", choices=["synth", "bugbench", "tools"],
                   help="Generate only a subset of figures")
    args = p.parse_args()

    if args.only == "synth":
        generate_synth()
    elif args.only == "bugbench":
        generate_bugbench()
    elif args.only == "tools":
        generate_tools_only()
    else:
        generate_synth()
        generate_bugbench()

    print(f"\nAll figures saved to: {FIGS}/")


if __name__ == "__main__":
    main()
