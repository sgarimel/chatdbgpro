#!/usr/bin/env python3
"""
Run ChatDBG on a buggy xv6 kernel via LLDB + QEMU.

Usage:
    cd xv6-bench
    # Terminal 1: start QEMU
    ./scripts/start_qemu.sh build-bug1

    # Terminal 2: run ChatDBG
    python3 scripts/run_chatdbg_xv6.py --build-dir build-bug1 \
        --model openrouter/openai/gpt-4o \
        --results-dir results/xv6-interactive

This script generates an LLDB command file that:
  1. Loads the kernel ELF for symbols
  2. Connects to QEMU's GDB stub on localhost:1234
  3. Sets a breakpoint on usertrap (for page-fault bugs) or panic
  4. Continues until the breakpoint fires
  5. Loads ChatDBG and runs `why`

Results are collected via CHATDBG_COLLECT_DATA into the results dir.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
BENCH_DIR = SCRIPT_DIR.parent
REPO_DIR = BENCH_DIR.parent  # chatdbgpro root
CHATDBG_SRC = REPO_DIR / "src"
BUGS_DIR = BENCH_DIR / "bugs"


def write_lldb_script(
    kernel_path: Path,
    collect_path: Path,
    model: str,
    tool_config: str | None,
    question: str,
) -> Path:
    """Write an LLDB command file for the ChatDBG session."""
    script = BENCH_DIR / "scripts" / "_lldb_session.cmd"

    env_lines = [
        f'settings set target.env-vars CHATDBG_MODEL="{model}"',
        f'settings set target.env-vars CHATDBG_COLLECT_DATA="{collect_path}"',
        'settings set target.env-vars CHATDBG_FORMAT="text"',
    ]
    if tool_config:
        env_lines.append(
            f'settings set target.env-vars CHATDBG_TOOL_CONFIG="{tool_config}"'
        )

    # Set PYTHONPATH so ChatDBG can be imported
    pypath = str(CHATDBG_SRC)
    env_lines.append(
        f'settings set target.env-vars PYTHONPATH="{pypath}"'
    )

    cmds = [
        # Load kernel symbols
        f'target create "{kernel_path}"',
        # Connect to QEMU
        "gdb-remote 1234",
        # Set breakpoints
        "breakpoint set -n panic",
        # For page-fault bugs, break when usertrap sees scause 12/13/15
        # We break on usertrap and let it run — ChatDBG will see the state
        "breakpoint set -n usertrap",
        # Continue past first few normal syscall traps, stop at faults
        "continue",
        # Skip initial syscalls (scause=8), keep continuing until page fault
        # We'll use a Python script for this
        f"""script
import lldb
import time

target = lldb.debugger.GetSelectedTarget()
process = target.GetProcess()

# Continue past normal syscall traps until we hit a page fault or panic
for attempt in range(200):
    # Check if we stopped at panic
    frame = process.GetSelectedThread().GetSelectedFrame()
    fn = frame.GetFunctionName() or ""
    if "panic" in fn:
        print(f"[xv6-chatdbg] Hit panic() at attempt {{attempt}}")
        break

    # Check scause register for page fault
    # scause: 12=instruction page fault, 13=load page fault, 15=store page fault
    if "usertrap" in fn:
        # Try to read scause
        scause_val = frame.EvaluateExpression("r_scause()")
        if scause_val.IsValid():
            sc = scause_val.GetValueAsUnsigned(0)
            if sc in (12, 13, 15):
                print(f"[xv6-chatdbg] Page fault! scause={{sc}} at attempt {{attempt}}")
                break

    # Not a fault — continue
    process.Continue()
    time.sleep(0.1)
    if process.GetState() != lldb.eStateStopped:
        time.sleep(1)
else:
    print("[xv6-chatdbg] WARNING: did not hit page fault in 200 attempts")
""",
        # Now we should be stopped at the fault. Load ChatDBG.
        f'command script import {CHATDBG_SRC / "chatdbg" / "chatdbg_lldb.py"}',
        f'why {question}',
        "quit",
    ]

    with open(script, "w") as f:
        for cmd in cmds:
            f.write(cmd + "\n")

    return script


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", required=True,
                        help="Path to the built xv6 directory (e.g. build-bug1)")
    parser.add_argument("--bug", required=True,
                        help="Bug ID (e.g. bug1-uvmcopy-perm)")
    parser.add_argument("--model", default="openrouter/openai/gpt-4o")
    parser.add_argument("--results-dir", default=None)
    parser.add_argument("--port", type=int, default=1234)
    parser.add_argument("--question", default=(
        "What is the root cause of this crash? Walk through the program state, "
        "identify the defect, and propose a fix in code."
    ))
    args = parser.parse_args()

    build_dir = Path(args.build_dir).resolve()
    kernel = build_dir / "kernel" / "kernel"
    if not kernel.exists():
        print(f"ERROR: kernel not found at {kernel}")
        sys.exit(1)

    bug_config = yaml.safe_load(
        (BUGS_DIR / f"{args.bug}.yaml").read_text()
    )

    model_slug = args.model.replace("/", "_")
    run_id = f"{bug_config['id']}__{model_slug}"
    results_dir = Path(args.results_dir or f"results/xv6-interactive") / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    collect_path = results_dir / "collect.json"

    # Write case.yaml
    with open(results_dir / "case.yaml", "w") as f:
        yaml.dump({
            "id": bug_config["id"],
            "language": "c",
            "source_file": bug_config["source_file"],
            "criteria": bug_config["criteria"],
        }, f)

    # Copy source file
    src = build_dir / bug_config["source_file"]
    dest = results_dir / bug_config["source_file"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy(src, dest)

    # Set env vars for ChatDBG
    os.environ["CHATDBG_MODEL"] = args.model
    os.environ["CHATDBG_COLLECT_DATA"] = str(collect_path)
    os.environ["CHATDBG_FORMAT"] = "text"
    os.environ["PYTHONPATH"] = str(CHATDBG_SRC)

    # Write LLDB script
    script = write_lldb_script(
        kernel, collect_path, args.model, None, args.question
    )

    print(f"[xv6-chatdbg] Bug: {args.bug}")
    print(f"[xv6-chatdbg] Model: {args.model}")
    print(f"[xv6-chatdbg] Results: {results_dir}")
    print(f"[xv6-chatdbg] Make sure QEMU is running: ")
    print(f"  qemu-system-riscv64 -machine virt -bios none \\")
    print(f"    -kernel {kernel} -m 128M -smp 1 -nographic \\")
    print(f"    -global virtio-mmio.force-legacy=false \\")
    print(f"    -drive file={build_dir}/fs.img,if=none,format=raw,id=x0 \\")
    print(f"    -device virtio-blk-device,drive=x0,bus=virtio-mmio-bus.0 \\")
    print(f"    -S -gdb tcp::1234")
    print()

    # Run LLDB
    start = time.time()
    proc = subprocess.run(
        ["lldb", "--batch", "-s", str(script)],
        capture_output=True, text=True, timeout=300,
        env={**os.environ},
    )
    elapsed = time.time() - start

    (results_dir / "lldb_stdout.log").write_text(proc.stdout)
    (results_dir / "lldb_stderr.log").write_text(proc.stderr)

    # Write result.json
    with open(results_dir / "result.json", "w") as f:
        json.dump({
            "run_id": run_id, "status": "ok",
            "exit_code": proc.returncode,
            "elapsed_s": elapsed, "model": args.model,
            "tool_config": "xv6_lldb_interactive",
            "tier": "xv6-interactive", "trial": 1,
            "case_id": bug_config["id"], "language": "c",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, f, indent=2)

    print(f"\n[xv6-chatdbg] Done in {elapsed:.1f}s")
    print(f"[xv6-chatdbg] Results: {results_dir}")
    if collect_path.exists():
        with open(collect_path) as f:
            c = json.load(f)
        if c.get("queries"):
            resp = c["queries"][0].get("response", "")[:500]
            print(f"\nModel response preview:\n{resp}")


if __name__ == "__main__":
    main()
