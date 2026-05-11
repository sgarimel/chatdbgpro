# Synthetic panel — Anika 2026-05-10 reruns only

Source: `bench/results/final_paper_bench/synthetic`. `full RC/LF/GF` counts cells whose response contains all three labelled paragraphs; `recovered` are cells whose response was patched in by `bench/recover_responses.py` from tool output.

| Tier | Model | N | ok | timeout | no_collect | full RC/LF/GF | (of which recovered) | partial prose | empty |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| T1 | anthropic claude-sonnet-4.5 | 16 | 16 | 0 | 0 | 16 | 0 | 0 | 0 |
| T1 | google gemini-3.1-flash-lite-preview | 16 | 16 | 0 | 0 | 10 | 5 | 0 | 6 |
| T1 | meta-llama llama-3.1-8b-instruct | 20 | 18 | 2 | 0 | 16 | 0 | 2 | 2 |
| T1 | nvidia nemotron-3-nano-30b-a3b | 16 | 1 | 15 | 0 | 2 | 0 | 0 | 14 |
| T1 | openai gpt-4o | 20 | 20 | 0 | 0 | 17 | 6 | 3 | 0 |
| T1 | openai gpt-5.5 | 12 | 12 | 0 | 0 | 12 | 0 | 0 | 0 |
| T1 | qwen qwen3-30b-a3b-instruct-2507 | 12 | 11 | 1 | 0 | 8 | 0 | 0 | 4 |
| T1 | x-ai grok-4 | 16 | 14 | 2 | 0 | 12 | 0 | 1 | 3 |
| T3 | anthropic claude-sonnet-4.5 | 16 | 14 | 0 | 2 | 5 | 0 | 9 | 2 |
| T3 | google gemini-3.1-flash-lite-preview | 2 | 2 | 0 | 0 | 1 | 0 | 0 | 1 |
| T3 | meta-llama llama-3.1-8b-instruct | 20 | 20 | 0 | 0 | 18 | 0 | 1 | 1 |
| T3 | nvidia nemotron-3-nano-30b-a3b | 2 | 2 | 0 | 0 | 2 | 0 | 0 | 0 |
| T3 | openai gpt-4o | 20 | 19 | 0 | 1 | 16 | 0 | 2 | 2 |
| T3 | openai gpt-5.5 | 2 | 2 | 0 | 0 | 2 | 0 | 0 | 0 |
| T3 | qwen qwen3-30b-a3b-instruct-2507 | 3 | 3 | 0 | 0 | 2 | 0 | 0 | 1 |
| T3 | x-ai grok-4 | 16 | 16 | 0 | 0 | 4 | 0 | 7 | 5 |
| | **TOTAL** | **209** | **186** | **20** | **3** | **143** | **11** | **25** | **41** |
