"""Stronger heuristic: extract the buggy function name from each
synthetic source file and check for direct mention. Also extract
1-2 lexical 'fix-anchor' tokens per case from the local_fix patch
diff and check those. This is still not a judge, but catches the
'gave correct code without saying the line' false negatives.
"""
from __future__ import annotations
import json, re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT  = ROOT / "bench" / "analysis_artifacts"

# Per-case fix-anchors: tokens whose presence in the response is strong
# evidence that the model identified the bug. Curated from case.yaml +
# source inspection.
ANCHORS = {
    "heap-overflow-csv":      ["n + 1", "n+1", "malloc(n + 1", "malloc(n+1"],
    "off-by-one-crc":         ["<=", "i < ", "len - 1", "off-by-one"],
    "double-free-errpath":    ["NULL", "= NULL", "double free", "set", "after free"],
    "uaf-linked-list":        ["use-after-free", "after free", "next", "freed"],
    "intoverflow-alloc":      ["overflow", "size_t", "SIZE_MAX", "n * sizeof"],
    "null-deref-env":         ["getenv", "NULL", "null check"],
    "signed-unsigned-loop":   ["unsigned", "signed", "underflow", "i--"],
    "uninit-stack-accumulator":["uninitialized", "= 0", "init"],
}

BUGGY_FUNCS = {
    "heap-overflow-csv": "first_field",
    "off-by-one-crc":    "crc",
    "double-free-errpath":"cleanup",
    "uaf-linked-list":   None,
    "intoverflow-alloc": None,
    "null-deref-env":    None,
    "signed-unsigned-loop": None,
    "uninit-stack-accumulator": None,
}

df = pd.read_csv(OUT / "all_runs.csv")

def score_response(case_id: str, run_dir: str) -> dict:
    rd = Path(run_dir)
    cj = rd / "collect.json"
    if not cj.exists():
        return {"strong_hit": False, "anchors_hit": 0, "func_hit": False,
                "line_or_anchor": False}
    try:
        q = json.loads(cj.read_text())["queries"][0]
    except Exception:
        return {"strong_hit": False, "anchors_hit": 0, "func_hit": False,
                "line_or_anchor": False}
    resp = q.get("response","") or ""
    anchors = ANCHORS.get(case_id, [])
    n_anchor = sum(1 for a in anchors if a.lower() in resp.lower())
    fn = BUGGY_FUNCS.get(case_id)
    func_hit = bool(fn) and (fn in resp)
    return {
        "strong_hit": n_anchor >= 2 or (func_hit and n_anchor >= 1),
        "anchors_hit": n_anchor,
        "func_hit": func_hit,
    }

extra = df.apply(lambda r: pd.Series(score_response(r["case_id"], r["run_dir"])), axis=1)
df = pd.concat([df, extra], axis=1)
df["line_or_anchor"] = df["line_mentioned"].fillna(False) | df["strong_hit"]
df.to_csv(OUT / "all_runs_scored.csv", index=False)

# Synthetic rollup
syn = df[(df.suite=="full-synthetic-v1-stripped") & df.valid_target].copy()

def short_model(m):
    if "nemotron-3-nano-30b" in m: return "nemotron-30B"
    if "qwen3-30b" in m: return "qwen-30B"
    return m
syn["model_s"] = syn["model"].map(short_model)

print("=== Per-case correctness on synthetic (stronger heuristic) ===")
print(syn.pivot_table(index="case_id", columns="model_s",
        values=["strong_hit","line_or_anchor","n_tool_calls"], aggfunc="first").to_string())

# Hard cases: neither model has line_or_anchor
hard = (syn.groupby("case_id")
            .agg(n=("run_id","count"),
                 hit_rate=("line_or_anchor","mean"),
                 anchor_hits=("anchors_hit","mean"),
                 mean_tools=("n_tool_calls","mean"),
                 mean_resp=("resp_len","mean"))
            .sort_values("hit_rate"))
hard.to_csv(OUT/"hard_cases_strong.csv")
print("\n=== Hard cases (sorted by strong-hit rate) ===")
print(hard.to_string())

# Save list of "promising" (≥1 hit on small models) for ½-SOTA retry
promising = hard[hard["hit_rate"]>0].index.tolist()
(OUT/"promising_cases_for_half_sota.txt").write_text("\n".join(promising)+"\n")
print("\nPromising for ½-SOTA retry:", promising)
