You're debugging a real-codebase bug in `cjson-parse-string-oob` (an open-source C/C++ project).

You are at the project root. The buggy binary is at `./bench_driver`. The bug was injected by a small patch — somewhere in the source tree, a guard / check / initializer was removed or weakened.

Use bash to navigate the source tree, reproduce the failure, localize the defect, and propose both a local fix and a structural global fix.

Your final response MUST include three labelled paragraphs:

  ROOT CAUSE: <file:line and what is wrong, in your own words>
  LOCAL FIX:  <minimal code change that resolves the symptom>
  GLOBAL FIX: <structural change preventing this CLASS of bug>

Do NOT modify the source files on disk. Just investigate and produce the diagnosis as your final assistant message.
