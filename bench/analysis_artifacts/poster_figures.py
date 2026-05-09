"""Poster figures for the COS484 ChatDBG project.

Generates a coordinated set of figures into bench/analysis_artifacts/figs/poster/.

Data sources:
  - SYNTH:  bench/results/external-native-ablation-20260504-merged-t3rerun
            (Crashbench + Juliet single-file bugs, 5 OR models × 4 tiers + 2 local Claude T4)
  - REAL:   bench/results/berry_consolidated
            (5 berry bugs × 6 OR models × 4 tiers; T4 = 3 anthropic models)

Each figure is a function `fig_<name>` that writes a PNG to OUT/.
Run via: python -m bench.analysis_artifacts.poster_figures
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SYNTH_DIR = ROOT / "bench/results/external-native-ablation-20260504-merged-t3rerun"
REAL_DIR = ROOT / "bench/results/berry_consolidated"
OUT = ROOT / "bench/analysis_artifacts/figs/poster"
OUT.mkdir(parents=True, exist_ok=True)

# ---------- model labels & ordering ----------

MODEL_LABEL = {
    # synthetic models
    "openrouter_anthropic_claude-sonnet-4.5": "Sonnet-4.5",
    "openrouter_google_gemini-3.1-flash-lite-preview": "Gemini-3.1-FL",
    "openrouter_nvidia_nemotron-3-nano-30b-a3b": "Nemotron-30B",
    "openrouter_openai_gpt-5.5": "GPT-5.5",
    "openrouter_qwen_qwen3-30b-a3b-instruct-2507": "Qwen-30B",
    # real-world berry-only models
    "openrouter_google_gemini-2.5-flash": "Gemini-2.5-FL",
    "openrouter_meta-llama_llama-3.1-8b-instruct": "Llama-8B",
    "openrouter_openai_gpt-4o": "GPT-4o",
    # T4
    "openrouter_anthropic_claude-haiku-4.5": "Haiku-4.5",
    "openrouter_anthropic_claude-sonnet-4.6": "Sonnet-4.6",
    "openrouter_anthropic_claude-opus-4.7": "Opus-4.7",
    "anthropic_claude-haiku-4.5": "Haiku-4.5",
    "anthropic_claude-sonnet-4.5": "Sonnet-4.5",
}

# Model order for unified plots (by approximate strength × availability)
UNIFIED_MODELS = [
    "GPT-5.5", "Sonnet-4.5", "Gemini-3.1-FL", "Gemini-2.5-FL", "GPT-4o",
    "Qwen-30B", "Nemotron-30B", "Llama-8B",
]

# Color palette — paired warm/cool for synth/real
C_SYN = "#2a9d8f"
C_REAL = "#e76f51"
TIER_COLORS = {1: "#264653", 2: "#2a9d8f", 3: "#e9c46a", 4: "#e76f51"}

mpl.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
})


# ---------- data loading ----------

def parse_run_dir(name: str) -> tuple[str, int, str] | None:
    """('crashbench-abo1', 3, 'GPT-5.5') from a run dirname."""
    parts = name.split("__")
    if len(parts) < 3:
        return None
    case_id = parts[0]
    tier_str = parts[1]
    model_id = parts[2]
    if not tier_str.startswith("tier"):
        return None
    try:
        tier = int(tier_str[4:])
    except ValueError:
        return None
    label = MODEL_LABEL.get(model_id, model_id.split("/")[-1])
    return case_id, tier, label


def load_runs(root: Path) -> list[dict]:
    """Load every run cell's result/score/collect into a flat list of dicts."""
    rows = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        meta = parse_run_dir(d.name)
        if meta is None:
            continue
        case_id, tier, model = meta
        try:
            r = json.loads((d / "result.json").read_text())
        except FileNotFoundError:
            continue
        s_path = d / "score.json"
        s = json.loads(s_path.read_text()) if s_path.exists() else {}
        c_path = d / "collect.json"
        c = json.loads(c_path.read_text()) if c_path.exists() else {}
        q = (c.get("queries") or [{}])[0]
        scores = s.get("scores", {})
        rows.append({
            "case_id": case_id,
            "tier": tier,
            "model": model,
            "model_id": d.name.split("__")[2],
            "status": r.get("status"),
            "elapsed_s": r.get("elapsed_s", 0),
            "rc": int(scores.get("root_cause", 0) or 0) if scores else None,
            "lf": int(scores.get("local_fix", 0) or 0) if scores else None,
            "gf": int(scores.get("global_fix", 0) or 0) if scores else None,
            "judged": s_path.exists(),
            "num_tool_calls": q.get("num_tool_calls", 0) or 0,
            "tool_frequency": q.get("tool_frequency", {}) or {},
            "tokens": (q.get("stats") or {}).get("tokens", 0) or 0,
            "prompt_tokens": (q.get("stats") or {}).get("prompt_tokens", 0) or 0,
            "completion_tokens": (q.get("stats") or {}).get("completion_tokens", 0) or 0,
        })
    return rows


# ---------- helpers ----------

def mean(values):
    vs = [v for v in values if v is not None]
    return float(np.mean(vs)) if vs else np.nan


def aggregate(rows, tiers, axis="rc"):
    """Return {model: mean_score} aggregating over case_id within tiers."""
    bag = defaultdict(list)
    for r in rows:
        if r["tier"] not in tiers:
            continue
        if not r["judged"]:
            continue
        bag[r["model"]].append(r[axis])
    return {m: mean(v) for m, v in bag.items()}


# ---------- figure 1: unified 12-col heatmap ----------

def fig_unified_heatmap(synth, real):
    """y=models, x=12 cols: (T1,T3) × (Synth,Real) × (RC,LF,GF)."""
    groups = [
        ("T1\nSynth", 1, synth),
        ("T1\nReal-world", 1, real),
        ("T3\nSynth", 3, synth),
        ("T3\nReal-world", 3, real),
    ]
    axes = [("rc", "RC"), ("lf", "LF"), ("gf", "GF")]
    cols = [(g[0], a[0], a[1], g[1], g[2]) for g in groups for a in axes]

    # determine model rows: include any model with data in any cell
    models_with_data = set()
    for _, axis_key, _, tier, src in cols:
        agg = aggregate(src, [tier], axis_key)
        for m, v in agg.items():
            if not np.isnan(v):
                models_with_data.add(m)
    model_rows = [m for m in UNIFIED_MODELS if m in models_with_data]
    extras = [m for m in models_with_data if m not in UNIFIED_MODELS]
    model_rows += sorted(extras)

    # Build matrix
    M = np.full((len(model_rows), len(cols)), np.nan)
    for j, (_, axis_key, _, tier, src) in enumerate(cols):
        agg = aggregate(src, [tier], axis_key)
        for i, m in enumerate(model_rows):
            v = agg.get(m, np.nan)
            M[i, j] = v

    fig, ax = plt.subplots(figsize=(13, 0.55 * len(model_rows) + 2.5))
    im = ax.imshow(M, cmap="YlGnBu", vmin=0, vmax=1, aspect="auto")

    # cell text
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            v = M[i, j]
            if np.isnan(v):
                ax.text(j, i, "—", ha="center", va="center", color="#888", fontsize=9)
            else:
                color = "white" if v > 0.55 else "#222"
                ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                        color=color, fontsize=9, fontweight="bold")

    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels([c[2] for c in cols], fontsize=9)
    ax.set_yticks(range(len(model_rows)))
    ax.set_yticklabels(model_rows, fontsize=10)

    # group separators / labels above
    for k in range(1, 4):
        ax.axvline(k * 3 - 0.5, color="white", linewidth=2.5)
    group_centers = [1, 4, 7, 10]
    for c, (gname, _, _) in zip(group_centers, groups):
        ax.text(c, -0.85, gname, ha="center", va="bottom",
                fontsize=11, fontweight="bold")

    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cb.set_label("Pass rate (mean over bugs)", fontsize=10)
    fig.suptitle("ChatDBG pass rate — Tier 1 (bash) vs Tier 3 (gdb) on synthetic vs real-world bugs",
                 fontsize=14, fontweight="bold", y=1.02)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    p = OUT / "01_unified_heatmap.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {p}")


# ---------- figure 2/3: full per-bug heatmaps ----------

def fig_full_heatmap(rows, title, fname):
    """Per-bug × per-model heatmap with tier subpanels (RC + LF + GF averaged)."""
    cases = sorted({r["case_id"] for r in rows})
    models = []
    seen = set()
    for r in rows:
        if r["model"] not in seen:
            seen.add(r["model"])
            models.append(r["model"])
    # reorder by UNIFIED_MODELS
    models = [m for m in UNIFIED_MODELS if m in seen] + \
             sorted(m for m in seen if m not in UNIFIED_MODELS)

    tiers = sorted({r["tier"] for r in rows if r["judged"]})
    fig, axes = plt.subplots(1, len(tiers), figsize=(4 * len(tiers) + 1, 0.45 * len(models) + 2),
                              sharey=True)
    if len(tiers) == 1:
        axes = [axes]

    for ax, tier in zip(axes, tiers):
        M = np.full((len(models), len(cases)), np.nan)
        for r in rows:
            if r["tier"] != tier or not r["judged"]:
                continue
            i = models.index(r["model"]) if r["model"] in models else None
            j = cases.index(r["case_id"]) if r["case_id"] in cases else None
            if i is None or j is None:
                continue
            avg = mean([r["rc"], r["lf"], r["gf"]])
            M[i, j] = avg
        im = ax.imshow(M, cmap="YlGnBu", vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(len(cases)))
        ax.set_xticklabels(cases, rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(len(models)))
        ax.set_yticklabels(models, fontsize=9)
        ax.set_title(f"Tier {tier}", fontsize=12)
        # cell text
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                v = M[i, j]
                if not np.isnan(v):
                    color = "white" if v > 0.55 else "#222"
                    ax.text(j, i, f"{v:.1f}" if v in (0.0, 1.0) else f"{v:.2f}",
                            ha="center", va="center", color=color, fontsize=7)

    fig.suptitle(title, fontsize=13, fontweight="bold", y=1.02)
    cb = fig.colorbar(im, ax=axes[-1], fraction=0.04, pad=0.02)
    cb.set_label("Mean pass (RC+LF+GF)/3", fontsize=9)
    fig.tight_layout()
    p = OUT / fname
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {p}")


# ---------- figure 4: gdb tool-call breakdown ----------

GDB_ALIASES = {
    "bt": "backtrace", "p": "print", "n": "next", "s": "step",
    "c": "continue", "b": "break", "r": "run", "where": "backtrace",
    "list": "list", "code": "code", "info": "info",
    "frame": "frame", "f": "frame",
    "watch": "watch", "until": "until", "finish": "finish",
}

def fig_gdb_breakdown(rows, title, fname, top_k=8):
    """Stacked bar: per-model breakdown of T3 gdb tool-frequency."""
    t3 = [r for r in rows if r["tier"] == 3 and r["status"] == "ok"]
    if not t3:
        print(f"  skip {fname} — no T3 ok cells")
        return

    # aggregate per model
    per_model = defaultdict(lambda: defaultdict(int))
    for r in t3:
        for k, v in r["tool_frequency"].items():
            cmd = GDB_ALIASES.get(k.lower(), k.lower())
            per_model[r["model"]][cmd] += int(v)

    # pick top-k commands by total frequency
    totals = defaultdict(int)
    for m, freqs in per_model.items():
        for cmd, v in freqs.items():
            totals[cmd] += v
    top_cmds = [c for c, _ in sorted(totals.items(), key=lambda x: -x[1])[:top_k]]

    models = sorted(per_model.keys(), key=lambda m: UNIFIED_MODELS.index(m)
                     if m in UNIFIED_MODELS else 99)
    M = np.zeros((len(models), len(top_cmds) + 1))
    for i, m in enumerate(models):
        freqs = per_model[m]
        total = sum(freqs.values())
        for j, cmd in enumerate(top_cmds):
            M[i, j] = freqs.get(cmd, 0) / max(total, 1)
        other = sum(v for k, v in freqs.items() if k not in top_cmds)
        M[i, -1] = other / max(total, 1)

    cmd_labels = top_cmds + ["other"]
    cmap = plt.get_cmap("tab20")
    colors = [cmap(i / max(len(cmd_labels) - 1, 1)) for i in range(len(cmd_labels))]

    fig, ax = plt.subplots(figsize=(8, 0.5 * len(models) + 1.5))
    bottom = np.zeros(len(models))
    for j, cmd in enumerate(cmd_labels):
        bars = ax.barh(range(len(models)), M[:, j], left=bottom, color=colors[j],
                       label=cmd, edgecolor="white", linewidth=0.5)
        bottom += M[:, j]

    ax.set_yticks(range(len(models)))
    ax.set_yticklabels(models)
    ax.set_xlabel("Fraction of T3 gdb tool calls")
    ax.set_xlim(0, 1)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8, frameon=False)
    ax.set_title(title)

    # n-cells label per row
    n_per_model = defaultdict(int)
    for r in t3:
        n_per_model[r["model"]] += 1
    for i, m in enumerate(models):
        ax.text(1.01, i, f"n={n_per_model[m]}", va="center", fontsize=8, color="#666")

    fig.tight_layout()
    p = OUT / fname
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {p}")


# ---------- figure 5: tool calls per model ----------

def fig_tool_calls(rows, title, fname):
    """Grouped bar: mean tool calls per model, per tier."""
    tiers = [1, 2, 3]
    models_set = set()
    by = defaultdict(list)
    for r in rows:
        if r["tier"] not in tiers:
            continue
        if r["status"] != "ok":
            continue
        models_set.add(r["model"])
        by[(r["tier"], r["model"])].append(r["num_tool_calls"])

    models = [m for m in UNIFIED_MODELS if m in models_set]
    extras = sorted(models_set - set(models))
    models += extras

    fig, ax = plt.subplots(figsize=(max(8, 0.85 * len(models) + 2), 4.5))
    x = np.arange(len(models))
    width = 0.27
    for k, t in enumerate(tiers):
        ys = [mean(by.get((t, m), [])) for m in models]
        ax.bar(x + (k - 1) * width, ys, width, label=f"T{t}",
               color=TIER_COLORS[t], edgecolor="white", linewidth=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=30, ha="right")
    ax.set_ylabel("Mean tool calls per cell")
    ax.set_title(title)
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25, linestyle="--")
    fig.tight_layout()
    p = OUT / fname
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {p}")


# ---------- figure 6: tokens per model ----------

def fig_tokens(rows, title, fname):
    """Grouped bar: mean total tokens per model, per tier."""
    tiers = [1, 2, 3]
    models_set = set()
    by = defaultdict(list)
    for r in rows:
        if r["tier"] not in tiers:
            continue
        if r["status"] != "ok":
            continue
        if r["tokens"] <= 0:
            continue
        models_set.add(r["model"])
        by[(r["tier"], r["model"])].append(r["tokens"])

    models = [m for m in UNIFIED_MODELS if m in models_set]
    extras = sorted(models_set - set(models))
    models += extras

    fig, ax = plt.subplots(figsize=(max(8, 0.85 * len(models) + 2), 4.5))
    x = np.arange(len(models))
    width = 0.27
    for k, t in enumerate(tiers):
        ys = [mean(by.get((t, m), [])) / 1000.0 for m in models]
        ax.bar(x + (k - 1) * width, ys, width, label=f"T{t}",
               color=TIER_COLORS[t], edgecolor="white", linewidth=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=30, ha="right")
    ax.set_ylabel("Mean total tokens per cell (×1000)")
    ax.set_title(title)
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25, linestyle="--")
    fig.tight_layout()
    p = OUT / fname
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {p}")


# ---------- figure 7: berry T1-T4 main ----------

def fig_berry_main(rows):
    """Headline figure: berry across T1-T4 by model.

    Two panels: mean RC across bugs by tier (lines + markers per model),
    and per-axis grouped bar at T3 vs T4."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # panel 1: tier × model RC
    tiers = sorted({r["tier"] for r in rows if r["judged"]})
    by = defaultdict(list)
    for r in rows:
        if not r["judged"]: continue
        by[(r["tier"], r["model"])].append(r["rc"])
    models = sorted({r["model"] for r in rows if r["judged"]},
                    key=lambda m: UNIFIED_MODELS.index(m) if m in UNIFIED_MODELS else 99)
    cmap = plt.get_cmap("tab10")
    for i, m in enumerate(models):
        ys = [mean(by.get((t, m), [])) for t in tiers]
        ax1.plot(tiers, ys, marker="o", linewidth=2, markersize=8,
                 color=cmap(i / 10), label=m)
    ax1.set_xticks(tiers)
    ax1.set_xticklabels([f"T{t}" for t in tiers])
    ax1.set_ylim(-0.05, 1.05)
    ax1.set_ylabel("Mean root_cause score (over 5 bugs)")
    ax1.set_title("Berry: Root-cause pass rate by tier")
    ax1.grid(axis="y", alpha=0.25, linestyle="--")
    ax1.legend(frameon=False, fontsize=8, loc="upper left", ncol=2)

    # panel 2: per-axis at T3 vs T4 (grouped)
    axes = ["rc", "lf", "gf"]
    axis_labels = ["Root cause", "Local fix", "Global fix"]
    t3_rows = [r for r in rows if r["tier"] == 3 and r["judged"]]
    t4_rows = [r for r in rows if r["tier"] == 4 and r["judged"]]

    def axis_means(rs):
        return [mean([r[a] for r in rs]) for a in axes]

    t3_m = axis_means(t3_rows)
    t4_m = axis_means(t4_rows)
    x = np.arange(len(axes))
    width = 0.36
    ax2.bar(x - width/2, t3_m, width, color="#e9c46a", label=f"T3 (gdb only, n={len(t3_rows)})",
            edgecolor="white", linewidth=0.5)
    ax2.bar(x + width/2, t4_m, width, color="#e76f51", label=f"T4 (Claude Code, n={len(t4_rows)})",
            edgecolor="white", linewidth=0.5)
    for xi, vt3, vt4 in zip(x, t3_m, t4_m):
        ax2.text(xi - width/2, vt3 + 0.02, f"{vt3:.2f}", ha="center", fontsize=9)
        ax2.text(xi + width/2, vt4 + 0.02, f"{vt4:.2f}", ha="center", fontsize=9)
    ax2.set_xticks(x)
    ax2.set_xticklabels(axis_labels)
    ax2.set_ylim(0, 1.1)
    ax2.set_ylabel("Mean pass rate")
    ax2.set_title("Berry: T3 (ChatDBG) vs T4 (Claude Code), per axis")
    ax2.legend(frameon=False, loc="upper right")
    ax2.grid(axis="y", alpha=0.25, linestyle="--")

    fig.suptitle("Berry — climbing the harness ladder (T1 → T4)",
                 fontsize=15, fontweight="bold", y=1.02)
    fig.tight_layout()
    p = OUT / "07_berry_main.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {p}")


# ---------- entry point ----------

def main():
    print(f"Loading {SYNTH_DIR.name}...")
    synth = load_runs(SYNTH_DIR)
    print(f"  {len(synth)} synthetic cells")
    print(f"Loading {REAL_DIR.name}...")
    real = load_runs(REAL_DIR)
    print(f"  {len(real)} real-world cells")

    print("\nGenerating figures into", OUT)
    fig_unified_heatmap(synth, real)
    fig_full_heatmap(synth, "Synthetic bugs — per-bug pass rate by model and tier",
                     "02_full_heatmap_synth.png")
    fig_full_heatmap(real, "Real-world bugs (berry) — per-bug pass rate by model and tier",
                     "03_full_heatmap_real.png")
    fig_gdb_breakdown(synth, "T3 gdb command distribution — synthetic",
                      "04a_gdb_breakdown_synth.png")
    fig_gdb_breakdown(real, "T3 gdb command distribution — real-world (berry)",
                      "04b_gdb_breakdown_real.png")
    fig_tool_calls(synth, "Tool calls per model — synthetic",
                   "05a_tool_calls_synth.png")
    fig_tool_calls(real, "Tool calls per model — real-world (berry)",
                   "05b_tool_calls_real.png")
    fig_tokens(synth, "Tokens per model — synthetic",
               "06a_tokens_synth.png")
    fig_tokens(real, "Tokens per model — real-world (berry)",
               "06b_tokens_real.png")
    fig_berry_main(real)

    print("\nDone.")


if __name__ == "__main__":
    main()
