#!/usr/bin/env python3
"""Aggregate scored ChatDBG ablation runs into tables.

Consumes a bench/results/<run_name>/ tree populated by orchestrator.py
and then by judge.py. Walks every child run's result.json + score.json
+ collect.json and emits:

  * runs.csv                      one row per run
  * summary_by_model.csv          mean scores / tokens / tool calls
  * summary_by_config.csv         grouped by tool_config
  * summary_by_model_config.csv   cross
  * summary_by_case.csv           per test case, across all runs
  * report.md                     human-readable rollup

All rollups use the standard 3-axis score and record the model-under-test's
input/output tokens, number of tool calls, tool_frequency histogram, and
wall-clock elapsed time. No inferential stats (std / CIs) — we emit
means and counts and leave the stats to the user.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BENCH_DIR = Path(__file__).resolve().parent


def load_json(p: Path) -> Any:
    with open(p) as f:
        return json.load(f)


def gather_runs(run_root: Path) -> list[dict]:
    rows: list[dict] = []
    for d in sorted(run_root.iterdir()):
        if not d.is_dir():
            continue
        rj = d / "result.json"
        if not rj.exists():
            continue
        result = load_json(rj)
        row = {
            "run_id": result.get("run_id", d.name),
            "case_id": result.get("case_id"),
            "model": result.get("model"),
            "tool_config": result.get("tool_config"),
            "context_lines": result.get("context_lines"),
            "trial": result.get("trial"),
            "status": result.get("status"),
            "elapsed_s": result.get("elapsed_s"),
            "exit_code": result.get("exit_code"),
            "root_cause": None,
            "local_fix": None,
            "global_fix": None,
            "judge_status": None,
            "judge_model": None,
            "mut_input_tokens": 0,
            "mut_output_tokens": 0,
            "num_tool_calls": 0,
            "tool_frequency_json": "",
            "total_code_length": 0,
        }
        sc = d / "score.json"
        if sc.exists():
            s = load_json(sc)
            scores = s.get("scores", {})
            row["root_cause"] = scores.get("root_cause")
            row["local_fix"] = scores.get("local_fix")
            row["global_fix"] = scores.get("global_fix")
            row["judge_status"] = s.get("status")
            row["judge_model"] = s.get("judge_model")
            mut = s.get("mut", {})
            row["mut_input_tokens"] = mut.get("mut_input_tokens", 0)
            row["mut_output_tokens"] = mut.get("mut_output_tokens", 0)
            row["num_tool_calls"] = mut.get("num_tool_calls", 0)
            row["tool_frequency_json"] = json.dumps(mut.get("tool_frequency", {}))
        # Supplement with collect.json for code-output length etc.
        cp = d / "collect.json"
        if cp.exists():
            try:
                coll = load_json(cp)
                queries = coll.get("queries", []) or []
                if queries:
                    q = queries[0]
                    row["total_code_length"] = q.get("total_code_length", 0)
                    # if judge wasn't run yet, still surface token/tool counts
                    if row["num_tool_calls"] == 0:
                        row["num_tool_calls"] = q.get("num_tool_calls", 0)
                    stats = q.get("stats", {}) or {}
                    if row["mut_input_tokens"] == 0:
                        row["mut_input_tokens"] = stats.get("prompt_tokens", 0)
                    if row["mut_output_tokens"] == 0:
                        row["mut_output_tokens"] = stats.get("completion_tokens", 0)
                    if not row["tool_frequency_json"]:
                        row["tool_frequency_json"] = json.dumps(
                            q.get("tool_frequency", {}))
            except Exception:
                pass
        rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    if not rows:
        path.write_text("")
        return
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def _mean(values: list[float]) -> float | None:
    vs = [v for v in values if v is not None]
    return round(statistics.mean(vs), 4) if vs else None


def group_summary(rows: list[dict], keys: list[str]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[tuple(r.get(k) for k in keys)].append(r)
    out: list[dict] = []
    for key_tuple, group in sorted(groups.items(), key=lambda kv: tuple(
            str(x) if x is not None else "" for x in kv[0])):
        row = {k: v for k, v in zip(keys, key_tuple)}
        row["n"] = len(group)
        row["root_cause_mean"] = _mean([g["root_cause"] for g in group])
        row["local_fix_mean"]  = _mean([g["local_fix"]  for g in group])
        row["global_fix_mean"] = _mean([g["global_fix"] for g in group])
        row["elapsed_s_mean"]  = _mean([g["elapsed_s"]  for g in group])
        row["input_tokens_mean"]  = _mean([g["mut_input_tokens"]  for g in group])
        row["output_tokens_mean"] = _mean([g["mut_output_tokens"] for g in group])
        row["tool_calls_mean"]    = _mean([g["num_tool_calls"]    for g in group])
        row["code_length_mean"]   = _mean([g["total_code_length"] for g in group])
        # Aggregate tool-frequency histogram across the group.
        counter: Counter = Counter()
        for g in group:
            try:
                counter.update(json.loads(g["tool_frequency_json"] or "{}"))
            except Exception:
                pass
        row["tool_histogram"] = json.dumps(dict(counter))
        out.append(row)
    return out


def render_markdown(run_root: Path, rows: list[dict]) -> str:
    total = len(rows)
    judged = [r for r in rows if r["root_cause"] is not None]
    scored_n = len(judged)
    lines: list[str] = []
    lines.append(f"# ChatDBG ablation report — `{run_root.name}`")
    lines.append("")
    lines.append(f"Runs: **{total}** total, **{scored_n}** scored.")
    lines.append("")
    if scored_n:
        rc = _mean([r["root_cause"] for r in judged])
        lf = _mean([r["local_fix"]  for r in judged])
        gf = _mean([r["global_fix"] for r in judged])
        lines.append(f"Overall mean — root_cause: **{rc}**, local_fix: **{lf}**, global_fix: **{gf}**")
        lines.append("")

    def section(title: str, summary: list[dict], key_names: list[str]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        header = key_names + [
            "n",
            "root_cause_mean", "local_fix_mean", "global_fix_mean",
            "elapsed_s_mean",
            "input_tokens_mean", "output_tokens_mean",
            "tool_calls_mean", "code_length_mean",
        ]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for r in summary:
            lines.append("| " + " | ".join(
                str(r.get(k, "")) if r.get(k) is not None else ""
                for k in header) + " |")
        lines.append("")

    section("By model", group_summary(rows, ["model"]), ["model"])
    section("By tool config", group_summary(rows, ["tool_config"]), ["tool_config"])
    section("By (model, tool_config)",
            group_summary(rows, ["model", "tool_config"]),
            ["model", "tool_config"])
    section("By case", group_summary(rows, ["case_id"]), ["case_id"])

    # Failure diagnostics
    lines.append("## Run status breakdown")
    lines.append("")
    stats: Counter = Counter(r["status"] for r in rows)
    for status, n in sorted(stats.items()):
        lines.append(f"- `{status}`: {n}")
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_dir")
    p.add_argument("--out", default=None,
                   help="Directory for analysis outputs. "
                        "Default: <run_dir>/analysis/")
    args = p.parse_args()

    run_root = Path(args.run_dir).resolve()
    if not run_root.is_dir():
        sys.stderr.write(f"Not a directory: {run_root}\n")
        return 2

    rows = gather_runs(run_root)
    if not rows:
        sys.stderr.write("No runs found.\n")
        return 2

    out_dir = Path(args.out) if args.out else run_root / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    write_csv(out_dir / "runs.csv", rows)
    write_csv(out_dir / "summary_by_model.csv",
              group_summary(rows, ["model"]))
    write_csv(out_dir / "summary_by_config.csv",
              group_summary(rows, ["tool_config"]))
    write_csv(out_dir / "summary_by_model_config.csv",
              group_summary(rows, ["model", "tool_config"]))
    write_csv(out_dir / "summary_by_case.csv",
              group_summary(rows, ["case_id"]))

    md = render_markdown(run_root, rows)
    (out_dir / "report.md").write_text(md)
    print(f"[analyze] wrote {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
