"""Side-by-side comparison of Anika's vs Ibraheem's T1 realworld sweeps.

Both runners targeted the same 20-case × 8-model panel on the same
runset_locked.tsv, but on different hosts:
  - Anika: local WSL2 Ubuntu, all 4 source types (crashbench, juliet,
           bugbench with custom build fixes, berry via Docker Desktop).
  - Ibraheem: adroit Linux, apptainer for berry, native for others.

Restrict to T1 sweep dirs dated 20260511 so the comparison is
apples-to-apples (same locked runset, same date, same prompt iter).

Output figures show, for each (case, model), the per-runner outcome
plus a unified bar chart with both runners side-by-side per model.

Usage:
    python bench/analyze_realworld_compare.py --out realworld_T1_compare
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "bench" / "results"

# Both runners locked their sweeps to 20260511 — anchor here so dates
# accidentally bleed between runs don't pollute the compare.
SWEEP_RE_TEMPLATE = (
    r"^{owner}-paper-final-realworld-20260511-"
    r"T(?P<tier>\d+)-openrouter-(?P<model>.+)$"
)
CELL_RE = re.compile(
    r"^(?P<case>.+)__tier(?P<tier>\d+)__openrouter_(?P<model>.+?)__"
    r"tier\d+_(?:bash_only|gdb_only|gdb_plus_bash|claude_code)__ctx\d+__t\d+$"
)

MODEL_ORDER = [
    "openai/gpt-5.5",
    "openai/gpt-4o",
    "anthropic/claude-sonnet-4.5",
    "google/gemini-2.5-flash",
    "google/gemini-3.1-flash-lite-preview",
    "qwen/qwen3-30b-a3b-instruct-2507",
    "nvidia/nemotron-3-nano-30b-a3b",
    "meta-llama/llama-3.1-8b-instruct",
]


def _slugify(m: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", m.lower()).strip("-")


SLUG_TO_MODEL = {_slugify(m): m for m in MODEL_ORDER}


def canonical_model_from_sweep_slug(slug: str) -> str:
    return SLUG_TO_MODEL.get(slug, slug)


def short_label(model: str) -> str:
    return model.split("/")[-1]


def parse_cell(cell_dir: Path, owner: str, tier: int, model: str):
    rj_path = cell_dir / "result.json"
    if not rj_path.exists():
        return None
    try:
        rj = json.loads(rj_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    m = CELL_RE.match(cell_dir.name)
    if not m:
        return None
    out = {
        "owner": owner,
        "case_id": rj.get("case_id") or m.group("case"),
        "tier": tier,
        "model": model,
        "status": rj.get("status"),
        "elapsed_s": rj.get("elapsed_s"),
        "tool_calls": None,
        "response_len": 0,
        "has_rc": False, "has_lf": False, "has_gf": False,
        "response_source": None,
        "has_collect": False,
    }
    cj_path = cell_dir / "collect.json"
    if cj_path.exists():
        try:
            cj = json.loads(cj_path.read_text(encoding="utf-8"))
            q = (cj.get("queries") or [{}])[0]
            resp = q.get("response") or ""
            out["tool_calls"] = q.get("num_tool_calls")
            out["response_len"] = len(resp)
            out["has_rc"] = "ROOT CAUSE" in resp
            out["has_lf"] = "LOCAL FIX" in resp
            out["has_gf"] = "GLOBAL FIX" in resp
            out["response_source"] = q.get("response_source")
            out["has_collect"] = True
        except Exception:
            pass
    return out


def collect_rows(owner: str, tier_filter: int):
    rx = re.compile(SWEEP_RE_TEMPLATE.format(owner=owner))
    rows = []
    for d in sorted(RESULTS.iterdir()):
        if not d.is_dir():
            continue
        m = rx.match(d.name)
        if not m:
            continue
        tier = int(m.group("tier"))
        if tier != tier_filter:
            continue
        model = canonical_model_from_sweep_slug(m.group("model"))
        for cell in sorted(d.iterdir()):
            if not cell.is_dir():
                continue
            r = parse_cell(cell, owner, tier, model)
            if r is not None:
                rows.append(r)
    return rows


def aggregate_by_model(rows):
    by = {}
    for r in rows:
        d = by.setdefault(r["model"], dict(
            N=0, ok=0, to=0, nc=0, bf=0, other=0,
            full=0, partial=0, empty=0,
            full_native=0, full_recovered=0,
        ))
        d["N"] += 1
        s = r["status"]
        if s == "ok":
            d["ok"] += 1
        elif s == "timeout":
            d["to"] += 1
        elif s == "no_collect":
            d["nc"] += 1
        elif s == "build_failed":
            d["bf"] += 1
        else:
            d["other"] += 1
        labels = sum([r["has_rc"], r["has_lf"], r["has_gf"]])
        if labels == 3:
            d["full"] += 1
            if r["response_source"] and "recovered" in r["response_source"]:
                d["full_recovered"] += 1
            else:
                d["full_native"] += 1
        elif r["response_len"] < 50:
            d["empty"] += 1
        else:
            d["partial"] += 1
    return by


def plot_compare_bars(by_anika, by_ibraheem, out_path, metric: str,
                      title_metric: str):
    models = [m for m in MODEL_ORDER
              if m in by_anika or m in by_ibraheem]
    labels = [short_label(m)[:18] for m in models]
    a_vals = [by_anika.get(m, {}).get(metric, 0) for m in models]
    i_vals = [by_ibraheem.get(m, {}).get(metric, 0) for m in models]
    a_N = [by_anika.get(m, {}).get("N", 0) for m in models]
    i_N = [by_ibraheem.get(m, {}).get("N", 0) for m in models]

    x = np.arange(len(models))
    w = 0.38
    fig, ax = plt.subplots(figsize=(max(11, 0.7 * len(models) + 2), 6))
    ba = ax.bar(x - w/2, a_vals, w, label="Anika (local WSL2)",
                color="#3a8e3a")
    bi = ax.bar(x + w/2, i_vals, w, label="Ibraheem (adroit login)",
                color="#4a8ec8")
    # N annotation above each bar
    for j, (v, n) in enumerate(zip(a_vals, a_N)):
        ax.text(j - w/2, v + 0.2, f"{v}/{n}", ha="center", fontsize=7)
    for j, (v, n) in enumerate(zip(i_vals, i_N)):
        ax.text(j + w/2, v + 0.2, f"{v}/{n}", ha="center", fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("cells")
    ax.set_title(f"Realworld T1 — {title_metric}, Anika vs Ibraheem "
                 f"(20260511 sweeps)")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_per_case_compare(rows_a, rows_i, out_path):
    """Two-panel heatmap (anika | ibraheem) over cases × models for T1."""
    cases = sorted({r["case_id"] for r in rows_a + rows_i})

    def grid(rows):
        g = {(r["case_id"], r["model"]): r for r in rows}
        M = np.zeros((len(cases), len(MODEL_ORDER)))
        text = [[""] * len(MODEL_ORDER) for _ in cases]
        for i, c in enumerate(cases):
            for j, m in enumerate(MODEL_ORDER):
                r = g.get((c, m))
                if r is None:
                    M[i, j] = -1
                    text[i][j] = "·"
                else:
                    full = r["has_rc"] and r["has_lf"] and r["has_gf"]
                    is_empty = r["response_len"] < 50
                    if r["status"] == "ok" and full:
                        M[i, j] = 2; text[i][j] = "Y"
                    elif r["status"] == "ok" and is_empty:
                        M[i, j] = 0; text[i][j] = "E"
                    elif r["status"] == "ok":
                        M[i, j] = 1; text[i][j] = "~"
                    elif r["status"] == "timeout":
                        M[i, j] = 0; text[i][j] = "T"
                    elif r["status"] == "no_collect":
                        M[i, j] = 0; text[i][j] = "N"
                    elif r["status"] == "build_failed":
                        M[i, j] = 0; text[i][j] = "B"
                    else:
                        M[i, j] = 0; text[i][j] = "x"
        return M, text

    Ma, ta = grid(rows_a)
    Mi, ti = grid(rows_i)

    from matplotlib.colors import ListedColormap
    cmap = ListedColormap(["#f0f0f0", "#c84a3a", "#e2c84b", "#3a8e3a"])
    fig, axes = plt.subplots(
        1, 2,
        figsize=(max(16, 0.55 * len(MODEL_ORDER) * 2 + 3),
                 max(5, 0.35 * len(cases) + 1)),
        sharey=True
    )
    for ax, (M, text), title in zip(axes, [(Ma, ta), (Mi, ti)],
                                    ["Anika (local WSL2)",
                                     "Ibraheem (adroit login)"]):
        ax.imshow(M + 1, aspect="auto", cmap=cmap, vmin=0, vmax=3)
        ax.set_xticks(range(len(MODEL_ORDER)))
        ax.set_xticklabels(
            [short_label(m)[:16] for m in MODEL_ORDER],
            rotation=55, ha="right", fontsize=7)
        for i in range(len(cases)):
            for j in range(len(MODEL_ORDER)):
                ax.text(j, i, text[i][j], ha="center", va="center",
                        color="black", fontsize=6)
        ax.set_title(title, fontsize=10)
    axes[0].set_yticks(range(len(cases)))
    axes[0].set_yticklabels(cases, fontsize=7)
    fig.suptitle("Realworld T1 case × model — Anika vs Ibraheem  "
                 "(Y=ok+full · ~=ok+labels missing · E=ok+empty · "
                 "T=timeout · N=no_collect · B=build_failed · ·=not run)",
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def write_compare_summary(by_a, by_i, out_path):
    models = [m for m in MODEL_ORDER if m in by_a or m in by_i]
    lines = [
        "# Anika vs Ibraheem — T1 realworld comparison (20260511)\n\n",
        "Same locked runset, same prompt iteration, different hosts.\n\n",
        "| Model | Anika N | Anika ok | Anika full | (rec.) | "
        "Ibraheem N | Ibraheem ok | Ibraheem full | (rec.) |\n",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|\n",
    ]
    totals = dict(an_N=0, an_ok=0, an_full=0, an_rec=0,
                  ib_N=0, ib_ok=0, ib_full=0, ib_rec=0)
    for m in models:
        a = by_a.get(m, {})
        i = by_i.get(m, {})
        lines.append(
            f"| {short_label(m)} | "
            f"{a.get('N', 0)} | {a.get('ok', 0)} | {a.get('full', 0)} | "
            f"{a.get('full_recovered', 0)} | "
            f"{i.get('N', 0)} | {i.get('ok', 0)} | {i.get('full', 0)} | "
            f"{i.get('full_recovered', 0)} |\n"
        )
        totals["an_N"] += a.get('N', 0)
        totals["an_ok"] += a.get('ok', 0)
        totals["an_full"] += a.get('full', 0)
        totals["an_rec"] += a.get('full_recovered', 0)
        totals["ib_N"] += i.get('N', 0)
        totals["ib_ok"] += i.get('ok', 0)
        totals["ib_full"] += i.get('full', 0)
        totals["ib_rec"] += i.get('full_recovered', 0)
    lines.append(
        f"| **TOTAL** | **{totals['an_N']}** | **{totals['an_ok']}** | "
        f"**{totals['an_full']}** | **{totals['an_rec']}** | "
        f"**{totals['ib_N']}** | **{totals['ib_ok']}** | "
        f"**{totals['ib_full']}** | **{totals['ib_rec']}** |\n"
    )
    out_path.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="realworld_T1_compare")
    args = p.parse_args()

    rows_a = collect_rows("anika", tier_filter=1)
    rows_i = collect_rows("ibraheem", tier_filter=1)
    print(f"[compare] anika rows: {len(rows_a)}, ibraheem rows: {len(rows_i)}")

    by_a = aggregate_by_model(rows_a)
    by_i = aggregate_by_model(rows_i)

    out = REPO / "bench" / "analysis_artifacts" / args.out
    out.mkdir(parents=True, exist_ok=True)

    write_compare_summary(by_a, by_i, out / "summary.md")
    plot_compare_bars(by_a, by_i, out / "ok_compare.png", "ok",
                      "cells with status=ok")
    plot_compare_bars(by_a, by_i, out / "full_compare.png", "full",
                      "cells with full RC/LF/GF labels")
    plot_compare_bars(by_a, by_i, out / "timeout_compare.png", "to",
                      "cells that timed out")
    plot_per_case_compare(rows_a, rows_i, out / "per_case_compare.png")

    # rows.csv combined
    with (out / "rows.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list((rows_a + rows_i)[0].keys()))
        w.writeheader()
        w.writerows(rows_a + rows_i)

    print(f"[compare] outputs -> {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
