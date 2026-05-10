# ChatDBG ablation report — `smoke-berry-t1t3-20260504-220419`

Runs: **60** total, **60** scored.

Overall mean — root_cause: **0**, local_fix: **0**, global_fix: **0**

## By model

| model | n | root_cause_mean | local_fix_mean | global_fix_mean | elapsed_s_mean | input_tokens_mean | output_tokens_mean | tool_calls_mean | code_length_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openrouter/google/gemini-2.5-flash | 10 | 0 | 0 | 0 | 87.704 | 447493.7 | 4698.4 | 46 | 48.4 |
| openrouter/meta-llama/llama-3.1-8b-instruct | 10 | 0 | 0 | 0 | 189.8576 | 149329.3 | 1398.7 | 21.5 | 232.7 |
| openrouter/nvidia/nemotron-3-nano-30b-a3b | 10 | 0 | 0 | 0 | 285.9659 | 0 | 0 | 0 | 0 |
| openrouter/openai/gpt-4o | 10 | 0 | 0 | 0 | 176.8968 | 851095.9 | 9476.7 | 51 | 83.3 |
| openrouter/openai/gpt-5.5 | 10 | 0 | 0 | 0 | 289.1627 | 0 | 0 | 0 | 0 |
| openrouter/qwen/qwen3-30b-a3b-instruct-2507 | 10 | 0 | 0 | 0 | 200.1304 | 243078.6 | 1948 | 31 | 0 |

## By tool config

| tool_config | n | root_cause_mean | local_fix_mean | global_fix_mean | elapsed_s_mean | input_tokens_mean | output_tokens_mean | tool_calls_mean | code_length_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tier1_bash_only.json | 30 | 0 | 0 | 0 | 380.7747 | 562389.2667 | 5647.7667 | 45.7667 | 0 |
| tier3_gdb_only.json | 30 | 0 | 0 | 0 | 29.1311 | 1276.5667 | 192.8333 | 4.0667 | 121.4667 |

## By (model, tool_config)

| model | tool_config | n | root_cause_mean | local_fix_mean | global_fix_mean | elapsed_s_mean | input_tokens_mean | output_tokens_mean | tool_calls_mean | code_length_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openrouter/google/gemini-2.5-flash | tier1_bash_only.json | 5 | 0 | 0 | 0 | 144.7818 | 891467 | 8760 | 77.2 | 0 |
| openrouter/google/gemini-2.5-flash | tier3_gdb_only.json | 5 | 0 | 0 | 0 | 30.6262 | 3520.4 | 636.8 | 14.8 | 96.8 |
| openrouter/meta-llama/llama-3.1-8b-instruct | tier1_bash_only.json | 5 | 0 | 0 | 0 | 359.0324 | 296416.6 | 2666.4 | 38.4 | 0 |
| openrouter/meta-llama/llama-3.1-8b-instruct | tier3_gdb_only.json | 5 | 0 | 0 | 0 | 20.6828 | 2242 | 131 | 4.6 | 465.4 |
| openrouter/nvidia/nemotron-3-nano-30b-a3b | tier1_bash_only.json | 5 | 0 | 0 | 0 | 540.9752 | 0 | 0 | 0 | 0 |
| openrouter/nvidia/nemotron-3-nano-30b-a3b | tier3_gdb_only.json | 5 | 0 | 0 | 0 | 30.9566 | 0 | 0 | 0 | 0 |
| openrouter/openai/gpt-4o | tier1_bash_only.json | 5 | 0 | 0 | 0 | 327.5648 | 1700294.8 | 18564.2 | 97 | 0 |
| openrouter/openai/gpt-4o | tier3_gdb_only.json | 5 | 0 | 0 | 0 | 26.2288 | 1897 | 389.2 | 5 | 166.6 |
| openrouter/openai/gpt-5.5 | tier1_bash_only.json | 5 | 0 | 0 | 0 | 541.0064 | 0 | 0 | 0 | 0 |
| openrouter/openai/gpt-5.5 | tier3_gdb_only.json | 5 | 0 | 0 | 0 | 37.319 | 0 | 0 | 0 | 0 |
| openrouter/qwen/qwen3-30b-a3b-instruct-2507 | tier1_bash_only.json | 5 | 0 | 0 | 0 | 371.2878 | 486157.2 | 3896 | 62 | 0 |
| openrouter/qwen/qwen3-30b-a3b-instruct-2507 | tier3_gdb_only.json | 5 | 0 | 0 | 0 | 28.973 | 0 | 0 | 0 | 0 |

## By case

| case_id | n | root_cause_mean | local_fix_mean | global_fix_mean | elapsed_s_mean | input_tokens_mean | output_tokens_mean | tool_calls_mean | code_length_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| berry-1 | 12 | 0 | 0 | 0 | 241.1255 | 179712.3333 | 2284.3333 | 22.5833 | 213.3333 |
| berry-2 | 12 | 0 | 0 | 0 | 199.2929 | 346963.8333 | 3652.25 | 26.9167 | 42.3333 |
| berry-3 | 12 | 0 | 0 | 0 | 240.6488 | 551365.5 | 5457 | 30.6667 | 19.3333 |
| berry-4 | 12 | 0 | 0 | 0 | 180.6927 | 199767.8333 | 1190.75 | 33.5833 | 0 |
| berry-5 | 12 | 0 | 0 | 0 | 163.0046 | 131355.0833 | 2017.1667 | 10.8333 | 28.6667 |

## Run status breakdown

- `no_collect`: 21
- `ok`: 27
- `timeout`: 12
