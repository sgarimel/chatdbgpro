# ChatDBG ablation bench

A reproducible harness for sweeping **(model × tool_config × test case)**
on top of [ChatDBG](https://github.com/plasma-umass/ChatDBG), with a
3-axis LLM-as-judge evaluator that mirrors the paper's proximate-cause
vs. root-cause rubric (Table 5 of Levin et al. 2025).

```
bench/
├── cases/                    # test-case database (see "Test cases" below)
│   ├── off-by-one-crc/
│   │   ├── program.c
│   │   └── case.yaml         # metadata + judging criteria
│   └── ...
├── configs/                  # tool-ablation presets (JSON)
│   ├── all_tools.json
│   ├── no_tools.json
│   ├── debug_only.json
│   └── with_oracle.json      # frontier-model-as-tool ablation
├── orchestrator.py           # (case × model × config × trial) sweep
├── judge.py                  # LLM-as-judge evaluator
├── analyze.py                # aggregates scored runs into CSVs + report.md
├── prompts/                  # judge system / user prompt templates
├── Makefile                  # make bench | make judge | make report
└── results/                  # per-run artifacts (gitignored)
```

## One-shot end-to-end

```bash
export OPENROUTER_API_KEY=...
export OPENAI_API_KEY=...     # only if the judge model goes via openai/

cd bench
make all \
    MODELS="openrouter/moonshotai/kimi-k2.5 openrouter/nvidia/nemotron-nano-9b-v2" \
    CONFIGS="all_tools debug_only no_tools" \
    TRIALS=3 \
    JUDGE_MODEL=openrouter/openai/gpt-5
```

Artifacts land in `bench/results/run-<timestamp>/`:
```
<run_id>/
    case.yaml        pinned copy of the test-case metadata (judge input)
    program.c        pinned copy of the buggy source
    compile.log      compiler invocation + warnings
    session.cmds     the lldb/gdb batch script we drove
    stdout.log       debugger + ChatDBG stdout
    stderr.log       debugger + ChatDBG stderr
    collect.json     structured ablation data (tool calls, tokens, ...)
    result.json      run-level metadata (status, elapsed, model, ...)
    score.json       3-axis judge scores + rationales   (after `make judge`)
```

## Test cases

Each case lives in its own directory with two files: the buggy program
and a `case.yaml` that records metadata + judging criteria. The criteria
are **pre-registered**: they are written before any model is run, so the
judge is evaluating against a fixed target rather than a post-hoc rubric.

Schema:

```yaml
id: <unique-id>
language: c | cpp
source_file: program.c

build:
  compiler: clang | clang++
  flags: ["-g", "-O0", "-fsanitize=address", ...]

run:
  args: []
  stdin: ""
  env: {}
  clean_env: false          # strip USER/LOGNAME/... before launch
  expected_crash: true

bug:
  category: off_by_one | heap_overflow | use_after_free | ...
  error_type: <finer-grained>
  root_cause_lines: [14]
  related_lines: []

criteria:
  root_cause:  "Prose description of what a correct diagnosis must say."
  local_fix:   "Prose description of an acceptable proximate-cause fix."
  global_fix:  "Prose description of an acceptable root-cause fix."
```

The three criteria are independent 0/1 axes:
- **root_cause** — did the response correctly name the defect?
- **local_fix** — does the proposed fix eliminate the immediate symptom?
- **global_fix** — does it address the underlying design flaw?

This mirrors the paper's "proximate cause" / "root cause" columns in
Table 5. All eight shipped cases are new (not from BugBench or BugsC++)
to mitigate training-data leakage on the models we're evaluating.

### Shipped cases

| ID                           | Class                | Language |
|------------------------------|----------------------|----------|
| off-by-one-crc               | off-by-one read      | C        |
| uninit-stack-accumulator     | uninitialized memory | C        |
| signed-unsigned-loop         | unsigned underflow   | C++      |
| heap-overflow-csv            | 1-byte heap OOB write| C        |
| double-free-errpath          | dangling member free | C        |
| uaf-linked-list              | use-after-free       | C++      |
| intoverflow-alloc            | size-mul overflow    | C++      |
| null-deref-env               | missing null check   | C        |

Add a new case by creating a directory under `cases/` containing
`program.{c,cpp}` and a `case.yaml`. Nothing else is required —
`orchestrator.py` auto-discovers every directory with a `case.yaml`.

## Ablation axes

### Models (`--models`)

Any LiteLLM path. The orchestrator sweeps them independently via ChatDBG's
existing `CHATDBG_MODEL` env var, so no code change is needed per model:

```
openai/gpt-4o
openai/gpt-5
openrouter/moonshotai/kimi-k2.5
openrouter/nvidia/nemotron-nano-9b-v2
openrouter/qwen/qwen-3-30b
```

### Tool configs (`--tool-configs`)

Each preset is a JSON map of the feature flags declared in
`src/chatdbg/util/config.py::_tool_flags`. For C/C++ runs the relevant
flags are:

| Flag                         | Tool                    |
|------------------------------|-------------------------|
| `enable_native_debug`        | run lldb/gdb commands   |
| `enable_get_code_surrounding`| show source at location |
| `enable_find_definition`     | clangd LSP lookup       |
| `enable_oracle`              | escalate to frontier LLM (see below) |

### Stack-trace depth (`--context-lines`)

ChatDBG's `context` config (default 10) controls how many lines of
source appear around each frame in the enriched stack trace. The
orchestrator exposes it as a sweep via `CHATDBG_CONTEXT`:

```bash
python orchestrator.py --context-lines 3 10 30 ...
```

This lets you reproduce the paper's "Default Stack (5 lines) vs Enriched
Stack (10 lines)" ablation — and go further.

### Frontier-model oracle tool

`enable_oracle` exposes a new tool `ask_oracle(question)` that routes a
single hard question from the model-under-test to a stronger model
(set via `CHATDBG_ORACLE_MODEL`, default `openrouter/openai/gpt-5`).
The oracle has no access to the program state — the caller must include
all necessary context in the question. Its tokens are recorded in the
returned text so `analyze.py` can account for the extra cost.

This implements the "small-model-with-oracle-escalation" ablation from
the project plan: does a weak model that *knows when it's stuck* match a
strong model that does everything itself?

## Judge

`judge.py` reads each run directory, pulls the model-under-test's
response and the pre-registered criteria, and asks a judge model for a
single JSON object:

```json
{
  "root_cause": 0 or 1,
  "local_fix":  0 or 1,
  "global_fix": 0 or 1,
  "rationale": { "root_cause": "...", "local_fix": "...", "global_fix": "..." }
}
```

The system prompt is deliberately strict: vague-but-fluent prose earns
no points; a fix described in prose counts only if every change is
explicit. See `prompts/judge_system.txt`.

Run it after a sweep:

```bash
python judge.py bench/results/run-20260417-120000 \
    --judge-model openrouter/openai/gpt-5
```

The judge is **stateless per run**: re-running it only re-scores runs
that don't yet have a `score.json` (pass `--overwrite` to force).

## Analysis

```bash
python analyze.py bench/results/run-20260417-120000
```

Writes `analysis/` alongside the run containing:

- `runs.csv` — one row per run, every axis flat
- `summary_by_model.csv` — means across all configs/cases for each model
- `summary_by_config.csv` — means across all models/cases for each config
- `summary_by_model_config.csv` — the cross
- `summary_by_case.csv` — per-case difficulty
- `report.md` — human-readable markdown rollup

Every summary reports mean score on each axis plus **input/output tokens,
tool calls, and code-output length** averaged over the group, so
compute/cost tradeoffs and model behaviour can be read off directly.

## Reproducing the paper's C/C++ axes

| Paper config  | Here                               |
|---------------|------------------------------------|
| Default Stack | `CONFIGS=no_tools CONTEXT=5`       |
| Enriched Stack| `CONFIGS=no_tools CONTEXT=10`      |
| + Take Wheel  | `CONFIGS=all_tools CONTEXT=10`     |
| + Targeted Q. | same as above; edit `DEFAULT_QUESTION` in `orchestrator.py` to use a case-specific question |
| + Dialog      | not yet; requires a follow-up driver (future work) |

## Caveats

- **Darwin default → lldb.** On Linux the orchestrator auto-selects
  gdb if lldb isn't present. The gdb path shares the same ChatDBG
  module (`chatdbg.chatdbg_gdb`) but has had less coverage here;
  expect to iterate on the gdb batch script for your toolchain.
- **API keys.** The orchestrator runs entirely locally, but the
  model-under-test and the judge both call external APIs. Make sure
  `OPENROUTER_API_KEY` / `OPENAI_API_KEY` / etc. are set.
- **AddressSanitizer.** Most shipped cases compile with ASan so they
  crash deterministically even for bugs that wouldn't segfault under
  vanilla builds. On macOS you may need `brew install llvm` if the
  system clang is too old.
