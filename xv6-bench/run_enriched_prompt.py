#!/usr/bin/env python3
"""
Test whether an enriched prompt (with decoded RISC-V trap info) helps
models debug in LLDB-only mode (no bash).

Compares:
  - Current prompt: "[3 skipped frames...], breakpoint 1 deleted"
  - Enriched prompt: decoded scause, faulting address, process info, source context
"""
import json
import os
import shutil
import time
from pathlib import Path

import yaml
import litellm

SCRIPT_DIR = Path(__file__).resolve().parent
XV6_SRC = SCRIPT_DIR / "xv6-riscv"
BUGS_DIR = SCRIPT_DIR / "bugs"
RESULTS_BASE = SCRIPT_DIR / "results"

MODELS = [
    "openrouter/openai/gpt-4o",
    "openrouter/meta-llama/llama-3.1-8b-instruct",
    "openrouter/nvidia/nemotron-3-nano-30b-a3b",
    "openrouter/qwen/qwen3-30b-a3b-instruct-2507",
]

SYSTEM = """\
You are a kernel debugging assistant analyzing an xv6 operating system trap.
You have access to LLDB connected to the xv6 kernel via QEMU's GDB stub.

Available tools:
- `debug <cmd>`: Run an LLDB command (bt, frame variable, register read, \
expression, source list, etc.)
- `get_code_surrounding <file>:<line>`: Read source code around a line

You do NOT have bash/shell access. Use only debugger commands and source reading.

Your task:
1. Analyze the trap state and registers to understand what happened.
2. Trace the fault back to the kernel function that caused it.
3. Identify the specific file, function, and line with the defect.
4. Explain WHY the bug causes this fault.
5. Propose a minimal fix."""


ENRICHED_PROMPT = """\
The xv6 kernel has trapped while handling a user-space process.
The debugger (LLDB) is stopped inside `usertrap()` at kernel/trap.c:42.

## Trap State (from RISC-V CSR registers)

| Register | Value | Meaning |
|----------|-------|---------|
| scause | 12 | **Instruction page fault** — the CPU tried to fetch an instruction but the page table denied access |
| sepc | 0x370 | The user-space virtual address of the instruction that faulted |
| stval | 0x370 | Same as sepc for instruction faults — the faulting address |
| sstatus | 0x200000020 | Previous mode was User (SPP=0), interrupts were enabled |

## Process Context

- The faulting process is a **child process** that was just created via `fork()`.
- The **parent process** (init, pid=1) does NOT experience this fault.
- The child dies immediately upon trying to execute its first instruction.
- The fault address 0x370 is within the child's text segment (executable code).

## What this means

An instruction page fault (scause=12) at a valid text address means the page
table entry for this address exists but **lacks the necessary permission bits**.
The CPU checks the PTE permission bits (R/W/X/U) on every memory access.
For user-mode instruction fetch, both PTE_X (executable) and PTE_U (user-accessible)
must be set.

Since the parent process can execute code at the same virtual address without
faulting, the child's page table must have been set up differently from the
parent's during `fork()`.

## Source context: usertrap() in kernel/trap.c

```c
37  uint64
38  usertrap(void)
39  {
40    int which_dev = 0;
41
42    if((r_sstatus() & SSTATUS_SPP) != 0)    // <-- LLDB stopped here
43      panic("usertrap: not from user mode");
44
45    w_stvec((uint64)kernelvec);
46
47    struct proc *p = myproc();
48    p->trapframe->epc = r_sepc();
49
50    if(r_scause() == 8){
51      // system call
52      ...
53    } else if((which_dev = devintr()) != 0){
54      // device interrupt
55    } else {
56      // UNEXPECTED FAULT — this is the branch we hit
57      printf("usertrap(): unexpected scause 0x%lx pid=%d\\n", r_scause(), p->pid);
58      setkilled(p);
59    }
```

## Key question

The child's page table was created by `uvmcopy()` during `fork()`.
Find the defect in the kernel that causes the child's page table entries
to lack proper permissions. Look at how `uvmcopy()` copies PTEs from
parent to child.

The relevant kernel source files are:
- kernel/vm.c — contains uvmcopy(), mappages(), walk()
- kernel/proc.c — contains kfork() which calls uvmcopy()
- kernel/riscv.h — defines PTE flags (PTE_V, PTE_R, PTE_W, PTE_X, PTE_U)

What is the root cause? Identify the exact file, function, and line."""


def call_llm(prompt: str, model: str) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM},
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


def main():
    bug_config = yaml.safe_load((BUGS_DIR / "bug1-uvmcopy-perm.yaml").read_text())
    run_name = f"xv6-enriched-{time.strftime('%Y%m%d_%H%M%S')}"
    results_dir = RESULTS_BASE / run_name

    print(f"Enriched prompt ablation: {len(MODELS)} models")
    print(f"Results: {results_dir}\n")

    for i, model in enumerate(MODELS):
        model_slug = model.replace("/", "_")
        run_id = f"{bug_config['id']}__{model_slug}__enriched"
        run_dir = results_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        print(f"[{i+1}/{len(MODELS)}] {model.split('/')[-1]}...", end=" ", flush=True)

        try:
            result = call_llm(ENRICHED_PROMPT, model)
            print(f"OK ({result['total_tokens']} tok, {result['elapsed_s']:.1f}s)")

            # Write case.yaml
            with open(run_dir / "case.yaml", "w") as f:
                yaml.dump({
                    "id": bug_config["id"],
                    "language": "c",
                    "source_file": bug_config["source_file"],
                    "criteria": bug_config["criteria"],
                }, f, default_flow_style=False)

            # Copy buggy source
            src = SCRIPT_DIR / "build-bug1-uvmcopy-perm" / bug_config["source_file"]
            dest = run_dir / bug_config["source_file"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy(src, dest)

            # Write collect.json
            with open(run_dir / "collect.json", "w") as f:
                json.dump({
                    "meta": {"model": model, "benchmark": "xv6-enriched"},
                    "instructions": SYSTEM,
                    "queries": [{
                        "user_text": ENRICHED_PROMPT,
                        "prompt": ENRICHED_PROMPT,
                        "thinking": "",
                        "response": result["response"],
                        "code_blocks": [], "total_code_length": 0,
                        "num_tool_calls": 0, "tool_calls": [],
                        "tool_frequency": {},
                        "stats": {
                            "prompt_tokens": result["prompt_tokens"],
                            "completion_tokens": result["completion_tokens"],
                            "total_tokens": result["total_tokens"],
                        },
                    }],
                }, f, indent=2)

            # Write result.json
            with open(run_dir / "result.json", "w") as f:
                json.dump({
                    "run_id": run_id, "status": "ok", "exit_code": 0,
                    "elapsed_s": result["elapsed_s"], "model": model,
                    "tool_config": "enriched_prompt_no_tools",
                    "tier": "enriched", "trial": 1,
                    "case_id": bug_config["id"], "language": "c",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }, f, indent=2)

        except Exception as e:
            print(f"FAILED: {e}")

    print(f"\nDone. Judge: cd .. && python3 bench/judge.py --judge-model openrouter/openai/gpt-4o {results_dir}")


if __name__ == "__main__":
    main()
