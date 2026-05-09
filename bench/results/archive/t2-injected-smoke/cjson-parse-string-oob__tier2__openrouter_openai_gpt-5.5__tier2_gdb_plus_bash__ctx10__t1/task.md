You're debugging a real-codebase bug in `cjson-parse-string-oob` (an open-source C/C++ project).

cJSON.c's parse_string() scans input looking for the closing quote. The pre-patch guard `(input_end - content) < length` is dropped, so an unterminated JSON string causes the loop to read past the input buffer. AddressSanitizer flags a heap-buffer-overflow in parse_string on any input of the form `"abc` with no closing quote.

You are at the project root (cloned upstream source tree). The buggy binary is at `./bench_driver` and a stateful gdb session is pre-loaded with it (with the failing-test argv already configured).

The failing-input bytes for this bug have been written to `/work/bench/results/t2-injected-smoke/cjson-parse-string-oob__tier2__openrouter_openai_gpt-5.5__tier2_gdb_plus_bash__ctx10__t1/stdin.bin`. To reproduce the crash:
  - In gdb: `run < /work/bench/results/t2-injected-smoke/cjson-parse-string-oob__tier2__openrouter_openai_gpt-5.5__tier2_gdb_plus_bash__ctx10__t1/stdin.bin`
  - Or in bash: `cat /work/bench/results/t2-injected-smoke/cjson-parse-string-oob__tier2__openrouter_openai_gpt-5.5__tier2_gdb_plus_bash__ctx10__t1/stdin.bin | ./bench_driver`


Use `gdb` for runtime debugging (set breakpoints in the upstream source files, run, step, print). Use `bash` to navigate the source tree (`grep -rn`, `find`, `nl`). Identify the root cause and propose both a local fix and a structural global fix.
