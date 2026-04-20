# ChatDBG Pro — Project Context

## Overview

This is a COS 484 research project extending **ChatDBG** (Zheng, Berger et al.), an AI-powered debugging assistant that augments GDB/LLDB/pdb with an LLM agent. The original paper achieves 67% actionable fix rate on a single query (85% with follow-up) using GPT-4.

**Original codebase we fork from:** https://github.com/plasma-umass/ChatDBG

**Core research question:** How much of ChatDBG's performance comes from model scale vs. the structure of the interaction itself?

---

## Motivation

Three key limitations of the original ChatDBG:

1. **Cost and scalability** — repeated GPT-4 calls with full interaction history passed each step → high latency and cost at scale.
2. **Unclear necessity of large models** — many debugging actions (inspect variables, step through stack) are local and simple; smaller models may suffice.
3. **Inference-only reasoning** — no learning from past debugging trajectories; relies on implicit reasoning rather than structured decision-making.

---

## Study Plan

## Test Case Database

The file `chatdbg_test_case_pipeline.md` documents the complete pipeline for 
building the evaluation test case corpus from BugsC++. It covers:

- Environment setup (Docker, GDB, Python dependencies, BugsC++ CLI)
- The SQLite database schema (`data/corpus.db`) and companion flat file structure
- Six sequential scripts (`scripts/seed_db.py` through `scripts/finalize_corpus.py`)
  that filter BugsC++'s 209 C/C++ bugs down to ~120-160 reproducible crash cases
- Verification and commit instructions

The database stores ground-truth crash locations (function, file, line) and 
developer patches for each included test case. These are the two reference 
answers used for automated scoring in the evaluation harness.

Run all scripts in order before attempting any evaluation runs.

### Baselines (drop-in model replacements for ChatDBG procedure)

Run smallest → largest, repeating the original ChatDBG tests:

| Model | Notes |
|-------|-------|
| Mamba 3 | Smallest; compresses long-range info into one state — expected worst |
| Nemotron 30B (Nano 3 A3B) | Hybrid Mamba+attention; ~$0.05/M input via API; can run locally |
| Qwen 30B | Same params as Nemotron 30B; head-to-head comparison |
| Nemotron 120B (Super A12B) | 12B active params; ~$0.10/M input via OpenRouter; free tier available |

GPT-4 serves as the paper's original upper-bound reference.

### Ablations

1. **Improved tool calls**
   - Expose GPT-4/frontier model as a tool (local model calls it only when confused)
   - Code execution tool: let model run code in a kernel to verify outputs

2. **Enriched stack trace context** — increase lines of source code passed in the stack trace (paper uses 10 lines); test whether more code context alone improves debugging

3. **Chain-of-prompt** — allow model to prompt itself iteratively for longer per context state (paper uses one-shot per new state)

4. **Reinforcement Learning (ambitious)**
   - RLVR + RLHF to train smaller models specifically for debugging tool use
   - New test cases: failed student submissions from COS 226/COS 217 paired with correct spec/autograder/reference solution → debugging instances
   - GDB Environment on Tinker
   - Tests hypothesis: large models only necessary for longer-range reasoning

5. **Streaming state model (Mamba policy)**
   - Mamba policy receives only new GDB observation, updates persistent hidden state, predicts next action
   - No reprocessing/attending over full transcript
   - Hypothesis: GDB control is a constrained sequential decision process with low-entropy actions
   - Measure: debugging success + latency/step, wall-clock time to diagnosis, peak memory, compute per session

### GDB Environment (for RL ablation)

```python
class GDBEnv(Env):
    def initial_observation(self):
        """Launch GDB on buggy program, run until crash.
        Return crash state (backtrace, error message) as initial observation."""
        ...

    def step(self, action):
        """Parse model action as GDB command (e.g. 'print x', 'backtrace', 'step', 'frame 2').
        Execute in GDB. Return GDB output as next observation.
        Compute reward if model issues a diagnose action."""
        ...
```

Action space: valid GDB commands + special `diagnose <explanation>` action that ends the episode and triggers reward.

---

## Codebase Approach

- Start in the existing ChatDBG codebase; analyze tools, language support, and GDB-style debugger → tool call format
- Target models (Nemotron, Qwen, etc.) are post-trained for MCP-style tool calls → convert existing tool call functionality to work with these models
- May propose a fork or redesign the port for better context efficiency
- Key area: how debugger state/history is passed to the model at each step

---

## Computational Resources

| Model | Params (active) | Context | Cost | Notes |
|-------|----------------|---------|------|-------|
| Nemotron Super 120B A12B | 12B active | 262K | $0.10/M in, $0.50/M out | Free tier on OpenRouter (telemetry) |
| Nemotron Nano 30B A3B | 3B active | — | $0.05/M in, $0.20/M out | Can run locally / on Tinker |
| Qwen 30B | — | — | TBD | — |
| Mamba 3 | — | — | Local | — |

Anticipated cost per benchmark run: ~$1 (much smaller than full Intelligence Index benchmark).

Compute platform: **Tinker** (Princeton HPC) for larger models; local inference feasible for Nemotron Nano 30B.
