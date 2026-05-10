"""Build comparison figures for the yara T3 unfence/prompt fix.

Three sweeps to compare:
  - PRE-FIX:    pilot-yara-20260503-v2-fixed       (T3 cells only)
  - POST-FIX1:  newt3-yara-20260504-postfix        (Tier3Driver fix only)
  - POST-FIX2:  newt3-yara-20260504-postfix2       (DockerDriver fix landed)

Reads result.json + score.json + chatdbg.log.yaml + collect.json from each
run, derives metrics, writes PNGs to bench/analysis_artifacts/figs_yara_t3_fix/.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(r"C:\Users\Owner\OneDrive\Documents\Classes\COS\COS484\chatdbgpro\bench\results")
FIGS = Path(__file__).parent

SWEEPS = [
    ("pre-fix", ROOT / "pilot-yara-20260503-v2-fixed", "tier3"),
    ("post-fix1\n(Tier3Driver)", ROOT / "newt3-yara-20260504-postfix", "tier3"),
    ("post-fix2\n(DockerDriver)", ROOT / "newt3-yara-20260504-postfix2", "tier3"),
]

# Ground-truth correct files per case (from case.yaml criteria)
TRUTH_FILES = {
    "yara-1": "libyara/parser.c",
    "yara-2": "libyara/scan.c",
    "yara-3": "libyara/atoms.c",
    "yara-4": "libyara/include/yara/globals.h",
    "yara-5": "libyara/parser.c",
}

CASES = ["yara-1", "yara-2", "yara-3", "yara-4", "yara-5"]


def parse_sweep(sweep_dir: Path, tier_filter: str):
    rows = []
    if not sweep_dir.exists():
        return rows
    for d in sorted(sweep_dir.iterdir()):
        if not d.is_dir():
            continue
        parts = d.name.split("__")
        if len(parts) < 3:
            continue
        case, tier, model = parts[0], parts[1], parts[2]
        if tier_filter and tier != tier_filter:
            continue
        sp = d / "score.json"
        cp = d / "collect.json"
        log = d / "chatdbg.log.yaml"
        score = json.load(open(sp, encoding="utf-8")) if sp.exists() else {}
        scores = score.get("scores", {})
        rc, lf, gf = scores.get("root_cause", 0), scores.get("local_fix", 0), scores.get("global_fix", 0)
        n_tools = score.get("mut", {}).get("num_tool_calls", 0)
        n_blocked = 0
        if log.exists():
            try:
                n_blocked = sum(1 for _ in open(log, encoding="utf-8") if "is not allowed" in _)
            except Exception:
                n_blocked = 0
        # right-file mention
        resp_text = ""
        prompt_has_source = False
        if cp.exists():
            c = json.load(open(cp, encoding="utf-8"))
            q = c["queries"][0]
            resp_text = (q.get("response") or "")
            prompt_has_source = "Source file:" in (q.get("prompt") or "")
        truth = TRUTH_FILES.get(case, "")
        right_file = bool(truth and truth in resp_text)
        rows.append({
            "case": case, "tier": tier, "model": model,
            "rc": rc, "lf": lf, "gf": gf,
            "tools": n_tools, "blocked": n_blocked,
            "right_file": right_file,
            "prompt_has_source": prompt_has_source,
            "judge_model": score.get("judge_model", "?"),
            "resp_len": len(resp_text),
        })
    return rows


def main():
    FIGS.mkdir(parents=True, exist_ok=True)
    data = {label: parse_sweep(p, tier) for label, p, tier in SWEEPS}
    labels = list(data.keys())

    # ---------- Figure 1: Total score per sweep ----------
    fig, ax = plt.subplots(figsize=(7, 4.5))
    rc_tot = [sum(r["rc"] for r in data[l]) for l in labels]
    lf_tot = [sum(r["lf"] for r in data[l]) for l in labels]
    gf_tot = [sum(r["gf"] for r in data[l]) for l in labels]
    n_per = [len(data[l]) for l in labels]
    x = np.arange(len(labels))
    w = 0.25
    ax.bar(x - w, rc_tot, w, label="root_cause", color="#1f77b4")
    ax.bar(x, lf_tot, w, label="local_fix", color="#ff7f0e")
    ax.bar(x + w, gf_tot, w, label="global_fix", color="#2ca02c")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    for i, n in enumerate(n_per):
        ax.text(i, max(rc_tot[i], lf_tot[i], gf_tot[i]) + 0.05,
                f"n={n}", ha="center", fontsize=9, color="#555")
    ax.set_ylabel("# correct (out of n cases)")
    ax.set_title("Yara T3 (gpt-4o) — judge scores per axis × sweep")
    ax.set_ylim(0, max([max(rc_tot+lf_tot+gf_tot+[1])+1, 5]))
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "01_scores_by_axis.png", dpi=140)
    plt.close(fig)

    # ---------- Figure 2: Tool calls per case across sweeps ----------
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(CASES))
    w = 0.27
    for i, label in enumerate(labels):
        vals = []
        for c in CASES:
            r = next((r for r in data[label] if r["case"] == c), None)
            vals.append(r["tools"] if r else 0)
        ax.bar(x + (i - 1) * w, vals, w, label=label.replace("\n", " "))
    ax.set_xticks(x)
    ax.set_xticklabels(CASES)
    ax.set_ylabel("tool calls")
    ax.set_title("Tool calls per case × sweep — model is debugging more after fix")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "02_tool_calls.png", dpi=140)
    plt.close(fig)

    # ---------- Figure 3: Blocked commands ----------
    fig, ax = plt.subplots(figsize=(7, 4))
    blocked_tot = [sum(r["blocked"] for r in data[l]) for l in labels]
    bars = ax.bar(labels, blocked_tot, color=["#d62728", "#ff9896", "#2ca02c"])
    for b, v in zip(bars, blocked_tot):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.05, str(v), ha="center")
    ax.set_ylabel("# 'Command X is not allowed' across 5 runs")
    ax.set_title("Safety-allowlist blocks: 6 → 3 → 0 after both fixes land")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "03_blocked_commands.png", dpi=140)
    plt.close(fig)

    # ---------- Figure 4: Right file mentioned in diagnosis ----------
    fig, ax = plt.subplots(figsize=(7, 4))
    rf_count = [sum(1 for r in data[l] if r["right_file"]) for l in labels]
    bars = ax.bar(labels, rf_count, color=["#d62728", "#ff9896", "#2ca02c"])
    for b, v, n in zip(bars, rf_count, n_per):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.05,
                f"{v}/{n}", ha="center")
    ax.set_ylabel("# diagnoses that name the correct source file")
    ax.set_title("Diagnosis localization (file-level)")
    ax.set_ylim(0, max(rf_count + [5]) + 0.5)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "04_right_file_mention.png", dpi=140)
    plt.close(fig)

    # ---------- Figure 5: Source file leak into prompt ----------
    fig, ax = plt.subplots(figsize=(7, 4))
    ph = [sum(1 for r in data[l] if r["prompt_has_source"]) for l in labels]
    bars = ax.bar(labels, ph, color=["#d62728", "#ff9896", "#2ca02c"])
    for b, v, n in zip(bars, ph, n_per):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.05,
                f"{v}/{n}", ha="center")
    ax.set_ylabel("# runs where prompt includes 'Source file:' line")
    ax.set_title("Prompt enrichment reach")
    ax.set_ylim(0, max(ph + [5]) + 0.5)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "05_source_file_in_prompt.png", dpi=140)
    plt.close(fig)

    # ---------- CSV dump ----------
    import csv
    with open(FIGS / "data.csv", "w", newline="", encoding="utf-8") as f:
        w_ = csv.writer(f)
        w_.writerow(["sweep", "case", "tier", "rc", "lf", "gf",
                     "tools", "blocked", "right_file", "prompt_has_source",
                     "judge_model", "resp_len"])
        for label in labels:
            for r in data[label]:
                w_.writerow([label.replace("\n", " "), r["case"], r["tier"],
                             r["rc"], r["lf"], r["gf"],
                             r["tools"], r["blocked"],
                             int(r["right_file"]),
                             int(r["prompt_has_source"]),
                             r["judge_model"], r["resp_len"]])

    print("Wrote:")
    for p in sorted(FIGS.glob("*")):
        print(" ", p)
    print()
    print("Summary table:")
    print(f"{'sweep':30s} {'n':>3} {'rc':>3} {'lf':>3} {'gf':>3} {'total':>5} {'tools':>5} {'blocked':>7} {'right_file':>10} {'src_in_prompt':>14}")
    for label in labels:
        d = data[label]
        n = len(d)
        rc = sum(r["rc"] for r in d); lf = sum(r["lf"] for r in d); gf = sum(r["gf"] for r in d)
        tot = rc + lf + gf
        tt = sum(r["tools"] for r in d)
        bl = sum(r["blocked"] for r in d)
        rf = sum(1 for r in d if r["right_file"])
        sp = sum(1 for r in d if r["prompt_has_source"])
        print(f"{label.replace(chr(10), ' '):30s} {n:>3} {rc:>3} {lf:>3} {gf:>3} {tot:>5} {tt:>5} {bl:>7} {rf:>10} {sp:>14}")


if __name__ == "__main__":
    main()
