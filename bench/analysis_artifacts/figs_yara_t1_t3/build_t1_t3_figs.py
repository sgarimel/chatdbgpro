"""T1 vs T3 yara comparison — what data do we have, and does it look reasonable?

T1 = mini-swe-agent + bash only       (works on Windows)
T3 = ChatDBG + gdb in container       (works on Windows)
T2 is omitted (Windows select.select pipe-FD blocker, see notes).

Data sources:
  T1: pilot-yara-20260503-v2-fixed   (haiku-4.5, sonnet-4.5)
  T3: newt3-yara-20260504-postfix2    (gpt-4o, post both fixes)
      newt3-yara-haikusonnet-20260504 (haiku-4.5, sonnet-4.5)

All re-judged with openrouter/openai/gpt-4o-mini for consistency.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(r"C:\Users\Owner\OneDrive\Documents\Classes\COS\COS484\chatdbgpro\bench\results")
FIGS = Path(__file__).parent

# (tier_label, sweep_dir, tier_filter, allowed_models)
SOURCES = [
    ("T1", ROOT / "pilot-yara-20260503-v2-fixed", "tier1",
     ["openrouter_anthropic_claude-haiku-4.5",
      "openrouter_anthropic_claude-sonnet-4.5"]),
    ("T3", ROOT / "newt3-yara-20260504-postfix2", "tier3",
     ["openrouter_openai_gpt-4o"]),
    # v4 had only 1 real haiku run, plus we now have a fresh "real" sweep
    # with yara-1 haiku, yara-1 sonnet, yara-2 sonnet (the rest credit-
    # blocked again before completion). Include both so we have what we have.
    ("T3", ROOT / "newt3-yara-haikusonnet-20260504-v4", "tier3",
     ["openrouter_anthropic_claude-haiku-4.5"]),
    ("T3", ROOT / "newt3-yara-haikusonnet-20260504-real", "tier3",
     ["openrouter_anthropic_claude-haiku-4.5",
      "openrouter_anthropic_claude-sonnet-4.5"]),
]

CASES = ["yara-1", "yara-2", "yara-3", "yara-4", "yara-5"]


def short_model(m: str) -> str:
    m = m.replace("openrouter_anthropic_claude-", "")
    m = m.replace("openrouter_openai_", "")
    return m


def parse():
    rows = []
    for tier_label, sweep, tier_filter, models in SOURCES:
        if not sweep.exists():
            continue
        for d in sorted(sweep.iterdir()):
            if not d.is_dir():
                continue
            parts = d.name.split("__")
            if len(parts) < 3:
                continue
            case, tier, model = parts[0], parts[1], parts[2]
            if tier != tier_filter:
                continue
            if model not in models:
                continue
            sp = d / "score.json"
            cp = d / "collect.json"
            if not cp.exists():
                continue
            try:
                c = json.load(open(cp, encoding="utf-8"))
            except Exception:
                continue
            tools = c["queries"][0].get("tool_calls", [])
            resp = c["queries"][0].get("response", "") or ""
            # Drop credit-failure runs — they have empty transcripts and
            # any score is fake. Real engagement = at least one tool call
            # OR non-empty response.
            if len(tools) == 0 and len(resp) == 0:
                continue
            sc = {}
            judged = False
            if sp.exists():
                try:
                    s = json.load(open(sp, encoding="utf-8"))
                    sc = s.get("scores", {})
                    judged = sc != {}
                except Exception:
                    pass
            rows.append({
                "tier": tier_label, "case": case,
                "model": model, "model_short": short_model(model),
                "rc": sc.get("root_cause", 0) if judged else None,
                "lf": sc.get("local_fix", 0) if judged else None,
                "gf": sc.get("global_fix", 0) if judged else None,
                "total": (sc.get("root_cause", 0) + sc.get("local_fix", 0)
                          + sc.get("global_fix", 0)) if judged else None,
                "judged": judged,
                "tools": len(tools),
                "resp_len": len(resp),
            })
    return rows


def main():
    FIGS.mkdir(parents=True, exist_ok=True)
    rows = parse()
    if not rows:
        print("no data")
        return
    print(f"parsed {len(rows)} runs")

    # Cells = real (tier, model) combos with at least one engaged run.
    # Sort by tier then model so T1 cells appear before T3.
    cells = sorted({(r["tier"], r["model_short"]) for r in rows})

    # ---------- Figure 1: total score per (tier, model) ----------
    fig, ax = plt.subplots(figsize=(9, 5))
    labels = [f"{t} · {m}" for t, m in cells]
    totals = []
    ns = []
    rc_ax = []
    lf_ax = []
    gf_ax = []
    for t, m in cells:
        d = [r for r in rows if r["tier"] == t and r["model_short"] == m
             and r["judged"]]
        ns.append(len(d))
        totals.append(sum(r["total"] for r in d))
        rc_ax.append(sum(r["rc"] for r in d))
        lf_ax.append(sum(r["lf"] for r in d))
        gf_ax.append(sum(r["gf"] for r in d))

    x = np.arange(len(cells))
    w = 0.27
    ax.bar(x - w, rc_ax, w, label="root_cause", color="#1f77b4")
    ax.bar(x,     lf_ax, w, label="local_fix",  color="#ff7f0e")
    ax.bar(x + w, gf_ax, w, label="global_fix", color="#2ca02c")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    for i, n in enumerate(ns):
        ax.text(i, max(rc_ax[i], lf_ax[i], gf_ax[i]) + 0.1,
                f"n={n}", ha="center", fontsize=9, color="#555")
    ax.set_ylabel("# correct (out of n)")
    ax.set_title("Yara T1 vs T3 — judge scores per axis (5 cases per cell)")
    ax.set_ylim(0, max([max(rc_ax+lf_ax+gf_ax+[1])+1, 5.5]))
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "01_total_scores.png", dpi=140)
    plt.close(fig)

    # ---------- Figure 2: per-case heatmap of total score ----------
    fig, ax = plt.subplots(figsize=(9, 5))
    grid = np.full((len(cells), len(CASES)), np.nan)
    judge_status = [["missing"] * len(CASES) for _ in cells]
    for ci, (t, m) in enumerate(cells):
        for kj, c in enumerate(CASES):
            r = next((r for r in rows
                      if r["tier"] == t and r["model_short"] == m and r["case"] == c), None)
            if r is None:
                judge_status[ci][kj] = "missing"  # credit-failure or never run
            elif r["judged"]:
                grid[ci, kj] = r["total"]
                judge_status[ci][kj] = "judged"
            else:
                judge_status[ci][kj] = "unjudged"  # ran but not yet scored
    im = ax.imshow(grid, cmap="RdYlGn", vmin=0, vmax=3, aspect="auto")
    ax.set_xticks(range(len(CASES)))
    ax.set_xticklabels(CASES)
    ax.set_yticks(range(len(cells)))
    ax.set_yticklabels(labels)
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            v = grid[i, j]
            st = judge_status[i][j]
            if st == "judged":
                txt = f"{int(v)}/3"
                color = "white" if v >= 2 else "black"
            elif st == "unjudged":
                txt = "ran\n(unjudged)"
                color = "black"
            else:
                txt = "no run\n(credits)"
                color = "#888"
            ax.text(j, i, txt, ha="center", va="center",
                    color=color, fontsize=8)
    ax.set_title("Yara per-case total score (real runs only;\n"
                 "credit-blocked cells marked)")
    cbar = plt.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cbar.set_label("total score (0–3)")
    fig.tight_layout()
    fig.savefig(FIGS / "02_heatmap.png", dpi=140)
    plt.close(fig)

    # ---------- Figure 3: tool-call counts by tier+model ----------
    fig, ax = plt.subplots(figsize=(9, 5))
    tool_means = []
    tool_max = []
    for t, m in cells:
        d = [r for r in rows if r["tier"] == t and r["model_short"] == m]
        tool_means.append(np.mean([r["tools"] for r in d]) if d else 0)
        tool_max.append(max((r["tools"] for r in d), default=0))
    x = np.arange(len(cells))
    bars = ax.bar(x, tool_means, color=["#1f77b4" if t == "T1" else "#d62728"
                                         for t, m in cells],
                  edgecolor="black")
    for b, m_, mx in zip(bars, tool_means, tool_max):
        ax.text(b.get_x() + b.get_width() / 2, m_ + 1,
                f"mean {m_:.1f}\nmax {mx}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("# tool calls (mean across 5 cases)")
    ax.set_title("Yara — tool-call volume per tier+model")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "03_tool_call_volume.png", dpi=140)
    plt.close(fig)

    # ---------- Figure 4: same model, T1 vs T3 contrast (sonnet, haiku) ----------
    fig, ax = plt.subplots(figsize=(8, 5))
    contrast_models = ["haiku-4.5", "sonnet-4.5"]
    bash_only = []
    gdb_only = []
    for m in contrast_models:
        t1 = next((c for c in cells if c == ("T1", m)), None)
        t3 = next((c for c in cells if c == ("T3", m)), None)
        bash_only.append(sum(r["total"] for r in rows
                             if r["tier"] == "T1" and r["model_short"] == m
                             and r["judged"]) if t1 else np.nan)
        gdb_only.append(sum(r["total"] for r in rows
                            if r["tier"] == "T3" and r["model_short"] == m
                            and r["judged"]) if t3 else np.nan)
    x = np.arange(len(contrast_models))
    w = 0.35
    ax.bar(x - w/2, bash_only, w, label="T1 (bash only)",   color="#1f77b4")
    ax.bar(x + w/2, gdb_only,  w, label="T3 (gdb-curated)", color="#d62728")
    ax.set_xticks(x)
    ax.set_xticklabels(contrast_models)
    ax.set_ylabel("total score (out of 15)")
    ax.set_title("Same model · two tool surfaces · yara-1..5\n"
                 "(bash agent ≫ ChatDBG-on-gdb on this case set)")
    for xi, v in zip(x - w/2, bash_only):
        if not np.isnan(v):
            ax.text(xi, v + 0.2, str(int(v)), ha="center")
    for xi, v in zip(x + w/2, gdb_only):
        if not np.isnan(v):
            ax.text(xi, v + 0.2, str(int(v)), ha="center")
    ax.set_ylim(0, 15.5)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "04_t1_vs_t3_same_model.png", dpi=140)
    plt.close(fig)

    # ---------- CSV ----------
    import csv
    with open(FIGS / "data.csv", "w", newline="", encoding="utf-8") as f:
        w_ = csv.writer(f)
        w_.writerow(["tier", "case", "model", "rc", "lf", "gf", "total",
                     "tools", "resp_len"])
        for r in rows:
            w_.writerow([r["tier"], r["case"], r["model_short"],
                         r["rc"], r["lf"], r["gf"], r["total"],
                         r["tools"], r["resp_len"]])

    print()
    print(f"{'cell':30s} {'judged_n':>9}  rc lf gf  total  mean tools")
    for (t, m), n, rc, lf, gf, tt, tm in zip(
            cells, ns, rc_ax, lf_ax, gf_ax, totals, tool_means):
        ran = sum(1 for r in rows if r["tier"] == t and r["model_short"] == m)
        print(f"  {t} · {m:24s} {n:>9}  {rc}/{n} {lf}/{n} {gf}/{n}  "
              f"{tt}/{3*n}  {tm:.1f}  (ran={ran})")
    print()
    for p in sorted(FIGS.glob("*")):
        print(" ", p)


if __name__ == "__main__":
    main()
