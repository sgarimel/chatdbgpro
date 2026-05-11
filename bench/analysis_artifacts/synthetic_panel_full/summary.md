# Synthetic panel — full final_paper_bench (T1 + T3, all sweeps)

Source: `bench/results/final_paper_bench/synthetic`. `full RC/LF/GF` counts cells whose response contains all three labelled paragraphs; `recovered` are cells whose response was patched in by `bench/recover_responses.py` from tool output.

| Tier | Model | N | ok | timeout | no_collect | full RC/LF/GF | (of which recovered) | partial prose | empty |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| T1 | anthropic claude-sonnet-4.5 | 20 | 20 | 0 | 0 | 19 | 0 | 1 | 0 |
| T1 | google gemini-3.1-flash-lite-preview | 20 | 20 | 0 | 0 | 14 | 7 | 0 | 6 |
| T1 | meta-llama llama-3.1-8b-instruct | 20 | 18 | 2 | 0 | 16 | 0 | 2 | 2 |
| T1 | nvidia nemotron-3-nano-30b-a3b | 20 | 5 | 15 | 0 | 2 | 0 | 0 | 18 |
| T1 | openai gpt-4o | 20 | 20 | 0 | 0 | 17 | 6 | 3 | 0 |
| T1 | openai gpt-5.5 | 20 | 20 | 0 | 0 | 17 | 0 | 2 | 1 |
| T1 | qwen qwen3-30b-a3b-instruct-2507 | 20 | 19 | 1 | 0 | 11 | 0 | 3 | 6 |
| T1 | x-ai grok-4 | 20 | 18 | 2 | 0 | 15 | 0 | 2 | 3 |
| T3 | anthropic claude-sonnet-4.5 | 20 | 4 | 0 | 15 | 0 | 0 | 4 | 16 |
| T3 | google gemini-3.1-flash-lite-preview | 20 | 18 | 0 | 2 | 0 | 0 | 10 | 10 |
| T3 | meta-llama llama-3.1-8b-instruct | 20 | 0 | 0 | 19 | 0 | 0 | 0 | 20 |
| T3 | nvidia nemotron-3-nano-30b-a3b | 20 | 18 | 0 | 2 | 0 | 0 | 17 | 3 |
| T3 | openai gpt-4o | 20 | 0 | 0 | 19 | 0 | 0 | 0 | 20 |
| T3 | openai gpt-5.5 | 20 | 18 | 0 | 2 | 0 | 0 | 18 | 2 |
| T3 | qwen qwen3-30b-a3b-instruct-2507 | 20 | 17 | 0 | 3 | 0 | 0 | 17 | 3 |
| T3 | x-ai grok-4 | 20 | 4 | 0 | 15 | 0 | 0 | 4 | 16 |
| | **TOTAL** | **320** | **219** | **20** | **77** | **111** | **13** | **83** | **126** |
