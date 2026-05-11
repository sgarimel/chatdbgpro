You're debugging a real-codebase bug in `berry-5` (project `berry`, an open-source C/C++ project from the BugsC++ corpus).

You are inside a Linux/amd64 container at /work — that's the project's source tree with the buggy binary already built.

## What we know
- Buggy binary: `/work/berry`
- Failing test invocation: `./berry tests/suffix.be`
- Observed behavior: `exit_code:0`
- Bug type: `other`
- Language: `c`
- Likely-buggy source file: `src/be_code.c` (the developer patch touched this file; start your investigation there).

## How to investigate
Use bash inside the container — run commands like `cd`, `ls`, `grep -rn`, `cat`, `find`, run the binary, run gdb in batch mode (`gdb -batch -ex run -ex bt --args /work/berry ...`).

Suggested first moves:
1. Run the failing-test command and capture its output to understand what fails.
2. List source files: `find /work -name '*.c' -not -path '*/test*' | head -30`.
3. Read the test file driving the failure to learn what behavior was expected.
4. Search the source for functions related to the failing test and inspect them.

Investigate the failure, localize the defect in the source, and propose both a local fix and a structural global fix.

## Final answer

Your final response MUST include three labelled paragraphs:

  ROOT CAUSE: <file:line and what is wrong, in your own words>
  LOCAL FIX:  <minimal code change that resolves the symptom>
  GLOBAL FIX: <structural change preventing this CLASS of bug>

Do NOT modify the source files on disk. Just investigate and produce the diagnosis as your final assistant message.
