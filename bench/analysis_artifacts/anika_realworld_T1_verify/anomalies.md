# Anomalies in Anika realworld sweep

Total flagged cells: **27** / 85

| Tier | Model | Case | Status | Elapsed | RespLen | Reasons |
|---|---|---|---|---:|---:|---|
| T1 | anthropic-claude-sonnet-4-5 | berry-1 | no_collect | 9.143 | 0 | status=no_collect |
| T1 | anthropic-claude-sonnet-4-5 | berry-2 | ok | 256.661 | 96 | missing RC/LF/GF |
| T1 | anthropic-claude-sonnet-4-5 | berry-3 | no_collect | 10.366 | 0 | status=no_collect |
| T1 | anthropic-claude-sonnet-4-5 | berry-4 | ok | 289.011 | 121 | missing RC/LF/GF |
| T1 | anthropic-claude-sonnet-4-5 | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | google-gemini-2-5-flash | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | google-gemini-3-1-flash-lite-preview | berry-2 | ok | 157.401 | 0 | empty response (len=0) |
| T1 | google-gemini-3-1-flash-lite-preview | berry-3 | ok | 111.434 | 0 | empty response (len=0) |
| T1 | google-gemini-3-1-flash-lite-preview | berry-4 | ok | 150.751 | 0 | empty response (len=0) |
| T1 | google-gemini-3-1-flash-lite-preview | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | meta-llama-llama-3-1-8b-instruct | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | meta-llama-llama-3-1-8b-instruct | ncompress-overflow | ok | 13.665 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | polymorph-overflow | ok | 10.811 | 0 | empty response (len=0) |
| T1 | nvidia-nemotron-3-nano-30b-a3b | berry-1 | timeout | 601.459 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | berry-3 | timeout | 601.532 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | berry-4 | timeout | 601.577 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | berry-5 | timeout | 601.609 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | crashbench-abo2 | timeout | 601.701 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | crashbench-abo3 | timeout | 601.702 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | crashbench-abo5 | timeout | 601.675 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | crashbench-abo7 | timeout | 601.685 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | nvidia-nemotron-3-nano-30b-a3b | ncompress-overflow | timeout | 9085.768 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | polymorph-overflow | timeout | 9085.773 | 0 | status=timeout |
| T1 | openai-gpt-5-5 | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | qwen-qwen3-30b-a3b-instruct-2507 | crashbench-abo5 | ok | 26.101 | 0 | empty response (len=0) |
| T1 | qwen-qwen3-30b-a3b-instruct-2507 | ncompress-overflow | timeout | 778.243 | 0 | status=timeout |
