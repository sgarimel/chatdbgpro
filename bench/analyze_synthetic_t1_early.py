"""Early diagnostics for Anika's synthetic-T1 sweep.

Reads result.json + collect.json under
`bench/results/anika-paper-final-synthetic-20260510-T1-*/` and emits
plots and tables into `bench/analysis_artifacts/anika_synthetic_T1_early/`
for a human eyeball pass *before* the judge step.

What we compute:
- coverage per model: cells run, status (ok / timeout / no_collect / other)
- format compliance: response contains ROOT CAUSE + LOCAL FIX + GLOBAL FIX
  (the labelled-paragraph format the prompt requires; judge.py treats short
  responses without these as no_prose_synthesis 0/0/0)
- tool-use shape: number of bash tool calls and response length
- latency: driver elapsed_s per cell
- per-case matrix: which models passed format for each case

Usage:
    python -m bench.analyze_synthetic_t1_early
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[1]
SWEEP_GLOB = "anika-paper-final-synthetic-20260510-T1-*"
OUT = REPO / "bench/analysis_artifacts/anika_synthetic_T1_early"
OUT.mkdir(parents=True, exist_ok=True)


def short_model_slug(sweep_dir: Path) -> str:
    name = sweep_dir.name
    if "-openrouter-" in name:
        tail = name.split("-openrouter-")[-1]
    else:
        tail = name
    return tail.replace("-", " ")


def parse_cell(cell_dir: Path):
    rj_path = cell_dir / "result.json"
    cj_path = cell_dir / "collect.json"
    if not rj_path.exists():
        return None
    rj = json.loads(rj_path.read_text())
    out = {
        "case_id":   rj.get("case_id"),
        "status":    rj.get("status"),
        "elapsed_s": rj.get("elapsed_s"),
        "exit_code": rj.get("exit_code"),
        "tool_calls": None,
        "response_len": 0,
        "has_rc": False,
        "has_lf": False,
        "has_gf": False,
    }
    if cj_path.exists():
        try:
            cj = json.loads(cj_path.read_text())
            q = cj["queries"][0]
            resp = q.get("response") or ""
            out["tool_calls"] = q.get("num_tool_calls")
            out["response_len"] = len(resp)
            out["has_rc"] = bool(re.search(r"ROOT CAUSE", resp))
            out["has_lf"] = bool(re.search(r"LOCAL FIX",  resp))
            out["has_gf"] = bool(re.search(r"GLOBAL FIX", resp))
        except Exception:
            pass
    return out


def collect_all():
    rows = []
    for sweep in sorted((REPO / "bench/results").glob(SWEEP_GLOB)):
        model = short_model_slug(sweep)
        for cell in sorted(p for p in sweep.iterdir() if p.is_dir()):
            r = parse_cell(cell)
            if r is None:
                continue
            r["model"] = model
            rows.append(r)
    return rows


def write_per_model_table(rows, out_path):
    by_model = {}
    for r in rows:
        m = r["model"]
        d = by_model.setdefault(m, dict(N=0, ok=0, to=0, nc=0, other=0,
                                        full=0, partial=0, empty=0))
        d["N"] += 1
        if r["status"] == "ok":      d["ok"] += 1
        elif r["status"] == "timeout":  d["to"] += 1
        elif r["status"] == "no_collect": d["nc"] += 1
        else:                          d["other"] += 1
        labels = sum([r["has_rc"], r["has_lf"], r["has_gf"]])
        if labels == 3:
            d["full"] += 1
        elif r["response_len"] < 50:
            d["empty"] += 1
        else:
            d["partial"] += 1

    lines = []
    lines.append("# Synthetic T1 — early diagnostics (Anika)\n")
    lines.append("Sweep glob: `bench/results/anika-paper-final-synthetic-20260510-T1-*`\n")
    lines.append("All cells are pre-judge; the judge step is deferred until both panels finish.\n\n")
    lines.append("## Per-model coverage + format compliance\n")
    lines.append("| Model | N | ok | timeout | no_collect | full RC/LF/GF | partial prose | empty |\n")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|\n")
    totals = dict(N=0, ok=0, to=0, nc=0, full=0, partial=0, empty=0)
    for m, d in sorted(by_model.items()):
        lines.append(f"| {m} | {d['N']} | {d['ok']} | {d['to']} | {d['nc']} | "
                     f"{d['full']} | {d['partial']} | {d['empty']} |\n")
        for k in totals: totals[k] += d.get(k, 0)
    lines.append(f"| **TOTAL** | **{totals['N']}** | **{totals['ok']}** | "
                 f"**{totals['to']}** | **{totals['nc']}** | "
                 f"**{totals['full']}** | **{totals['partial']}** | **{totals['empty']}** |\n")

    out_path.write_text("".join(lines), encoding="utf-8")
    return by_model


def plot_coverage_stacked(by_model, out_path):
    models = sorted(by_model.keys())
    ok = [by_model[m]["ok"] for m in models]
    to = [by_model[m]["to"] for m in models]
    nc = [by_model[m]["nc"] for m in models]
    other = [by_model[m]["other"] for m in models]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    x = list(range(len(models)))
    bot1 = [a for a in ok]
    bot2 = [a+b for a,b in zip(ok, to)]
    bot3 = [a+b+c for a,b,c in zip(ok, to, nc)]
    ax.bar(x, ok, label="status=ok", color="#3a8e3a")
    ax.bar(x, to, bottom=bot1, label="timeout (inner 600s fired)", color="#e2884b")
    ax.bar(x, nc, bottom=bot2, label="no_collect (runner crashed)", color="#c84a3a")
    ax.bar(x, other, bottom=bot3, label="other", color="#888")
    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("cells")
    ax.set_title("Synthetic T1 — coverage by model (run completion)")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_format_stacked(by_model, out_path):
    models = sorted(by_model.keys())
    full = [by_model[m]["full"] for m in models]
    partial = [by_model[m]["partial"] for m in models]
    empty = [by_model[m]["empty"] for m in models]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    x = list(range(len(models)))
    bot1 = full[:]
    bot2 = [a+b for a,b in zip(full, partial)]
    ax.bar(x, full, label="full RC/LF/GF", color="#3a8e3a")
    ax.bar(x, partial, bottom=bot1, label="some prose, missing label(s)", color="#e2c84b")
    ax.bar(x, empty, bottom=bot2, label="empty / <50 chars", color="#c84a3a")
    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("cells")
    ax.set_title("Synthetic T1 — final-response format compliance by model")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_latency_box(rows, out_path):
    by_model = {}
    for r in rows:
        if r["elapsed_s"] is None: continue
        by_model.setdefault(r["model"], []).append(r["elapsed_s"])
    models = sorted(by_model.keys())
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.boxplot([by_model[m] for m in models], labels=models, showfliers=True)
    ax.set_xticklabels(models, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("driver elapsed_s (log)")
    ax.set_yscale("log")
    ax.set_title("Synthetic T1 — driver wall-clock per cell (log scale)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def write_per_case_heatmap(rows, out_path):
    """For each (case, model) → did the response have full RC/LF/GF format?"""
    cases = sorted({r["case_id"] for r in rows})
    models = sorted({r["model"] for r in rows})
    grid = {(r["case_id"], r["model"]): r for r in rows}

    fig, ax = plt.subplots(figsize=(11, max(4, 0.32 * len(cases))))
    import numpy as np
    M = np.zeros((len(cases), len(models)))
    text = [[""] * len(models) for _ in cases]
    for i, c in enumerate(cases):
        for j, m in enumerate(models):
            r = grid.get((c, m))
            if r is None:
                M[i, j] = -1
                text[i][j] = "·"
            else:
                full = r["has_rc"] and r["has_lf"] and r["has_gf"]
                is_empty = r["response_len"] < 50
                if r["status"] == "ok" and full:
                    M[i, j] = 2; text[i][j] = "✓"
                elif r["status"] == "ok" and is_empty:
                    M[i, j] = 0; text[i][j] = "E"
                elif r["status"] == "ok":
                    M[i, j] = 1; text[i][j] = "~"
                elif r["status"] == "timeout":
                    M[i, j] = 0; text[i][j] = "T"
                else:
                    M[i, j] = 0; text[i][j] = "x"
    from matplotlib.colors import ListedColormap
    cmap = ListedColormap(["#f0f0f0", "#c84a3a", "#e2c84b", "#3a8e3a"])
    im = ax.imshow(M + 1, aspect="auto", cmap=cmap, vmin=0, vmax=3)
    ax.set_xticks(range(len(models)))
    ax.set_xticklabels(models, rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(len(cases)))
    ax.set_yticklabels(cases, fontsize=8)
    for i in range(len(cases)):
        for j in range(len(models)):
            ax.text(j, i, text[i][j], ha="center", va="center",
                    color="black", fontsize=7)
    ax.set_title("Synthetic T1 — per (case, model) result\n"
                 "✓=ok+full format · ~=ok+missing labels · E=ok+empty response · T=timeout · ·=not in runset")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def main():
    rows = collect_all()
    print(f"[analyze] {len(rows)} cells across "
          f"{len({r['model'] for r in rows})} models")
    by_model = write_per_model_table(rows, OUT / "summary.md")
    plot_coverage_stacked(by_model, OUT / "coverage_by_model.png")
    plot_format_stacked(by_model, OUT / "format_by_model.png")
    plot_latency_box(rows, OUT / "latency_per_model.png")
    write_per_case_heatmap(rows, OUT / "per_case_heatmap.png")

    # also dump raw rows for further analysis
    import csv
    csv_path = OUT / "rows.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    print(f"[analyze] outputs -> {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
