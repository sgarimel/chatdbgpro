# Paper figure 3 — full panel (synthetic + realworld, T1 + T3)

Source: `bench/results/final_paper_bench/{synthetic,realworld}`. Union of every cell in both panels.

| Panel | Tier | Model | N | ok | timeout | no_collect | full RC/LF/GF | (of which recovered) | partial prose | empty |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| realworld | T1 | anthropic claude-sonnet-4.5 | 10 | 10 | 0 | 0 | 7 | 0 | 0 | 3 |
| realworld | T1 | google gemini-2.5-flash | 5 | 5 | 0 | 0 | 5 | 0 | 0 | 0 |
| realworld | T1 | google gemini-3.1-flash-lite-preview | 11 | 11 | 0 | 0 | 10 | 0 | 0 | 1 |
| realworld | T1 | meta-llama llama-3.1-8b-instruct | 5 | 5 | 0 | 0 | 2 | 0 | 2 | 1 |
| realworld | T1 | nvidia nemotron-3-nano-30b-a3b | 10 | 7 | 3 | 0 | 7 | 0 | 0 | 3 |
| realworld | T1 | openai gpt-4o | 8 | 8 | 0 | 0 | 8 | 0 | 0 | 0 |
| realworld | T1 | openai gpt-5.5 | 15 | 15 | 0 | 0 | 15 | 0 | 0 | 0 |
| realworld | T1 | qwen qwen3-30b-a3b-instruct-2507 | 15 | 15 | 0 | 0 | 11 | 0 | 1 | 3 |
| realworld | T3 | anthropic claude-sonnet-4.5 | 4 | 4 | 0 | 0 | 0 | 0 | 2 | 2 |
| realworld | T3 | google gemini-2.5-flash | 4 | 4 | 0 | 0 | 4 | 0 | 0 | 0 |
| realworld | T3 | google gemini-3.1-flash-lite-preview | 1 | 1 | 0 | 0 | 0 | 0 | 1 | 0 |
| realworld | T3 | meta-llama llama-3.1-8b-instruct | 7 | 7 | 0 | 0 | 1 | 0 | 5 | 1 |
| realworld | T3 | nvidia nemotron-3-nano-30b-a3b | 6 | 6 | 0 | 0 | 2 | 0 | 2 | 2 |
| realworld | T3 | openai gpt-4o | 7 | 7 | 0 | 0 | 4 | 0 | 3 | 0 |
| realworld | T3 | openai gpt-5.5 | 3 | 3 | 0 | 0 | 1 | 0 | 1 | 1 |
| realworld | T3 | qwen qwen3-30b-a3b-instruct-2507 | 9 | 9 | 0 | 0 | 7 | 0 | 2 | 0 |
| synthetic | T1 | anthropic claude-sonnet-4.5 | 20 | 20 | 0 | 0 | 19 | 0 | 1 | 0 |
| synthetic | T1 | google gemini-3.1-flash-lite-preview | 20 | 20 | 0 | 0 | 14 | 7 | 0 | 6 |
| synthetic | T1 | meta-llama llama-3.1-8b-instruct | 20 | 18 | 2 | 0 | 16 | 0 | 2 | 2 |
| synthetic | T1 | nvidia nemotron-3-nano-30b-a3b | 20 | 5 | 15 | 0 | 2 | 0 | 0 | 18 |
| synthetic | T1 | openai gpt-4o | 20 | 20 | 0 | 0 | 17 | 6 | 3 | 0 |
| synthetic | T1 | openai gpt-5.5 | 20 | 20 | 0 | 0 | 17 | 0 | 2 | 1 |
| synthetic | T1 | qwen qwen3-30b-a3b-instruct-2507 | 20 | 19 | 1 | 0 | 11 | 0 | 3 | 6 |
| synthetic | T1 | x-ai grok-4 | 20 | 18 | 2 | 0 | 15 | 0 | 2 | 3 |
| synthetic | T3 | anthropic claude-sonnet-4.5 | 20 | 18 | 0 | 2 | 5 | 0 | 13 | 2 |
| synthetic | T3 | google gemini-3.1-flash-lite-preview | 20 | 20 | 0 | 0 | 1 | 0 | 10 | 9 |
| synthetic | T3 | meta-llama llama-3.1-8b-instruct | 20 | 20 | 0 | 0 | 19 | 0 | 1 | 0 |
| synthetic | T3 | nvidia nemotron-3-nano-30b-a3b | 20 | 20 | 0 | 0 | 2 | 0 | 17 | 1 |
| synthetic | T3 | openai gpt-4o | 20 | 19 | 0 | 1 | 14 | 0 | 3 | 3 |
| synthetic | T3 | openai gpt-5.5 | 20 | 20 | 0 | 0 | 2 | 0 | 18 | 0 |
| synthetic | T3 | qwen qwen3-30b-a3b-instruct-2507 | 20 | 20 | 0 | 0 | 2 | 0 | 17 | 1 |
| synthetic | T3 | x-ai grok-4 | 20 | 20 | 0 | 0 | 2 | 0 | 14 | 4 |
| | | **TOTAL** | **440** | **414** | **23** | **3** | **242** | **13** | **125** | **73** |
