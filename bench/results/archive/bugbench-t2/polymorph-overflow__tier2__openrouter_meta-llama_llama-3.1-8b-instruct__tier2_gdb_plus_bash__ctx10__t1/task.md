You're debugging a bug in `polymorph-overflow`, a real C program from the BugBench benchmark suite.

polymorph-0.4.0 stack buffer overflow in convert_fileName(). A for-loop copies characters from the 'original' argument into a stack buffer newname[MAX] (MAX=2048) one by one without bounds checking. When the input filename exceeds 2048 characters, the loop overwrites the stack return address, causing a crash.

You are in the project's source directory. The buggy binary is at `./polymorph`.
Key source file(s): polymorph.c, polymorph_types.h.

Crash reproduction: `./polymorph -f AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA...`

You have two tools: `bash` (a shell) and `gdb` (a stateful debugger session pre-loaded with the buggy binary). Use both to investigate the crash, identify the root cause, and propose both a local fix and a structural global fix.
