# ChatDBG ablation report — `external-native-ablation-20260504-merged`

Runs: **187** total, **27** scored.

Overall mean — root_cause: **0.037**, local_fix: **0**, global_fix: **0.037**

## By model

| model | n | root_cause_mean | local_fix_mean | global_fix_mean | elapsed_s_mean | input_tokens_mean | output_tokens_mean | tool_calls_mean | code_length_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| haiku | 11 |  |  |  | 0.0 | 0 | 0 | 0 | 0 |
| openrouter/anthropic/claude-sonnet-4.5 | 33 | 1 | 0 | 1 | 137.249 | 12565.697 | 762.6364 | 6.2424 | 52.7576 |
| openrouter/google/gemini-3.1-flash-lite-preview | 33 | 0 | 0 | 0 | 39.4246 | 7902.5152 | 406.4848 | 8.7273 | 72.2121 |
| openrouter/nvidia/nemotron-3-nano-30b-a3b | 33 | 0 | 0 | 0 | 173.1825 | 931.697 | 1285.4242 | 1.9394 | 177.0303 |
| openrouter/openai/gpt-5.5 | 33 | 0 | 0 | 0 | 70.2057 | 8554.4848 | 945.0606 | 6.4545 | 88.6061 |
| openrouter/qwen/qwen3-30b-a3b-instruct-2507 | 33 | 0 | 0 | 0 | 90.083 | 7356.3939 | 436.3333 | 5.303 | 94.1818 |
| sonnet | 11 |  |  |  | 0.0 | 0 | 0 | 0 | 0 |

## By tool config

| tool_config | n | root_cause_mean | local_fix_mean | global_fix_mean | elapsed_s_mean | input_tokens_mean | output_tokens_mean | tool_calls_mean | code_length_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tier1_bash_only.json | 55 | 0.3333 | 0 | 0.3333 | 102.3437 | 8687.6545 | 852.7455 | 3.1818 | 0 |
| tier2_gdb_plus_bash.json | 55 | 0 | 0 | 0 | 137.7868 | 10759.8545 | 554.0182 | 3.2727 | 0 |
| tier3_gdb_only.json | 55 | 0 | 0 | 0 | 65.9564 | 2938.9636 | 894.8 | 10.7455 | 290.8727 |
| tier4_claude_code.json | 22 |  |  |  | 0.0 | 0 | 0 | 0 | 0 |

## By (model, tool_config)

| model | tool_config | n | root_cause_mean | local_fix_mean | global_fix_mean | elapsed_s_mean | input_tokens_mean | output_tokens_mean | tool_calls_mean | code_length_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| haiku | tier4_claude_code.json | 11 |  |  |  | 0.0 | 0 | 0 | 0 | 0 |
| openrouter/anthropic/claude-sonnet-4.5 | tier1_bash_only.json | 11 | 1 | 0 | 1 | 170.6279 | 18004.6364 | 1283.9091 | 4.9091 | 0 |
| openrouter/anthropic/claude-sonnet-4.5 | tier2_gdb_plus_bash.json | 11 |  |  |  | 182.8531 | 16918.0909 | 745.2727 | 4.0909 | 0 |
| openrouter/anthropic/claude-sonnet-4.5 | tier3_gdb_only.json | 11 |  |  |  | 58.266 | 2774.3636 | 258.7273 | 9.7273 | 158.2727 |
| openrouter/google/gemini-3.1-flash-lite-preview | tier1_bash_only.json | 11 |  |  |  | 35.1805 | 5166.1818 | 458.5455 | 2.1818 | 0 |
| openrouter/google/gemini-3.1-flash-lite-preview | tier2_gdb_plus_bash.json | 11 | 0 | 0 | 0 | 45.0522 | 13359.9091 | 286 | 4.0909 | 0 |
| openrouter/google/gemini-3.1-flash-lite-preview | tier3_gdb_only.json | 11 |  |  |  | 38.0411 | 5181.4545 | 474.9091 | 19.9091 | 216.6364 |
| openrouter/nvidia/nemotron-3-nano-30b-a3b | tier1_bash_only.json | 11 |  |  |  | 117.3384 | 532 | 755 | 0.7273 | 0 |
| openrouter/nvidia/nemotron-3-nano-30b-a3b | tier2_gdb_plus_bash.json | 11 |  |  |  | 270.6401 | 837.3636 | 92.3636 | 0.2727 | 0 |
| openrouter/nvidia/nemotron-3-nano-30b-a3b | tier3_gdb_only.json | 11 | 0 | 0 | 0 | 131.5689 | 1425.7273 | 3008.9091 | 4.8182 | 531.0909 |
| openrouter/openai/gpt-5.5 | tier1_bash_only.json | 11 |  |  |  | 83.2402 | 9686.0909 | 1375.6364 | 4.5455 | 0 |
| openrouter/openai/gpt-5.5 | tier2_gdb_plus_bash.json | 11 |  |  |  | 56.0251 | 14239.7273 | 1171.9091 | 5 | 0 |
| openrouter/openai/gpt-5.5 | tier3_gdb_only.json | 11 | 0 | 0 | 0 | 71.3519 | 1737.6364 | 287.6364 | 9.8182 | 265.8182 |
| openrouter/qwen/qwen3-30b-a3b-instruct-2507 | tier1_bash_only.json | 11 | 0 | 0 | 0 | 105.3315 | 10049.3636 | 390.6364 | 3.5455 | 0 |
| openrouter/qwen/qwen3-30b-a3b-instruct-2507 | tier2_gdb_plus_bash.json | 11 |  |  |  | 134.3635 | 8444.1818 | 474.5455 | 2.9091 | 0 |
| openrouter/qwen/qwen3-30b-a3b-instruct-2507 | tier3_gdb_only.json | 11 | 0 | 0 | 0 | 30.554 | 3575.6364 | 443.8182 | 9.4545 | 282.5455 |
| sonnet | tier4_claude_code.json | 11 |  |  |  | 0.0 | 0 | 0 | 0 | 0 |

## By case

| case_id | n | root_cause_mean | local_fix_mean | global_fix_mean | elapsed_s_mean | input_tokens_mean | output_tokens_mean | tool_calls_mean | code_length_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| crashbench-abo1 | 17 | 0.25 | 0 | 0.25 | 51.8068 | 6666.1176 | 606.7647 | 5.5882 | 34.9412 |
| crashbench-abo2 | 17 | 0 | 0 | 0 | 98.9606 | 7280.1765 | 652.1176 | 5.5294 | 164.4706 |
| crashbench-abo3 | 17 | 0 | 0 | 0 | 127.2486 | 5096.8235 | 374.7059 | 5.1176 | 84.4706 |
| crashbench-abo5 | 17 | 0 | 0 | 0 | 105.3494 | 7510.8824 | 578.7059 | 4.5294 | 13.7059 |
| crashbench-abo7 | 17 | 0 | 0 | 0 | 73.4101 | 7286.2353 | 521.4118 | 6.4706 | 45.1765 |
| crashbench-abo8 | 17 | 0 | 0 | 0 | 81.9294 | 4865.7647 | 1901.7059 | 4.8824 | 133.8824 |
| juliet-cwe121-char-type-overrun-memcpy-01 | 17 | 0 | 0 | 0 | 86.0683 | 6142.1176 | 746.7647 | 5.0588 | 167.7059 |
| juliet-cwe122-char-type-overrun-memcpy-01 | 17 | 0 | 0 | 0 | 69.8387 | 12015.4706 | 875.7059 | 7.8824 | 208.9412 |
| juliet-cwe126-char-alloca-loop-01 | 17 | 0 | 0 | 0 | 111.031 | 7410.2353 | 369.5294 | 3.4706 | 8.1176 |
| juliet-cwe415-malloc-free-char-01 | 17 | 0 | 0 | 0 | 74.2599 | 4539.5294 | 573 | 4 | 67.5294 |
| juliet-cwe416-malloc-free-char-01 | 17 | 0 | 0 | 0 | 110.3781 | 3613.4706 | 245.8235 | 3.1176 | 12.1176 |

## Run status breakdown

- `missing_dep`: 22
- `ok`: 138
- `timeout`: 27
