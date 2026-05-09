"""Reproduce the "Real-World / Multi-File Bugs (20 cases)" T1+T3 heatmap.

8 models × 20 cases. For each (model, case) cell we render two stacked
sub-rows: T1 (bash only) on top, T3 (ChatDBG-on-gdb) on the bottom.
Score is total = root_cause + local_fix + global_fix in [0..3].

Data sources (post-pull):
  bench/results/berry_consolidated/                              berry-{1..5}
  bench/results/external-native-ablation-20260504-merged-t3rerun/  cb-abo*, j-*
  bench/results/bugbench-t1/, bugbench-t2/, bugbench-t3/        bugbench cases
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "bench/results"
OUT = ROOT / "bench/analysis_artifacts/figs/poster/10_realworld_20case_T1T3.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

# --- canonical case-id and model-id mapping ---

CASES = [
    "bc-heap-overflow",
    "berry-1", "berry-2", "berry-3", "berry-4", "berry-5",
    "cb-abo1", "cb-abo2", "cb-abo3", "cb-abo5", "cb-abo7", "cb-abo8",
    "j-121", "j-122", "j-126", "j-415", "j-416",
    "man-overflow", "ncompress-overflow", "polymorph-overflow",
]

def norm_case(case_id: str) -> str:
    if case_id.startswith("crashbench-abo"):
        return "cb-" + case_id.split("crashbench-")[1]
    if case_id.startswith("juliet-cwe"):
        return "j-" + case_id.split("juliet-cwe")[1].split("-")[0]
    return case_id

MODEL_LABEL = {
    "openrouter_openai_gpt-5.5":                          "GPT-5.5",
    "openrouter_openai_gpt-4o":                           "GPT-4o",
    "openrouter_anthropic_claude-sonnet-4.5":             "Sonnet-4.5",
    "openrouter_anthropic_claude-sonnet-4-5-20250514":    "Sonnet-4.5",
    "openrouter_google_gemini-2.5-flash":                 "Gemini-FL",
    "openrouter_google_gemini-3.1-flash-lite-preview":    "Gemini-FL-Lite",
    "openrouter_qwen_qwen3-30b-a3b-instruct-2507":        "Qwen-30B",
    "openrouter_nvidia_nemotron-3-nano-30b-a3b":          "Nemotron-30B",
    "openrouter_meta-llama_llama-3.1-8b-instruct":        "Llama-8B",
}

MODEL_ROWS = [
    "GPT-5.5", "GPT-4o", "Sonnet-4.5", "Gemini-FL", "Gemini-FL-Lite",
    "Qwen-30B", "Nemotron-30B", "Llama-8B",
]


# --- collect best-per-cell scores across the whole repo ---

def load_scores() -> dict:
    """Return scores[(case, model_label)][tier] = total int 0..3."""
    out: dict[tuple, dict[int, int]] = defaultdict(dict)
    for sweep_dir in RESULTS.iterdir():
        if not sweep_dir.is_dir():
            continue
        for cell in sweep_dir.iterdir():
            if not cell.is_dir():
                continue
            parts = cell.name.split("__")
            if len(parts) < 3 or not parts[1].startswith("tier"):
                continue
            try:
                tier = int(parts[1][4:])
            except ValueError:
                continue
            if tier not in (1, 3):
                continue
            case = norm_case(parts[0])
            if case not in CASES:
                continue
            model_id = parts[2]
            label = MODEL_LABEL.get(model_id)
            if label is None:
                continue
            rj = cell / "result.json"
            sj = cell / "score.json"
            if not (rj.exists() and sj.exists()):
                continue
            try:
                r = json.loads(rj.read_text())
                if r.get("status") != "ok":
                    continue
                s = json.loads(sj.read_text()).get("scores", {})
            except Exception:
                continue
            total = (int(s.get("root_cause") or 0)
                     + int(s.get("local_fix") or 0)
                     + int(s.get("global_fix") or 0))
            existing = out[(case, label)].get(tier)
            # keep the strongest scoring run if multiple sweeps cover same cell
            if existing is None or total > existing:
                out[(case, label)][tier] = total
    return out


# --- render ---

def main():
    scores = load_scores()

    n_models = len(MODEL_ROWS)
    n_cases = len(CASES)
    # 2 sub-rows per model
    M = np.full((n_models * 2, n_cases), np.nan)
    for i, model in enumerate(MODEL_ROWS):
        for j, case in enumerate(CASES):
            cell = scores.get((case, model), {})
            t1 = cell.get(1)
            t3 = cell.get(3)
            if t1 is not None:
                M[2 * i, j] = t1
            if t3 is not None:
                M[2 * i + 1, j] = t3

    cmap = plt.get_cmap("RdYlGn").copy()
    cmap.set_bad("#eaeaea")
    masked = np.ma.masked_invalid(M)

    fig, ax = plt.subplots(figsize=(15, 7.5))
    im = ax.imshow(masked, cmap=cmap, vmin=0, vmax=3, aspect="auto",
                   interpolation="nearest")

    # Numeric annotations + "—" for masked
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            v = M[i, j]
            if np.isnan(v):
                ax.text(j, i, "—", ha="center", va="center",
                        color="#888", fontsize=9)
            else:
                color = "white" if (v <= 0.6 or v >= 2.4) else "#222"
                ax.text(j, i, f"{int(v)}", ha="center", va="center",
                        color=color, fontsize=9, fontweight="bold")

    # Y axis: one label per model, centered between its 2 sub-rows
    ax.set_yticks([2 * i + 0.5 for i in range(n_models)])
    ax.set_yticklabels(MODEL_ROWS, fontsize=11)

    # Thin grid lines between models
    for i in range(1, n_models):
        ax.axhline(2 * i - 0.5, color="white", linewidth=2.5)

    # X axis
    ax.set_xticks(range(n_cases))
    ax.set_xticklabels(CASES, rotation=45, ha="right", fontsize=9)
    ax.set_xlim(-0.5, n_cases - 0.5)
    ax.set_ylim(2 * n_models - 0.5, -0.5)  # invert: top model at top

    # Title and colorbar
    ax.set_title(f"Real-World / Multi-File Bugs ({n_cases} cases)",
                 fontsize=14, fontweight="bold", pad=10)
    cb = fig.colorbar(im, ax=ax, fraction=0.022, pad=0.015)
    cb.set_label("Total Score (0–3)", fontsize=10)

    # Legend: T1 top / T3 bottom
    legend_handles = [
        mpatches.Patch(facecolor="white", edgecolor="#444",
                       linewidth=1.0, label="T1: bash (top)"),
        mpatches.Patch(facecolor="#dddddd", edgecolor="#444",
                       linewidth=1.0, label="T3: ChatDBG (bottom)"),
    ]
    ax.legend(handles=legend_handles, loc="upper right",
              bbox_to_anchor=(1.15, 1.10), frameon=True,
              edgecolor="#888", framealpha=1.0, fontsize=9)

    fig.tight_layout()
    fig.savefig(OUT, dpi=200, bbox_inches="tight")
    print(f"wrote {OUT}")

    # Also dump an audit CSV alongside
    csv = OUT.with_suffix(".csv")
    with csv.open("w") as f:
        f.write("case,model,tier1,tier3\n")
        for case in CASES:
            for model in MODEL_ROWS:
                cell = scores.get((case, model), {})
                t1 = cell.get(1, "")
                t3 = cell.get(3, "")
                f.write(f"{case},{model},{t1},{t3}\n")
    print(f"wrote {csv}")


if __name__ == "__main__":
    main()
