# Benchmark Results — Data Map

Last updated: 2026-05-04

## Primary Sweep Data (use these for paper figures)

### T1 and T2: `synth-8model-sweep/`

| Tier | Runs | Cases | Models | Config | Notes |
|------|------|-------|--------|--------|-------|
| T1 (bash only) | 200 | 25 | 8 | `tier1_bash_only.json` | mini-swe-agent, stateless bash |
| T2 (bash+gdb) | 200 | 25 | 8 | `tier2_gdb_plus_bash.json` | mini-swe-agent, unrestricted gdb |

T1/T2 scores are in `score.json` (judged by `openrouter/openai/gpt-4o`).

This directory also contains 168 **old fenced T3 runs** (`tier3_gdb_only.json`)
with the restricted safety.py allowlist and generic prompt. These are superseded
by `synth-t3-unfenced/` but kept for fenced-vs-unfenced comparison.

### T3 Unfenced Baseline: `synth-t3-unfenced/`

| Runs | Cases | Models | Config | Status |
|------|-------|--------|--------|--------|
| 168 | 21 | 8 | `t3_unfenced.json` | COMPLETE |

Fixes applied vs old T3:
- `CHATDBG_UNSAFE=true` — all lldb commands unfenced (break, step, continue,
  disassemble, x, etc. all work). Previously safety.py blocked ~95% of commands.
- Enriched prompt — source file name, expected behavior, case description
  passed via `CHATDBG_PROMPT_*` env vars (matching T1/T2/T4 info).
- Structured output — instructions require ROOT CAUSE / LOCAL FIX / GLOBAL FIX
  (matching T1/T2/T4 format).
- No shell references — removed misleading `ls`/`find` guidance when bash is off.

### T3 Unfenced + Check-My-Work: `synth-t3-unfenced-cmw/`

| Runs | Cases | Models | Config | Status |
|------|-------|--------|--------|--------|
| 168 | 21 | 8 | `t3_unfenced_cmw.json` | IN PROGRESS (118/168) |

Same fixes as `synth-t3-unfenced/` plus the CMW judge feedback loop.
Judge model: `openrouter/openai/gpt-4o`, max stale checks: 2.
No bash confound (unlike the archived `synth-cmw-t3-sweep/` which had bash on).

### T4 Claude Code: `synth-t4-sweep/`

| Runs | Cases | Models | Config |
|------|-------|--------|--------|
| 21 | 21 | 1 (Claude) | `tier4_claude_code.json` |

## 8 Models

All sweeps use the same 8 models (OpenRouter):

| Short Name | Full Model ID |
|------------|--------------|
| GPT-5.5 | `openrouter/openai/gpt-5.5` |
| GPT-4o | `openrouter/openai/gpt-4o` |
| Grok-4 | `openrouter/x-ai/grok-4` |
| Sonnet-4.5 | `openrouter/anthropic/claude-sonnet-4-5` |
| Gemini-2.5 | `openrouter/google/gemini-2.5-flash` |
| Qwen-30B | `openrouter/qwen/qwen3-30b-a3b-instruct-2507` |
| Nemotron-30B | `openrouter/nvidia/nemotron-3-nano-30b-a3b` |
| Llama-8B | `openrouter/meta-llama/llama-3.1-8b-instruct` |

## How to Read the Data

### Scores (after running `bench/judge.py`)
```python
import json
score = json.load(open("<run_dir>/score.json"))
score["scores"]  # {"root_cause": 0|1, "local_fix": 0|1, "global_fix": 0|1}
```

### Tool Calls (T3 unfenced — see which lldb commands models use)
```python
import json
c = json.load(open("<run_dir>/collect.json"))
q = c["queries"][0]
q["tool_frequency"]   # e.g. {"code": 5, "bt": 2, "breakpoint": 3, "run": 2}
q["num_tool_calls"]   # total count
for tc in q["tool_calls"]:
    print(tc["tool_name"], tc["call"], tc["result_length"])
```

### Check-My-Work Data (CMW runs only)
```python
c = json.load(open("<run_dir>/collect.json"))
cmw = c["check_my_work"]
cmw["num_checks"]           # how many judge rounds
cmw["final_scores"]         # {"root_cause": 0|1, ...}
cmw["checks_to_root_cause"] # check # where RC first scored 1 (or None)
cmw["checks_to_local_fix"]
cmw["checks_to_global_fix"]
cmw["stale_exit"]           # True if model couldn't improve
cmw["history"]              # per-check scores + feedback
```

### Result Metadata
```python
r = json.load(open("<run_dir>/result.json"))
r["status"]       # "ok", "timeout", "skipped_platform", "no_collect"
r["elapsed_s"]    # wall-clock seconds
r["model"]        # full model ID
r["case_id"]      # case name
r["tier"]         # 1, 2, 3, or 4
r["tool_config"]  # config file name
```

## Other Experiment Data (not primary sweeps)

| Directory | What |
|-----------|------|
| `bugbench-t1/`, `bugbench-t2/`, `bugbench-t3/` | BugBench real C bugs (4 cases, 5 models) |
| `merged-yara-pilot/` | Yara cross-tier pilot (T1-T4, 3 models) |
| `adroit-yara-*` | Yara runs on Adroit HPC |
| `nemotron-full/` | Nemotron-30B on 158 BugsCPP cases |
| `overnight-tier1-*` | BugsCPP overnight T3 run (632 runs, 4 models) |
| `synth-ctx5/`, `synth-ctx20/`, `synth-ctx999/` | Context-line ablations |
| `synth-gdb-cheatsheet/` | GDB cheatsheet in system prompt ablation |

## Archived (in `_archive/`)

| Directory | Why Archived |
|-----------|-------------|
| `synth-cmw-t3-sweep/` | Old CMW with fenced GDB + bash confound. Superseded by `synth-t3-unfenced-cmw/` |
| `cmw-test-*` | CMW development smoke tests |
| `SAMPLEpaper-ablation-4models/` | Early 4-model pilot |
| `ablation-4models-v2/` | Early 4-model pilot v2 |
| `synth-7cases-both-models/` | Early 2-model test |
| `synth-full-8model/` | Partial early 8-model run |
| `synthetic-7case-2model/` | Early 2-model test |
| `full-synthetic-sweep/` | Single-case test |
| Various smoke/dry-run tests | Development artifacts |

## Key Confounds to Know About

1. **T3 fenced vs unfenced**: The old T3 in `synth-8model-sweep/` used `safety.py`
   which blocked break/step/continue/disassemble/x etc. The new T3 in
   `synth-t3-unfenced/` has `CHATDBG_UNSAFE=true`. Compare these to measure
   the impact of command restrictions.

2. **T2 uses gdb-in-Docker, T3 uses lldb-on-macOS**: On macOS, T2 runs inside a
   Linux Docker container (gdb), while T3 runs lldb natively. Different debuggers,
   different platforms.

3. **T3 has code/LSP tools that T1/T2 don't**: T3 gets `get_code_surrounding` and
   `find_definition`; T1/T2 only have bash (T1) or bash+gdb (T2).

4. **Old CMW had bash confound**: `synth-cmw-t3-sweep/` (archived) used
   `with_cmw.json` which enabled bash. The new `synth-t3-unfenced-cmw/` uses
   `t3_unfenced_cmw.json` with bash disabled — clean comparison.
