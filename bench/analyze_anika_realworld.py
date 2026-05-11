"""Verification figures for Anika's local realworld sweep.

Scans every `bench/results/anika-paper-final-realworld-20260511-T*-*`
sweep dir directly (no `final_paper_bench/realworld` promote step
needed) and emits:

  - summary.md: per-(tier, model) coverage + format compliance
  - coverage_by_model_tier.png: stacked bars (ok / timeout / no_collect / build_failed / other)
  - format_by_model_tier.png: stacked bars (full RC/LF/GF / partial prose / empty)
  - per_case_heatmap.png: case x (tier, model) grid
  - rows.csv: one row per cell with raw fields
  - anomalies.md: cells that look suspicious for hand inspection

Model order follows the project convention from
`feedback_figure_conventions.md`: gpt-5.5, gpt-4o, sonnet, grok, gemini-2.5-flash,
gemini-3.1-flash-lite, qwen30, nemotron30, llama-3.1-8b.

Usage:
    python bench/analyze_anika_realworld.py --out anika_realworld_T1_verify
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

SWEEP_RE = re.compile(
    r"^anika-paper-final-realworld-(?P<date>\d{8})-T(?P<tier>\d+)-"
    r"openrouter-(?P<model>.+)$"
)
CELL_RE = re.compile(
    r"^(?P<case>.+)__tier(?P<tier>\d+)__openrouter_(?P<model>.+?)__"
    r"tier\d+_(?:bash_only|gdb_only|gdb_plus_bash|claude_code)__ctx\d+__t\d+$"
)

# Fixed order for figures (memory: feedback_figure_conventions.md). Models
# missing from a sweep are simply dropped from that figure.
MODEL_ORDER = [
    "openai/gpt-5.5",
    "openai/gpt-4o",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4",
    "google/gemini-2.5-flash",
    "google/gemini-3.1-flash-lite-preview",
    "qwen/qwen3-30b-a3b-instruct-2507",
    "nvidia/nemotron-3-nano-30b-a3b",
    "meta-llama/llama-3.1-8b-instruct",
]


def short_model(slug: str) -> str:
    # slug is dir-style: anthropic_claude-sonnet-4-5
    # MODEL_ORDER uses provider/model-with-dots
    parts = slug.split("_", 1)
    if len(parts) != 2:
        return slug
    provider, rest = parts
    # restore dots in the model name (sweep dirs use dashes for dots in version
    # numbers, but the canonical model id uses dots: gpt-4o stays as-is, but
    # claude-sonnet-4-5 -> claude-sonnet-4.5)
    canonical = rest
    canonical = re.sub(r"(\d)-(\d)", r"\1.\2", canonical)
    return f"{provider}/{canonical}"


def short_label(model: str) -> str:
    # short last-segment label for plotting
    return model.split("/")[-1]


def parse_cell(cell_dir: Path, tier: int, model: str):
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


def collect_rows():
    rows = []
    for d in sorted(RESULTS.iterdir()):
        if not d.is_dir():
            continue
        m = SWEEP_RE.match(d.name)
        if not m:
            continue
        tier = int(m.group("tier"))
        model = short_model(m.group("model"))
        for cell in sorted(d.iterdir()):
            if not cell.is_dir():
                continue
            r = parse_cell(cell, tier, model)
            if r is not None:
                rows.append(r)
    return rows


def aggregate(rows):
    by = {}
    for r in rows:
        key = (r["tier"], r["model"])
        d = by.setdefault(key, dict(
            N=0, ok=0, to=0, nc=0, bf=0, other=0,
            full=0, partial=0, empty=0,
            full_native=0, full_recovered=0,
            no_collect_file=0,
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
        if not r["has_collect"]:
            d["no_collect_file"] += 1
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


def sorted_keys(by):
    """Return keys sorted by (tier asc, MODEL_ORDER position)."""
    pos = {m: i for i, m in enumerate(MODEL_ORDER)}

    def sk(key):
        t, m = key
        return (t, pos.get(m, 999), m)

    return sorted(by.keys(), key=sk)


def write_summary(by, out_path):
    lines = [
        "# Anika realworld sweep — verification summary\n\n",
        "Source: every `bench/results/anika-paper-final-realworld-20260511-T*-*` "
        "sweep dir scanned directly. Model order follows "
        "`feedback_figure_conventions.md`.\n\n",
        "| Tier | Model | N | ok | timeout | no_collect | build_failed | "
        "(missing collect.json) | full RC/LF/GF | (of which recovered) | "
        "partial prose | empty |\n",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n",
    ]
    totals = dict(N=0, ok=0, to=0, nc=0, bf=0,
                  no_collect_file=0, full=0, full_recovered=0,
                  partial=0, empty=0)
    for k in sorted_keys(by):
        tier, model = k
        d = by[k]
        lines.append(
            f"| T{tier} | {model} | {d['N']} | {d['ok']} | "
            f"{d['to']} | {d['nc']} | {d['bf']} | {d['no_collect_file']} | "
            f"{d['full']} | {d['full_recovered']} | {d['partial']} | {d['empty']} |\n"
        )
        for k2 in totals:
            totals[k2] += d.get(k2, 0)
    lines.append(
        f"| | **TOTAL** | **{totals['N']}** | **{totals['ok']}** | "
        f"**{totals['to']}** | **{totals['nc']}** | **{totals['bf']}** | "
        f"**{totals['no_collect_file']}** | **{totals['full']}** | "
        f"**{totals['full_recovered']}** | **{totals['partial']}** | "
        f"**{totals['empty']}** |\n"
    )
    out_path.write_text("".join(lines), encoding="utf-8")


def plot_coverage(by, out_path):
    keys = sorted_keys(by)
    labels = [f"T{t} {short_label(m)[:16]}" for (t, m) in keys]
    ok = [by[k]["ok"] for k in keys]
    to = [by[k]["to"] for k in keys]
    nc = [by[k]["nc"] for k in keys]
    bf = [by[k]["bf"] for k in keys]
    other = [by[k]["other"] for k in keys]
    fig, ax = plt.subplots(figsize=(max(11, 0.5 * len(keys) + 2), 6))
    x = list(range(len(keys)))
    ax.bar(x, ok, label="ok", color="#3a8e3a")
    ax.bar(x, to, bottom=ok, label="timeout", color="#e2884b")
    bot2 = [a + b for a, b in zip(ok, to)]
    ax.bar(x, nc, bottom=bot2, label="no_collect", color="#c84a3a")
    bot3 = [a + b + c for a, b, c in zip(ok, to, nc)]
    ax.bar(x, bf, bottom=bot3, label="build_failed", color="#7a4a8e")
    bot4 = [a + b + c + d for a, b, c, d in zip(ok, to, nc, bf)]
    ax.bar(x, other, bottom=bot4, label="other", color="#888")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=55, ha="right", fontsize=8)
    ax.set_ylabel("cells")
    ax.set_title("Anika realworld sweep  —  run completion (per tier × model)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_format(by, out_path):
    keys = sorted_keys(by)
    labels = [f"T{t} {short_label(m)[:16]}" for (t, m) in keys]
    fn = [by[k]["full_native"] for k in keys]
    fr = [by[k]["full_recovered"] for k in keys]
    partial = [by[k]["partial"] for k in keys]
    empty = [by[k]["empty"] for k in keys]
    fig, ax = plt.subplots(figsize=(max(11, 0.5 * len(keys) + 2), 6))
    x = list(range(len(keys)))
    ax.bar(x, fn, label="full RC/LF/GF (native)", color="#3a8e3a")
    ax.bar(x, fr, bottom=fn,
           label="full RC/LF/GF (recovered from tool output)", color="#7fc97f")
    bot2 = [a + b for a, b in zip(fn, fr)]
    ax.bar(x, partial, bottom=bot2,
           label="some prose, missing label(s)", color="#e2c84b")
    bot3 = [a + b + c for a, b, c in zip(fn, fr, partial)]
    ax.bar(x, empty, bottom=bot3, label="empty / <50 chars", color="#c84a3a")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=55, ha="right", fontsize=8)
    ax.set_ylabel("cells")
    ax.set_title("Anika realworld sweep  —  final-response format compliance")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_heatmap(rows, out_path):
    cases = sorted({r["case_id"] for r in rows})
    by_present = {(r["tier"], r["model"]) for r in rows}

    def sk(key):
        pos = {m: i for i, m in enumerate(MODEL_ORDER)}
        t, m = key
        return (t, pos.get(m, 999), m)

    keys = sorted(by_present, key=sk)
    grid = {(r["case_id"], (r["tier"], r["model"])): r for r in rows}
    M = np.zeros((len(cases), len(keys)))
    text = [[""] * len(keys) for _ in cases]
    for i, c in enumerate(cases):
        for j, k in enumerate(keys):
            r = grid.get((c, k))
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
    from matplotlib.colors import ListedColormap
    cmap = ListedColormap(["#f0f0f0", "#c84a3a", "#e2c84b", "#3a8e3a"])
    fig, ax = plt.subplots(
        figsize=(max(13, 0.42 * len(keys) + 3),
                 max(5, 0.35 * len(cases) + 1)))
    ax.imshow(M + 1, aspect="auto", cmap=cmap, vmin=0, vmax=3)
    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels(
        [f"T{t} {short_label(m)[:18]}" for (t, m) in keys],
        rotation=55, ha="right", fontsize=7)
    ax.set_yticks(range(len(cases)))
    ax.set_yticklabels(cases, fontsize=7)
    for i in range(len(cases)):
        for j in range(len(keys)):
            ax.text(j, i, text[i][j], ha="center", va="center",
                    color="black", fontsize=6)
    ax.set_title(
        "Anika realworld sweep  —  case × (tier, model) heatmap\n"
        "Y=ok+full · ~=ok+missing labels · E=ok+empty · "
        "T=timeout · N=no_collect · B=build_failed · ·=not in panel")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def write_anomalies(rows, out_path):
    bad = []
    for r in rows:
        reasons = []
        if r["status"] == "ok":
            if not r["has_collect"]:
                reasons.append("status=ok but no collect.json")
            elif r["response_len"] < 50:
                reasons.append(f"empty response (len={r['response_len']})")
            elif not (r["has_rc"] and r["has_lf"] and r["has_gf"]):
                missing = []
                if not r["has_rc"]: missing.append("RC")
                if not r["has_lf"]: missing.append("LF")
                if not r["has_gf"]: missing.append("GF")
                reasons.append("missing " + "/".join(missing))
        elif r["status"] in ("no_collect", "timeout"):
            reasons.append(f"status={r['status']}")
        elif r["status"] == "build_failed":
            reasons.append("build_failed (probably man-overflow — known)")
        else:
            reasons.append(f"status={r['status']}")
        if reasons:
            bad.append((r, reasons))
    bad.sort(key=lambda x: (x[0]["tier"], x[0]["model"], x[0]["case_id"]))
    lines = [
        "# Anomalies in Anika realworld sweep\n\n",
        f"Total flagged cells: **{len(bad)}** / {len(rows)}\n\n",
        "| Tier | Model | Case | Status | Elapsed | RespLen | Reasons |\n",
        "|---|---|---|---|---:|---:|---|\n",
    ]
    for r, reasons in bad:
        lines.append(
            f"| T{r['tier']} | {short_label(r['model'])} | {r['case_id']} | "
            f"{r['status']} | {r['elapsed_s']} | {r['response_len']} | "
            f"{'; '.join(reasons)} |\n"
        )
    out_path.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="anika_realworld_T1_verify")
    args = p.parse_args()

    rows = collect_rows()
    keys = {(r["tier"], r["model"]) for r in rows}
    cases = {r["case_id"] for r in rows}
    print(f"[analyze] {len(rows)} cells across {len(keys)} "
          f"(tier, model) groups, {len(cases)} unique cases")

    out = REPO / "bench" / "analysis_artifacts" / args.out
    out.mkdir(parents=True, exist_ok=True)

    by = aggregate(rows)
    write_summary(by, out / "summary.md")
    plot_coverage(by, out / "coverage_by_model_tier.png")
    plot_format(by, out / "format_by_model_tier.png")
    plot_heatmap(rows, out / "per_case_heatmap.png")
    write_anomalies(rows, out / "anomalies.md")

    with (out / "rows.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"[analyze] outputs -> {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
