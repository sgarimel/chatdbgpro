#!/usr/bin/env python3
"""
xv6-bench driver: build buggy xv6, boot in QEMU+GDB, capture crash state,
send to LLM for diagnosis, and produce results in the standard
case.yaml / collect.json / result.json / score.json pipeline format.

Usage (inside Docker):
    python3 run_xv6_bench.py --bug bug1-uvmcopy-perm --model openrouter/openai/gpt-4o

Usage (from host, via docker run):
    See run_all.sh for the full pipeline.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import yaml
from pathlib import Path

BUGS_DIR = Path("/xv6/bugs")
TRIGGERS_DIR = Path("/xv6/trigger-programs")
SCRIPTS_DIR = Path("/xv6/scripts")
RESULTS_BASE = Path("/xv6/results")


def load_bug_config(bug_id: str) -> dict:
    """Load the bug's YAML config (ground truth)."""
    yaml_path = BUGS_DIR / f"{bug_id}.yaml"
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def build_xv6(bug_id: str, bug_config: dict) -> Path:
    """Build xv6 with the specified bug."""
    patch_file = BUGS_DIR / f"{bug_id}.patch"
    trigger = bug_config["trigger"]
    trigger_src = TRIGGERS_DIR / f"{trigger}.c"

    subprocess.run(
        ["bash", str(SCRIPTS_DIR / "build_bug.sh"),
         bug_id, str(patch_file), str(trigger_src)],
        check=True,
    )
    return Path(f"/xv6/builds/{bug_id}")


def capture_crash_state(bug_id: str, trigger: str, results_dir: Path,
                        timeout: int = 90) -> dict:
    """Boot xv6 in QEMU, run trigger, capture GDB state at panic."""
    results_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["BUILD_DIR"] = f"/xv6/builds/{bug_id}"

    proc = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "run_qemu_gdb.sh"),
         bug_id, trigger, str(results_dir), str(timeout)],
        capture_output=True, text=True, timeout=timeout + 30,
        env=env,
    )

    (results_dir / "stdout.log").write_text(proc.stdout)
    (results_dir / "stderr.log").write_text(proc.stderr)

    # Read captured state
    state = {"backtrace": "", "frames": [], "panic_msg": ""}

    bt_path = results_dir / "backtrace.txt"
    if bt_path.exists():
        state["backtrace"] = bt_path.read_text()

    frames_path = results_dir / "frames.json"
    if frames_path.exists():
        with open(frames_path) as f:
            state["frames"] = json.load(f)

    msg_path = results_dir / "panic_msg.txt"
    if msg_path.exists():
        state["panic_msg"] = msg_path.read_text().strip()

    return state


def build_prompt(bug_config: dict, crash_state: dict) -> str:
    """Build the prompt sent to the LLM, mimicking ChatDBG's format."""
    bt = crash_state.get("backtrace", "(no backtrace captured)")
    panic_msg = crash_state.get("panic_msg", "(unknown)")

    # Build enriched stack trace with source code
    frames = crash_state.get("frames", [])
    frame_text = ""
    build_dir = Path(f"/xv6/builds/{bug_config['id']}")

    for fr in frames[:5]:
        if "error" in fr:
            frame_text += f"Frame #{fr['depth']}: (error: {fr['error']})\n"
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

        # Include source code around the frame
        src_path = build_dir / src_file
        if src_path.exists():
            try:
                lines = src_path.read_text().splitlines()
                start = max(0, line - 10)
                end = min(len(lines), line + 10)
                frame_text += f"\n  Source ({src_file}:{start+1}-{end}):\n"
                for i in range(start, end):
                    marker = " >>>" if i + 1 == line else "    "
                    frame_text += f"  {marker} {i+1:4d} {lines[i]}\n"
            except Exception:
                pass

    prompt = f"""The xv6 operating system kernel has panicked. Here is the GDB backtrace:
```
{bt}
```

Panic message: {panic_msg}

Enriched stack frames with source context:
{frame_text}

The trigger program was: {bug_config['trigger']}
The xv6 kernel source is at /xv6/builds/{bug_config['id']}/kernel/

What is the root cause of this kernel panic? Walk through the program state,
identify the defect, and propose a fix in code. Cover both a minimal local fix
and a more thorough root-cause fix if they differ."""

    return prompt


def call_llm(prompt: str, model: str, system_instructions: str) -> dict:
    """Call the LLM via litellm and return the response + metadata."""
    import litellm

    messages = [
        {"role": "system", "content": system_instructions},
        {"role": "user", "content": prompt},
    ]

    start = time.time()
    response = litellm.completion(
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=4096,
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
        "model": model,
    }


SYSTEM_INSTRUCTIONS = """You are a kernel debugging assistant analyzing an xv6
operating system panic. You have access to the GDB backtrace, stack frame
variables, and source code context around the crash site.

Your task:
1. Identify the root cause of the panic by analyzing the backtrace and variables.
2. Trace the bug back to the specific file and line in the kernel source.
3. Explain WHY the bug causes the observed behavior.
4. Propose a minimal local fix (what code to change).
5. If applicable, explain the broader design principle violated.

Be specific: name the file, function, line number, and the exact code change needed."""


def write_results(run_dir: Path, bug_config: dict, prompt: str,
                  llm_result: dict, crash_state: dict, model: str):
    """Write results in the standard pipeline format."""
    run_dir.mkdir(parents=True, exist_ok=True)

    # case.yaml (ground truth for judge)
    case_yaml = {
        "id": bug_config["id"],
        "language": bug_config["language"],
        "source_file": bug_config["source_file"],
        "criteria": bug_config["criteria"],
    }
    with open(run_dir / "case.yaml", "w") as f:
        yaml.dump(case_yaml, f, default_flow_style=False)

    # collect.json (model interaction log)
    collect = {
        "meta": {
            "model": model,
            "benchmark": "xv6-bench",
            "bug_id": bug_config["id"],
        },
        "instructions": SYSTEM_INSTRUCTIONS,
        "queries": [{
            "user_text": prompt,
            "prompt": prompt,
            "thinking": "",
            "response": llm_result["response"],
            "code_blocks": [],
            "total_code_length": 0,
            "num_tool_calls": 0,
            "tool_calls": [],
            "tool_frequency": {},
            "stats": {
                "prompt_tokens": llm_result["prompt_tokens"],
                "completion_tokens": llm_result["completion_tokens"],
                "total_tokens": llm_result["total_tokens"],
            },
        }],
    }
    with open(run_dir / "collect.json", "w") as f:
        json.dump(collect, f, indent=2)

    # result.json (run metadata)
    result = {
        "run_id": run_dir.name,
        "status": "ok",
        "exit_code": 0,
        "elapsed_s": llm_result["elapsed_s"],
        "model": model,
        "tool_config": "xv6_gdb_only",
        "context_lines": 20,
        "tier": "xv6",
        "trial": 1,
        "case_id": bug_config["id"],
        "language": "c",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "collect_path": "collect.json",
    }
    with open(run_dir / "result.json", "w") as f:
        json.dump(result, f, indent=2)

    # Copy relevant source files for the judge
    build_dir = Path(f"/xv6/builds/{bug_config['id']}")
    src_file = bug_config["source_file"]
    src_path = build_dir / src_file
    if src_path.exists():
        shutil.copy(src_path, run_dir / src_path.name)


def main():
    parser = argparse.ArgumentParser(description="xv6-bench: LLM kernel debugging benchmark")
    parser.add_argument("--bug", required=True, help="Bug ID (e.g., bug1-uvmcopy-perm)")
    parser.add_argument("--model", required=True, help="LLM model (e.g., openrouter/openai/gpt-4o)")
    parser.add_argument("--timeout", type=int, default=90, help="QEMU timeout in seconds")
    parser.add_argument("--results-dir", default=None, help="Override results directory")
    parser.add_argument("--skip-build", action="store_true", help="Skip build (reuse existing)")
    parser.add_argument("--skip-qemu", action="store_true", help="Skip QEMU (reuse crash state)")
    args = parser.parse_args()

    bug_config = load_bug_config(args.bug)
    model_slug = args.model.replace("/", "_")
    run_id = f"{bug_config['id']}__{model_slug}"

    if args.results_dir:
        run_dir = Path(args.results_dir) / run_id
    else:
        run_dir = RESULTS_BASE / run_id

    crash_dir = run_dir / "crash_state"
    print(f"[xv6-bench] Bug: {args.bug}")
    print(f"[xv6-bench] Model: {args.model}")
    print(f"[xv6-bench] Results: {run_dir}")

    # Step 1: Build
    if not args.skip_build:
        print("[xv6-bench] Building xv6 with bug...")
        build_xv6(args.bug, bug_config)

    # Step 2: Capture crash state
    if not args.skip_qemu:
        print("[xv6-bench] Booting QEMU and capturing crash state...")
        crash_state = capture_crash_state(
            args.bug, bug_config["trigger"], crash_dir, args.timeout
        )
    else:
        # Load from existing files
        crash_state = {"backtrace": "", "frames": [], "panic_msg": ""}
        bt_path = crash_dir / "backtrace.txt"
        if bt_path.exists():
            crash_state["backtrace"] = bt_path.read_text()
        frames_path = crash_dir / "frames.json"
        if frames_path.exists():
            with open(frames_path) as f:
                crash_state["frames"] = json.load(f)
        msg_path = crash_dir / "panic_msg.txt"
        if msg_path.exists():
            crash_state["panic_msg"] = msg_path.read_text().strip()

    # Step 3: Build prompt
    prompt = build_prompt(bug_config, crash_state)
    print(f"[xv6-bench] Prompt length: {len(prompt)} chars")

    # Step 4: Call LLM
    print(f"[xv6-bench] Calling {args.model}...")
    llm_result = call_llm(prompt, args.model, SYSTEM_INSTRUCTIONS)
    print(f"[xv6-bench] Response: {llm_result['total_tokens']} tokens, "
          f"{llm_result['elapsed_s']:.1f}s")

    # Step 5: Write results
    write_results(run_dir, bug_config, prompt, llm_result, crash_state, args.model)
    print(f"[xv6-bench] Results written to {run_dir}")

    # Print summary
    print("\n" + "=" * 60)
    print(f"Model response (first 500 chars):")
    print(llm_result["response"][:500])
    print("=" * 60)


if __name__ == "__main__":
    main()
