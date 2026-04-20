# mongoose-http-uninit

**Category:** missing zero-init → use-of-uninitialized-value
**Sanitizer:** MemorySanitizer
**Upstream:** [Mongoose v7.15](https://github.com/cesanta/mongoose/tree/7.15)

## The bug

`mg_http_parse()` in `mongoose.c` fills out a caller-supplied
`struct mg_http_message *hm`. Upstream zeroes the struct at entry:

```c
memset(hm, 0, sizeof(*hm));
```

so that fields the parser never writes (e.g. `hm->body.len`,
`hm->query.buf`, unused header slots in `hm->headers[]`) read as
deterministic zero. The injected patch deletes that memset.

When a request arrives that doesn't populate every optional field
(e.g. a simple `GET / HTTP/1.0\r\n\r\n` with no body and few
headers), the caller reads uninitialized stack memory out of the
struct. MemorySanitizer reports
`use-of-uninitialized-value` inside `mg_http_parse` (or the caller
that branches on one of the unset fields).

## Why it's instructive

- **Invisible in ASan.** This bug requires MSan — AddressSanitizer
  says nothing because the memory is validly allocated on the caller's
  stack. Runs tiering that uses the right sanitizer per bug.
- **Parser code is dense and plausible.** Unlike a toy, `mg_http_parse`
  is real production code with pointer arithmetic and control flow;
  removing one `memset` disappears easily into a diff review.
- **Global-fix is real engineering.** The root-cause answer is to
  stop relying on callers to zero output structs — either initialize
  per-field at the point of parse, or return a value struct instead
  of filling an out-param.

## Calibration pending (step 4)

- Pin context lines against Mongoose 7.15 `mongoose.c`.
- Pick a minimal MSan-instrumented test harness (short HTTP client
  loop against `mg_http_parse` directly, or the `http-server` sample
  rebuilt with MSan). `bench-repro.sh` uses a small self-contained
  harness `msan_http_parse` to avoid MSan-interposing libc.
- Flip `verified: true`.
