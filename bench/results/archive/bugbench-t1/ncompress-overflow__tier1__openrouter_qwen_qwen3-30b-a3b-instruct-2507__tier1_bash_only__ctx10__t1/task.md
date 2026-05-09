You're debugging a bug in `ncompress-overflow`, a real C program from the BugBench benchmark suite.

ncompress-4.2.4 stack buffer overflow. In compress42.c function comprexx(), a stack array tempname[MAXPATHLEN] is overflowed by strcpy(tempname, *fileptr) when the input filename exceeds MAXPATHLEN (1024) bytes. The overflow corrupts the stack return address, causing a crash.

You are in the project's source directory. The buggy binary is at `./compress`.
Key source file(s): compress42.c.

Crash reproduction: `./compress aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa...`

The binary was compiled with AddressSanitizer (-fsanitize=address). Running it with the crashing input will produce an ASan report showing the exact overflow location.

Use bash to investigate: read the source, reproduce the crash, run gdb in batch mode, etc. Identify the root cause and propose both a local fix and a structural global fix.
