You're debugging a bug in `bc-heap-overflow`, a real C program from the BugBench benchmark suite.

bc-1.06 heap buffer overflow in storage.c more_arrays(). The initialization loop on line 176 uses 'v_count' (variable count) as the upper bound instead of 'a_count' (array count). When v_count > a_count, the loop writes past the allocated a_names/arrays heap buffers, corrupting heap metadata and causing a crash in subsequent lookups.

You are in the project's source directory. The buggy binary is at `./bc_buggy`.
Key source file(s): bc/storage.c, bc/util.c, bc/bc.c.

Crash reproduction (stdin): `./bc_buggy < crash_stdin.bin`

You have two tools: `bash` (a shell) and `gdb` (a stateful debugger session pre-loaded with the buggy binary). Use both to investigate the crash, identify the root cause, and propose both a local fix and a structural global fix.
