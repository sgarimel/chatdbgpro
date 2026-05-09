You're debugging a C/C++ bug. The buggy binary is at `./build/prog` and the source file is `program.cpp` in the current directory.

Run command: `./build/prog`

Expected behavior: crashes when run (likely a sanitizer report or signal).

Use your bash tool to investigate (run the binary, run gdb / lldb in batch mode, read source). Identify the root cause and propose both a local fix and a structural global fix.

When done, your final response MUST include three labelled paragraphs:

  ROOT CAUSE: <file:line and what is wrong, in your own words>
  LOCAL FIX:  <minimal code change that resolves the symptom>
  GLOBAL FIX: <structural change preventing this CLASS of bug>

Do NOT modify the source file. Just investigate and produce the diagnosis as your final assistant message.
