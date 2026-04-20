# lua-string-use-after-free

**Category:** missing GC write-barrier → use-after-free on concat
**Sanitizer:** AddressSanitizer
**Upstream:** [Lua 5.4.7](https://github.com/lua/lua/tree/v5.4.7)

## The bug

Lua's VM implements string concatenation (`OP_CONCAT`) in `lvm.c` via
`luaV_concat`, which produces new strings on the heap and stores the
result back into a VM register. Because the register slot lives in a
parent GC object (the running function's stack), any time an old
string is replaced by a new one the code must call `luaC_barrier` /
`luaC_objbarrier` to tell the incremental collector that a previously
black object now points at a (possibly white) new one.

The injected patch deletes the write-barrier call in the concat path.
Subsequent GC steps walk the heap believing the stack already mentions
only black objects, miss the white result string, and collect it. The
next bytecode instruction that reads that register dereferences freed
memory. ASan reports `heap-use-after-free READ` inside `luaV_execute`
or a TString accessor.

## Why it's instructive

- **Classic incremental-GC invariant bug.** Missing write-barriers are
  among the hardest real-world bugs in managed-memory runtimes; this
  is a realistic instance of that pattern.
- **Crash is delayed from the bug site.** The offending opcode and the
  crashing opcode are not the same instruction — an agent that only
  inspects the crashing frame will miss the cause. Favors agents that
  can step backwards and reason about invariants.
- **Clean separation of local vs. global fix.** Local fix: add the
  barrier call back. Global fix: wrap register writes in a helper that
  enforces the barrier, so future maintainers cannot forget it on a
  new opcode.

## Calibration pending (step 4)

- Confirm exact barrier call name (`luaC_barrier`, `luaC_objbarrier`,
  `luaC_objbarrierback`) against 5.4.7 sources — names vary slightly.
- Pick a script that forces an incremental GC step between the concat
  and the next read of the result; `collectgarbage("step", 1)` loop
  is the reliable trigger.
- Flip `verified: true`.
