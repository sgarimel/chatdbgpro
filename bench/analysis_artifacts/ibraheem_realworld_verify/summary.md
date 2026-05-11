# Ibraheem realworld sweeps — verification summary

Source: every `bench/results/ibraheem-paper-final-realworld-*` sweep dir scanned directly (no `final_paper_bench/realworld` promote step).

| Date | Tier | Model | N | ok | timeout | no_collect | (missing collect.json) | full RC/LF/GF | partial prose | empty |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 20260510 | T1 | anthropic-claude-sonnet-4-5 | 11 | 7 | 0 | 0 | 4 | 0 | 0 | 11 |
| 20260510 | T1 | google-gemini-2-5-flash | 15 | 11 | 0 | 0 | 4 | 0 | 0 | 15 |
| 20260510 | T1 | google-gemini-3-1-flash-lite-preview | 9 | 5 | 0 | 0 | 4 | 0 | 0 | 9 |
| 20260510 | T1 | meta-llama-llama-3-1-8b-instruct | 15 | 11 | 0 | 0 | 4 | 0 | 0 | 15 |
| 20260510 | T1 | nvidia-nemotron-3-nano-30b-a3b | 13 | 9 | 0 | 0 | 4 | 0 | 0 | 13 |
| 20260510 | T1 | openai-gpt-4o | 12 | 11 | 0 | 0 | 1 | 0 | 0 | 12 |
| 20260510 | T1 | openai-gpt-5-5 | 5 | 1 | 0 | 0 | 4 | 0 | 0 | 5 |
| 20260510 | T1 | qwen-qwen3-30b-a3b-instruct-2507 | 5 | 4 | 0 | 0 | 1 | 0 | 0 | 5 |
| 20260510 | T3 | anthropic-claude-sonnet-4-5 | 9 | 0 | 0 | 3 | 9 | 0 | 0 | 9 |
| 20260510 | T3 | google-gemini-2-5-flash | 16 | 0 | 0 | 12 | 16 | 0 | 0 | 16 |
| 20260510 | T3 | google-gemini-3-1-flash-lite-preview | 9 | 0 | 0 | 4 | 9 | 0 | 0 | 9 |
| 20260510 | T3 | meta-llama-llama-3-1-8b-instruct | 13 | 0 | 0 | 11 | 13 | 0 | 0 | 13 |
| 20260510 | T3 | nvidia-nemotron-3-nano-30b-a3b | 5 | 0 | 0 | 2 | 5 | 0 | 0 | 5 |
| 20260510 | T3 | openai-gpt-4o | 13 | 0 | 0 | 11 | 13 | 0 | 0 | 13 |
| 20260510 | T3 | openai-gpt-5-5 | 8 | 0 | 0 | 3 | 8 | 0 | 0 | 8 |
| 20260510 | T3 | qwen-qwen3-30b-a3b-instruct-2507 | 3 | 0 | 0 | 0 | 3 | 0 | 0 | 3 |
| 20260511 | T1 | anthropic-claude-sonnet-4-5 | 11 | 8 | 0 | 0 | 3 | 8 | 0 | 3 |
| 20260511 | T1 | google-gemini-2-5-flash | 15 | 12 | 0 | 0 | 3 | 12 | 0 | 3 |
| 20260511 | T1 | google-gemini-3-1-flash-lite-preview | 9 | 6 | 0 | 0 | 3 | 1 | 0 | 8 |
| 20260511 | T1 | meta-llama-llama-3-1-8b-instruct | 15 | 12 | 0 | 0 | 3 | 0 | 0 | 15 |
| 20260511 | T1 | nvidia-nemotron-3-nano-30b-a3b | 13 | 0 | 10 | 0 | 13 | 0 | 0 | 13 |
| 20260511 | T1 | openai-gpt-4o | 12 | 4 | 7 | 0 | 8 | 3 | 1 | 8 |
| 20260511 | T1 | openai-gpt-5-5 | 5 | 2 | 0 | 0 | 3 | 2 | 0 | 3 |
| 20260511 | T1 | qwen-qwen3-30b-a3b-instruct-2507 | 5 | 3 | 1 | 0 | 2 | 1 | 0 | 4 |
| | | **TOTAL** | **246** | **106** | **18** | **46** | **140** | **27** | **1** | **218** |
