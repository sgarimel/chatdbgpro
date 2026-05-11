"""Diagnostics over `bench/results/final_paper_bench/synthetic`.

Two modes:
- `--filter recent`: only cells whose source sweep matches Anika's
  20260510 reruns (the post-recovery view of my T1 shard).
- `--filter all` (default): every cell in the panel, including the
  archived runs that filled in earlier — gives a fully-covered grid.

For each cell:
- status (ok / timeout / no_collect / other)
- format compliance: ROOT CAUSE + LOCAL FIX + GLOBAL FIX present in
  collect.json.queries[0].response (after recover_responses ran)
- empty: response < 50 chars

Outputs PNG + summary.md into `bench/analysis_artifacts/<out-name>/`.

Usage:
    python -m bench.analyze_synthetic_panel --filter recent  --out anika_synthetic_T1_recovered
    python -m bench.analyze_synthetic_panel --filter all     --out synthetic_panel_full
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[1]
PANEL = REPO / "bench/results/final_paper_bench/synthetic"
PROV  = REPO / "bench/results/final_paper_bench/_provenance.json"

# Cell dir name format: <case>__tier<N>__<model_slug>__<cfg>__ctxN__tN
CELL_RE = re.compile(r"^(?P<case>.+)__tier(?P<tier>\d+)__openrouter_(?P<model>.+?)__"
                     r"tier\d+_(?:bash_only|gdb_only|gdb_plus_bash|claude_code)__ctx\d+__t\d+$")


def short_model(slug: str) -> str:
    """Compact display label for figures."""
    parts = slug.split("_")
    return " ".join(parts)


def load_provenance() -> dict[str, dict]:
    """Map cell dir-name -> provenance entry. Used to filter to recent sweeps."""
    if not PROV.exists():
        return {}
    try:
        data = json.loads(PROV.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for e in data.get("copied", []):
        # final_paper_bench cell dir name = source_cell when the panel
        # was assembled (see bench/copy_to_final_bench.py).
        out[e.get("source_cell", "")] = e
    return out


def parse_cell(cell_dir: Path):
    rj_path = cell_dir / "result.json"
    if not rj_path.exists():
        return None
    try:
        rj = json.loads(rj_path.read_text())
    except Exception:
        return None
    m = CELL_RE.match(cell_dir.name)
    if not m:
        return None
    out = {
        "case_id":   rj.get("case_id") or m.group("case"),
        "tier":      int(m.group("tier")),
        "model":     short_model(m.group("model")),
        "status":    rj.get("status"),
        "elapsed_s": rj.get("elapsed_s"),
        "exit_code": rj.get("exit_code"),
        "tool_calls": None,
        "response_len": 0,
        "has_rc": False, "has_lf": False, "has_gf": False,
        "response_source": None,
    }
    cj_path = cell_dir / "collect.json"
    if cj_path.exists():
        try:
            cj = json.loads(cj_path.read_text())
            q = cj["queries"][0]
            resp = q.get("response") or ""
            out["tool_calls"] = q.get("num_tool_calls")
            out["response_len"] = len(resp)
            out["has_rc"] = "ROOT CAUSE" in resp
            out["has_lf"] = "LOCAL FIX"  in resp
            out["has_gf"] = "GLOBAL FIX" in resp
            out["response_source"] = q.get("response_source")
        except Exception:
            pass
    return out


def collect_rows(filter_mode: str):
    prov = load_provenance()
    rows = []
    for cell in sorted(PANEL.iterdir()):
        if not cell.is_dir(): continue
        r = parse_cell(cell)
        if r is None: continue
        if filter_mode == "recent":
            entry = prov.get(cell.name) or {}
            sweep = entry.get("source_sweep", "")
            if "anika-paper-final-synthetic-20260510" not in sweep:
                continue
        rows.append(r)
    return rows


def summarise(rows, out_path, title):
    by = {}
    for r in rows:
        key = (r["tier"], r["model"])
        d = by.setdefault(key, dict(N=0, ok=0, to=0, nc=0, other=0,
                                    full=0, partial=0, empty=0, recovered=0))
        d["N"] += 1
        if r["status"] == "ok": d["ok"] += 1
        elif r["status"] == "timeout": d["to"] += 1
        elif r["status"] == "no_collect": d["nc"] += 1
        else: d["other"] += 1
        labels = sum([r["has_rc"], r["has_lf"], r["has_gf"]])
        if labels == 3:
            d["full"] += 1
            if r["response_source"] == "recovered_from_tool_output":
                d["recovered"] += 1
        elif r["response_len"] < 50:
            d["empty"] += 1
        else:
            d["partial"] += 1

    lines = [f"# {title}\n\n"]
    lines.append("Source: `bench/results/final_paper_bench/synthetic`. "
                 "`full RC/LF/GF` counts cells whose response contains all three "
                 "labelled paragraphs; `recovered` are cells whose response was "
                 "patched in by `bench/recover_responses.py` from tool output.\n\n")
    lines.append("| Tier | Model | N | ok | timeout | no_collect | full RC/LF/GF | (of which recovered) | partial prose | empty |\n")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    totals = dict(N=0,ok=0,to=0,nc=0,full=0,recovered=0,partial=0,empty=0)
    for (tier, model), d in sorted(by.items()):
        lines.append(f"| T{tier} | {model} | {d['N']} | {d['ok']} | {d['to']} | {d['nc']} | "
                     f"{d['full']} | {d['recovered']} | {d['partial']} | {d['empty']} |\n")
        for k in totals: totals[k] += d.get(k, 0)
    lines.append(f"| | **TOTAL** | **{totals['N']}** | **{totals['ok']}** | **{totals['to']}** | "
                 f"**{totals['nc']}** | **{totals['full']}** | **{totals['recovered']}** | "
                 f"**{totals['partial']}** | **{totals['empty']}** |\n")
    out_path.write_text("".join(lines), encoding="utf-8")
    return by


def plot_coverage(by, out_path, title):
    keys = sorted(by.keys())
    labels = [f"T{t} {m}" for t,m in keys]
    ok = [by[k]["ok"] for k in keys]
    to = [by[k]["to"] for k in keys]
    nc = [by[k]["nc"] for k in keys]
    other = [by[k]["other"] for k in keys]
    fig, ax = plt.subplots(figsize=(max(8, 0.7*len(keys)+2), 5))
    x = list(range(len(keys)))
    ax.bar(x, ok, label="status=ok", color="#3a8e3a")
    ax.bar(x, to, bottom=ok, label="timeout (600s)", color="#e2884b")
    bot2 = [a+b for a,b in zip(ok, to)]
    ax.bar(x, nc, bottom=bot2, label="no_collect", color="#c84a3a")
    bot3 = [a+b+c for a,b,c in zip(ok, to, nc)]
    ax.bar(x, other, bottom=bot3, label="other", color="#888")
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("cells")
    ax.set_title(f"{title}  —  run completion")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130); plt.close(fig)


def plot_format(by, out_path, title):
    keys = sorted(by.keys())
    labels = [f"T{t} {m}" for t,m in keys]
    full = [by[k]["full"] for k in keys]
    recovered = [by[k]["recovered"] for k in keys]
    full_native = [f-r for f,r in zip(full, recovered)]
    partial = [by[k]["partial"] for k in keys]
    empty = [by[k]["empty"] for k in keys]
    fig, ax = plt.subplots(figsize=(max(8, 0.7*len(keys)+2), 5))
    x = list(range(len(keys)))
    ax.bar(x, full_native, label="full RC/LF/GF (native)", color="#3a8e3a")
    ax.bar(x, recovered, bottom=full_native, label="full RC/LF/GF (recovered from tool output)", color="#7fc97f")
    bot2 = [a+b for a,b in zip(full_native, recovered)]
    ax.bar(x, partial, bottom=bot2, label="some prose, missing label(s)", color="#e2c84b")
    bot3 = [a+b+c for a,b,c in zip(full_native, recovered, partial)]
    ax.bar(x, empty, bottom=bot3, label="empty / <50 chars", color="#c84a3a")
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("cells")
    ax.set_title(f"{title}  —  final-response format compliance")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130); plt.close(fig)


def plot_latency(rows, out_path, title):
    by = {}
    for r in rows:
        if r["elapsed_s"] is None: continue
        key = (r["tier"], r["model"])
        by.setdefault(key, []).append(r["elapsed_s"])
    keys = sorted(by.keys())
    labels = [f"T{t} {m}" for t,m in keys]
    fig, ax = plt.subplots(figsize=(max(8, 0.7*len(keys)+2), 5))
    ax.boxplot([by[k] for k in keys], tick_labels=labels, showfliers=True)
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax.set_yscale("log")
    ax.set_ylabel("driver elapsed_s (log)")
    ax.set_title(f"{title}  —  driver wall-clock per cell")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130); plt.close(fig)


def plot_heatmap(rows, out_path, title):
    """Per (case, model+tier) result grid."""
    cases = sorted({r["case_id"] for r in rows})
    keys = sorted({(r["tier"], r["model"]) for r in rows})
    grid = {(r["case_id"], (r["tier"], r["model"])): r for r in rows}
    M = np.zeros((len(cases), len(keys)))
    text = [[""] * len(keys) for _ in cases]
    for i, c in enumerate(cases):
        for j, k in enumerate(keys):
            r = grid.get((c, k))
            if r is None:
                M[i,j] = -1; text[i][j] = "·"
            else:
                full = r["has_rc"] and r["has_lf"] and r["has_gf"]
                is_empty = r["response_len"] < 50
                if r["status"] == "ok" and full:
                    M[i,j] = 2; text[i][j] = "✓"
                elif r["status"] == "ok" and is_empty:
                    M[i,j] = 0; text[i][j] = "E"
                elif r["status"] == "ok":
                    M[i,j] = 1; text[i][j] = "~"
                elif r["status"] == "timeout":
                    M[i,j] = 0; text[i][j] = "T"
                elif r["status"] == "no_collect":
                    M[i,j] = 0; text[i][j] = "N"
                else:
                    M[i,j] = 0; text[i][j] = "x"
    from matplotlib.colors import ListedColormap
    cmap = ListedColormap(["#f0f0f0", "#c84a3a", "#e2c84b", "#3a8e3a"])
    fig, ax = plt.subplots(figsize=(max(10, 0.7*len(keys)+2), max(4, 0.35*len(cases))))
    ax.imshow(M + 1, aspect="auto", cmap=cmap, vmin=0, vmax=3)
    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels([f"T{t} {m}" for t,m in keys], rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(len(cases)))
    ax.set_yticklabels(cases, fontsize=8)
    for i in range(len(cases)):
        for j in range(len(keys)):
            ax.text(j, i, text[i][j], ha="center", va="center", color="black", fontsize=7)
    ax.set_title(f"{title}\n✓=ok+full · ~=ok+missing labels · E=ok+empty · T=timeout · N=no_collect · ·=not in panel")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130); plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--filter", choices=("recent", "all"), default="all")
    p.add_argument("--out", required=True,
                   help="Output dirname under bench/analysis_artifacts/")
    p.add_argument("--title", default=None)
    args = p.parse_args()

    rows = collect_rows(args.filter)
    print(f"[analyze] filter={args.filter} -> {len(rows)} cells")
    title = args.title or (
        "Synthetic panel — Anika 2026-05-10 reruns only" if args.filter == "recent"
        else "Synthetic panel — full final_paper_bench (T1 + T3, all sweeps)"
    )
    out = REPO / "bench/analysis_artifacts" / args.out
    out.mkdir(parents=True, exist_ok=True)
    by = summarise(rows, out / "summary.md", title)
    plot_coverage(by, out / "coverage_by_model_tier.png", title)
    plot_format(by,   out / "format_by_model_tier.png",   title)
    plot_latency(rows, out / "latency_per_model_tier.png", title)
    plot_heatmap(rows, out / "per_case_heatmap.png",       title)
    print(f"[analyze] outputs -> {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
