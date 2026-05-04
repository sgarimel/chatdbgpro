# T3/T4 Prompt and Tool-Surface Diagnosis

Date: 2026-05-04

## Executive Summary

The very low scores seen for strong models on recent synthetic/BugsCPP/YARA-style ablations are likely not explained by model weakness alone. The observed failures line up with harness and prompt issues:

- Tier 3 ChatDBG is often given a much weaker task surface than Tier 4 Claude Code.
- Tier 3 `tier3_gdb_only` does not expose bash and also restricts many normal GDB commands.
- The ChatDBG prompt still tells the model to use shell discovery commands even when bash is disabled.
- Some logs show GDB attached to `/usr/bin/bash` or another wrapper rather than the actual buggy binary.
- Wrong-output bugs are presented through a run-until-exit debugger contract, which often leaves ChatDBG stopped at an uninformative `exit` frame.
- Tier 1/Tier 2 final-answer capture can discard useful prose if the model fails the required submit-tool protocol.
- Tier 4 successes may be contaminated when agents can inspect git history and directly read the injected patch.

The benchmark should not be interpreted as clean evidence that strong models cannot solve these bugs until these harness issues are controlled.

## T3 Prompt Surface

Tier 3 uses ChatDBG's generic prompt path:

- System instructions: `src/chatdbg/util/instructions/default.txt`
- Prompt assembly: `src/chatdbg/util/prompts.py`
- GDB-specific prompt facts: `src/chatdbg/chatdbg_gdb.py`

The first user prompt has this shape:

```text
The program has this stack trace:
...
The program encountered the following error:
...
This was the command line:
...
This was the program's input:
...
This is the history of some debugger commands I ran:
...
<CHATDBG_PROMPT_EXTRA>
What's the bug? Give me a fix.
```

The default instructions tell the model to discover source layout with shell commands such as `ls` and `find`, then read relevant source with `get_code_surrounding`. That instruction is reasonable when the bash tool is enabled, but misleading for `tier3_gdb_only`, where bash is explicitly disabled.

For wrong-output BugsCPP/YARA cases, this prompt can be especially thin: the model may see only a system-frame stack such as `exit`, a generic non-crash error, and a command line. If the command line is a wrapper such as `/usr/bin/bash`, the model has little or no actionable path to the root cause.

## T4 Prompt Surface

Tier 4 writes an explicit `task.md` in `bench/drivers/tier4_claude.py`.

For BugsCPP-style cases, the prompt includes:

- case id and project name,
- host source-tree path,
- `/work` container mount,
- container name,
- buggy binary path,
- failing test invocation,
- observed behavior,
- bug type,
- language,
- source-reading instructions,
- docker/apptainer command templates for running the binary or GDB,
- required final labels: `ROOT CAUSE`, `LOCAL FIX`, `GLOBAL FIX`.

This is much richer than the T3 prompt. Tier 4 is told how to read source, how to run commands, and how to enter the target container. Tier 3 must infer much more from a generic ChatDBG stack/error prompt and may not have the tools the prompt suggests using.

## GDB Command Restrictions

GDB actions are restricted in Tier 3 ChatDBG unless `unsafe` is enabled.

The enforcement point is:

- `src/chatdbg/chatdbg_gdb.py`, `GDBDialog.llm_debug`

It checks:

```python
if not chatdbg_config.unsafe and not command_is_safe(command):
    self._unsafe_cmd = True
    return command, f"Command `{command}` is not allowed."
```

The allowlist is:

- `src/chatdbg/native_util/safety.py`

Allowed unconditionally:

```text
apropos
bt
down
frame
h
help
info
language
l
list
source
up
version
```

Allowed conditionally:

```text
p
print
```

The `p`/`print` commands must match a restrictive expression regex.

Common GDB commands blocked by default include:

```text
break
run
continue
next
step
finish
shell
disassemble
x
set
watch
catch
call
backtrace
```

Note that `bt` is allowed, but full `backtrace` is not.

## Log Corroboration

A random check of `tier3_gdb_only` run logs confirmed the restriction behavior.

In sampled logs, enabled tools were:

```text
llm_debug
llm_get_code_surrounding
```

No bash tool was available.

The logs showed attempted restricted commands, but ChatDBG refused to execute them. Examples:

- `disassemble exit_shell` returned `Command `disassemble exit_shell` is not allowed.`
- `disassemble main` returned `Command `disassemble main` is not allowed.`
- `backtrace` returned `Command `backtrace` is not allowed.`

Across the local `tier3_gdb_only` corpus inspected:

```text
tier3_gdb_only files: 865
total logged tool calls: 4897
blocked/unallowed attempts: 572
```

Most common blocked attempts:

```text
shell: 223
disassemble: 126
backtrace: 122
break: 55
set: 16
run: 13
continue: 6
catch: 3
x: 2
call: 2
```

So the precise statement is: restricted GDB commands are sometimes attempted, but they are not successfully executed.

## Wrong Binary / Wrapper Failure Mode

Older logs show ChatDBG being attached to `/usr/bin/bash`, with a stack like:

```text
exit -> exit_shell -> main
```

For YARA-style cases, the expected root cause might be in a source file such as `libyara/parser.c`, but the model is shown a bash process and may not have bash access to inspect the source tree.

Recent code in `bench/drivers/docker_gdb.py` and `bench/common.py` appears to try to surface `buggy_binary_path`, `buggy_binary_argv`, and richer `CHATDBG_PROMPT_*` fields. That is a partial fix, but the run artifacts show that this failure mode has affected previous ablations and should be guarded against explicitly.

Recommended invariant: if a case has a known `buggy_binary_path`, the harness should fail or mark the run as harness-invalid when the debugged target shown to ChatDBG is `/bin/bash`, `/usr/bin/bash`, `make`, `sed`, `find`, or another wrapper.

## Wrong-Output Bug Mismatch

The ChatDBG setup is strongest when the program crashes and the debugger stops near useful source frames. Many BugsCPP/YARA cases are wrong-output or test-oracle failures. In those cases:

- the program may exit cleanly or with a generic nonzero code,
- GDB may stop at `exit`,
- the stack may contain only system/wrapper frames,
- the prompt may still ask for the "root cause of this crash."

Without bash, source search, useful breakpoints, or a task-level observed/expected-output description, this is not a fair presentation of an "easy single-file synthetic" debugging problem.

## Tier 1 / Tier 2 Final-Answer Capture

Tier 1 and Tier 2 use mini-swe-agent. Their protocol requires every assistant turn to include a tool call, and final diagnostic prose must be paired with a submit command.

Some logs show models producing useful final prose without the submit tool call. The harness then records format errors and may eventually exhaust limits. The judge sees no usable final synthesis and scores the run as zero.

This means some low scores reflect final-answer protocol brittleness rather than failure to investigate.

## Tier 4 Patch Leakage Risk

Tier 4 Claude Code runs can use bash and source tools. In at least one successful YARA run, the agent used git history commands such as:

```text
git diff HEAD~1 HEAD --name-only
git diff HEAD~1 HEAD -- libyara/parser.c
```

That can reveal the injected patch directly. If `.git` history contains the bug injection diff, a solved Tier 4 run may not reflect debugging ability. It may reflect oracle leakage.

For clean comparisons, benchmark workspaces should hide patch provenance:

- remove `.git`,
- squash/flatten history,
- create an exported source snapshot,
- or forbid git-diff access for benchmark runs.

## Expected Versus Observed Alignment

Expected benchmark contract:

- The model gets enough context and tools to investigate the buggy program.
- All tiers see comparable facts about the failing case.
- T3 represents ChatDBG plus GDB/source tooling.
- T4 represents a stronger general coding agent with broader tools.
- Scores measure diagnosis quality.

Observed contract in problematic runs:

- T3 may see a wrapper process instead of the buggy binary.
- T3 may be instructed to use shell but not given bash.
- T3 GDB commands are heavily sanitized.
- Wrong-output bugs stop in unhelpful exit frames.
- Tier 1/Tier 2 may lose final prose due to submit protocol.
- T4 may have access to patch history.

These mismatches can drive low T3 scores and inflated T4 scores at the same time.

## Recommended Fixes

1. Make T3 prompt instructions conditional on enabled tools. Do not mention shell discovery unless `enable_bash` is true.
2. For `tier3_gdb_only`, either expand the safe GDB allowlist or describe the tier honestly as restricted GDB inspection only.
3. Consider allowing at least `break`, `run`, `continue`, `finish`, `disassemble`, `x`, and `backtrace`, or set `CHATDBG_UNSAFE=true` in isolated benchmark containers.
4. Add an explicit harness validity check for the actual debug target. Mark wrapper targets as harness-invalid, not model failures.
5. For wrong-output cases, provide observed/expected behavior and a useful failing invocation in the ChatDBG prompt.
6. Use `buggy_binary_path` and `buggy_binary_argv` whenever available; fail fast when they are missing for cases that need them.
7. Use `--breakpoint-at-patch` or another non-oracle localization strategy for wrong-output cases where run-until-exit is uninformative.
8. Fix mini-swe-agent final-answer capture so final prose without a submit tool is not silently lost.
9. Remove or flatten git history in benchmark workspaces before running bash-enabled agents.
10. Re-run a small smoke suite before the next ablation: one YARA case and one true synthetic case across T3 restricted, T3 with bash, and T4 with patch history removed.

## Bottom Line

The current artifacts support the diagnosis that the benchmark is partially measuring harness and prompt affordances rather than pure model debugging ability. T3 ChatDBG, especially with `tier3_gdb_only`, is not receiving the same practical investigative surface as T4 Claude Code. The low scores should be treated as suspect until the tool restrictions, wrapper-target failures, wrong-output prompt mismatch, final-answer capture, and patch leakage are fixed or explicitly separated in the analysis.
