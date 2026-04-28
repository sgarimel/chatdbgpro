#!/usr/bin/env python3
"""Display model responses and metadata from collect.json files.

Usage:
    python bench/show_runs.py --results-dir bench/results/ablation-4models-v2
    python bench/show_runs.py --results-dir bench/results/ablation-4models-v2 --case null-deref-env
    python bench/show_runs.py --results-dir bench/results/ablation-4models-v2 --model nemotron
    python bench/show_runs.py --results-dir bench/results/ablation-4models-v2 --case null-deref-env --model gpt-4
    python bench/show_runs.py --results-dir bench/results/SAMPLEpaper-ablation-4models --output report.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_run(run_dir: Path) -> dict | None:
    result_path = run_dir / "result.json"
    collect_path = run_dir / "collect.json"
    score_path = run_dir / "score.json"
    if not result_path.exists():
        return None

    result = json.loads(result_path.read_text())
    collect = json.loads(collect_path.read_text()) if collect_path.exists() else None
    score = json.loads(score_path.read_text()) if score_path.exists() else None

    entry = {
        "run_id": result.get("run_id", run_dir.name),
        "case_id": result.get("case_id", "?"),
        "model": result.get("model", "?"),
        "tier": result.get("tier", 3),
        "status": result.get("status", "?"),
        "elapsed_s": result.get("elapsed_s", 0),
        "tool_config": result.get("tool_config", "?"),
        "context_lines": result.get("context_lines", 10),
    }

    if collect:
        q = collect.get("queries", [{}])[0] if collect.get("queries") else {}
        entry["prompt"] = q.get("prompt", "")
        entry["response"] = q.get("response", "")
        entry["code_blocks"] = q.get("code_blocks", [])
        entry["num_tool_calls"] = q.get("num_tool_calls", 0)
        entry["tool_calls"] = q.get("tool_calls", [])
        entry["tool_frequency"] = q.get("tool_frequency", {})
        stats = q.get("stats", {})
        entry["tokens"] = stats.get("tokens", 0)
        entry["prompt_tokens"] = stats.get("prompt_tokens", 0)
        entry["completion_tokens"] = stats.get("completion_tokens", 0)
        entry["cost"] = stats.get("cost", 0)
        entry["completed"] = stats.get("completed", False)

    if score:
        s = score.get("scores", {})
        entry["score_rc"] = s.get("root_cause", "?")
        entry["score_lf"] = s.get("local_fix", "?")
        entry["score_gf"] = s.get("global_fix", "?")
        entry["rationale"] = score.get("rationale", {})

    return entry


def short_model(name: str) -> str:
    return name.split("/")[-1]


def format_run(run: dict) -> str:
    lines = []
    lines.append(f"## {run['case_id']} — {short_model(run['model'])}")
    lines.append("")

    # Metadata table
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Model | `{run['model']}` |")
    lines.append(f"| Status | {run['status']} |")
    lines.append(f"| Elapsed | {run['elapsed_s']:.1f}s |")
    lines.append(f"| Tool calls | {run.get('num_tool_calls', 0)} |")
    lines.append(f"| Tool frequency | {json.dumps(run.get('tool_frequency', {}))} |")
    lines.append(f"| Prompt tokens | {run.get('prompt_tokens', 0)} |")
    lines.append(f"| Completion tokens | {run.get('completion_tokens', 0)} |")
    lines.append(f"| Total tokens | {run.get('tokens', 0)} |")
    lines.append(f"| Completed | {run.get('completed', '?')} |")
    if "score_rc" in run:
        lines.append(f"| **Score: root_cause** | **{run['score_rc']}** |")
        lines.append(f"| **Score: local_fix** | **{run['score_lf']}** |")
        lines.append(f"| **Score: global_fix** | **{run['score_gf']}** |")
    lines.append("")

    # Tool calls detail
    if run.get("tool_calls"):
        lines.append("### Tool calls")
        lines.append("")
        for i, tc in enumerate(run["tool_calls"], 1):
            lines.append(f"{i}. `{tc.get('tool_name', '?')}`: `{tc.get('call', '?')}` ({tc.get('result_length', 0)} chars)")
        lines.append("")

    # Model response
    lines.append("### Response")
    lines.append("")
    response = run.get("response", "(no response)")
    if len(response) > 5000:
        response = response[:5000] + "\n\n... [truncated] ..."
    lines.append(response)
    lines.append("")

    # Code blocks
    if run.get("code_blocks"):
        lines.append("### Proposed fixes")
        lines.append("")
        for i, block in enumerate(run["code_blocks"], 1):
            lines.append(f"**Fix {i}:**")
            lines.append(f"```")
            lines.append(block)
            lines.append(f"```")
            lines.append("")

    # Judge rationale
    if run.get("rationale"):
        lines.append("### Judge rationale")
        lines.append("")
        for axis, text in run["rationale"].items():
            lines.append(f"- **{axis}**: {text}")
        lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results-dir", required=True, help="Results directory")
    p.add_argument("--case", default=None, help="Filter by case_id (substring match)")
    p.add_argument("--model", default=None, help="Filter by model name (substring match)")
    p.add_argument("--output", default=None, help="Write to file instead of stdout")
    args = p.parse_args()

    results_dir = Path(args.results_dir)
    runs = []
    for run_dir in sorted(results_dir.iterdir()):
        if not run_dir.is_dir() or run_dir.name == "figures":
            continue
        run = load_run(run_dir)
        if run:
            runs.append(run)

    if args.case:
        runs = [r for r in runs if args.case.lower() in r["case_id"].lower()]
    if args.model:
        runs = [r for r in runs if args.model.lower() in r["model"].lower()]

    if not runs:
        sys.exit("No matching runs found.")

    # Sort by case, then model
    runs.sort(key=lambda r: (r["case_id"], r["model"]))

    header = f"# Run Report — {results_dir.name}\n\n"
    header += f"**{len(runs)} runs** "
    if args.case:
        header += f"| case filter: `{args.case}` "
    if args.model:
        header += f"| model filter: `{args.model}` "
    header += "\n\n---\n\n"

    output = header + "".join(format_run(r) for r in runs)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Written to {args.output} ({len(runs)} runs)")
    else:
        print(output)


if __name__ == "__main__":
    main()
