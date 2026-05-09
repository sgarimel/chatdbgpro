# ChatDBG-Pro: Comprehensive Results Analysis

**Data sources:** T1/T2 from `synth-8model-sweep/` (200 runs each), T3 from `synth-t3-unfenced/` (169 runs, 155 ok), T3+CMW from `synth-t3-unfenced-cmw/` (107 ok), T4 from `synth-t4-sweep/` (20 scored). All T3 data uses `unsafe=true` (unfenced LLDB). Judge: `gpt-4o`. 21 synthetic C/C++ cases, 8 models.

---

## 1. Cross-Tier Model Rankings

### T1 — Bash Only (no debugger)

| Model | N (ok) | Mean Score | Perfect (3/3) | Zero (0/3) | Mean Tools | Timeouts |
|-------|--------|-----------|---------------|------------|------------|----------|
| GPT-5.5 | 24 | **2.88** | 23 | 1 | 5.9 | 0 |
| Sonnet-4.5 | 23 | 2.70 | 18 | 1 | 9.1 | 1 |
| Grok-4 | 15 | 2.60 | 10 | 0 | 4.9 | 9 |
| Gemini-FL | 22 | 2.50 | 13 | 1 | 4.5 | 2 |
| Qwen-30B | 23 | 2.13 | 14 | 5 | 7.4 | 1 |
| GPT-4o | 24 | 1.88 | 8 | 5 | 5.2 | 0 |
| Nemotron-30B | 14 | 0.21 | 1 | 13 | 7.5 | **10** |
| Llama-8B | 23 | 0.17 | 0 | 20 | 4.6 | 1 |

**Key insight:** Without a debugger, models rely entirely on reading source + crash output via bash. GPT-5.5 nearly perfect-scores with minimal tooling (5.9 calls/run). Nemotron-30B times out in 10/24 runs — it struggles to compose bash commands into a coherent investigation pipeline. Llama-8B gets zero on 87% of runs despite similar tool-call volume (4.6/run) — it uses tools but can't synthesize findings.

### T2 — Bash + GDB

| Model | N (ok) | Mean Score | Perfect | Zero | Mean Tools | Timeouts |
|-------|--------|-----------|---------|------|------------|----------|
| GPT-5.5 | 24 | **2.75** | 20 | 1 | 6.8 | 0 |
| Grok-4 | 10 | 2.60 | 6 | 0 | 4.9 | **14** |
| Sonnet-4.5 | 23 | 2.35 | 12 | 1 | 10.0 | 1 |
| Gemini-FL | 21 | 2.10 | 7 | 1 | 5.1 | 3 |
| Qwen-30B | 19 | 2.05 | 8 | 2 | 7.1 | 5 |
| GPT-4o | 24 | 1.79 | 6 | 4 | 7.0 | 0 |
| Llama-8B | 23 | 0.61 | 0 | 14 | 4.8 | 1 |
| Nemotron-30B | 5 | 0.40 | 0 | 4 | 8.0 | **19** |

**Key insight:** Adding GDB access doesn't uniformly help. T2 scores are *lower* than T1 for most models. The timeout rate explodes: Nemotron-30B times out on 19/24 runs (vs 10 in T1), and Grok-4 on 14/24. These models get stuck in GDB — they issue commands, get confused by the output, and loop until timeout. **GDB is a trap for models that can't interpret debugger output.**

### T3 — ChatDBG/LLDB (unfenced, unsafe=true)

| Model | N (ok) | Mean Score | Perfect | Zero | Mean Tools | Timeouts |
|-------|--------|-----------|---------|------|------------|----------|
| GPT-5.5 | 20 | **2.70** | 18 | 2 | 21.7 | 0 |
| Qwen-30B | 18 | 2.61 | 13 | 1 | 9.1 | 2 |
| Sonnet-4.5 | 18 | 2.44 | 13 | 2 | 15.4 | 2 |
| GPT-4o | 20 | 2.30 | 9 | 1 | 1.9 | 0 |
| Nemotron-30B | 20 | 2.30 | 14 | 4 | 1.9 | 0 |
| Gemini-FL | 20 | 1.80 | 6 | 5 | 9.6 | 0 |
| Grok-4 | 19 | 1.00 | 4 | 11 | 1.7 | 1 |
| Llama-8B | 20 | 0.70 | 0 | 10 | 3.3 | 0 |

**Key insight:** ChatDBG's structured prompt (enriched stack trace + source context + custom tools) dramatically reduces timeouts. Nemotron-30B goes from 19 timeouts in T2 to **zero** in T3, and its score jumps from 0.40 to 2.30. The structured prompt does the heavy lifting that the model couldn't do by itself. GPT-4o and Nemotron-30B both average only 1.9 tool calls — they rely on the enriched initial prompt, not exploration.

### T4 — Claude Code (full agent)

| Metric | Value |
|--------|-------|
| N (scored) | 20 |
| Mean Score | **2.45** |
| Perfect (3/3) | 11 |

### T3+CMW — Check-My-Work feedback loop (unfenced)

| Model | N | Mean Score | Perfect | Mean Checks |
|-------|---|-----------|---------|-------------|
| Sonnet-4.5 | 13 | **3.00** | 13 | 2.15 |
| GPT-4o | 15 | 2.80 | 13 | 2.33 |
| GPT-5.5 | 14 | 2.79 | 13 | 1.07 |
| Gemini-FL | 14 | 2.79 | 12 | 2.57 |
| Nemotron-30B | 13 | 2.46 | 8 | 2.77 |
| Qwen-30B | 11 | 2.36 | 6 | 2.55 |
| Grok-4 | 13 | 2.23 | 9 | 2.08 |
| Llama-8B | 14 | 1.43 | 3 | 2.71 |

**Key insight:** Iterative feedback benefits mid-tier models the most. Sonnet-4.5 achieves 3.00 (perfect across all runs) with CMW vs 2.44 without — a +0.56 lift. GPT-4o jumps from 2.30 to 2.80. GPT-5.5 gets nearly identical scores (2.79 vs 2.70) with only 1.07 checks — it gets the answer right on the first try. Llama-8B can't self-correct (1.43, needing 2.71 checks on average). **CMW is most valuable for the middle of the model distribution.**

---

## 2. Model Behavioral Profiles

### GPT-5.5: The Heavy Explorer
- **Highest tool usage across all models** in T3: 21.7 calls/run (next highest: Sonnet at 15.4)
- Diverse command vocabulary: `code` (4.3), `p` (4.3), `definition` (3.7), `frame` (3.4), `expr` (1.2)
- The **only model that reliably solves multi-step reasoning bugs** like `uninit-stack-accumulator` (38 tool calls, traversing MSan's report through source)
- Never times out in T3. Only 1 timeout across all tiers.
- With CMW, needs only 1.07 checks — it gets the answer right first try
- **Tradeoff:** 78.7s mean elapsed in T3, vs 22.9s for GPT-4o

### GPT-4o: The Minimalist
- **Fewest tool calls in T3:** 1.9/run, tied with Nemotron-30B
- Almost exclusively uses `code` (1.4/run) and `definition` (0.55/run) — never uses `p`, `frame`, or `bt`
- **14 of 20 ok runs used zero tools** — answered entirely from the enriched stack trace prompt
- Among zero-tool runs, scores 2.43 — the best zero-tool scorer of any model
- **Reads the prompt, doesn't explore.** This works well on simple bugs but leaves it at 2.30 overall (mid-pack)
- Strong CMW responder: jumps from 2.30 → 2.80 with feedback

### Sonnet-4.5: The Methodical Debugger
- 15.4 tools/run in T3 — second-highest after GPT-5.5
- Heavy `p`/print usage (4.78/run) — the most variable-inspection of any model
- Uses `bt` (0.83/run) more than most — actually backtrace-oriented
- **Perfect 3.00 with CMW** — the biggest CMW beneficiary. Reliably self-corrects
- Occasionally times out (2 in T3) — willing to spend time on hard cases

### Qwen-30B (3B active): The Stack Walker
- **Frame navigation specialist:** 3.06 `frame` calls/run — highest of any model
- Also uses `register` (0.44/run) — the only model that inspects registers meaningfully
- 2.61 mean score in T3 — **outperforms GPT-4o** (2.30) despite being 10x smaller
- Known "hallucinated sandbox" failure mode: occasionally misinterprets LLDB output as denial-of-access and bails (Mode B)
- 2 timeouts in T3 from getting stuck in exploration loops

### Nemotron-30B (3B active): The One-Shot Reader
- **1.9 tools/run in T3** — reads the enriched prompt, produces an answer, done
- 8 of 20 ok runs used zero tools. Among those, scores 1.62
- **Most dramatic tier dependence:** 0.21 (T1, 10 timeouts) → 0.40 (T2, 19 timeouts) → 2.30 (T3, 0 timeouts)
- When given a structured prompt with source context, performs comparably to GPT-4o
- Without structure, gets stuck in bash loops and times out. **This model cannot self-direct.**
- Uses almost exclusively `code` (1.65/run) — no variable inspection, no frame navigation

### Gemini-FL: The Execution-Control Experimenter
- Unique tool profile: heavy on `breakpoint` (2.05/run), `run` (1.85/run) — tries to **re-execute** the program
- Only model with significant execution-control usage — others inspect the crash state
- Known "tool-loop empty answer" failure (Mode C): 9 of 11 zero-score runs have response length ≈ number of tool calls (one newline per tool turn, no prose synthesis)
- Example: `uninit-stack-accumulator` — 41 tool calls, 41-char response (all newlines)
- Uses `ls` in the LLDB context (17× on one case) — hallucinating shell commands into the debugger
- **Mean score degrades from T1 (2.50) to T3 (1.80):** the additional tool surface actually hurts this model

### Grok-4: The Silent Timer
- **Catastrophic timeout rate:** 9/24 T1, 14/24 T2, 1/21 T3
- In T3 where it completes: only 1.7 tools/run, 1.00 mean score, 11 zero-score runs
- Of 19 ok runs, 58% score zero — the worst completion-quality of any model
- Extremely long elapsed times even on ok runs: 97.4s mean in T3
- Appears to spend most of its budget on internal reasoning, not tool use

### Llama-8B: The Floor
- **Zero perfect scores across any tier.** Best: T3 at 0.70 mean
- 10 zero-score runs in T3 (50%), 20 in T1 (87%)
- 3.3 tools/run — modest engagement but no synthesis ability
- Uses `code` (1.25) and `expr` (0.80) — can operate tools but can't compose findings into a diagnosis
- With CMW: 1.43 mean score, 2.71 checks — **cannot self-correct.** Iterative feedback doesn't help at this model scale
- 7 zero-tool runs → all score 0. Cannot answer from prompt alone either

---

## 3. Tool Usage and What Predicts Success

### Which LLDB Commands Correlate with Score (Spearman r, n=155)

| Command | Total Calls | Spearman r | p-value | Interpretation |
|---------|------------|-----------|---------|---------------|
| `frame` | 199 | **+0.41*** | <0.0001 | Strongest predictor — navigating stack frames matters most |
| `code` | 277 | **+0.35*** | <0.0001 | Reading source context strongly predicts success |
| `p`/`print` | 258 | **+0.30*** | 0.0001 | Variable inspection is the 3rd strongest signal |
| `definition` | 146 | **+0.26**  | 0.001 | Symbol lookup helps |
| `bt` | 41 | **+0.22**  | 0.006 | Backtrace useful but less than frame/code |
| `breakpoint` | 64 | +0.04 | 0.62 | No significant relationship |
| `run` | 63 | +0.09 | 0.24 | No significant relationship |
| `expr` | 50 | +0.07 | 0.38 | No significant relationship |
| `continue` | 12 | -0.02 | 0.84 | No relationship |
| `next` | 6 | +0.02 | 0.79 | Almost never used |
| `step` | 1 | -0.03 | 0.70 | Essentially unused |

**The winning debugging strategy is inspect-not-execute:** `frame` → `code` → `p`. Navigate the stack, read the source around each frame, print variable values. Models that try to re-execute (`breakpoint` + `run` + `continue`) don't score better — and sometimes score worse (Gemini-FL).

### What `code`, `frame`, and `definition` Actually Do

These are ChatDBG's custom tools, not raw LLDB commands:

- **`code`** = `get_code_surrounding(file, line)` — reads ~10 lines of source around a given line number. The most-called tool across all models.
- **`frame`** = LLDB's `frame select N` / `frame variable` — switch stack frames and inspect local variables.
- **`definition`** = `find_definition(file, line, symbol)` — uses clangd LSP to jump to a symbol's definition. A code-navigation tool.

Models treat debugging as a **code reading task**, not a stepping task. They navigate the crash-state stack trace and read source, rather than re-running the program.

### Why `next`/`step` Are Almost Unused

Across 155 completed T3 runs: `next` was used 6 times total, `step` once. Models don't single-step because:

1. The enriched prompt already shows the crash state with source context
2. Single-stepping requires a mental model of program flow that current models struggle with
3. The crash has already happened — there's no earlier state to step through unless you set breakpoints and re-run (which only Gemini-FL attempts, unsuccessfully)

### Zero-Tool Runs: When the Prompt Is Enough

39 of 155 T3 runs (25%) used zero tools — the model answered entirely from the enriched stack trace.

| Model | Zero-Tool Runs | Mean Score |
|-------|---------------|-----------|
| GPT-4o | 14/20 (70%) | **2.43** |
| Nemotron-30B | 8/20 (40%) | 1.62 |
| Llama-8B | 7/20 (35%) | 0.00 |
| Grok-4 | 4/19 (21%) | 0.00 |
| Gemini-FL | 3/20 (15%) | 1.00 |
| GPT-5.5 | 1/20 (5%) | 0.00 |
| Qwen-30B | 1/18 (6%) | 0.00 |
| Sonnet-4.5 | 1/18 (6%) | 0.00 |

**GPT-4o is uniquely effective at zero-tool debugging:** it scores 2.43 on runs where it used no tools at all — better than Llama-8B's overall average (0.70) across all runs with tools. This suggests GPT-4o's strength is in prompt comprehension, not tool use. Meanwhile, GPT-5.5/Sonnet/Qwen rarely go zero-tool — they actively explore even when the answer is in the prompt.

---

## 4. Timeout and Failure Modes

### Timeout Epidemic in T1/T2

| Model | T1 Timeouts | T2 Timeouts | T3 Timeouts |
|-------|------------|------------|------------|
| Nemotron-30B | **10/24 (42%)** | **19/24 (79%)** | 0/21 (0%) |
| Grok-4 | **9/24 (38%)** | **14/24 (58%)** | 1/21 (5%) |
| Gemini-FL | 2/24 (8%) | 3/24 (13%) | 0/21 (0%) |
| Qwen-30B | 1/24 (4%) | 5/24 (21%) | 2/21 (10%) |
| Llama-8B | 1/24 (4%) | 1/24 (4%) | 0/21 (0%) |
| Sonnet-4.5 | 1/24 (4%) | 1/24 (4%) | 2/21 (10%) |
| GPT-5.5 | 0/24 (0%) | 0/24 (0%) | 0/21 (0%) |
| GPT-4o | 0/24 (0%) | 0/24 (0%) | 0/21 (0%) |

**Nemotron-30B and Grok-4 cannot self-direct.** In T1 (bash only) and T2 (bash + GDB), they get trapped in loops — issuing commands, failing to parse output, retrying. The structured T3 prompt eliminates this by front-loading the crash context. This is the single strongest evidence that **prompt structure > model scale**: the same 3B-active-parameter Nemotron goes from 79% timeouts to 0% timeouts just by changing the prompt.

### Three Distinct Failure Modes (from transcript analysis)

**Mode A — "Wave the White Flag" (Nemotron-30B, Grok-4)**
Model issues `bt`, sees a complex stack trace, and emits no prose. 1 tool call, 1-character response. It cannot reason from a non-trivial stack trace without additional help.

**Mode B — "Hallucinated Sandbox" (Qwen-30B)**
Model attempts tools, gets valid results, but misinterprets LLDB output as an error or restriction. Example: Qwen on `test-overflow` received valid `process status` output but responded "The debugging session cannot proceed because the necessary LLDB commands are not permitted." **The commands did return data.** A learned "this looks unfamiliar → blame the environment" reflex.

**Mode C — "Tool-Loop, Empty Answer" (Gemini-FL)**
The most striking failure. Across 9 of 11 zero-score runs, `response_length ≈ num_tool_calls` — one newline per tool turn, zero prose synthesis. Examples:
- `uninit-stack-accumulator`: 41 tools → 41-char response
- `test-overflow`: 29 tools → 29-char response
- `cjson-parse-string-oob`: 20 tools → 20-char response

Gemini-FL explores thoroughly (diverse commands: `bt`, `frame`, `disassemble`, `register`, `code`, `breakpoint`) but **fails to emit a final prose answer.** It exhausts its planning budget on tool calls. This is a model-side tool-use synthesis bug, not a debugging ability issue.

---

## 5. The Prompt Structure Argument

### Enriched Stack Trace Is the #1 Lever

The most striking result in this data is Nemotron-30B's performance jump:

| Tier | What it gets | Score | Timeouts |
|------|-------------|-------|----------|
| T1 (bash only) | Crash output, source files | 0.21 | 42% |
| T2 (bash + GDB) | T1 + debugger access | 0.40 | 79% |
| T3 (ChatDBG) | Enriched stack trace + source context | **2.30** | 0% |

The enriched prompt includes: a formatted stack trace with source lines around each frame, the crash error message, the command line, and program input. This is ~10x more informative than what the model sees in T1/T2 before it starts investigating. For a 3B-active-parameter model, this front-loaded context is the difference between useless (0.21) and competitive (2.30, matching GPT-4o).

### Models Prefer Bash Over GDB (T1 vs T2)

For most models, **T1 ≥ T2** — adding GDB access doesn't help and sometimes hurts:

| Model | T1 Score | T2 Score | Delta |
|-------|---------|---------|-------|
| GPT-5.5 | 2.88 | 2.75 | -0.13 |
| Sonnet-4.5 | 2.70 | 2.35 | -0.35 |
| Gemini-FL | 2.50 | 2.10 | -0.40 |
| Qwen-30B | 2.13 | 2.05 | -0.08 |
| GPT-4o | 1.88 | 1.79 | -0.09 |
| Llama-8B | 0.17 | 0.61 | +0.44 |

Models are "debugger-illiterate" — when given GDB alongside bash, they either:
1. Ignore GDB and use bash anyway (GPT-5.5, Sonnet)
2. Try GDB, get confused, waste time (Gemini-FL, Qwen)
3. Get stuck in GDB and timeout (Nemotron, Grok)

Only Llama-8B benefits from T2 over T1, and even then it only reaches 0.61. The implication is that **raw GDB access is not useful for LLMs** — they need the structured ChatDBG wrapper (T3) to get value from the debugger.

---

## 6. Scale vs Structure: The Core Research Question

### Small Models Match GPT-4o When Given Structure

| Model | Active Params | T3 Score | T3 Tools/Run |
|-------|--------------|---------|-------------|
| GPT-5.5 | ~1T (est) | **2.70** | 21.7 |
| Qwen-30B | 3B | **2.61** | 9.1 |
| Sonnet-4.5 | ~100B (est) | 2.44 | 15.4 |
| GPT-4o | ~200B (est) | 2.30 | 1.9 |
| Nemotron-30B | 3B | 2.30 | 1.9 |

**Qwen-30B (3B active) outperforms GPT-4o in T3.** With ChatDBG's structured prompt and tools, a model with ~100x fewer active parameters scores higher (2.61 vs 2.30). This supports the core hypothesis: the structure of the interaction (prompt + tools + crash context) matters more than raw model scale for the majority of debugging cases.

However, **GPT-5.5 remains the frontier** at 2.70, and is the only model that solves the hardest multi-step reasoning bugs. The gap narrows but doesn't close.

### Where Scale Still Matters

The hardest cases expose a clear scale gap:

| Case | GPT-5.5 | Qwen-30B | Nemotron-30B | Llama-8B |
|------|---------|----------|-------------|---------|
| `test-overflow` | 3 | 3 | 3 | 0 |
| `uninit-stack-accumulator` (pre-unfenced) | 3 | 0 | 0 | 0 |
| `cjson-parse-string-oob` | 3 | 0 | 0 | 0 |
| `double-free-errpath` | 3 | 3 | 3 | 0 |

Cases requiring **multi-step temporal reasoning** (following MSan reports through source, tracking allocate-free-use sequences) still need frontier-scale models. The enriched prompt helps localize the crash but doesn't help compose a chain of reasoning about program semantics.

---

## 7. The "Fix vs Explain" Cliff (Global Fix Bottleneck)

Across all models, `global_fix` is the hardest axis:

- Mean `root_cause`: 0.82
- Mean `local_fix`: 0.82
- Mean `global_fix`: **0.55**

On `off-by-one-crc`, **all four models — including GPT-5.5 — score 0 on global_fix.** They correctly flip `<=` to `<` but none propose structural alternatives (half-open ranges, `std::span<const uint8_t>`, length-invariant assertions).

This is not a model-scale issue. It's a prompt framing issue: the model is asked "propose a fix in code" and minimizes the diff. The CMW ablation partially addresses this by providing feedback that nudges toward structural fixes.

---

## 8. BugBench (Real-World C Bugs)

4 real bugs from BugBench (ncompress, man, polymorph, bc-1.06), only partially evaluated:

| Case | Bug Type | T3 Results |
|------|----------|-----------|
| bc-heap-overflow | Heap overflow (v_count vs a_count) | Nemotron: 3, GPT-4o: 2, Qwen: 2, Llama: 0 |
| ncompress-overflow | Stack overflow (strcpy) | Runs completed, unjudged |
| man-overflow | Global overflow (sizeof) | All timeouts |
| polymorph-overflow | Stack overflow (unbounded loop) | No collect (harness issue) |

Small sample, but `bc-heap-overflow` is notable: **Nemotron-30B (3B active) got 3/3** on a real-world heap corruption bug, outperforming GPT-4o (2/3). Confirms the synthetic findings — small models with structured prompts can debug real bugs.

---

## 9. Harness Lessons Learned

1. **Fenced vs Unfenced GDB:** The original `tier3_gdb_only` config blocked `run`, `break`, `continue`, `next`, `step`, `disassemble`, `backtrace` (only `bt` abbreviation allowed). This artificially suppressed GDB usage. Unfenced T3 shows dramatically different tool profiles (e.g., `bt`: 41 calls vs ~23 fenced).

2. **Wrong binary attachment:** 95% of BugsCPP runs had GDB attached to `/bin/bash` or `/usr/bin/find` instead of the buggy binary. All analysis on those runs is invalid.

3. **Wrong-output bugs:** BugsCPP includes "wrong output" bugs where the program exits normally. ChatDBG's crash-based contract (`run-until-stop`) shows a useless `exit()` frame for these.

4. **T4 patch leakage:** Claude Code agents can `git diff` to find injected patches. T4 results may overstate debugging ability when `.git` history is present.

5. **Mini-swe-agent answer capture:** T1/T2 sometimes lose final prose when the model doesn't follow the submit-tool protocol. Some zero scores reflect protocol brittleness, not investigation failure.

---

## 10. Summary of Key Findings

1. **Prompt quality > model scale > tool availability.** Nemotron-30B goes from 0.21 (T1) to 2.30 (T3) purely from a better prompt. Adding raw GDB (T2) actually makes most models worse.

2. **3B-active models match GPT-4o with the right scaffolding.** Qwen-30B (2.61) outperforms GPT-4o (2.30) in T3. Nemotron-30B (2.30) ties it. Both have 3B active parameters.

3. **Models are debugger-illiterate.** They prefer bash/grep over GDB commands. In T3, the winning strategy is inspect-not-execute: `frame` → `code` → `p`. Nobody single-steps.

4. **Tool volume doesn't predict success.** GPT-5.5 uses 21.7 tools/run and scores 2.70. Gemini-FL uses 9.6 tools/run and scores 1.80. GPT-4o uses 1.9 tools/run and scores 2.30. The *quality* of tool use (which commands, in what order) matters far more than quantity.

5. **Iterative feedback (CMW) helps mid-tier models most.** Sonnet goes 2.44 → 3.00, GPT-4o goes 2.30 → 2.80. GPT-5.5 doesn't need it. Llama-8B can't use it.

6. **Frontier models still win on hard bugs.** Multi-step reasoning (MSan report tracing, temporal allocation tracking) still requires GPT-5.5-class models. The gap is small for simple bugs but real for complex ones.

7. **Global fix is the universal bottleneck.** Even GPT-5.5 fails to propose structural fixes when asked for a "fix in code." This is a prompt framing issue, not a capability ceiling.

8. **Some models get worse with more tools.** Gemini-FL scores 2.50 in T1 but 1.80 in T3 — additional tools cause Mode C (tool-loop, empty answer). Grok-4 has catastrophic timeouts in T2 (58%) but not T3 (5%).
