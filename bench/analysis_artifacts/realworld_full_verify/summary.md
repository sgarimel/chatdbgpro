# Realworld full panel — verification summary

Combines fresh local Anika sweep (`anika-paper-final-realworld-20260511-T*-*`) with pre-bound cells in `final_paper_bench/realworld/` (sourced from earlier archive sweeps via `_provenance.json`).

Model order follows `feedback_figure_conventions.md`. Per-cell precedence: local sweep > bound archive (no overlap expected because the locked runset excludes already-bound rows).

| Tier | Model | N | ok | timeout | no_collect | build_failed | local | bound | full RC/LF/GF | (of which recovered) | partial prose | empty |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| T1 | openai/gpt-5.5 | 20 | 19 | 0 | 0 | 1 | 5 | 15 | 19 | 4 | 0 | 1 |
| T1 | openai/gpt-4o | 20 | 20 | 0 | 0 | 0 | 12 | 8 | 20 | 9 | 0 | 0 |
| T1 | anthropic/claude-sonnet-4.5 | 20 | 17 | 0 | 2 | 1 | 11 | 9 | 12 | 6 | 2 | 6 |
| T1 | google/gemini-2.5-flash | 20 | 19 | 0 | 0 | 1 | 15 | 5 | 19 | 4 | 0 | 1 |
| T1 | google/gemini-3.1-flash-lite-preview | 20 | 19 | 0 | 0 | 1 | 9 | 11 | 15 | 5 | 0 | 5 |
| T1 | qwen/qwen3-30b-a3b-instruct-2507 | 20 | 19 | 1 | 0 | 0 | 5 | 15 | 14 | 3 | 1 | 5 |
| T1 | nvidia/nemotron-3-nano-30b-a3b | 20 | 9 | 10 | 0 | 1 | 13 | 7 | 9 | 2 | 0 | 11 |
| T1 | meta-llama/llama-3.1-8b-instruct | 20 | 19 | 0 | 0 | 1 | 15 | 5 | 14 | 12 | 2 | 4 |
| T3 | openai/gpt-5.5 | 3 | 3 | 0 | 0 | 0 | 0 | 3 | 1 | 0 | 1 | 1 |
| T3 | openai/gpt-4o | 7 | 7 | 0 | 0 | 0 | 0 | 7 | 4 | 0 | 3 | 0 |
| T3 | anthropic/claude-sonnet-4.5 | 4 | 4 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 2 | 2 |
| T3 | google/gemini-2.5-flash | 4 | 4 | 0 | 0 | 0 | 0 | 4 | 4 | 0 | 0 | 0 |
| T3 | google/gemini-3.1-flash-lite-preview | 1 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 0 |
| T3 | qwen/qwen3-30b-a3b-instruct-2507 | 9 | 9 | 0 | 0 | 0 | 0 | 9 | 7 | 0 | 2 | 0 |
| T3 | nvidia/nemotron-3-nano-30b-a3b | 6 | 6 | 0 | 0 | 0 | 0 | 6 | 2 | 0 | 2 | 2 |
| T3 | meta-llama/llama-3.1-8b-instruct | 7 | 7 | 0 | 0 | 0 | 0 | 7 | 1 | 0 | 5 | 1 |
| | **TOTAL** | **201** | **182** | **11** | **2** | **6** | **85** | **116** | **141** | **45** | **21** | **39** |
