"""Full-panel verification figures for the realworld panel.

Combines:
  - Pre-existing bound cells under `bench/results/final_paper_bench/realworld/`
    (promoted earlier from archive sweeps — see `_provenance.json`).
  - Fresh local sweep cells under
    `bench/results/anika-paper-final-realworld-20260511-T*-*/`.

For each (case, tier, model) cell, prefer the fresh local cell if both
sources have it (the locked runset shouldn't produce overlaps, but
de-dup defensively).

Output: per-tier × model coverage + format figures, per-case heatmap,
summary table, anomalies, rows.csv. Same shape as
`analyze_anika_realworld.py` so the two outputs can sit side-by-side.

Usage:
    python bench/analyze_realworld_full.py --out realworld_full_verify
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
PANEL = RESULTS / "final_paper_bench" / "realworld"
LOCAL_SWEEP_RE = re.compile(
    r"^anika-paper-final-realworld-(?P<date>\d{8})-T(?P<tier>\d+)-"
    r"openrouter-(?P<model>.+)$"
)
CELL_RE = re.compile(
    r"^(?P<case>.+)__tier(?P<tier>\d+)__openrouter_(?P<model>.+?)__"
    r"(?:tier\d+_(?:bash_only|gdb_only|gdb_plus_bash|claude_code)"
    r"|t\d+_unfenced_cmw)__ctx\d+__t\d+$"
)

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

# Build a reverse map from sweep-dir slug form to canonical id.
# Sweep slugify rule from bench/run_runset_shard.py:_slugify:
#   re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
# Without this map, regex-based "restore dots" mangles names like
# llama-3.1-8b-instruct → llama-3.1.8b-instruct (false dot).
def _slugify(m: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", m.lower()).strip("-")

SLUG_TO_MODEL = {_slugify(m): m for m in MODEL_ORDER}


def canonical_model_from_sweep_slug(slug: str) -> str:
    """Sweep-dir form: all dashes between provider and model parts
    (e.g. `anthropic-claude-sonnet-4-5`, `meta-llama-llama-3-1-8b-instruct`).
    Resolve back via SLUG_TO_MODEL. Fall back to the slug itself."""
    return SLUG_TO_MODEL.get(slug, slug)


def canonical_model_from_cell_dirname(slug: str) -> str:
    """Cell-name form: first `_` separates provider from model; the
    model part already carries dots
    (e.g. `anthropic_claude-sonnet-4.5`, `meta-llama_llama-3.1-8b-instruct`).
    Just split on first underscore and rejoin with `/`."""
    parts = slug.split("_", 1)
    if len(parts) != 2:
        return slug
    return f"{parts[0]}/{parts[1]}"


def short_label(model: str) -> str:
    return model.split("/")[-1]


def parse_cell(cell_dir: Path, source: str, tier_hint: int | None = None,
               model_hint: str | None = None):
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
    tier = tier_hint if tier_hint is not None else int(m.group("tier"))
    if model_hint is not None:
        model = model_hint
    else:
        # promoted cells have dotted model in the cell name itself
        model = canonical_model_from_cell_dirname(m.group("model"))
    out = {
        "source": source,
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
    rows: list[dict] = []
    seen: dict[tuple[str, int, str], dict] = {}

    # Local fresh sweeps first — preferred if there's overlap
    for d in sorted(RESULTS.iterdir()):
        if not d.is_dir():
            continue
        m = LOCAL_SWEEP_RE.match(d.name)
        if not m:
            continue
        tier = int(m.group("tier"))
        model = canonical_model_from_sweep_slug(m.group("model"))
        for cell in sorted(d.iterdir()):
            if not cell.is_dir():
                continue
            r = parse_cell(cell, "local", tier_hint=tier, model_hint=model)
            if r is None:
                continue
            key = (r["case_id"], r["tier"], r["model"])
            seen[key] = r

    # Bound cells from final_paper_bench/realworld/
    if PANEL.exists():
        for cell in sorted(PANEL.iterdir()):
            if not cell.is_dir():
                continue
            r = parse_cell(cell, "bound")
            if r is None:
                continue
            key = (r["case_id"], r["tier"], r["model"])
            if key not in seen:
                seen[key] = r

    rows.extend(seen.values())
    return rows


def aggregate(rows):
    by = {}
    for r in rows:
        key = (r["tier"], r["model"])
        d = by.setdefault(key, dict(
            N=0, ok=0, to=0, nc=0, bf=0, other=0,
            full=0, partial=0, empty=0,
            full_native=0, full_recovered=0,
            local=0, bound=0,
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
        d[r["source"]] = d.get(r["source"], 0) + 1
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
    pos = {m: i for i, m in enumerate(MODEL_ORDER)}

    def sk(key):
        t, m = key
        return (t, pos.get(m, 999), m)

    return sorted(by.keys(), key=sk)


def write_summary(by, out_path):
    lines = [
        "# Realworld full panel — verification summary\n\n",
        "Combines fresh local Anika sweep "
        "(`anika-paper-final-realworld-20260511-T*-*`) with pre-bound "
        "cells in `final_paper_bench/realworld/` (sourced from earlier "
        "archive sweeps via `_provenance.json`).\n\n",
        "Model order follows `feedback_figure_conventions.md`. "
        "Per-cell precedence: local sweep > bound archive (no overlap "
        "expected because the locked runset excludes already-bound rows).\n\n",
        "| Tier | Model | N | ok | timeout | no_collect | build_failed | "
        "local | bound | full RC/LF/GF | (of which recovered) | "
        "partial prose | empty |\n",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n",
    ]
    totals = dict(N=0, ok=0, to=0, nc=0, bf=0, local=0, bound=0,
                  full=0, full_recovered=0, partial=0, empty=0)
    for k in sorted_keys(by):
        tier, model = k
        d = by[k]
        lines.append(
            f"| T{tier} | {model} | {d['N']} | {d['ok']} | "
            f"{d['to']} | {d['nc']} | {d['bf']} | "
            f"{d.get('local', 0)} | {d.get('bound', 0)} | "
            f"{d['full']} | {d['full_recovered']} | "
            f"{d['partial']} | {d['empty']} |\n"
        )
        for k2 in totals:
            totals[k2] += d.get(k2, 0)
    lines.append(
        f"| | **TOTAL** | **{totals['N']}** | **{totals['ok']}** | "
        f"**{totals['to']}** | **{totals['nc']}** | **{totals['bf']}** | "
        f"**{totals['local']}** | **{totals['bound']}** | "
        f"**{totals['full']}** | **{totals['full_recovered']}** | "
        f"**{totals['partial']}** | **{totals['empty']}** |\n"
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
    fig, ax = plt.subplots(figsize=(max(12, 0.5 * len(keys) + 2), 6))
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
    ax.set_title("Realworld full panel  —  run completion (local + bound)")
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
    fig, ax = plt.subplots(figsize=(max(12, 0.5 * len(keys) + 2), 6))
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
    ax.set_title("Realworld full panel  —  format compliance (local + bound)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_heatmap(rows, out_path):
    cases = sorted({r["case_id"] for r in rows})
    pos = {m: i for i, m in enumerate(MODEL_ORDER)}

    def sk(key):
        t, m = key
        return (t, pos.get(m, 999), m)

    keys = sorted({(r["tier"], r["model"]) for r in rows}, key=sk)
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
        figsize=(max(14, 0.42 * len(keys) + 3),
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
        "Realworld full panel  —  case × (tier, model)\n"
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
            reasons.append("build_failed")
        else:
            reasons.append(f"status={r['status']}")
        if reasons:
            bad.append((r, reasons))
    bad.sort(key=lambda x: (x[0]["tier"], x[0]["model"], x[0]["case_id"]))
    lines = [
        "# Anomalies in realworld full panel\n\n",
        f"Total flagged cells: **{len(bad)}** / {len(rows)}\n\n",
        "| Source | Tier | Model | Case | Status | Elapsed | RespLen | Reasons |\n",
        "|---|---|---|---|---|---:|---:|---|\n",
    ]
    for r, reasons in bad:
        lines.append(
            f"| {r['source']} | T{r['tier']} | {short_label(r['model'])} | "
            f"{r['case_id']} | {r['status']} | {r['elapsed_s']} | "
            f"{r['response_len']} | {'; '.join(reasons)} |\n"
        )
    out_path.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="realworld_full_verify")
    args = p.parse_args()

    rows = collect_rows()
    keys = {(r["tier"], r["model"]) for r in rows}
    cases = {r["case_id"] for r in rows}
    n_local = sum(1 for r in rows if r["source"] == "local")
    n_bound = sum(1 for r in rows if r["source"] == "bound")
    print(f"[analyze] {len(rows)} cells ({n_local} local + {n_bound} bound) "
          f"across {len(keys)} (tier, model) groups, "
          f"{len(cases)} unique cases")

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
