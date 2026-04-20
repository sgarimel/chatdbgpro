# sqlite-shell-null-deref

**Category:** missing null-check → NULL pointer dereference
**Sanitizer:** AddressSanitizer
**Upstream:** [SQLite v3.45.2](https://github.com/sqlite/sqlite/tree/version-3.45.2)

## The bug

The SQLite command-line shell (`shell.c`) implements the `.read FILE`
dot-command by calling `fopen(FILE, "rb")` and then feeding lines from
the returned `FILE *` into the parser. Upstream code checks the result
of `fopen` and prints `cannot open "..."` when it is NULL.

The injected patch deletes the `if (in == 0) { ... }` guard. When the
user runs `.read /nonexistent/path`, `fopen` returns NULL, and the next
line calls `fgets(..., in)` with `in == NULL`. On glibc / Apple libc
this is a straight NULL deref inside `fgets` and ASan reports
`SEGV on unknown address 0x000000000000`.

## Why it's instructive

- **Classic error-path omission.** "Forgot to check the return value"
  is one of the most common real C bugs. The fix is to re-add four
  lines.
- **Small but real code.** `shell.c` is a ~27k-line real program, not
  a toy. An agent that can localize this purely from a stack trace
  that points into libc's `fgets` has shown it can navigate past the
  superficial frame into the caller.
- **Global-fix angle is clean.** The root-cause answer is a helper
  (e.g. `open_or_complain(path)`) that centralizes the "open a file,
  print a nice error, return NULL on failure" idiom used in several
  dot-commands, so the guard cannot be forgotten again.

## Calibration pending (step 4)

- Confirm patch context lines against the v3.45.2 `shell.c` checkout.
- Confirm macOS/Linux ASan both produce a SEGV (not a silent abort)
  when `fgets(NULL)` is called — glibc is known to crash here.
- Flip `verified: true`.
