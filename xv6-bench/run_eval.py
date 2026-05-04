#!/usr/bin/env python3
"""
xv6-bench LLM evaluation — no Docker required.

Reads pre-captured crash states and xv6 source, builds prompts,
calls LLMs via litellm, and writes results in the standard
case.yaml / collect.json / result.json format for bench/judge.py.

Usage:
    cd chatdbgpro/xv6-bench
    export OPENROUTER_API_KEY=sk-or-...
    python3 run_eval.py                     # all bugs x all models
    python3 run_eval.py --bug bug1-uvmcopy-perm --model openrouter/openai/gpt-4o
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
XV6_SRC = SCRIPT_DIR / "xv6-riscv"
BUGS_DIR = SCRIPT_DIR / "bugs"
CRASH_STATES_DIR = SCRIPT_DIR / "crash_states"
RESULTS_BASE = SCRIPT_DIR / "results"

ALL_MODELS = [
    "openrouter/openai/gpt-4o",
    "openrouter/meta-llama/llama-3.1-8b-instruct",
    "openrouter/nvidia/nemotron-3-nano-30b-a3b",
    "openrouter/qwen/qwen3-30b-a3b-instruct-2507",
]

ALL_BUGS = [
    "bug1-uvmcopy-perm",
    "bug2-pipewrite-off-by-one",
    "bug3-kalloc-double-link",
]

SYSTEM_INSTRUCTIONS = """\
You are a kernel debugging assistant analyzing an xv6 operating system panic.
You have access to the GDB backtrace, stack frame variables, and source code
context around the crash site.

Your task:
1. Identify the root cause of the panic by analyzing the backtrace and variables.
2. Trace the bug back to the specific file and line in the kernel source.
3. Explain WHY the bug causes the observed behavior.
4. Propose a minimal local fix (what code to change).
5. If applicable, explain the broader design principle violated.

Be specific: name the file, function, line number, and the exact code change."""


def load_bug_config(bug_id: str) -> dict:
    with open(BUGS_DIR / f"{bug_id}.yaml") as f:
        return yaml.safe_load(f)


def load_crash_state(bug_id: str) -> dict:
    d = CRASH_STATES_DIR / bug_id
    state = {"backtrace": "", "frames": [], "panic_msg": ""}
    if (d / "backtrace.txt").exists():
        state["backtrace"] = (d / "backtrace.txt").read_text()
    if (d / "frames.json").exists():
        with open(d / "frames.json") as f:
            state["frames"] = json.load(f)
    if (d / "panic_msg.txt").exists():
        state["panic_msg"] = (d / "panic_msg.txt").read_text().strip()
    return state


def read_source_context(filepath: str, center_line: int, window: int = 15) -> str:
    src_path = XV6_SRC / filepath
    if not src_path.exists():
        return f"(source file {filepath} not found)"
    lines = src_path.read_text().splitlines()
    start = max(0, center_line - window)
    end = min(len(lines), center_line + window)
    result = []
    for i in range(start, end):
        marker = " >>>" if i + 1 == center_line else "    "
        result.append(f"{marker} {i + 1:4d} {lines[i]}")
    return "\n".join(result)


def build_prompt(bug_config: dict, crash_state: dict) -> str:
    bt = crash_state.get("backtrace", "(no backtrace)")
    panic_msg = crash_state.get("panic_msg", "(unknown)")
    frames = crash_state.get("frames", [])

    frame_text = ""
    for fr in frames[:6]:
        if "error" in fr:
            frame_text += f"\nFrame #{fr['depth']}: (error: {fr['error']})\n"
            continue
        func = fr.get("function", "??")
        src_file = fr.get("file", "??")
        line = fr.get("line", 0)
        args = fr.get("args", "")
        locals_str = fr.get("locals", "")

        frame_text += f"\nFrame #{fr['depth']}: {func}() at {src_file}:{line}\n"
        if args and args != "No arguments.":
            frame_text += f"  Arguments: {args}\n"
        if locals_str and locals_str != "No locals.":
            frame_text += f"  Locals: {locals_str}\n"

        if src_file != "??" and line > 0:
            ctx = read_source_context(src_file, line, bug_id=bug_config["id"])
            frame_text += f"\n  Source ({src_file}:{max(1,line-15)}-{line+15}):\n"
            for sl in ctx.splitlines():
                frame_text += f"  {sl}\n"

    trigger = bug_config.get("trigger", "unknown")

    return f"""The xv6 operating system kernel has crashed. Here is the GDB backtrace:
```
{bt}
```

Crash/panic message:
```
{panic_msg}
```

Enriched stack frames with source context:
{frame_text}

The trigger program was: {trigger}
The xv6 kernel source is the standard MIT xv6-riscv codebase.

What is the root cause of this kernel panic/crash? Walk through the program state,
identify the defect, and propose a fix in code. Cover both a minimal local fix
and a more thorough root-cause fix if they differ."""


def call_llm(prompt: str, model: str) -> dict:
    import litellm
    messages = [
        {"role": "system", "content": SYSTEM_INSTRUCTIONS},
        {"role": "user", "content": prompt},
    ]
    start = time.time()
    response = litellm.completion(
        model=model, messages=messages, temperature=0.0, max_tokens=4096,
    )
    elapsed = time.time() - start
    choice = response.choices[0]
    usage = response.usage
    return {
        "response": choice.message.content,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "elapsed_s": elapsed,
    }


def write_results(run_dir: Path, bug_config: dict, prompt: str,
                  llm_result: dict, model: str):
    run_dir.mkdir(parents=True, exist_ok=True)

    with open(run_dir / "case.yaml", "w") as f:
        yaml.dump({
            "id": bug_config["id"],
            "language": bug_config["language"],
            "source_file": bug_config["source_file"],
            "criteria": bug_config["criteria"],
        }, f, default_flow_style=False)

    with open(run_dir / "collect.json", "w") as f:
        json.dump({
            "meta": {"model": model, "benchmark": "xv6-bench",
                     "bug_id": bug_config["id"]},
            "instructions": SYSTEM_INSTRUCTIONS,
            "queries": [{
                "user_text": prompt, "prompt": prompt, "thinking": "",
                "response": llm_result["response"],
                "code_blocks": [], "total_code_length": 0,
                "num_tool_calls": 0, "tool_calls": [], "tool_frequency": {},
                "stats": {
                    "prompt_tokens": llm_result["prompt_tokens"],
                    "completion_tokens": llm_result["completion_tokens"],
                    "total_tokens": llm_result["total_tokens"],
                },
            }],
        }, f, indent=2)

    with open(run_dir / "result.json", "w") as f:
        json.dump({
            "run_id": run_dir.name, "status": "ok", "exit_code": 0,
            "elapsed_s": llm_result["elapsed_s"], "model": model,
            "tool_config": "xv6_static_context", "context_lines": 30,
            "tier": "xv6", "trial": 1, "case_id": bug_config["id"],
            "language": "c",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "collect_path": "collect.json",
        }, f, indent=2)

    src = XV6_SRC / bug_config["source_file"]
    if src.exists():
        # Judge expects run_dir / source_file (e.g. "kernel/vm.c")
        dest = run_dir / bug_config["source_file"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bug", nargs="*", default=None)
    parser.add_argument("--model", nargs="*", default=None)
    parser.add_argument("--name", default=None)
    args = parser.parse_args()

    bugs = args.bug or ALL_BUGS
    models = args.model or ALL_MODELS
    run_name = args.name or f"xv6-run-{time.strftime('%Y%m%d_%H%M%S')}"
    results_dir = RESULTS_BASE / run_name

    total = len(bugs) * len(models)
    print(f"xv6-bench: {len(bugs)} bugs x {len(models)} models = {total} runs")
    print(f"Results: {results_dir}\n")

    for i, bug_id in enumerate(bugs):
        bug_config = load_bug_config(bug_id)
        crash_state = load_crash_state(bug_id)
        prompt = build_prompt(bug_config, crash_state)

        for j, model in enumerate(models):
            idx = i * len(models) + j + 1
            model_slug = model.replace("/", "_")
            run_id = f"{bug_config['id']}__{model_slug}"
            run_dir = results_dir / run_id

            print(f"[{idx}/{total}] {bug_id} x {model.split('/')[-1]}...",
                  end=" ", flush=True)
            try:
                result = call_llm(prompt, model)
                write_results(run_dir, bug_config, prompt, result, model)
                print(f"OK ({result['total_tokens']} tok, "
                      f"{result['elapsed_s']:.1f}s)")
            except Exception as e:
                print(f"FAILED: {e}")
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "error.txt").write_text(str(e))

    print(f"\nDone. Results in {results_dir}")
    print(f"Run judge: cd .. && python3 bench/judge.py --results-dir "
          f"xv6-bench/{results_dir.relative_to(SCRIPT_DIR)}")


if __name__ == "__main__":
    main()
