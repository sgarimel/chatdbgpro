"""Yara pilot summary figures.

Aggregates score.json files under a yara pilot directory and produces:
  fig_score_heatmap.png    — bug × (tier, model) cells, three sub-grids (rc/lf/gf)
  fig_tier_model_bars.png  — mean score per (tier, model) across the 5 cases
  fig_summary.txt          — flat text table

Usage:
  python -m bench.analysis_artifacts.yara_pilot_figures \
      bench/results/merged-yara-pilot --label before
  python -m bench.analysis_artifacts.yara_pilot_figures \
      bench/results/<after-dir> --label after

Both calls write into bench/analysis_artifacts/figs/<label>/.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from collections import defaultdict

import numpy as np
import matplotlib.pyplot as plt


def parse_run_dir(name: str) -> dict | None:
    parts = name.split("__")
    if len(parts) < 5:
        return None
    bug, tier, model, *_ = parts
    return {"bug": bug, "tier": tier, "model": model.replace("openrouter_", "")}


def load_runs(pilot_dir: Path) -> list[dict]:
    rows = []
    for run in sorted(pilot_dir.iterdir()):
        if not run.is_dir():
            continue
        meta = parse_run_dir(run.name)
        if meta is None:
            continue
        score_path = run / "score.json"
        if not score_path.exists():
            meta.update(rc=None, lf=None, gf=None, status="no_score")
            rows.append(meta)
            continue
        s = json.loads(score_path.read_text())
        scores = s.get("scores", {})
        meta.update(
            rc=scores.get("root_cause"),
            lf=scores.get("local_fix"),
            gf=scores.get("global_fix"),
            status=s.get("status", "?"),
        )
        rows.append(meta)
    return rows


def write_summary(rows: list[dict], out: Path) -> None:
    lines = ["bug      tier   model                                   rc  lf  gf"]
    for r in rows:
        lines.append(
            f"{r['bug']:<8} {r['tier']:<6} {r['model']:<40} "
            f"{r['rc'] if r['rc'] is not None else '-':>3} "
            f"{r['lf'] if r['lf'] is not None else '-':>3} "
            f"{r['gf'] if r['gf'] is not None else '-':>3}"
        )
    by_tm: dict[tuple, list] = defaultdict(list)
    for r in rows:
        if r["rc"] is None:
            continue
        by_tm[(r["tier"], r["model"])].append((r["rc"], r["lf"], r["gf"]))
    lines.append("")
    lines.append("=== mean score per (tier, model), n cases ===")
    lines.append("tier   model                                   rc   lf   gf  n")
    for (tier, model), scores in sorted(by_tm.items()):
        n = len(scores)
        rc = np.mean([s[0] for s in scores])
        lf = np.mean([s[1] for s in scores])
        gf = np.mean([s[2] for s in scores])
        lines.append(f"{tier:<6} {model:<40} {rc:.2f} {lf:.2f} {gf:.2f}  {n}")
    out.write_text("\n".join(lines) + "\n")


def plot_score_heatmap(rows: list[dict], out: Path) -> None:
    """3-panel heatmap: bug rows × (tier,model) columns, one panel per metric."""
    bugs = sorted({r["bug"] for r in rows})
    cols = sorted({(r["tier"], r["model"]) for r in rows})
    col_labels = [f"{t}\n{m[:20]}" for t, m in cols]

    metrics = [("rc", "root cause"), ("lf", "local fix"), ("gf", "global fix")]
    fig, axes = plt.subplots(1, 3, figsize=(max(3 * len(cols) * 0.9, 9), len(bugs) * 0.7 + 1))
    if len(metrics) == 1:
        axes = [axes]

    for ax, (key, label) in zip(axes, metrics):
        grid = np.full((len(bugs), len(cols)), np.nan)
        for r in rows:
            if r[key] is None:
                continue
            i = bugs.index(r["bug"])
            j = cols.index((r["tier"], r["model"]))
            grid[i, j] = r[key]
        im = ax.imshow(grid, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels(col_labels, rotation=30, ha="right", fontsize=8)
        ax.set_yticks(range(len(bugs)))
        ax.set_yticklabels(bugs, fontsize=9)
        ax.set_title(label)
        for i in range(len(bugs)):
            for j in range(len(cols)):
                v = grid[i, j]
                if np.isnan(v):
                    ax.text(j, i, "-", ha="center", va="center", color="gray", fontsize=7)
                else:
                    ax.text(j, i, f"{int(v)}", ha="center", va="center",
                            color="white" if v < 0.5 else "black", fontsize=9)
    fig.suptitle(f"yara pilot score heatmap ({out.parent.name})")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=140)
    plt.close(fig)


def plot_tier_model_bars(rows: list[dict], out: Path) -> None:
    """Grouped bar chart: mean score per (tier, model), three bars each."""
    by_tm: dict[tuple, list] = defaultdict(list)
    for r in rows:
        if r["rc"] is None:
            continue
        by_tm[(r["tier"], r["model"])].append((r["rc"], r["lf"], r["gf"]))
    keys = sorted(by_tm.keys())
    means = np.array([
        [np.mean([s[i] for s in by_tm[k]]) for i in range(3)]
        for k in keys
    ])
    labels = [f"{t}\n{m[:18]}" for t, m in keys]

    x = np.arange(len(keys))
    w = 0.27
    fig, ax = plt.subplots(figsize=(max(len(keys) * 1.0, 6), 3.4))
    ax.bar(x - w, means[:, 0], w, label="root cause", color="#2a9d8f")
    ax.bar(x,     means[:, 1], w, label="local fix",  color="#e9c46a")
    ax.bar(x + w, means[:, 2], w, label="global fix", color="#e76f51")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("mean score (0-1)")
    ax.set_ylim(0, 1.05)
    ax.set_title(f"yara pilot — mean score per (tier, model) ({out.parent.name})")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=140)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pilot_dir", type=Path)
    ap.add_argument("--label", required=True,
                    help="subdir under figs/ to write into")
    args = ap.parse_args()

    rows = load_runs(args.pilot_dir)
    if not rows:
        raise SystemExit(f"no runs found in {args.pilot_dir}")

    out_dir = Path(__file__).resolve().parent / "figs" / args.label
    out_dir.mkdir(parents=True, exist_ok=True)

    write_summary(rows, out_dir / "fig_summary.txt")
    plot_score_heatmap(rows, out_dir / "fig_score_heatmap.png")
    plot_tier_model_bars(rows, out_dir / "fig_tier_model_bars.png")

    print(f"[yara_pilot_figures] wrote 3 artifacts under {out_dir}/")


if __name__ == "__main__":
    main()
