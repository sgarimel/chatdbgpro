#!/usr/bin/env python3
"""
Run all 4 tiers of xv6-bench on bug1-uvmcopy-perm across 4 models.

Tier 0: Garbage prompt (what ChatDBG currently produces), no tools
Tier 1: Enriched prompt (decoded RISC-V state, process info), no tools
Tier 2: Enriched prompt + LLDB tools only (no bash)
Tier 3: Enriched prompt + LLDB + bash tools

Tiers 0 and 1 are static (single prompt→response, no tool calls).
Tiers 2 and 3 use existing ablation data from the live LLDB runs.
"""
import json
import os
import shutil
import time
from pathlib import Path

import yaml
import litellm

SCRIPT_DIR = Path(__file__).resolve().parent
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
Your task:
1. Identify the root cause of the panic/fault.
2. Trace the bug to the specific file, function, and line.
3. Explain WHY the bug causes the observed behavior.
4. Propose a minimal code fix.
5. Explain the broader design principle violated."""


# ── Tier 0: Garbage prompt (what ChatDBG currently produces) ──────
TIER0_PROMPT = """\
The program has this stack trace:
```
[3 skipped frames...]
```

The program encountered the following error:
```
breakpoint 1 which has been deleted.
```

This was the command line:
```
./build-bug1-uvmcopy-perm/kernel/kernel
```

What is the root cause of this crash? Walk through the program state, \
identify the defect, and propose a fix in code. Cover both a minimal \
local fix and a more thorough root-cause fix if they differ."""


# ── Tier 1: Enriched prompt (decoded RISC-V state) ───────────────
TIER1_PROMPT = """\
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
For user-mode instruction fetch, both PTE_X (executable) and PTE_U (user-accessible)
must be set.

Since the parent process can execute code at the same virtual address without
faulting, the child's page table must have been set up differently during `fork()`.

## Source context: usertrap() in kernel/trap.c

```c
38  usertrap(void)
39  {
40    int which_dev = 0;
42    if((r_sstatus() & SSTATUS_SPP) != 0)    // <-- stopped here
43      panic("usertrap: not from user mode");
45    w_stvec((uint64)kernelvec);
47    struct proc *p = myproc();
48    p->trapframe->epc = r_sepc();
50    if(r_scause() == 8){
51      // system call ...
53    } else if((which_dev = devintr()) != 0){
55    } else {
57      printf("usertrap(): unexpected scause 0x%lx pid=%d\\n", r_scause(), p->pid);
58      setkilled(p);
59    }
```

## Key question

The child's page table was created by `uvmcopy()` during `fork()`.
Find the defect in the kernel that causes the child's pages to lack proper
permissions. The relevant files are kernel/vm.c, kernel/proc.c, kernel/riscv.h.

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


def write_run(run_dir: Path, bug_config: dict, prompt: str,
              llm_result: dict, model: str, tier: str):
    run_dir.mkdir(parents=True, exist_ok=True)

    with open(run_dir / "case.yaml", "w") as f:
        yaml.dump({
            "id": bug_config["id"], "language": "c",
            "source_file": bug_config["source_file"],
            "criteria": bug_config["criteria"],
        }, f, default_flow_style=False)

    # Copy buggy source
    src = SCRIPT_DIR / "build-bug1-uvmcopy-perm" / bug_config["source_file"]
    dest = run_dir / bug_config["source_file"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy(src, dest)

    with open(run_dir / "collect.json", "w") as f:
        json.dump({
            "meta": {"model": model, "benchmark": "xv6-tiers", "tier": tier},
            "instructions": SYSTEM,
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
            "tool_config": tier, "tier": tier, "trial": 1,
            "case_id": bug_config["id"], "language": "c",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, f, indent=2)


def main():
    bug_config = yaml.safe_load((BUGS_DIR / "bug1-uvmcopy-perm.yaml").read_text())
    run_name = f"xv6-all-tiers-{time.strftime('%Y%m%d_%H%M%S')}"
    results_dir = RESULTS_BASE / run_name

    # Only run tiers 0 and 1 (static, no tools needed)
    # Tiers 2 and 3 will be copied from existing ablation data
    tiers = [
        ("tier0_garbage_no_tools", TIER0_PROMPT),
        ("tier1_enriched_no_tools", TIER1_PROMPT),
    ]

    total = len(MODELS) * len(tiers)
    print(f"xv6 tier ablation: {len(MODELS)} models × {len(tiers)} static tiers = {total} runs")
    print(f"(Tiers 2/3 will be copied from existing LLDB ablation data)")
    print(f"Results: {results_dir}\n")

    idx = 0
    for tier_name, prompt in tiers:
        for model in MODELS:
            idx += 1
            model_slug = model.replace("/", "_")
            run_id = f"{bug_config['id']}__{model_slug}__{tier_name}"
            run_dir = results_dir / run_id

            short_model = model.split("/")[-1]
            print(f"[{idx}/{total}] {short_model} × {tier_name}...", end=" ", flush=True)

            try:
                result = call_llm(prompt, model)
                write_run(run_dir, bug_config, prompt, result, model, tier_name)
                print(f"OK ({result['total_tokens']} tok, {result['elapsed_s']:.1f}s)")
            except Exception as e:
                print(f"FAILED: {e}")

    # Copy tier 2/3 data from existing ablation
    ablation_dir = RESULTS_BASE / "xv6-ablation-20260503_131250"
    if ablation_dir.exists():
        print("\nCopying tier 2/3 from existing ablation data...")
        for model in MODELS:
            model_slug = model.replace("/", "_")
            for old_tier, new_tier in [
                ("tier1_lldb_only", "tier2_lldb_only"),
                ("tier2_lldb_plus_bash", "tier3_lldb_plus_bash"),
            ]:
                old_dir = ablation_dir / f"bug1-uvmcopy-perm__{model_slug}__{old_tier}"
                new_dir = results_dir / f"{bug_config['id']}__{model_slug}__{new_tier}"
                if old_dir.exists():
                    shutil.copytree(old_dir, new_dir, dirs_exist_ok=True)
                    print(f"  Copied {old_tier} → {new_tier} for {model.split('/')[-1]}")
                else:
                    print(f"  MISSING: {old_dir.name}")

    print(f"\nDone. Results: {results_dir}")
    print(f"Judge: cd .. && python3 bench/judge.py --judge-model openrouter/openai/gpt-4o {results_dir}")


if __name__ == "__main__":
    main()
