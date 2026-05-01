#!/usr/bin/env python3
"""LLM-as-judge evaluator for ChatDBG ablation runs.

Walks a results/<run_name>/ directory produced by orchestrator.py, loads
each run's collect.json + case.yaml, and asks a judge model (via
LiteLLM) to score three axes: root_cause, local_fix, global_fix.

Each run grows a sibling `score.json`:

    {
      "judge_model": "openai/gpt-5",
      "scores": {"root_cause": 1, "local_fix": 1, "global_fix": 0},
      "rationale": {"root_cause": "...", "local_fix": "...", ...},
      "judge_input_tokens": 1234,
      "judge_output_tokens": 89
    }

The judge prompt intentionally receives the run's buggy source, the
pre-registered criteria, and the model-under-test's final response
(plus any thinking trace ChatDBG captured). It does NOT see the
debugger transcript directly — the criteria are the contract.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML required. pip install pyyaml\n")
    raise

try:
    import litellm
except ImportError:
    sys.stderr.write("litellm required. pip install litellm\n")
    raise

BENCH_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = BENCH_DIR / "prompts"
RESULTS_DIR = BENCH_DIR / "results"

SYSTEM_PROMPT = (PROMPTS_DIR / "judge_system.txt").read_text()
USER_TEMPLATE = (PROMPTS_DIR / "judge_user.txt").read_text()

MAX_SRC_CHARS = 20_000        # truncate pathological cases
MAX_RESPONSE_CHARS = 40_000   # long runs can emit walls of text


def load_json(p: Path) -> Any:
    with open(p) as f:
        return json.load(f)


def load_yaml(p: Path) -> Any:
    with open(p) as f:
        return yaml.safe_load(f)


def build_user_prompt(run_dir: Path) -> tuple[str, dict] | None:
    """Return (prompt, meta_for_score) or None if the run is unjudgable."""
    case_yaml = run_dir / "case.yaml"
    result_json = run_dir / "result.json"
    collect_json = run_dir / "collect.json"
    if not (case_yaml.exists() and result_json.exists()):
        return None
    case = load_yaml(case_yaml)
    result = load_json(result_json)
    criteria = case.get("criteria", {})
    # For synthetic cases, source_file is a sibling of case.yaml. For
    # `kind: injected_repo` cases the source lives in the workspace
    # cache under bench/.workspace-cache/<case_id>/<bug.root_cause_file>;
    # fall back to that when the synthetic file isn't present.
    source_file = case.get("source_file")
    source = None
    if source_file:
        source_path = run_dir / source_file
        if source_path.exists():
            try:
                source = source_path.read_text()
            except UnicodeDecodeError:
                source = source_path.read_text(errors="replace")
    if source is None:
        rc_file = (case.get("bug", {}) or {}).get("root_cause_file")
        if rc_file:
            cached = (BENCH_DIR / ".workspace-cache" / case.get("id", "") / rc_file)
            if cached.exists():
                try:
                    source = cached.read_text()
                except UnicodeDecodeError:
                    source = cached.read_text(errors="replace")
                source_file = rc_file
    if source is None:
        return None
    if len(source) > MAX_SRC_CHARS:
        source = source[:MAX_SRC_CHARS] + "\n/* ... source truncated ... */\n"

    if not collect_json.exists():
        # The orchestrator still produced a record; the model never
        # emitted anything. Treat as a 0/0/0 trivially — but let the
        # judge see the empty output so its rationale is explicit.
        thinking = "(no ChatDBG collect.json — session produced no data)"
        response = "(empty)"
        num_tool_calls = 0
        tool_frequency = {}
        in_tok = 0
        out_tok = 0
    else:
        coll = load_json(collect_json)
        queries = coll.get("queries", [])
        if not queries:
            thinking = "(no queries recorded)"
            response = "(empty)"
            num_tool_calls = 0
            tool_frequency = {}
            in_tok = 0
            out_tok = 0
        else:
            q = queries[0]          # we drive a single `why ...` per run
            thinking = q.get("thinking") or "(no thinking trace emitted)"
            response = q.get("response") or "(empty)"
            num_tool_calls = q.get("num_tool_calls", 0)
            tool_frequency = q.get("tool_frequency", {})
            stats = q.get("stats", {})
            in_tok = stats.get("prompt_tokens", 0)
            out_tok = stats.get("completion_tokens", 0)

    if len(response) > MAX_RESPONSE_CHARS:
        response = response[:MAX_RESPONSE_CHARS] + "\n... [truncated] ..."

    prompt = USER_TEMPLATE.format(
        language=case.get("language", "c"),
        source_file=source_file,
        source=source,
        root_cause_criterion=criteria.get("root_cause", "(missing)").strip(),
        local_fix_criterion=criteria.get("local_fix", "(missing)").strip(),
        global_fix_criterion=criteria.get("global_fix", "(missing)").strip(),
        model=result.get("model", "?"),
        tool_config=result.get("tool_config", "?"),
        context_lines=result.get("context_lines", "?"),
        num_tool_calls=num_tool_calls,
        tool_frequency=json.dumps(tool_frequency) if tool_frequency else "{}",
        input_tokens=in_tok,
        output_tokens=out_tok,
        thinking=thinking,
        response=response,
    )
    meta = {
        "num_tool_calls": num_tool_calls,
        "tool_frequency": tool_frequency,
        "mut_input_tokens": in_tok,
        "mut_output_tokens": out_tok,
    }
    return prompt, meta


def extract_json(text: str) -> dict | None:
    """Pull the first top-level JSON object from `text`."""
    text = text.strip()
    # Unwrap a ``` fence if the model ignored instructions
    fence = re.match(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Find the first balanced {...}
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                blob = text[start:i + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    return None
    return None


def judge_one(
    run_dir: Path,
    judge_model: str,
    temperature: float,
    overwrite: bool,
) -> dict | None:
    score_path = run_dir / "score.json"
    if score_path.exists() and not overwrite:
        return load_json(score_path)
    built = build_user_prompt(run_dir)
    if built is None:
        return None
    prompt, meta = built

    # A7: detect "no prose synthesis" failures — the model engaged the
    # debugger (n_tools > 0) but emitted essentially no answer
    # (Gemini-Flash-Lite hits this on ~half of runs). Don't burn judge
    # API quota; record the discriminator so the heatmap can render
    # this distinctly from a content-failure 0/0/0.
    response_text = "(empty)"
    if (run_dir / "collect.json").exists():
        try:
            q = (load_json(run_dir / "collect.json").get("queries") or [{}])[0]
            response_text = q.get("response") or "(empty)"
        except Exception:
            pass
    n_tools = meta.get("num_tool_calls", 0) or 0
    if len(response_text.strip()) < 50 and n_tools > 0:
        score = {
            "judge_model": judge_model,
            "status": "no_prose_synthesis",
            "elapsed_s": 0.0,
            "judge_input_tokens": 0,
            "judge_output_tokens": 0,
            "raw_judge_output": "",
            "mut": meta,
            "scores": {"root_cause": 0, "local_fix": 0, "global_fix": 0},
            "rationale": {
                "root_cause": (
                    f"Model engaged the debugger ({n_tools} tool calls) but "
                    f"emitted only {len(response_text.strip())} chars of prose; "
                    f"no diagnosis to score against. Likely model-side stop-token "
                    f"or output-format regression."),
                "local_fix": "Skipped — no prose to evaluate.",
                "global_fix": "Skipped — no prose to evaluate.",
            },
            "no_prose_response_len": len(response_text.strip()),
        }
        score_path.write_text(json.dumps(score, indent=2))
        return score

    # A6: retry up to twice on parse_failed. gpt-4o emits malformed
    # JSON ~0.5% of the time; without retry that becomes a permanent
    # 0/0/0 cell in the heatmap.
    last_content = ""
    last_usage = {}
    last_elapsed = 0.0
    parsed = None
    attempts = 0
    for attempts in range(1, 3):
        t0 = time.time()
        resp = litellm.completion(
            model=judge_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature if attempts == 1 else 0.0,
        )
        last_elapsed = time.time() - t0
        last_content = resp.choices[0].message.content or ""
        last_usage = getattr(resp, "usage", None) or {}
        parsed = extract_json(last_content)
        if parsed is not None:
            break

    ptok = getattr(last_usage, "prompt_tokens", None) or (last_usage.get("prompt_tokens", 0) if isinstance(last_usage, dict) else 0)
    ctok = getattr(last_usage, "completion_tokens", None) or (last_usage.get("completion_tokens", 0) if isinstance(last_usage, dict) else 0)

    score = {
        "judge_model": judge_model,
        "elapsed_s": round(last_elapsed, 3),
        "judge_input_tokens": ptok,
        "judge_output_tokens": ctok,
        "raw_judge_output": last_content,
        "judge_attempts": attempts,
        "mut": meta,
    }
    if parsed is None:
        score["status"] = "parse_failed"
        score["scores"] = {"root_cause": 0, "local_fix": 0, "global_fix": 0}
        score["rationale"] = {}
    else:
        score["status"] = "ok"
        score["scores"] = {
            "root_cause": _to01(parsed.get("root_cause")),
            "local_fix":  _to01(parsed.get("local_fix")),
            "global_fix": _to01(parsed.get("global_fix")),
        }
        score["rationale"] = parsed.get("rationale", {})
    score_path.write_text(json.dumps(score, indent=2))
    return score


def _to01(v: Any) -> int:
    if v in (0, 1):
        return int(v)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, str):
        v = v.strip().lower()
        if v in ("1", "true", "yes"):
            return 1
        if v in ("0", "false", "no"):
            return 0
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_dir", help="bench/results/<run_name>/ produced by orchestrator.py")
    p.add_argument("--judge-model", default=os.environ.get(
        "CHATDBG_JUDGE_MODEL", "openai/gpt-4o"),
        help="Judge model in LiteLLM format (default: $CHATDBG_JUDGE_MODEL or openai/gpt-4o).")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--overwrite", action="store_true",
                   help="Rescore runs that already have score.json.")
    p.add_argument("--limit", type=int, default=None,
                   help="Judge at most N runs (useful for dry-runs).")
    args = p.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        sys.stderr.write(f"Not a directory: {run_dir}\n")
        return 2

    child_runs = sorted([d for d in run_dir.iterdir()
                         if d.is_dir() and (d / "result.json").exists()])
    if not child_runs:
        sys.stderr.write(f"No runs found under {run_dir}\n")
        return 2

    if args.limit:
        child_runs = child_runs[:args.limit]

    print(f"[judge] scoring {len(child_runs)} runs with {args.judge_model}")
    for i, d in enumerate(child_runs, 1):
        try:
            score = judge_one(d, args.judge_model, args.temperature,
                              overwrite=args.overwrite)
        except Exception as e:
            print(f"[{i}/{len(child_runs)}] {d.name}  ERROR: {e}")
            continue
        if score is None:
            print(f"[{i}/{len(child_runs)}] {d.name}  skipped (no source/result)")
            continue
        s = score.get("scores", {})
        print(f"[{i}/{len(child_runs)}] {d.name}  "
              f"rc={s.get('root_cause', 0)} "
              f"lf={s.get('local_fix', 0)} "
              f"gf={s.get('global_fix', 0)} "
              f"({score.get('status')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
