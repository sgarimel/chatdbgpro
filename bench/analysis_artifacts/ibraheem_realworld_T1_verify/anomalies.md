# Anomalies in Anomalies realworld sweep

Total flagged cells: **128** / 161

| Tier | Model | Case | Status | Elapsed | RespLen | Reasons |
|---|---|---|---|---:|---:|---|
| T1 | anthropic-claude-sonnet-4-5 | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | anthropic-claude-sonnet-4-5 | ncompress-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | anthropic-claude-sonnet-4-5 | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | google-gemini-2-5-flash | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | google-gemini-2-5-flash | ncompress-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | google-gemini-2-5-flash | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | google-gemini-3-1-flash-lite-preview | berry-2 | ok | 52.094 | 0 | empty response (len=0) |
| T1 | google-gemini-3-1-flash-lite-preview | berry-3 | ok | 11.898 | 0 | empty response (len=0) |
| T1 | google-gemini-3-1-flash-lite-preview | berry-4 | ok | 10.62 | 0 | empty response (len=0) |
| T1 | google-gemini-3-1-flash-lite-preview | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | google-gemini-3-1-flash-lite-preview | ncompress-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | google-gemini-3-1-flash-lite-preview | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | meta-llama-llama-3-1-8b-instruct | bc-heap-overflow | ok | 53.685 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | crashbench-abo1 | ok | 4.392 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | crashbench-abo2 | ok | 3.919 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | crashbench-abo3 | ok | 4.024 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | crashbench-abo5 | ok | 529.917 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | crashbench-abo7 | ok | 4.187 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | crashbench-abo8 | ok | 5.8 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | juliet-cwe121-char-type-overrun-memcpy-01 | ok | 11.972 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | juliet-cwe122-char-type-overrun-memcpy-01 | ok | 14.621 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | juliet-cwe126-char-alloca-loop-01 | ok | 12.498 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | juliet-cwe415-malloc-free-char-01 | ok | 13.024 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | juliet-cwe416-malloc-free-char-01 | ok | 9.361 | 0 | empty response (len=0) |
| T1 | meta-llama-llama-3-1-8b-instruct | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | meta-llama-llama-3-1-8b-instruct | ncompress-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | meta-llama-llama-3-1-8b-instruct | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | nvidia-nemotron-3-nano-30b-a3b | bc-heap-overflow | timeout | 600.063 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | berry-1 | timeout | 600.054 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | berry-2 | timeout | 600.066 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | berry-3 | timeout | 600.109 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | berry-4 | timeout | 600.097 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | berry-5 | timeout | 600.032 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | crashbench-abo2 | timeout | 600.071 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | crashbench-abo3 | timeout | 600.095 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | crashbench-abo5 | timeout | 600.103 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | crashbench-abo7 | timeout | 600.069 | 0 | status=timeout |
| T1 | nvidia-nemotron-3-nano-30b-a3b | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | nvidia-nemotron-3-nano-30b-a3b | ncompress-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | nvidia-nemotron-3-nano-30b-a3b | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | openai-gpt-4o | crashbench-abo1 | timeout | 600.064 | 0 | status=timeout |
| T1 | openai-gpt-4o | crashbench-abo2 | timeout | 600.113 | 0 | status=timeout |
| T1 | openai-gpt-4o | crashbench-abo3 | timeout | 600.019 | 0 | status=timeout |
| T1 | openai-gpt-4o | crashbench-abo7 | ok | 541.863 | 706 | missing RC/LF/GF |
| T1 | openai-gpt-4o | crashbench-abo8 | timeout | 600.029 | 0 | status=timeout |
| T1 | openai-gpt-4o | juliet-cwe122-char-type-overrun-memcpy-01 | timeout | 600.019 | 0 | status=timeout |
| T1 | openai-gpt-4o | juliet-cwe126-char-alloca-loop-01 | timeout | 600.108 | 0 | status=timeout |
| T1 | openai-gpt-4o | juliet-cwe416-malloc-free-char-01 | timeout | 600.041 | 0 | status=timeout |
| T1 | openai-gpt-4o | ncompress-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | openai-gpt-5-5 | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | openai-gpt-5-5 | ncompress-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | openai-gpt-5-5 | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T1 | qwen-qwen3-30b-a3b-instruct-2507 | berry-5 | timeout | 600.107 | 0 | status=timeout |
| T1 | qwen-qwen3-30b-a3b-instruct-2507 | crashbench-abo3 | ok | 33.573 | 0 | empty response (len=0) |
| T1 | qwen-qwen3-30b-a3b-instruct-2507 | crashbench-abo5 | ok | 59.055 | 0 | empty response (len=0) |
| T1 | qwen-qwen3-30b-a3b-instruct-2507 | ncompress-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | anthropic-claude-sonnet-4-5 | bc-heap-overflow | error | None | 0 | status=error |
| T3 | anthropic-claude-sonnet-4-5 | berry-2 | no_collect | 155.887 | 0 | status=no_collect |
| T3 | anthropic-claude-sonnet-4-5 | berry-3 | no_collect | 536.907 | 0 | status=no_collect |
| T3 | anthropic-claude-sonnet-4-5 | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | anthropic-claude-sonnet-4-5 | ncompress-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | anthropic-claude-sonnet-4-5 | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | google-gemini-2-5-flash | bc-heap-overflow | error | None | 0 | status=error |
| T3 | google-gemini-2-5-flash | crashbench-abo1 | no_collect | 0.238 | 0 | status=no_collect |
| T3 | google-gemini-2-5-flash | crashbench-abo2 | no_collect | 0.222 | 0 | status=no_collect |
| T3 | google-gemini-2-5-flash | crashbench-abo3 | no_collect | 0.227 | 0 | status=no_collect |
| T3 | google-gemini-2-5-flash | crashbench-abo5 | no_collect | 0.221 | 0 | status=no_collect |
| T3 | google-gemini-2-5-flash | crashbench-abo7 | no_collect | 0.286 | 0 | status=no_collect |
| T3 | google-gemini-2-5-flash | crashbench-abo8 | no_collect | 0.271 | 0 | status=no_collect |
| T3 | google-gemini-2-5-flash | juliet-cwe121-char-type-overrun-memcpy-01 | no_collect | 0.353 | 0 | status=no_collect |
| T3 | google-gemini-2-5-flash | juliet-cwe122-char-type-overrun-memcpy-01 | no_collect | 0.34 | 0 | status=no_collect |
| T3 | google-gemini-2-5-flash | juliet-cwe126-char-alloca-loop-01 | no_collect | 0.176 | 0 | status=no_collect |
| T3 | google-gemini-2-5-flash | juliet-cwe415-malloc-free-char-01 | no_collect | 0.209 | 0 | status=no_collect |
| T3 | google-gemini-2-5-flash | juliet-cwe416-malloc-free-char-01 | no_collect | 0.238 | 0 | status=no_collect |
| T3 | google-gemini-2-5-flash | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | google-gemini-2-5-flash | ncompress-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | google-gemini-2-5-flash | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | google-gemini-3-1-flash-lite-preview | bc-heap-overflow | error | None | 0 | status=error |
| T3 | google-gemini-3-1-flash-lite-preview | berry-1 | timeout | 600.074 | 0 | status=timeout |
| T3 | google-gemini-3-1-flash-lite-preview | berry-2 | timeout | 600.05 | 0 | status=timeout |
| T3 | google-gemini-3-1-flash-lite-preview | berry-3 | timeout | 600.045 | 0 | status=timeout |
| T3 | google-gemini-3-1-flash-lite-preview | berry-4 | timeout | 600.085 | 0 | status=timeout |
| T3 | google-gemini-3-1-flash-lite-preview | berry-5 | timeout | 600.07 | 0 | status=timeout |
| T3 | google-gemini-3-1-flash-lite-preview | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | google-gemini-3-1-flash-lite-preview | ncompress-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | google-gemini-3-1-flash-lite-preview | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | meta-llama-llama-3-1-8b-instruct | crashbench-abo1 | no_collect | 0.209 | 0 | status=no_collect |
| T3 | meta-llama-llama-3-1-8b-instruct | crashbench-abo2 | no_collect | 0.202 | 0 | status=no_collect |
| T3 | meta-llama-llama-3-1-8b-instruct | crashbench-abo3 | no_collect | 0.206 | 0 | status=no_collect |
| T3 | meta-llama-llama-3-1-8b-instruct | crashbench-abo5 | no_collect | 0.211 | 0 | status=no_collect |
| T3 | meta-llama-llama-3-1-8b-instruct | crashbench-abo7 | no_collect | 0.263 | 0 | status=no_collect |
| T3 | meta-llama-llama-3-1-8b-instruct | crashbench-abo8 | no_collect | 0.261 | 0 | status=no_collect |
| T3 | meta-llama-llama-3-1-8b-instruct | juliet-cwe121-char-type-overrun-memcpy-01 | no_collect | 0.323 | 0 | status=no_collect |
| T3 | meta-llama-llama-3-1-8b-instruct | juliet-cwe122-char-type-overrun-memcpy-01 | no_collect | 0.322 | 0 | status=no_collect |
| T3 | meta-llama-llama-3-1-8b-instruct | juliet-cwe126-char-alloca-loop-01 | no_collect | 0.169 | 0 | status=no_collect |
| T3 | meta-llama-llama-3-1-8b-instruct | juliet-cwe415-malloc-free-char-01 | no_collect | 0.17 | 0 | status=no_collect |
| T3 | meta-llama-llama-3-1-8b-instruct | juliet-cwe416-malloc-free-char-01 | no_collect | 0.205 | 0 | status=no_collect |
| T3 | meta-llama-llama-3-1-8b-instruct | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | meta-llama-llama-3-1-8b-instruct | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | nvidia-nemotron-3-nano-30b-a3b | berry-2 | ok | 78.212 | 0 | empty response (len=0) |
| T3 | nvidia-nemotron-3-nano-30b-a3b | berry-3 | no_collect | 78.387 | 0 | status=no_collect |
| T3 | nvidia-nemotron-3-nano-30b-a3b | berry-4 | ok | 139.602 | 35 | empty response (len=35) |
| T3 | nvidia-nemotron-3-nano-30b-a3b | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | nvidia-nemotron-3-nano-30b-a3b | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | openai-gpt-4o | crashbench-abo1 | no_collect | 0.213 | 0 | status=no_collect |
| T3 | openai-gpt-4o | crashbench-abo2 | no_collect | 0.21 | 0 | status=no_collect |
| T3 | openai-gpt-4o | crashbench-abo3 | no_collect | 0.211 | 0 | status=no_collect |
| T3 | openai-gpt-4o | crashbench-abo5 | no_collect | 0.208 | 0 | status=no_collect |
| T3 | openai-gpt-4o | crashbench-abo7 | no_collect | 0.267 | 0 | status=no_collect |
| T3 | openai-gpt-4o | crashbench-abo8 | no_collect | 0.268 | 0 | status=no_collect |
| T3 | openai-gpt-4o | juliet-cwe121-char-type-overrun-memcpy-01 | no_collect | 0.318 | 0 | status=no_collect |
| T3 | openai-gpt-4o | juliet-cwe122-char-type-overrun-memcpy-01 | no_collect | 0.32 | 0 | status=no_collect |
| T3 | openai-gpt-4o | juliet-cwe126-char-alloca-loop-01 | no_collect | 0.172 | 0 | status=no_collect |
| T3 | openai-gpt-4o | juliet-cwe415-malloc-free-char-01 | no_collect | 0.173 | 0 | status=no_collect |
| T3 | openai-gpt-4o | juliet-cwe416-malloc-free-char-01 | no_collect | 0.207 | 0 | status=no_collect |
| T3 | openai-gpt-4o | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | openai-gpt-4o | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | openai-gpt-5-5 | bc-heap-overflow | error | None | 0 | status=error |
| T3 | openai-gpt-5-5 | berry-1 | timeout | 600.004 | 0 | status=timeout |
| T3 | openai-gpt-5-5 | berry-2 | timeout | 600.008 | 0 | status=timeout |
| T3 | openai-gpt-5-5 | berry-3 | timeout | 600.009 | 0 | status=timeout |
| T3 | openai-gpt-5-5 | berry-5 | timeout | 600.008 | 0 | status=timeout |
| T3 | openai-gpt-5-5 | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | openai-gpt-5-5 | ncompress-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | openai-gpt-5-5 | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | qwen-qwen3-30b-a3b-instruct-2507 | bc-heap-overflow | error | None | 0 | status=error |
| T3 | qwen-qwen3-30b-a3b-instruct-2507 | man-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
| T3 | qwen-qwen3-30b-a3b-instruct-2507 | polymorph-overflow | build_failed | 0.0 | 0 | build_failed (probably man-overflow — known) |
