# cjson-parse-string-oob

**Category:** off-by-one → buffer overread
**Sanitizer:** AddressSanitizer
**Upstream:** [cJSON v1.7.18](https://github.com/DaveGamble/cJSON/tree/v1.7.18)

## The bug

`parse_string()` in `cJSON.c` scans the input buffer for the closing
quote. The upstream loop has two termination conditions:

```c
while (((size_t)(input_end - input_buffer->content) < input_buffer->length)
       && (*input_end != '"'))
```

The injected patch drops the first condition, leaving only the
content-based test. For any input that lacks a closing `"`, the loop
walks off the end of the heap-allocated content region. ASan reports
`heap-buffer-overflow READ of size 1` inside `parse_string`.

## Why it's instructive

- **Small, local defect.** Exactly one token (`&&` sub-clause) is
  removed. The "fix" is a one-line restoration.
- **Realistic.** Dropped-bounds-check bugs are a documented pattern
  in C string parsers (cJSON itself has had a few historically).
- **Separates local from global fix.** Re-adding the check is the
  local fix. A root-cause fix moves to a bounded-buffer abstraction,
  which cJSON does not currently use — a non-trivial redesign and an
  honest test of the agent's taste.

## Calibration pending (step 4)

- Pin exact line numbers against the v1.7.18 commit sha.
- Confirm the repro input triggers the ASan report on x86_64 linux.
- Flip `verified: true` in `case.yaml`.
