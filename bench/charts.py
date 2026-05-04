#!/usr/bin/env python3
"""Generate the three core ablation charts from a scored bench run.

Outputs:
  1. score_heatmap_by_model_tier.png
     Rows = models. Columns = T1/T2/T3/T4 grouped by
     root_cause/local_fix/global_fix.
  2. average_debugging_score_by_model.png
     Mean total score by model, normalized to 0..1.
  3. average_tokens_by_model.png
     Mean input+output tokens by model.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np


AXES = ("root_cause", "local_fix", "global_fix")
TIER_LABELS = {
    1: "T1",
    2: "T2",
    3: "T3",
    4: "T4",
}


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def short_model(model: str | None) -> str:
    if not model:
        return "unknown"
    if model in {"haiku", "sonnet", "opus"}:
        return f"{model} (T4)"
    lowered = model.lower()
    if "gpt-5.5" in lowered:
        return "gpt-5.5"
    if "gpt-4o" in lowered:
        return "gpt-4o"
    if "claude" in lowered and "haiku" in lowered:
        return "claude-haiku"
    if "claude" in lowered and "sonnet" in lowered:
        return "claude-sonnet"
    if "qwen" in lowered:
        return "qwen"
    if "nemotron" in lowered:
        return "nemotron"
    if "gemini" in lowered:
        return "gemini"
    if "grok" in lowered:
        return "grok"
    return model.split("/")[-1]


def _collect_tokens(run_dir: Path, score: dict) -> tuple[int, int]:
    mut = score.get("mut") or {}
    input_tokens = int(mut.get("mut_input_tokens") or 0)
    output_tokens = int(mut.get("mut_output_tokens") or 0)
    collect_path = run_dir / "collect.json"
    if collect_path.exists() and (input_tokens == 0 or output_tokens == 0):
        try:
            collect = load_json(collect_path)
            query = (collect.get("queries") or [{}])[0]
            stats = query.get("stats") or {}
            input_tokens = input_tokens or int(stats.get("prompt_tokens") or 0)
            output_tokens = output_tokens or int(stats.get("completion_tokens") or 0)
        except Exception:
            pass
    return input_tokens, output_tokens


def gather_rows(run_root: Path) -> list[dict]:
    rows: list[dict] = []
    for run_dir in sorted(run_root.iterdir()):
        if not run_dir.is_dir():
            continue
        result_path = run_dir / "result.json"
        score_path = run_dir / "score.json"
        if not result_path.exists() or not score_path.exists():
            continue
        try:
            result = load_json(result_path)
            score = load_json(score_path)
        except json.JSONDecodeError:
            continue
        scores = score.get("scores") or {}
        if any(scores.get(axis) is None for axis in AXES):
            continue
        input_tokens, output_tokens = _collect_tokens(run_dir, score)
        tier = result.get("tier")
        try:
            tier = int(tier)
        except (TypeError, ValueError):
            tier = 0
        rows.append({
            "run_id": result.get("run_id", run_dir.name),
            "case_id": result.get("case_id"),
            "model": result.get("model"),
            "model_label": short_model(result.get("model")),
            "tier": tier,
            "trial": result.get("trial"),
            "status": result.get("status"),
            "judge_status": score.get("status"),
            "root_cause": float(scores.get("root_cause") or 0),
            "local_fix": float(scores.get("local_fix") or 0),
            "global_fix": float(scores.get("global_fix") or 0),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        })
    return rows


def _mean(values: list[float]) -> float:
    clean = [v for v in values if v is not None and not math.isnan(v)]
    return float(sum(clean) / len(clean)) if clean else float("nan")


def _group(rows: list[dict], keys: tuple[str, ...]) -> dict[tuple, list[dict]]:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = tuple(row[k] for k in keys)
        groups.setdefault(key, []).append(row)
    return groups


def write_summary_csv(rows: list[dict], out_dir: Path) -> None:
    fields = [
        "model_label", "model", "tier", "n",
        "root_cause_mean", "local_fix_mean", "global_fix_mean",
        "total_score_mean", "total_score_norm_mean", "tokens_mean",
    ]
    records = []
    for (model_label, model, tier), group in sorted(_group(rows, ("model_label", "model", "tier")).items()):
        rc = _mean([g["root_cause"] for g in group])
        lf = _mean([g["local_fix"] for g in group])
        gf = _mean([g["global_fix"] for g in group])
        total = _mean([g["root_cause"] + g["local_fix"] + g["global_fix"] for g in group])
        records.append({
            "model_label": model_label,
            "model": model,
            "tier": tier,
            "n": len(group),
            "root_cause_mean": round(rc, 4),
            "local_fix_mean": round(lf, 4),
            "global_fix_mean": round(gf, 4),
            "total_score_mean": round(total, 4),
            "total_score_norm_mean": round(total / 3.0, 4),
            "tokens_mean": round(_mean([g["total_tokens"] for g in group]), 2),
        })
    with (out_dir / "chart_summary_by_model_tier.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def plot_score_heatmap(rows: list[dict], out_dir: Path) -> None:
    model_labels = sorted({r["model_label"] for r in rows})
    tiers = [t for t in (1, 2, 3, 4) if any(r["tier"] == t for r in rows)]
    columns = [(tier, axis) for tier in tiers for axis in AXES]
    data = np.full((len(model_labels), len(columns)), np.nan)
    groups = _group(rows, ("model_label", "tier"))
    for i, model in enumerate(model_labels):
        for j, (tier, axis) in enumerate(columns):
            group = groups.get((model, tier), [])
            if group:
                data[i, j] = _mean([g[axis] for g in group])

    width = max(10, len(columns) * 0.85)
    height = max(4, len(model_labels) * 0.45)
    fig, ax = plt.subplots(figsize=(width, height))
    im = ax.imshow(data, vmin=0, vmax=1, cmap="RdYlGn", aspect="auto")

    ax.set_yticks(range(len(model_labels)))
    ax.set_yticklabels(model_labels)
    ax.set_xticks(range(len(columns)))
    ax.set_xticklabels([axis.replace("_", " ") for _, axis in columns], rotation=35, ha="right")

    for start in range(0, len(columns), 3):
        end = min(start + 2, len(columns) - 1)
        tier = columns[start][0]
        ax.text((start + end) / 2, -0.9, TIER_LABELS.get(tier, f"T{tier}"),
                ha="center", va="bottom", fontsize=11, fontweight="bold")
        if start:
            ax.axvline(start - 0.5, color="black", linewidth=1.2)

    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            value = data[i, j]
            text = "-" if np.isnan(value) else f"{value:.2f}"
            color = "white" if not np.isnan(value) and (value < 0.25 or value > 0.75) else "black"
            ax.text(j, i, text, ha="center", va="center", color=color, fontsize=9)

    ax.set_title("Average Rubric Score By Model, Tier, And Axis")
    ax.set_xlabel("Ablation tier and rubric axis")
    ax.set_ylabel("Model")
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, label="mean score")
    fig.tight_layout()
    fig.savefig(out_dir / "score_heatmap_by_model_tier.png", dpi=180)
    plt.close(fig)


def plot_average_score(rows: list[dict], out_dir: Path) -> None:
    groups = _group(rows, ("model_label",))
    labels = sorted(groups)
    scores = [
        _mean([r["root_cause"] + r["local_fix"] + r["global_fix"] for r in groups[label]]) / 3.0
        for label in labels
    ]
    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 0.8), 4.5))
    bars = ax.bar([label[0] for label in labels], scores, color="#2a9d8f")
    ax.set_ylim(0, 1)
    ax.set_ylabel("mean total score / 3")
    ax.set_title("Average Debugging Score By Model")
    ax.tick_params(axis="x", rotation=25)
    for bar, score in zip(bars, scores):
        ax.text(bar.get_x() + bar.get_width() / 2, score + 0.02,
                f"{score:.2f}", ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_dir / "average_debugging_score_by_model.png", dpi=180)
    plt.close(fig)


def plot_average_tokens(rows: list[dict], out_dir: Path) -> None:
    groups = _group(rows, ("model_label",))
    labels = sorted(groups)
    tokens = [_mean([r["total_tokens"] for r in groups[label]]) for label in labels]
    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 0.8), 4.5))
    bars = ax.bar([label[0] for label in labels], tokens, color="#457b9d")
    ax.set_ylabel("mean input + output tokens")
    ax.set_title("Average Tokens By Model")
    ax.tick_params(axis="x", rotation=25)
    for bar, value in zip(bars, tokens):
        ax.text(bar.get_x() + bar.get_width() / 2, value,
                f"{value:,.0f}", ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_dir / "average_tokens_by_model.png", dpi=180)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", help="bench/results/<sweep-name>")
    parser.add_argument("--out", default=None,
                        help="Output directory. Default: <run_dir>/analysis/charts")
    args = parser.parse_args()

    run_root = Path(args.run_dir).resolve()
    if not run_root.exists():
        raise SystemExit(f"Run directory not found: {run_root}")
    out_dir = Path(args.out).resolve() if args.out else run_root / "analysis" / "charts"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = gather_rows(run_root)
    if not rows:
        raise SystemExit(
            "No scored runs found. Run bench/judge.py first so each run has score.json."
        )

    write_summary_csv(rows, out_dir)
    plot_score_heatmap(rows, out_dir)
    plot_average_score(rows, out_dir)
    plot_average_tokens(rows, out_dir)
    print(f"[charts] wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
