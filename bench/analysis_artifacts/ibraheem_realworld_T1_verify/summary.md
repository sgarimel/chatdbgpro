# Ibraheem realworld sweep — verification summary

Source: every `bench/results/ibraheem-paper-final-realworld-*-T*-*` sweep dir scanned directly. Model order follows `feedback_figure_conventions.md`.

| Tier | Model | N | ok | timeout | no_collect | build_failed | (missing collect.json) | full RC/LF/GF | (of which recovered) | partial prose | empty |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| T1 | anthropic-claude-sonnet-4-5 | 11 | 8 | 0 | 0 | 3 | 3 | 8 | 0 | 0 | 3 |
| T1 | google-gemini-2-5-flash | 15 | 12 | 0 | 0 | 3 | 3 | 12 | 0 | 0 | 3 |
| T1 | google-gemini-3-1-flash-lite-preview | 9 | 6 | 0 | 0 | 3 | 3 | 3 | 2 | 0 | 6 |
| T1 | meta-llama-llama-3-1-8b-instruct | 15 | 12 | 0 | 0 | 3 | 3 | 0 | 0 | 0 | 15 |
| T1 | nvidia-nemotron-3-nano-30b-a3b | 13 | 0 | 10 | 0 | 3 | 13 | 0 | 0 | 0 | 13 |
| T1 | openai-gpt-4o | 12 | 4 | 7 | 0 | 1 | 8 | 3 | 0 | 1 | 8 |
| T1 | openai-gpt-5-5 | 5 | 2 | 0 | 0 | 3 | 3 | 2 | 0 | 0 | 3 |
| T1 | qwen-qwen3-30b-a3b-instruct-2507 | 5 | 3 | 1 | 0 | 1 | 2 | 1 | 0 | 0 | 4 |
| T3 | anthropic-claude-sonnet-4-5 | 9 | 3 | 0 | 2 | 3 | 6 | 3 | 0 | 0 | 6 |
| T3 | google-gemini-2-5-flash | 16 | 1 | 0 | 11 | 3 | 15 | 1 | 0 | 0 | 15 |
| T3 | google-gemini-3-1-flash-lite-preview | 9 | 0 | 5 | 0 | 3 | 9 | 0 | 0 | 0 | 9 |
| T3 | meta-llama-llama-3-1-8b-instruct | 13 | 0 | 0 | 11 | 2 | 13 | 0 | 0 | 0 | 13 |
| T3 | nvidia-nemotron-3-nano-30b-a3b | 5 | 2 | 0 | 1 | 2 | 3 | 0 | 0 | 0 | 5 |
| T3 | openai-gpt-4o | 13 | 0 | 0 | 11 | 2 | 13 | 0 | 0 | 0 | 13 |
| T3 | openai-gpt-5-5 | 8 | 0 | 4 | 0 | 3 | 8 | 0 | 0 | 0 | 8 |
| T3 | qwen-qwen3-30b-a3b-instruct-2507 | 3 | 0 | 0 | 0 | 2 | 3 | 0 | 0 | 0 | 3 |
| | **TOTAL** | **161** | **53** | **27** | **36** | **40** | **108** | **33** | **2** | **1** | **127** |
