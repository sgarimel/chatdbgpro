# zlib-inflate-dict-oob

**Category:** off-by-one → buffer overread/write (one past table slot)
**Sanitizer:** AddressSanitizer
**Upstream:** [zlib v1.3.1](https://github.com/madler/zlib/tree/v1.3.1)

## The bug

`inftrees.c::inflate_table()` builds Huffman decoding tables during
inflate. Its invariant: `used <= ENOUGH_{LENS,DISTS}`, and the "no more
room" guard is `used >= ENOUGH_…`. The injected patch weakens the
guard to `used > ENOUGH_…`, so the very last iteration can write
`table[ENOUGH_LENS]` — one past the array end.

For any input that requires a non-trivial dynamic Huffman tree, the
routine hits the weakened guard and oversteps. ASan reports a write
past the `work[]` array (stack or heap depending on build flags).

## Why it's instructive

- **Canonical single-char typo.** `>=` vs. `>` is the archetype of
  a numerical off-by-one. The fix is one character.
- **Deep in a performance-critical table builder**, so bashing with
  `printf`/`grep` alone is a realistic (and hard) strategy — tier 1
  vs tier 3 have very different chances here.
- **Global-fix angle is non-trivial.** zlib is C89, no templates or
  bounded-view types; the root-cause rubric pushes toward a real
  structural change (helper struct, checked push operation) that a
  zero-shot "revert the `=`" answer cannot satisfy.

## Calibration pending (step 4)

- Exact file is likely `inftrees.c` — confirm after clone.
- Confirm minigzip trips the guard on the repro input on x86_64 linux.
- Flip `verified: true`.
