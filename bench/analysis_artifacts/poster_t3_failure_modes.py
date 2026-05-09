"""T3 failure-mode diagnostic figure for berry.

Classifies each of the 30 (model × bug) T3 cells into one of:
  - quick_bail: model issued <10 tool calls and committed to a wrong answer
  - deep_wrong: explored deeply (>=10 calls) but synthesized incorrectly
  - deep_correct: explored deeply and got root_cause = 1
  - timeout_lost: hit the 600s wall (artifacts not flushed by orchestrator)
  - no_collect: ChatDBG / orchestrator died before writing collect.json

Two panels:
  Left:  stacked bar per model — failure-mode distribution (counts)
  Right: scatter (n_tool_calls × elapsed_s) colored by mode, with the
         "deliberation cliff" annotation showing where success lives.
"""
from __future__ import annotations
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "bench/results/berry_consolidated"
OUT = ROOT / "bench/analysis_artifacts/figs/poster/09_t3_failure_modes.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

MODEL_LABEL = {
    "openrouter_openai_gpt-5.5": "GPT-5.5",
    "openrouter_openai_gpt-4o": "GPT-4o",
    "openrouter_google_gemini-2.5-flash": "Gemini-2.5-FL",
    "openrouter_meta-llama_llama-3.1-8b-instruct": "Llama-8B",
    "openrouter_nvidia_nemotron-3-nano-30b-a3b": "Nemotron-30B",
    "openrouter_qwen_qwen3-30b-a3b-instruct-2507": "Qwen-30B",
}

MODE_COLOR = {
    "quick_bail":   "#bb3355",   # red — gave up
    "deep_wrong":   "#ddaa33",   # amber — wandered
    "timeout_lost": "#aa44aa",   # purple — wall hit, no artifacts
    "no_collect":   "#777777",   # grey — orchestrator died
    "deep_correct": "#117733",   # green — success
}
MODE_LABEL = {
    "quick_bail":   "Quick bail (<10 calls, wrong)",
    "deep_wrong":   "Deep, wrong synthesis",
    "timeout_lost": "Timeout (600s, no artifacts)",
    "no_collect":   "Orchestrator crash",
    "deep_correct": "Deep + correct (RC=1)",
}
MODE_ORDER = ["quick_bail", "deep_wrong", "timeout_lost", "no_collect", "deep_correct"]

mpl.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
})


def classify(row):
    if row["status"] == "timeout":
        return "timeout_lost"
    if row["status"] == "no_collect":
        return "no_collect"
    n = row["n_tool_calls_eff"]
    if row["rc"] == 1:
        return "deep_correct"
    if n < 10:
        return "quick_bail"
    return "deep_wrong"


def load():
    rows = []
    for d in sorted(DATA.iterdir()):
        if not d.is_dir():
            continue
        parts = d.name.split("__")
        if len(parts) < 3 or not parts[1].startswith("tier"):
            continue
        if int(parts[1][4:]) != 3:
            continue
        bug, model = parts[0], parts[2]
        r = json.loads((d / "result.json").read_text())
        s = json.loads((d / "score.json").read_text()) if (d/"score.json").exists() else {}
        cj = d / "collect.json"
        c = json.loads(cj.read_text()) if cj.exists() else {}
        q = (c.get("queries") or [{}])[0]
        # Effective tool-call count: prefer num_tool_calls; fallback to sum(tool_frequency)
        n_tools = q.get("num_tool_calls") or 0
        if n_tools == 0 and q.get("tool_frequency"):
            n_tools = sum(q["tool_frequency"].values())
        rows.append({
            "bug": bug,
            "model": MODEL_LABEL.get(model, model.split("/")[-1]),
            "model_id": model,
            "status": r.get("status"),
            "elapsed_s": r.get("elapsed_s") or 0,
            "rc": (s.get("scores") or {}).get("root_cause"),
            "n_tool_calls": q.get("num_tool_calls", 0) or 0,
            "n_tool_calls_eff": n_tools,
        })
    for r in rows:
        r["mode"] = classify(r)
    return rows


def main():
    rows = load()
    models = list(MODEL_LABEL.values())

    # ===== panel A: stacked bar per model =====
    counts = {m: {mode: 0 for mode in MODE_ORDER} for m in models}
    for r in rows:
        counts[r["model"]][r["mode"]] += 1

    fig = plt.figure(figsize=(15, 6.5))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.05, 1.0], wspace=0.30)
    axA = fig.add_subplot(gs[0])
    axB = fig.add_subplot(gs[1])

    y = np.arange(len(models))
    left = np.zeros(len(models))
    for mode in MODE_ORDER:
        widths = np.array([counts[m][mode] for m in models], dtype=float)
        bars = axA.barh(y, widths, left=left, color=MODE_COLOR[mode],
                         edgecolor="white", linewidth=0.7,
                         label=MODE_LABEL[mode])
        # numeric annotations only for non-zero
        for i, w in enumerate(widths):
            if w > 0:
                axA.text(left[i] + w/2, y[i], f"{int(w)}",
                          ha="center", va="center",
                          color="white" if mode != "deep_correct" else "white",
                          fontsize=9, fontweight="bold")
        left += widths

    axA.set_yticks(y)
    axA.set_yticklabels(models, fontsize=10)
    axA.set_xlabel("Number of T3 berry cells (out of 5)", fontsize=11)
    axA.set_xlim(0, 5)
    axA.set_xticks(range(6))
    axA.set_title("T3 (gdb-only) failure modes per model — 30 cells",
                   fontsize=12, fontweight="bold")
    # invert so strongest model (GPT-5.5) is on top
    axA.invert_yaxis()

    # ===== panel B: scatter n_tool_calls vs elapsed_s, colored by mode =====
    for mode in MODE_ORDER:
        xs = [r["n_tool_calls_eff"] for r in rows if r["mode"] == mode]
        ts = [r["elapsed_s"] for r in rows if r["mode"] == mode]
        marker = "*" if mode == "deep_correct" else "o"
        size = 280 if mode == "deep_correct" else 80
        axB.scatter(xs, ts, c=MODE_COLOR[mode], s=size, marker=marker,
                     edgecolor="white", linewidth=1.0, alpha=0.9,
                     label=MODE_LABEL[mode], zorder=3 if mode == "deep_correct" else 2)

    axB.set_xscale("symlog", linthresh=1)
    axB.set_xlabel("Tool calls in T3 session", fontsize=11)
    axB.set_ylabel("Elapsed time (s)", fontsize=11)
    axB.set_xlim(-0.5, 350)
    axB.set_ylim(0, 660)
    axB.axhline(600, color="#aa44aa", linestyle="--", linewidth=1.2, alpha=0.6)
    axB.text(1.5, 580, "600 s wall: artifacts lost", color="#aa44aa", fontsize=8.5, va="top")
    axB.axvline(10, color="#bb3355", linestyle="--", linewidth=1.2, alpha=0.6)
    axB.text(11.5, 30, "<10 calls = quick bail", color="#bb3355", fontsize=8.5, va="bottom")

    # annotate the one success
    success = [r for r in rows if r["mode"] == "deep_correct"]
    if success:
        s = success[0]
        axB.annotate(f"only success:\n{s['model']} on {s['bug']}\n({s['n_tool_calls_eff']} calls, {int(s['elapsed_s'])}s)",
                       xy=(s["n_tool_calls_eff"], s["elapsed_s"]),
                       xytext=(60, 530), fontsize=8.5, color="#117733",
                       arrowprops=dict(arrowstyle="->", color="#117733", linewidth=1.2),
                       ha="left", va="top",
                       bbox=dict(facecolor="#eef7ee", edgecolor="#117733",
                                 boxstyle="round,pad=0.3"))
    axB.set_title("Where do T3 cells land? Tool calls × wall time",
                   fontsize=12, fontweight="bold")
    axB.grid(alpha=0.25, linestyle="--")
    axB.legend(loc="upper left", bbox_to_anchor=(0.0, -0.13), ncol=3,
                frameon=False, fontsize=8.5)

    fig.suptitle("Why T3 fails on Berry: it isn't gdb — it's the harness around gdb",
                 fontsize=14, fontweight="bold", y=1.005)
    fig.tight_layout(rect=[0, 0.03, 1, 0.97])
    fig.savefig(OUT, dpi=200, bbox_inches="tight")
    print(f"wrote {OUT}")

    # also dump the failure-mode table
    csv = OUT.with_suffix(".csv")
    with open(csv, "w") as f:
        f.write("bug,model,status,elapsed_s,n_tool_calls,rc,mode\n")
        for r in rows:
            f.write(f"{r['bug']},{r['model']},{r['status']},{r['elapsed_s']:.1f},"
                    f"{r['n_tool_calls_eff']},{r['rc']},{r['mode']}\n")
    print(f"wrote {csv}")


if __name__ == "__main__":
    main()
