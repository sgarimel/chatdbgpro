You're debugging a bug in `ncompress-overflow`, a real C program from the BugBench benchmark suite.

ncompress-4.2.4 stack buffer overflow. In compress42.c function comprexx(), a stack array tempname[MAXPATHLEN] is overflowed by strcpy(tempname, *fileptr) when the input filename exceeds MAXPATHLEN (1024) bytes. The overflow corrupts the stack return address, causing a crash.

You are in the project's source directory. The buggy binary is at `./compress`.
Key source file(s): compress42.c.

Crash reproduction: `./compress aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa...`

You have two tools: `bash` (a shell) and `gdb` (a stateful debugger session pre-loaded with the buggy binary). Use both to investigate the crash, identify the root cause, and propose both a local fix and a structural global fix.
