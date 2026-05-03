"""Build the cross-tier comparison PDF report.

Reads enriched collect.json + score.json and generates 5 figures
stitched into a single PDF:

  Page 1 — Headline heatmap: total score (0-3) per (tier × model)
  Page 2 — Per-axis breakdown: rc / lf / gf, three side-by-side heatmaps
  Page 3 — Cost per run, $: bar grouped by tier × model
  Page 4 — Cost-effectiveness scatter: cost vs mean score, log-x
  Page 5 — Tool engagement: total tool calls per (tier × model)

Two modes for input layout:
  Legacy: 4 separate suites (xtier-t1, xtier-t2, xtier-t3, xtier-t4) —
          one tier per suite. Default for backward compat.
  Single: one suite holds runs from all tiers (the case for run_pilot.sh
          output). Tier is taken from each run's result.json. Pass
          --suite <path> to use this mode.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections import defaultdict

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import LinearSegmentedColormap

REPO = Path(__file__).resolve().parents[2]
LEGACY_SUITES = {
    1: REPO / "bench" / "results" / "xtier-t1",
    2: REPO / "bench" / "results" / "xtier-t2",
    3: REPO / "bench" / "results" / "xtier-t3",
    4: REPO / "bench" / "results" / "xtier-t4",
}

OUT_PDF = REPO / "bench" / "analysis_artifacts" / "figs" / "cross_tier_report.pdf"
OUT_PDF.parent.mkdir(parents=True, exist_ok=True)


def short_model(m: str) -> str:
    """Pretty-print model names for plot axes. Differentiates T4 alias
    forms (`haiku`, `sonnet` — Claude Code aliases) from OpenRouter
    full IDs (`openrouter/anthropic/claude-haiku-4.5` — used by T1-T3)
    so a cell's tier is unambiguous from the legend label alone."""
    if not isinstance(m, str): return "?"
    # T4 alias-only forms come in as bare `haiku` / `sonnet`.
    if m == "haiku":  return "haiku (T4)"
    if m == "sonnet": return "sonnet (T4)"
    if m == "opus":   return "opus (T4)"
    # T4's resolved full names (Claude Code reports these in stats.model).
    if "claude-sonnet-4-6" in m: return "sonnet (T4)"
    if "claude-haiku-4-5" in m and "openrouter" not in m: return "haiku (T4)"
    # OpenRouter / API-keyed forms (T1-T3).
    if "claude-haiku" in m: return "claude-haiku-4.5"
    if "claude-sonnet-4.5" in m: return "claude-sonnet-4.5"
    if "gpt-5.5" in m: return "gpt-5.5"
    if "qwen3-30b" in m: return "qwen-30B"
    if "gemini-3.1-flash-lite" in m: return "gemini-3.1-FL"
    if "nemotron-3-nano-30b" in m: return "nemotron-30B"
    if "grok-4" in m: return "grok-4"
    return m.split("/")[-1]


def _load_run_dir(d: Path, tier_override: int | None = None) -> dict | None:
    r_path = d / "result.json"
    c_path = d / "collect.json"
    s_path = d / "score.json"
    if not (r_path.exists() and c_path.exists()):
        return None
    try:
        r = json.loads(r_path.read_text())
        c = json.loads(c_path.read_text())
        s = json.loads(s_path.read_text()) if s_path.exists() else {}
    except json.JSONDecodeError:
        return None
    q = (c.get("queries") or [{}])[0]
    stats = q.get("stats") or {}
    scores = s.get("scores") or {}
    tier = tier_override if tier_override is not None else r.get("tier", 0)
    return {
        "tier": tier,
        "case_id": r.get("case_id"),
        "model_full": r.get("model"),
        "model": short_model(r.get("model", "")),
        "status": r.get("status"),
        "judge_status": s.get("status"),
        "rc": int(scores.get("root_cause", 0) or 0),
        "lf": int(scores.get("local_fix", 0) or 0),
        "gf": int(scores.get("global_fix", 0) or 0),
        "_q": q,
        "_stats": stats,
    }


def load_runs(suites: dict[int, Path] | None = None,
              single_suite: Path | None = None) -> pd.DataFrame:
    """Load runs in one of two layouts.

    `suites` (default LEGACY_SUITES): {tier: path}. tier is fixed per suite.
    `single_suite`: one path containing runs from all tiers; tier is read
                    from each run's result.json. Used by run_pilot.sh.
    """
    rows = []
    if single_suite is not None:
        for d in sorted(single_suite.iterdir()):
            if not d.is_dir():
                continue
            row = _load_run_dir(d)
            if row is None:
                continue
            rows.append(row)
    else:
        for tier, suite in (suites or LEGACY_SUITES).items():
            if not suite.exists():
                continue
            for d in sorted(suite.iterdir()):
                if not d.is_dir():
                    continue
                row = _load_run_dir(d, tier_override=tier)
                if row is None:
                    continue
                rows.append(row)
    # Reshape: pull the numeric columns the figure code expects out of
    # the cached _q / _stats helpers, dropping those helpers from the row.
    out = []
    for row in rows:
        q = row.pop("_q")
        stats = row.pop("_stats")
        out.append({
            **row,
            "total": row["rc"] + row["lf"] + row["gf"],
            "num_tool_calls": int(q.get("num_tool_calls", 0) or 0),
            "prompt_tokens": int(stats.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(stats.get("completion_tokens", 0) or 0),
            "tokens": int(stats.get("tokens", 0) or 0),
            "cost_estimated_usd": float(stats.get("cost_estimated_usd", 0.0) or 0.0),
            "cost_reported_usd": float(stats.get("cost", 0.0) or 0.0),
            "cost_source": stats.get("cost_source", "unknown"),
            "elapsed_s": float(stats.get("time", 0.0) or 0.0),
        })
    return pd.DataFrame(out)


def _heatmap(ax, pivot, title, *, vmax=3, fmt="d", cmap_name="rdylgn",
             show_cbar=True):
    if cmap_name == "rdylgn":
        cmap = LinearSegmentedColormap.from_list(
            "rdylgn", ["#a4161a", "#e76f51", "#f4a261", "#ffe66d",
                       "#90be6d", "#2a9d8f", "#1b4332"])
    else:
        cmap = plt.get_cmap(cmap_name)
    data = pivot.values.astype(float)
    im = ax.imshow(data, vmin=0, vmax=vmax, cmap=cmap, aspect="auto")
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels(pivot.columns, rotation=30, ha="right")
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels(pivot.index)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = data[i, j]
            if pd.isna(v):
                txt = "—"
            else:
                if fmt == "d":
                    txt = f"{int(round(v))}"
                else:
                    txt = format(v, fmt)
            color = "white" if (v < vmax * 0.35 or v > vmax * 0.75) else "black"
            ax.text(j, i, txt, ha="center", va="center",
                    fontsize=10, fontweight="bold", color=color)
    ax.set_title(title)
    if show_cbar:
        plt.colorbar(im, ax=ax, fraction=0.025)


# Tier-model sort orders. Lock these so figures stay legible across
# re-runs as the data churns.
MODEL_ORDER = [
    "gpt-5.5", "claude-sonnet-4.5", "qwen-30B", "grok-4",
    "gemini-3.1-FL", "nemotron-30B", "sonnet (T4)", "haiku (T4)",
]
TIER_LABELS = {1: "T1 (bash)", 2: "T2 (bash+gdb)",
               3: "T3 (ChatDBG)", 4: "T4 (Claude Code)"}


def fig_total_score(df: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 5.5))
    # Mean total per (tier, model) over our cases
    p = (df.groupby(["tier", "model"])["total"].mean()
         .reset_index()
         .pivot(index="tier", columns="model", values="total"))
    cols = [m for m in MODEL_ORDER if m in p.columns]
    p = p.reindex(columns=cols)
    p.index = [TIER_LABELS.get(t, f"T{t}") for t in p.index]
    _heatmap(ax, p, "Mean total score (root_cause + local_fix + global_fix, /3)\n"
                    "across 4 synthetic cases — judge=openrouter/openai/gpt-4o",
             vmax=3, fmt=".2f")
    return fig


def fig_per_axis(df: pd.DataFrame) -> plt.Figure:
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8))
    cols = [m for m in MODEL_ORDER if m in df["model"].unique()]
    for ax, axis, title in zip(axes,
                                ("rc", "lf", "gf"),
                                ("root_cause", "local_fix", "global_fix")):
        p = (df.groupby(["tier", "model"])[axis].mean()
             .reset_index()
             .pivot(index="tier", columns="model", values=axis))
        p = p.reindex(columns=cols)
        p.index = [TIER_LABELS.get(t, f"T{t}") for t in p.index]
        _heatmap(ax, p, title, vmax=1, fmt=".2f", show_cbar=(axis == "gf"))
    fig.suptitle("Per-axis means (judge 0/1 per axis, averaged across cases)", y=1.02)
    fig.tight_layout()
    return fig


def fig_cost_bars(df: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(12, 5.5))
    # Total cost per (tier, model) summed over cases
    g = (df.groupby(["tier", "model"])["cost_estimated_usd"].sum()
         .reset_index())
    cols = [m for m in MODEL_ORDER if m in g["model"].unique()]
    p = (g.pivot(index="model", columns="tier", values="cost_estimated_usd")
         .reindex(index=cols))
    tiers = sorted(p.columns)
    bar_w = 0.18
    x = np.arange(len(p.index))
    colors = {1: "#264653", 2: "#2a9d8f", 3: "#e9c46a", 4: "#e76f51"}
    for i, t in enumerate(tiers):
        vals = p[t].fillna(0).values
        ax.bar(x + (i - (len(tiers)-1)/2) * bar_w, vals, bar_w,
               color=colors.get(t, "#999"),
               label=TIER_LABELS.get(t, f"T{t}"))
        # Annotate non-zero bars
        for xi, v in zip(x, vals):
            if v > 0.0001:
                ax.text(xi + (i - (len(tiers)-1)/2) * bar_w, v,
                        f"${v:.3f}", ha="center", va="bottom",
                        fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels(p.index, rotation=20, ha="right")
    ax.set_ylabel("estimated cost (USD, summed over 4 cases)")
    ax.set_title("Cost per (tier × model) sweep — token-count × OpenRouter pricing\n"
                 "Tier 4 keychain auth = $0 reported (subscription quota); "
                 "estimate uses Anthropic published rates")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    return fig


def fig_cost_vs_score(df: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 6))
    # Per (tier, model): mean score vs total cost
    g = df.groupby(["tier", "model"]).agg(
        cost=("cost_estimated_usd", "sum"),
        score=("total", "mean"),
        n=("total", "count"),
    ).reset_index()
    markers = {1: "o", 2: "s", 3: "^", 4: "D"}
    colors = {1: "#264653", 2: "#2a9d8f", 3: "#e9c46a", 4: "#e76f51"}
    for t, sub in g.groupby("tier"):
        ax.scatter(sub["cost"].clip(lower=1e-5), sub["score"],
                   marker=markers.get(t, "o"),
                   s=120, alpha=0.85, edgecolor="black", linewidth=0.6,
                   color=colors.get(t, "#999"),
                   label=TIER_LABELS.get(t, f"T{t}"))
        for _, row in sub.iterrows():
            ax.annotate(row["model"],
                        (max(row["cost"], 1e-5), row["score"]),
                        fontsize=7,
                        xytext=(4, -2), textcoords="offset points")
    ax.set_xscale("log")
    ax.set_xlabel("estimated cost (USD per 4-case sweep, log scale)")
    ax.set_ylabel("mean total score / 3")
    ax.set_title("Cost-effectiveness: mean score vs. sweep cost\n"
                 "(4 synthetic cases per (tier × model))")
    ax.legend(loc="lower right")
    ax.set_ylim(-0.1, 3.2)
    ax.grid(linestyle=":", alpha=0.4)
    fig.tight_layout()
    return fig


def fig_tool_engagement(df: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 5.5))
    p = (df.groupby(["tier", "model"])["num_tool_calls"].sum()
         .reset_index()
         .pivot(index="tier", columns="model", values="num_tool_calls"))
    cols = [m for m in MODEL_ORDER if m in p.columns]
    p = p.reindex(columns=cols)
    p.index = [TIER_LABELS.get(t, f"T{t}") for t in p.index]
    _heatmap(ax, p,
             "Total tool calls (summed over 4 cases) — agent engagement",
             vmax=max(50, p.values.max() if not p.empty else 50),
             fmt=".0f", cmap_name="viridis")
    return fig


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--suite",
        type=Path,
        default=None,
        help="Single sweep dir (e.g. bench/results/pilot-yara-...) "
             "containing all-tier runs. If omitted, loads from the legacy "
             "xtier-t{1,2,3,4} sibling dirs.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="PDF output path (default: bench/analysis_artifacts/figs/"
             "cross_tier_report.pdf for legacy mode, or "
             "<suite>.pdf for --suite mode).",
    )
    args = p.parse_args()

    if args.suite is not None:
        df = load_runs(single_suite=args.suite.resolve())
        out_pdf = args.out or (
            REPO / "bench" / "analysis_artifacts" / "figs"
            / f"{args.suite.name}.pdf"
        )
    else:
        df = load_runs()
        out_pdf = args.out or OUT_PDF
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    print(f"loaded {len(df)} runs")
    print(df.groupby(["tier", "model"]).size().to_string())
    print()

    # Filter to "ok" runs for the headline charts; failing ones surface
    # as missing cells. skipped_platform also gets excluded — those are
    # arch-incompatible (Apple Silicon T2/T3 BugsCPP), not data points.
    ok = df[df["status"] == "ok"].copy()

    figs = [
        fig_total_score(ok),
        fig_per_axis(ok),
        fig_cost_bars(df),  # show cost even for failed runs
        fig_cost_vs_score(ok),
        fig_tool_engagement(ok),
    ]
    with PdfPages(out_pdf) as pdf:
        for f in figs:
            pdf.savefig(f, bbox_inches="tight")
            plt.close(f)
    print(f"wrote {out_pdf}")

    summary_csv = out_pdf.with_suffix(".csv")
    df.to_csv(summary_csv, index=False)
    print(f"wrote {summary_csv}")


if __name__ == "__main__":
    main()
