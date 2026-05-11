# Anika realworld sweep — verification summary

Source: every `bench/results/anika-paper-final-realworld-20260511-T*-*` sweep dir scanned directly. Model order follows `feedback_figure_conventions.md`.

| Tier | Model | N | ok | timeout | no_collect | build_failed | (missing collect.json) | full RC/LF/GF | (of which recovered) | partial prose | empty |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| T1 | anthropic-claude-sonnet-4-5 | 11 | 8 | 0 | 2 | 1 | 3 | 6 | 6 | 2 | 3 |
| T1 | google-gemini-2-5-flash | 15 | 14 | 0 | 0 | 1 | 1 | 14 | 4 | 0 | 1 |
| T1 | google-gemini-3-1-flash-lite-preview | 9 | 8 | 0 | 0 | 1 | 1 | 5 | 5 | 0 | 4 |
| T1 | meta-llama-llama-3-1-8b-instruct | 15 | 14 | 0 | 0 | 1 | 1 | 12 | 12 | 0 | 3 |
| T1 | nvidia-nemotron-3-nano-30b-a3b | 13 | 2 | 10 | 0 | 1 | 11 | 2 | 2 | 0 | 11 |
| T1 | openai-gpt-4o | 12 | 12 | 0 | 0 | 0 | 0 | 12 | 9 | 0 | 0 |
| T1 | openai-gpt-5-5 | 5 | 4 | 0 | 0 | 1 | 1 | 4 | 4 | 0 | 1 |
| T1 | qwen-qwen3-30b-a3b-instruct-2507 | 5 | 4 | 1 | 0 | 0 | 1 | 3 | 3 | 0 | 2 |
| | **TOTAL** | **85** | **66** | **11** | **2** | **6** | **19** | **58** | **45** | **2** | **25** |
