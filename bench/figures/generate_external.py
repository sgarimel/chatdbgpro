#!/usr/bin/env python3
"""External-native figure generator.

Companion to bench/figures/generate_all.py. Produces the same figure
shapes (heatmap_t{1,2,3}, cross_tier_bars, per_axis_bars, tool_cmd_*)
for the merged external-native ablation suite at
bench/results/external-native-ablation-20260504-merged-t3rerun/.

Output filenames: external_*.png — chosen so they sort alongside
synth_*.png and bugbench_*.png in bench/figures/.

Usage:
    python bench/figures/generate_external.py
"""
from __future__ import annotations
import sys
from pathlib import Path

# Reuse helpers from generate_all.py
THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS))
from generate_all import (  # type: ignore
    load_scored_runs,
    _heatmap, _cross_tier_bars, _per_axis_bars,
    _tool_cmd_vs_score, _tool_cmd_by_model, _tool_cmd_win_vs_fail,
    TIER_LABELS, FIGS,
)

ROOT = THIS.parent  # bench/
EXT_DIR = ROOT / "results" / "external-native-ablation-20260504-merged-t3rerun"

# Same short names as generate_all.MODEL_MAP, restricted to the 5 models
# actually exercised on the external-native suite (T1-T3). T4 is haiku +
# sonnet via Claude Code, but those rows have no collect.json/score.json
# (status=missing_dep) so they don't surface in load_scored_runs.
EXT_MODEL_ORDER = ["GPT-5.5", "Sonnet-4.5", "Gemini-FL", "Qwen-30B", "Nemotron-30B"]


def main() -> int:
    if not EXT_DIR.exists():
        print(f"ERROR: external suite not found: {EXT_DIR}", file=sys.stderr)
        return 1

    print(f"\n── External-Native Figures ──")
    data = load_scored_runs(EXT_DIR)
    n_by_tier = {t: sum(1 for d in data if d["tier"] == t) for t in (1, 2, 3)}
    print(f"  Loaded {len(data)} ok runs from {EXT_DIR.name}")
    print(f"  Per tier: T1={n_by_tier[1]}, T2={n_by_tier[2]}, T3={n_by_tier[3]}")

    # Heatmaps T1, T2, T3
    for tier in (1, 2, 3):
        _heatmap(
            data, EXT_MODEL_ORDER, tier,
            f"External-Native — Total Score (0–3) — {TIER_LABELS[tier]}",
            f"external_heatmap_t{tier}.png",
        )

    # Cross-tier bars
    _cross_tier_bars(
        data, EXT_MODEL_ORDER,
        "External-Native: Mean Score by Model × Tier (11 multifile real-world bugs)",
        "external_cross_tier_bars.png",
    )

    # Per-axis bars
    _per_axis_bars(
        data, EXT_MODEL_ORDER,
        "External-Native: Per-Axis Scores by Model × Tier",
        "external_per_axis_bars.png",
    )

    # Tool-command analysis on T3 only
    t3 = [d for d in data if d["tier"] == 3]
    if t3 and any(d["tool_calls"] > 0 for d in t3):
        _tool_cmd_vs_score(t3, "External-Native T3 (unfenced+cmw)",
                           "external_tool_cmd_vs_score.png")
        _tool_cmd_by_model(t3, EXT_MODEL_ORDER, "External-Native T3 (unfenced+cmw)",
                           "external_tool_cmd_by_model.png")
        _tool_cmd_win_vs_fail(t3, "External-Native T3 (unfenced+cmw)",
                              "external_tool_cmd_win_vs_fail.png")

    print(f"\nAll figures saved to: {FIGS}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
