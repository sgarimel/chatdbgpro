# ChatDBG ablation report — `external-native-ablation-20260504-merged-t3rerun`

Runs: **187** total, **165** scored.

Overall mean — root_cause: **0.497**, local_fix: **0.3333**, global_fix: **0.5394**

## By model

| model | n | root_cause_mean | local_fix_mean | global_fix_mean | elapsed_s_mean | input_tokens_mean | output_tokens_mean | tool_calls_mean | code_length_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| haiku | 11 |  |  |  | 0.0 | 0 | 0 | 0 | 0 |
| openrouter/anthropic/claude-sonnet-4.5 | 33 | 0.4848 | 0.2121 | 0.4848 | 184.7249 | 14112.4242 | 866.6364 | 13.9697 | 112.2121 |
| openrouter/google/gemini-3.1-flash-lite-preview | 33 | 0.4848 | 0.3333 | 0.4848 | 41.2282 | 7392.2727 | 405.3333 | 9.4848 | 47.5758 |
| openrouter/nvidia/nemotron-3-nano-30b-a3b | 33 | 0.1515 | 0.1515 | 0.303 | 173.8209 | 957.6364 | 882.1212 | 1.8788 | 103.0909 |
| openrouter/openai/gpt-5.5 | 33 | 0.8485 | 0.8182 | 0.9091 | 90.6058 | 9261.2121 | 1296.7273 | 12.3333 | 459.4242 |
| openrouter/qwen/qwen3-30b-a3b-instruct-2507 | 33 | 0.5152 | 0.1515 | 0.5152 | 98.664 | 6785.9394 | 580.8485 | 4.2424 | 116.8182 |
| sonnet | 11 |  |  |  | 0.0 | 0 | 0 | 0 | 0 |

## By tool config

| tool_config | n | root_cause_mean | local_fix_mean | global_fix_mean | elapsed_s_mean | input_tokens_mean | output_tokens_mean | tool_calls_mean | code_length_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| t3_unfenced_cmw.json | 55 | 0.5091 | 0.4182 | 0.6182 | 113.2958 | 3658.1818 | 1012.2364 | 18.6909 | 503.4727 |
| tier1_bash_only.json | 55 | 0.5273 | 0.3273 | 0.5455 | 102.3437 | 8687.6545 | 852.7455 | 3.1818 | 0 |
| tier2_gdb_plus_bash.json | 55 | 0.4545 | 0.2545 | 0.4545 | 137.7868 | 10759.8545 | 554.0182 | 3.2727 | 0 |
| tier4_claude_code.json | 22 |  |  |  | 0.0 | 0 | 0 | 0 | 0 |

## By (model, tool_config)

| model | tool_config | n | root_cause_mean | local_fix_mean | global_fix_mean | elapsed_s_mean | input_tokens_mean | output_tokens_mean | tool_calls_mean | code_length_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| haiku | tier4_claude_code.json | 11 |  |  |  | 0.0 | 0 | 0 | 0 | 0 |
| openrouter/anthropic/claude-sonnet-4.5 | t3_unfenced_cmw.json | 11 | 0.3636 | 0.3636 | 0.4545 | 200.6937 | 7414.5455 | 570.7273 | 32.9091 | 336.6364 |
| openrouter/anthropic/claude-sonnet-4.5 | tier1_bash_only.json | 11 | 0.6364 | 0.1818 | 0.5455 | 170.6279 | 18004.6364 | 1283.9091 | 4.9091 | 0 |
| openrouter/anthropic/claude-sonnet-4.5 | tier2_gdb_plus_bash.json | 11 | 0.4545 | 0.0909 | 0.4545 | 182.8531 | 16918.0909 | 745.2727 | 4.0909 | 0 |
| openrouter/google/gemini-3.1-flash-lite-preview | t3_unfenced_cmw.json | 11 | 0.7273 | 0.4545 | 0.5455 | 43.4519 | 3650.7273 | 471.4545 | 22.1818 | 142.7273 |
| openrouter/google/gemini-3.1-flash-lite-preview | tier1_bash_only.json | 11 | 0.5455 | 0.3636 | 0.7273 | 35.1805 | 5166.1818 | 458.5455 | 2.1818 | 0 |
| openrouter/google/gemini-3.1-flash-lite-preview | tier2_gdb_plus_bash.json | 11 | 0.1818 | 0.1818 | 0.1818 | 45.0522 | 13359.9091 | 286 | 4.0909 | 0 |
| openrouter/nvidia/nemotron-3-nano-30b-a3b | t3_unfenced_cmw.json | 11 | 0.3636 | 0.3636 | 0.6364 | 133.4842 | 1503.5455 | 1799 | 4.6364 | 309.2727 |
| openrouter/nvidia/nemotron-3-nano-30b-a3b | tier1_bash_only.json | 11 | 0 | 0 | 0.1818 | 117.3384 | 532 | 755 | 0.7273 | 0 |
| openrouter/nvidia/nemotron-3-nano-30b-a3b | tier2_gdb_plus_bash.json | 11 | 0.0909 | 0.0909 | 0.0909 | 270.6401 | 837.3636 | 92.3636 | 0.2727 | 0 |
| openrouter/openai/gpt-5.5 | t3_unfenced_cmw.json | 11 | 0.7273 | 0.7273 | 0.8182 | 132.552 | 3857.8182 | 1342.6364 | 27.4545 | 1378.2727 |
| openrouter/openai/gpt-5.5 | tier1_bash_only.json | 11 | 0.9091 | 0.9091 | 0.9091 | 83.2402 | 9686.0909 | 1375.6364 | 4.5455 | 0 |
| openrouter/openai/gpt-5.5 | tier2_gdb_plus_bash.json | 11 | 0.9091 | 0.8182 | 1 | 56.0251 | 14239.7273 | 1171.9091 | 5 | 0 |
| openrouter/qwen/qwen3-30b-a3b-instruct-2507 | t3_unfenced_cmw.json | 11 | 0.3636 | 0.1818 | 0.6364 | 56.2972 | 1864.2727 | 877.3636 | 6.2727 | 350.4545 |
| openrouter/qwen/qwen3-30b-a3b-instruct-2507 | tier1_bash_only.json | 11 | 0.5455 | 0.1818 | 0.3636 | 105.3315 | 10049.3636 | 390.6364 | 3.5455 | 0 |
| openrouter/qwen/qwen3-30b-a3b-instruct-2507 | tier2_gdb_plus_bash.json | 11 | 0.6364 | 0.0909 | 0.5455 | 134.3635 | 8444.1818 | 474.5455 | 2.9091 | 0 |
| sonnet | tier4_claude_code.json | 11 |  |  |  | 0.0 | 0 | 0 | 0 | 0 |

## By case

| case_id | n | root_cause_mean | local_fix_mean | global_fix_mean | elapsed_s_mean | input_tokens_mean | output_tokens_mean | tool_calls_mean | code_length_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| crashbench-abo1 | 17 | 0.6 | 0.1333 | 0.6667 | 62.5898 | 6676.4706 | 749.3529 | 4.1765 | 41.6471 |
| crashbench-abo2 | 17 | 0.5333 | 0.1333 | 0.6667 | 107.0038 | 6908.2941 | 685.4706 | 4.0588 | 124.8235 |
| crashbench-abo3 | 17 | 0.4 | 0.1333 | 0.4667 | 158.5836 | 5152.5294 | 390.6471 | 9.7647 | 37.3529 |
| crashbench-abo5 | 17 | 0.4667 | 0.1333 | 0.5333 | 126.5812 | 8162 | 783 | 8.9412 | 143.6471 |
| crashbench-abo7 | 17 | 0.4667 | 0.2 | 0.6 | 93.6563 | 6041 | 581.8824 | 5.4118 | 113.7059 |
| crashbench-abo8 | 17 | 0.3333 | 0.2 | 0.7333 | 90.6688 | 5722.4706 | 741.4118 | 9.8235 | 172.4118 |
| juliet-cwe121-char-type-overrun-memcpy-01 | 17 | 0.6 | 0.5333 | 0.2667 | 88.2671 | 6309.8824 | 947.8235 | 4.4706 | 253.9412 |
| juliet-cwe122-char-type-overrun-memcpy-01 | 17 | 0.7333 | 0.8 | 0.6 | 85.2057 | 12367.4118 | 974.6471 | 7.2941 | 181.5294 |
| juliet-cwe126-char-alloca-loop-01 | 17 | 0.4 | 0.5333 | 0.5333 | 128.4162 | 9043.8235 | 976.3529 | 13.9412 | 193.6471 |
| juliet-cwe415-malloc-free-char-01 | 17 | 0.6 | 0.5333 | 0.4 | 84.6852 | 3912.3529 | 547.0588 | 5.4706 | 107.4118 |
| juliet-cwe416-malloc-free-char-01 | 17 | 0.3333 | 0.3333 | 0.4667 | 117.7803 | 4457.4706 | 448.5294 | 8 | 258.7647 |

## Run status breakdown

- `missing_dep`: 22
- `no_collect`: 2
- `ok`: 128
- `timeout`: 35
