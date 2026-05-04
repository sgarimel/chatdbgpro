# Enriched Prompt Fix for BugsCPP

## Problem

The current BugsCPP prompts across all tiers are broken or weak:

- **T3 (ChatDBG/GDB)**: GDB attaches to `bash` (the trigger wrapper), not the buggy binary. Stack trace shows `exit() → exit_shell() → main()` from bash. Model correctly identifies "this is bash, not yara" and gives up.
- **T1 (bash only)**: Prompt says `buggy binary: /work/(see workspace)` — the path is missing.
- **T2 (bash+gdb)**: Same wrong-binary problem as T3 for the GDB half.
- **All tiers**: No test output, no project structure, no description of expected vs actual behavior. Just "exit_code:2".

## Root Cause

1. `buggy_binary_path` is NULL for 91/158 bugs in corpus.db. When it's NULL, the harness falls back to `trigger_argv[0]` which is always `bash`.
2. The prompt templates don't include test output, project structure, or behavioral context.
3. For non-crashing bugs (96% of corpus), GDB has nothing useful to show even with the right binary.

## Fix: Two Parts

### Part 1: Fix `buggy_binary_path` in corpus.db

For every bug where `buggy_binary_path` is NULL, we need to populate it. The field should contain the path to the actual compiled binary (relative to `/work/`), NOT the bash trigger wrapper.

**How to find it**: Run the trigger command with `strace -f -e trace=execve` and find the deepest non-shell binary in the exec chain. Ibraheem's `pipeline2/reprobe_buggy_binary.py` does this — run it for all bugs that have `buggy_binary_path=NULL`.

```bash
# Check which bugs need fixing
python3 -c "
import sqlite3
conn = sqlite3.connect('data/corpus.db')
for r in conn.execute('''SELECT bug_id, project FROM bugs
    WHERE included_in_corpus=1 AND buggy_binary_path IS NULL'''):
    print(r[0])
"

# Run the reprobe script (needs Docker + built workspaces)
python3 pipeline2/reprobe_buggy_binary.py
```

For the yara project specifically, the binary is likely at:
- `yara-*`: binary is `/work/src/yara` or `/work/yara` (check with `find /work -name yara -type f -executable`)

### Part 2: Enrich the Prompt Templates

The prompt needs to include everything the harness legitimately knows. Here's what to change in each tier:

#### T3 (ChatDBG/GDB) — `src/chatdbg/native_util/dbg_dialog.py`

The `build_prompt()` method constructs the initial prompt from the debugger state. Currently it only includes:
- Stack trace (from GDB, which is attached to the wrong binary)
- Error message (generic)
- Command line

**Change it to include** (read from env vars set by the Docker driver):

```python
# In build_prompt() or build_enriched_stacktrace():

prompt = f"""Project: {project} ({language})
Buggy binary: {buggy_binary_path}
Test command: {' '.join(trigger_argv)}
Observed behavior: {bug_observed}
Bug type: {bug_type}

The program has this stack trace:
```
{stack_trace}
```

{enriched_source_context}

What is the root cause of this failure? Walk through the program state,
identify the defect, and propose a fix."""
```

The env vars `CHATDBG_PROMPT_BINARY`, `CHATDBG_PROMPT_ERROR`, `CHATDBG_PROMPT_EXTRA` are already wired up in `docker_gdb.py` via `build_oracle_strings()`. Use those.

#### T1 (bash only) — `bench/drivers/tier1_runner.py`

The `_build_task_description()` function builds the prompt. Currently:

```python
f"The buggy binary in this case is `/work/{case.buggy_binary_path or '(see workspace)'}`."
```

**Change to**:

```python
task = f"""You're debugging a real-codebase bug in `{case.bug_id}` (project `{case.project}`).

You are inside a Linux/amd64 container at /work with the buggy source tree.

## What we know
- Buggy binary: /work/{case.buggy_binary_path}
- Test command: {' '.join(case.trigger_argv)}
- Observed behavior: {case.bug_observed}
- Bug type: {case.bug_type}
- Language: {case.language}

## Project structure
Run `find /work -name "*.{case.language}" -not -path "*/test*" | head -30` to see the source layout.

## What to investigate
1. Run the test command and capture its output to understand what fails
2. Read the test file to understand what behavior it expects
3. Search the source for functions related to the failing test
4. Find the defect and propose a fix

Investigate the failure, localize the defect in the source, and propose both a local fix and a structural global fix.
"""
```

#### T2 (bash+gdb) — `bench/drivers/tier2_runner.py`

Same as T1 but also mention:

```python
f"""## GDB session
A gdb session is pre-loaded with the buggy binary at /work/{case.buggy_binary_path}.
You can set breakpoints, run, step, print variables, and inspect memory.
The binary was compiled with debug symbols (-ggdb).

Use gdb to:
- Set breakpoints in functions related to the failing test
- Step through the code path that the test exercises
- Print variable values to find where behavior diverges from expected
"""
```

#### T4 (Claude Code) — `bench/drivers/tier4_claude.py`

Already the best prompt. Just fix the binary path:

```python
f"Buggy binary inside the container: `/work/{case.buggy_binary_path}`"
```

### Part 3: Fix GDB Attachment in Docker Driver

In `bench/drivers/docker_gdb.py`, the `_build_gdb_session()` function needs to ensure GDB attaches to the right binary. The current code already has logic for this via `buggy_binary_path`:

```python
if case.buggy_binary_argv and case.buggy_binary_path:
    run_argv = [f"/work/{case.buggy_binary_path}"] + list(case.buggy_binary_argv[1:])
else:
    run_argv = case.trigger_argv  # Falls back to bash — THIS IS THE PROBLEM
```

Once `buggy_binary_path` is populated for all bugs, the fallback to `trigger_argv` (bash) won't happen.

## What NOT to Include (Cheating)

Do NOT put these in the prompt — they give away the answer:

- `patch_first_file` — which file the bug is in
- `patch_first_line` — which line the bug is on
- `patch_diff` — the actual fix
- Any hint like "look at function X" or "the bug is in module Y"

These are only used by the **judge** (in `case.yaml` criteria), never shown to the model.

## Validation

After applying the fix, verify with a single yara-1 run:

```bash
# T3 should now show a yara stack trace, not bash
python3 bench/orchestrator.py \
  --models openrouter/openai/gpt-4o \
  --tool-configs tier3_gdb_only.json \
  --tiers 3 \
  --cases yara-1 \
  --trials 1 \
  --docker \
  --name test-enriched \
  --timeout 180

# Check the prompt in collect.json
python3 -c "
import json
with open('bench/results/test-enriched/yara-1__tier3__openrouter_openai_gpt-4o__tier3_gdb_only__ctx10__t1/collect.json') as f:
    c = json.load(f)
print(c['queries'][0]['prompt'])
"
```

The prompt should mention `yara` (not `bash`), include the test command, and show a real stack trace from the yara binary.

## Summary of Files to Modify

| File | What to change |
|------|---------------|
| `data/corpus.db` | Populate `buggy_binary_path` for all 91 NULL entries |
| `pipeline2/reprobe_buggy_binary.py` | Run this to auto-detect binary paths |
| `src/chatdbg/native_util/dbg_dialog.py` | Enrich T3 prompt with project/binary/observed metadata |
| `bench/drivers/tier1_runner.py` | Enrich T1 prompt template |
| `bench/drivers/tier2_runner.py` | Enrich T2 prompt template |
| `bench/drivers/tier4_claude.py` | Fix binary path (minor) |
| `bench/drivers/docker_gdb.py` | Already handles buggy_binary_path — just needs db populated |

## Expected Impact

Based on our xv6 experiments:
- Enriched prompt alone (without changing tools) improved reasoning quality dramatically
- The combination of enriched prompt + correct binary + bash access should bring BugsCPP scores from ~0% to meaningful levels
- T4 (Claude Code) already scores well because it has git access — enriched prompts should help T1-T3 catch up
