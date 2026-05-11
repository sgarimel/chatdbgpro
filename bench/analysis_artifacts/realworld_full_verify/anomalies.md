# Anomalies in realworld full panel

Total flagged cells: **60** / 201

| Source | Tier | Model | Case | Status | Elapsed | RespLen | Reasons |
|---|---|---|---|---|---:|---:|---|
| local | T1 | claude-sonnet-4.5 | berry-1 | no_collect | 9.143 | 0 | status=no_collect |
| local | T1 | claude-sonnet-4.5 | berry-2 | ok | 256.661 | 96 | missing RC/LF/GF |
| local | T1 | claude-sonnet-4.5 | berry-3 | no_collect | 10.366 | 0 | status=no_collect |
| local | T1 | claude-sonnet-4.5 | berry-4 | ok | 289.011 | 121 | missing RC/LF/GF |
| bound | T1 | claude-sonnet-4.5 | juliet-cwe126-char-alloca-loop-01 | ok | 252.477 | 0 | empty response (len=0) |
| bound | T1 | claude-sonnet-4.5 | juliet-cwe415-malloc-free-char-01 | ok | 252.285 | 0 | empty response (len=0) |
| bound | T1 | claude-sonnet-4.5 | juliet-cwe416-malloc-free-char-01 | ok | 252.515 | 0 | empty response (len=0) |
| local | T1 | claude-sonnet-4.5 | man-overflow | build_failed | 0.0 | 0 | build_failed |
| local | T1 | gemini-2.5-flash | man-overflow | build_failed | 0.0 | 0 | build_failed |
| local | T1 | gemini-3.1-flash-lite-preview | berry-2 | ok | 157.401 | 0 | empty response (len=0) |
| local | T1 | gemini-3.1-flash-lite-preview | berry-3 | ok | 111.434 | 0 | empty response (len=0) |
| local | T1 | gemini-3.1-flash-lite-preview | berry-4 | ok | 150.751 | 0 | empty response (len=0) |
| bound | T1 | gemini-3.1-flash-lite-preview | crashbench-abo1 | ok | 10.74 | 0 | empty response (len=0) |
| local | T1 | gemini-3.1-flash-lite-preview | man-overflow | build_failed | 0.0 | 0 | build_failed |
| bound | T1 | llama-3.1-8b-instruct | berry-1 | ok | 14.391 | 1722 | missing RC/LF/GF |
| bound | T1 | llama-3.1-8b-instruct | berry-3 | ok | 22.047 | 3380 | missing RC/LF/GF |
| bound | T1 | llama-3.1-8b-instruct | berry-4 | ok | 309.323 | 0 | empty response (len=0) |
| local | T1 | llama-3.1-8b-instruct | man-overflow | build_failed | 0.0 | 0 | build_failed |
| local | T1 | llama-3.1-8b-instruct | ncompress-overflow | ok | 13.665 | 0 | empty response (len=0) |
| local | T1 | llama-3.1-8b-instruct | polymorph-overflow | ok | 10.811 | 0 | empty response (len=0) |
| local | T1 | nemotron-3-nano-30b-a3b | berry-1 | timeout | 601.459 | 0 | status=timeout |
| local | T1 | nemotron-3-nano-30b-a3b | berry-3 | timeout | 601.532 | 0 | status=timeout |
| local | T1 | nemotron-3-nano-30b-a3b | berry-4 | timeout | 601.577 | 0 | status=timeout |
| local | T1 | nemotron-3-nano-30b-a3b | berry-5 | timeout | 601.609 | 0 | status=timeout |
| local | T1 | nemotron-3-nano-30b-a3b | crashbench-abo2 | timeout | 601.701 | 0 | status=timeout |
| local | T1 | nemotron-3-nano-30b-a3b | crashbench-abo3 | timeout | 601.702 | 0 | status=timeout |
| local | T1 | nemotron-3-nano-30b-a3b | crashbench-abo5 | timeout | 601.675 | 0 | status=timeout |
| local | T1 | nemotron-3-nano-30b-a3b | crashbench-abo7 | timeout | 601.685 | 0 | status=timeout |
| local | T1 | nemotron-3-nano-30b-a3b | man-overflow | build_failed | 0.0 | 0 | build_failed |
| local | T1 | nemotron-3-nano-30b-a3b | ncompress-overflow | timeout | 9085.768 | 0 | status=timeout |
| local | T1 | nemotron-3-nano-30b-a3b | polymorph-overflow | timeout | 9085.773 | 0 | status=timeout |
| local | T1 | gpt-5.5 | man-overflow | build_failed | 0.0 | 0 | build_failed |
| local | T1 | qwen3-30b-a3b-instruct-2507 | crashbench-abo5 | ok | 26.101 | 0 | empty response (len=0) |
| bound | T1 | qwen3-30b-a3b-instruct-2507 | juliet-cwe126-char-alloca-loop-01 | ok | 25.713 | 0 | empty response (len=0) |
| bound | T1 | qwen3-30b-a3b-instruct-2507 | juliet-cwe416-malloc-free-char-01 | ok | 137.878 | 0 | empty response (len=0) |
| bound | T1 | qwen3-30b-a3b-instruct-2507 | man-overflow | ok | 13.086 | 2717 | missing RC/LF/GF |
| local | T1 | qwen3-30b-a3b-instruct-2507 | ncompress-overflow | timeout | 778.243 | 0 | status=timeout |
| bound | T1 | qwen3-30b-a3b-instruct-2507 | polymorph-overflow | ok | 181.963 | 0 | empty response (len=0) |
| bound | T3 | claude-sonnet-4.5 | crashbench-abo1 | ok | 40.406 | 0 | empty response (len=0) |
| bound | T3 | claude-sonnet-4.5 | crashbench-abo2 | ok | 102.941 | 474 | missing RC/LF/GF |
| bound | T3 | claude-sonnet-4.5 | crashbench-abo7 | ok | 156.429 | 6608 | missing RC/LF/GF |
| bound | T3 | claude-sonnet-4.5 | juliet-cwe415-malloc-free-char-01 | ok | 5.146 | 0 | empty response (len=0) |
| bound | T3 | gemini-3.1-flash-lite-preview | crashbench-abo2 | ok | 27.665 | 1734 | missing RC/LF/GF |
| bound | T3 | llama-3.1-8b-instruct | bc-heap-overflow | ok | 6.802 | 64 | missing RC/LF/GF |
| bound | T3 | llama-3.1-8b-instruct | berry-1 | ok | 16.61 | 2812 | missing RC/LF/GF |
| bound | T3 | llama-3.1-8b-instruct | berry-2 | ok | 10.921 | 0 | empty response (len=0) |
| bound | T3 | llama-3.1-8b-instruct | berry-3 | ok | 7.201 | 100 | missing RC/LF/GF |
| bound | T3 | llama-3.1-8b-instruct | berry-4 | ok | 7.501 | 50 | missing RC/LF/GF |
| bound | T3 | llama-3.1-8b-instruct | ncompress-overflow | ok | 5.9 | 64 | missing RC/LF/GF |
| bound | T3 | nemotron-3-nano-30b-a3b | berry-1 | ok | 225.884 | 4805 | missing RC/LF/GF |
| bound | T3 | nemotron-3-nano-30b-a3b | berry-5 | ok | 151.406 | 4151 | missing RC/LF/GF |
| bound | T3 | nemotron-3-nano-30b-a3b | crashbench-abo5 | ok | 39.945 | 0 | empty response (len=0) |
| bound | T3 | nemotron-3-nano-30b-a3b | crashbench-abo7 | ok | 184.819 | 11 | empty response (len=11) |
| bound | T3 | gpt-4o | bc-heap-overflow | ok | 13.25 | 3009 | missing RC/LF/GF |
| bound | T3 | gpt-4o | berry-4 | ok | 12.017 | 2712 | missing RC/LF/GF |
| bound | T3 | gpt-4o | ncompress-overflow | ok | 25.266 | 2495 | missing RC/LF/GF |
| bound | T3 | gpt-5.5 | crashbench-abo1 | ok | 108.991 | 4660 | missing RC/LF/GF |
| bound | T3 | gpt-5.5 | crashbench-abo3 | ok | 74.501 | 7 | empty response (len=7) |
| bound | T3 | qwen3-30b-a3b-instruct-2507 | juliet-cwe122-char-type-overrun-memcpy-01 | ok | 119.154 | 4594 | missing RC/LF/GF |
| bound | T3 | qwen3-30b-a3b-instruct-2507 | juliet-cwe415-malloc-free-char-01 | ok | 7.685 | 1277 | missing RC/LF/GF |
