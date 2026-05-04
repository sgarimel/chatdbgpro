# xv6-bench: Novel Kernel Debugging Test Cases

A contribution of this paper: **3 novel, hand-crafted kernel bugs in xv6-riscv**
designed to evaluate LLM debugging capabilities on operating-system-level code
that is unlikely to appear verbatim in training data.

## Why xv6?

xv6 is a teaching OS used at MIT, Princeton, and hundreds of universities.
While models have likely seen the xv6 *source code* in training, these bugs are
**novel** — they are not from any standard assignment and do not appear in any
public repository. The xv6 codebase is the *environment*, not the test.

## The 3 Bugs

| Bug ID | File | Function | Bug Type | Description |
|--------|------|----------|----------|-------------|
| bug1-uvmcopy-perm | kernel/vm.c | uvmcopy() | permission_error | Strips PTE_U from child page table entries during fork(), causing user-mode page faults in child |
| bug2-pipewrite-off-by-one | kernel/pipe.c | pipewrite() | off_by_one | Increments user-buffer index by 2 instead of 1, skipping bytes and overshooting buffer |
| bug3-kalloc-double-link | kernel/kalloc.c | kalloc() | memory_corruption | Freelist head never advances — every allocation returns same physical page |

Each bug has:
- A **patch file** (`.patch`) that introduces the bug into clean xv6
- A **trigger program** (in `trigger-programs/`) that reliably reproduces the crash
- A **ground truth YAML** (`.yaml`) with criteria for judging root_cause, local_fix, global_fix

## Pipeline

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────┐
│ Build xv6   │────>│ Boot QEMU    │────>│ GDB captures │────>│ LLM     │
│ with bug    │     │ + GDB stub   │     │ panic state  │     │ diagnose│
│ + trigger   │     │ run trigger  │     │ (bt, frames, │     │         │
│             │     │              │     │  source ctx) │     │         │
└─────────────┘     └──────────────┘     └──────────────┘     └─────────┘
                                                                   │
                                                              ┌────▼────┐
                                                              │ Judge   │
                                                              │ (GPT-4o)│
                                                              └─────────┘
```

All steps run inside Docker for reproducibility. The host only needs Docker and
an OPENROUTER_API_KEY.

## Directory Structure

```
xv6-bench/
├── README.md              # This file
├── Dockerfile             # RISC-V toolchain + QEMU + GDB
├── run_all.sh             # Top-level entry point (run from host)
├── xv6-riscv/             # Clean xv6 source (git clone)
├── bugs/
│   ├── bug1-uvmcopy-perm.patch
│   ├── bug1-uvmcopy-perm.yaml      # Ground truth + judge criteria
│   ├── bug2-pipewrite-off-by-one.patch
│   ├── bug2-pipewrite-off-by-one.yaml
│   ├── bug3-kalloc-double-link.patch
│   └── bug3-kalloc-double-link.yaml
├── trigger-programs/
│   ├── trigfork.c          # Triggers bug1
│   ├── trigpipe.c          # Triggers bug2
│   └── trigalloc.c         # Triggers bug3
├── scripts/
│   ├── build_bug.sh        # Build xv6 with a specific bug
│   ├── run_qemu_gdb.sh     # Boot QEMU, capture panic in GDB
│   └── run_xv6_bench.py    # Orchestrator: build → capture → LLM → results
├── configs/
└── results/                # Output (per-run directories)
```

## Usage

```bash
cd chatdbgpro/xv6-bench
export OPENROUTER_API_KEY=sk-or-...
bash run_all.sh
```

## Output Format

Each run produces the standard pipeline format compatible with `bench/judge.py`:

```
results/<run_name>/<bug_id>__<model_slug>/
├── case.yaml        # Ground truth criteria
├── collect.json     # Full prompt + response + token stats
├── result.json      # Run metadata (timing, model, status)
├── score.json       # Judge scores (after judge step)
└── crash_state/
    ├── backtrace.txt
    ├── frames.json
    └── panic_msg.txt
```

## Reproducibility

Everything is containerized:
- **Compiler**: `riscv64-linux-gnu-gcc` (Ubuntu 22.04 package)
- **Emulator**: `qemu-system-riscv64` (Ubuntu 22.04 package)
- **Debugger**: `gdb-multiarch` (Ubuntu 22.04 package)
- **xv6 source**: Pinned to a specific commit (git clone from mit-pdos/xv6-riscv)

The same Docker image, patches, and trigger programs will produce identical
crash states on any host. Only the LLM responses vary.
