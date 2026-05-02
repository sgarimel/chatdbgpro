"""Tier-2 runner — invoked as a subprocess by Tier2Driver.

Tier 2 = mini-swe-agent's bash-only scaffold extended with a SECOND
tool: a stateful gdb session. Bash is mini's canonical tool (stateless
`subprocess.run` per call). The gdb tool maintains a persistent gdb
subprocess for the duration of the agent run, so the model can set
breakpoints, run, step, examine variables, and continue across turns.

Architecture decisions (in accordance with how mini-swe-agent is used
in general):

1. **Tool-calling protocol, not text-mode.** Same as Tier 1's robust
   path. We extend mini's `LitellmModel` to register both `BASH_TOOL`
   and `GDB_TOOL` in `tools=[...]`. The default OpenAI-style
   tool-calling API handles the dispatch; mini's parser identifies
   which tool was called via `tool_call.function.name`.

2. **Custom action parser** that accepts both tool names — mini's
   built-in `parse_toolcall_actions` hardcodes "bash" and rejects
   everything else. The parsed action carries a `tool` key so the
   environment dispatches correctly.

3. **Custom Environment** that subclasses `LocalEnvironment`. For
   bash actions, falls through to parent (stateless `subprocess.run`).
   For gdb actions, dispatches to the persistent `GdbSession`.

4. **`GdbSession`** wraps a long-lived `gdb -q -nx --args <binary>`
   subprocess. Each `gdb` action sends commands then a unique
   sentinel `echo` and reads the gdb stdout stream until the sentinel
   appears. This is the standard "command boundary" technique for
   driving a REPL-style subprocess; works even when commands cause
   the inferior to run because gdb returns to prompt at crash /
   breakpoint / clean exit.

5. **Submit semantics unchanged.** Mini's `LocalEnvironment._check_finished`
   detects `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` in bash output and
   raises `Submitted`. We keep that — submission is via bash, not gdb,
   so the existing flow works.

6. **Same collect.json schema** as Tier 1 / Tier 3, with a richer
   `tool_frequency` (counts both bash and gdb) and per-tool_call
   `tool_name` labels. `judge.py` consumes Tier-2 runs without per-
   tier branching.
"""
from __future__ import annotations

import argparse
import json
import os
import select
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


# ----- prompts ------------------------------------------------------------

# System template — concise identity statement, matching mini's design
# (heavy lifting in the instance template).
T2_SYSTEM_TEMPLATE = """\
You are an expert software engineer debugging C/C++ programs. You
interact with a Unix shell via two tools — `bash` for general shell
commands and `gdb` for stateful debugger commands against the buggy
binary.
"""


# Instance template — explains BOTH tools, when to use which, and
# requires a structured ROOT CAUSE / LOCAL FIX / GLOBAL FIX diagnosis
# in the final response. Patterned after `swebench.yaml`'s structure.
T2_INSTANCE_TEMPLATE = """\
{{task}}

<instructions>
# Task Instructions

You're investigating a bug in a C/C++ program. Two tools are
available:

  bash   stateless shell — `ls`, `cat`, `grep`, `nl`, `file`, etc.
         Each call is a fresh subshell. Useful for source inspection.

  gdb    stateful gdb session pre-loaded with the buggy binary.
         The session persists across calls — `break`, `run`, `bt`,
         `print`, `step`, `continue`, `frame N`, etc. retain state
         from one call to the next. The binary and its argv are
         already configured; just `run` to start.

Use `gdb` for ANY debugger work — it's ~10x more useful than
`gdb -batch` from bash because state persists.

For each response:
1. Include reasoning text explaining your analysis.
2. Provide ONE OR MORE tool calls (`bash` and/or `gdb`).

## Workflow

1. `bash`: read the source (`nl -ba program.c`).
2. `gdb`: `run` to observe the crash; `bt` for backtrace.
3. `gdb`: `frame N` / `print VAR` / `info locals` to inspect state.
4. Iterate as needed — `gdb` keeps your breakpoints / current frame.
5. Form a diagnosis grounded in the evidence.

3-8 investigation steps is typical.

## CRITICAL REQUIREMENTS

- Every response MUST include AT LEAST ONE tool call (`bash` or
  `gdb`). A response with no tool calls is rejected.
- Use non-interactive flags. No editors / pagers (`vi`, `less`).
- Each `bash` call is a fresh subshell; `cd` and `export` don't
  persist between bash calls. The `gdb` session, by contrast, IS
  stateful.

## Submission

When done investigating, your final response MUST include all three
labelled paragraphs in the THOUGHT text BEFORE the submit `bash` call:

  ROOT CAUSE: <file:line and what is wrong, in your own words.>
  LOCAL FIX:  <minimal code change that resolves the symptom.>
  GLOBAL FIX: <structural change preventing this CLASS of bug —
              type changes, API redesign, compile-time check, etc.>

Then submit using:

    bash tool: {"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}

The judge reads your THOUGHT prose. If you submit without writing the
three labelled sections, your run scores 0.

<system_information>
{{system}} {{release}} {{machine}}
</system_information>
</instructions>
"""


T2_FORMAT_ERROR = """\
Tool call error:

<error>
{{error}}
</error>

Every response must include at least one `bash` or `gdb` tool call.

  bash:  Tool: bash    Arguments: {"command": "your_shell_command"}
  gdb:   Tool: gdb     Arguments: {"commands": "break X\\nrun\\nbt"}

If you're submitting your diagnosis, your final response MUST include
the structured ROOT CAUSE / LOCAL FIX / GLOBAL FIX paragraphs followed
by:

  Tool: bash
  Arguments: {"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}
"""


# ----- tool definitions ---------------------------------------------------

BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": (
            "Execute a single bash command (or a pipeline). Each call is a "
            "fresh subshell — `cd` and exported variables do not persist. "
            "Useful for source inspection, file listing, running grep / "
            "sed / nl, and for the FINAL submit command. Output is "
            "captured (combined stdout/stderr) with the exit code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute.",
                },
            },
            "required": ["command"],
        },
    },
}

GDB_TOOL = {
    "type": "function",
    "function": {
        "name": "gdb",
        "description": (
            "Send commands to a persistent gdb session that is preloaded "
            "with the buggy binary (already configured with its argv). "
            "The session is STATEFUL — breakpoints, the current frame, "
            "and variable inspections persist across calls. Use this for "
            "ALL debugger work; it's substantially more efficient than "
            "`gdb -batch` from bash. Multi-line commands separated by "
            "newlines are sent in order. Common commands: "
            "`run` (start the program), `bt` (backtrace), "
            "`break <file>:<line>` (set breakpoint), "
            "`p <expr>` (print), `info locals`, `frame N` (select frame), "
            "`step` / `next` / `continue`, `disassemble`, `x/<n><fmt> <addr>`."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "string",
                    "description": (
                        "One or more gdb commands separated by newlines. "
                        "Output is captured up to the next gdb prompt."
                    ),
                },
            },
            "required": ["commands"],
        },
    },
}


# ----- GdbSession: persistent gdb subprocess -----------------------------

@dataclass
class GdbSessionConfig:
    binary: Path
    args: list[str]
    cwd: Path
    startup_timeout_s: float = 10.0
    command_timeout_s: float = 30.0


class GdbSession:
    """Long-lived gdb subprocess driven via stdin/stdout pipes.

    Boundary detection: each command batch is followed by an `echo
    <sentinel>` so we can read the stdout stream until the sentinel
    appears. gdb's `echo` writes to gdb's own stdout (NOT the
    inferior's), so the sentinel is reliably visible even when the
    inferior also writes output. After a `run` command, gdb returns
    to its `(gdb)` prompt at crash / breakpoint / clean exit, after
    which the trailing `echo <sentinel>` executes normally.

    Edge cases handled:
      - Inferior never returns (infinite loop): caller's wallclock
        timeout fires; `_read_until` raises TimeoutError; we log and
        return a timeout dict rather than crashing the agent.
      - gdb itself crashed / quit: `proc.poll() != None`; subsequent
        calls return an "exception_info" dict.
      - Long output: streamed line-by-line, no single buffer overrun.
    """

    def __init__(self, config: GdbSessionConfig):
        self.config = config
        self._closed = False
        argv = ["gdb", "-q", "-nx", "--args",
                str(config.binary), *config.args]
        # stderr=STDOUT keeps the streams in order; gdb's prompts and
        # the inferior's stderr both surface in the same readable
        # buffer.
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(config.cwd),
            text=True,
            bufsize=1,
        )
        # Configure gdb for batch-friendly behavior. `set pagination off`
        # is critical — without it gdb halts on '--Type <RET>' prompts
        # mid-output and our reader hangs.
        self._send_raw(
            "set pagination off\n"
            "set confirm off\n"
            "set print pretty on\n"
            "set breakpoint pending on\n"
        )
        # Drain startup banner + the four config lines.
        self._drain_initial(timeout_s=config.startup_timeout_s)

    def _send_raw(self, s: str) -> None:
        if self._closed or self.proc.stdin is None or self.proc.stdin.closed:
            return
        try:
            self.proc.stdin.write(s)
            self.proc.stdin.flush()
        except BrokenPipeError:
            self._closed = True

    def _drain_initial(self, *, timeout_s: float) -> None:
        """Consume gdb's startup messages plus our four config lines'
        echo. We don't try to find the (gdb) prompt — instead we send
        a sentinel and read until we see it, which is the same
        approach used for every later command call."""
        sentinel = f"___GDB_INIT_DONE_{uuid.uuid4().hex}___"
        self._send_raw(f"echo {sentinel}\\n\n")
        try:
            self._read_until(sentinel, timeout_s=timeout_s)
        except TimeoutError:
            # gdb startup taking too long — keep going; per-command
            # reads have their own timeouts and will surface failures
            # to the model.
            pass

    def _read_until(self, sentinel: str, *, timeout_s: float) -> str:
        """Read from gdb's stdout until `sentinel` appears in the
        stream. Returns everything BEFORE the sentinel (the sentinel
        line itself is consumed but excluded). Raises TimeoutError
        after `timeout_s` of no progress on the read."""
        if self.proc.stdout is None:
            raise RuntimeError("gdb stdout closed")
        deadline = time.monotonic() + timeout_s
        chunks: list[str] = []
        # Read line-by-line so partial output is never lost on timeout.
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"gdb command exceeded {timeout_s:.1f}s timeout. "
                    f"Inferior may be in an infinite loop."
                )
            r, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not r:
                continue  # spurious wakeup; loop checks deadline
            line = self.proc.stdout.readline()
            if line == "":
                # EOF — gdb died.
                raise RuntimeError(
                    "gdb subprocess closed stdout (likely terminated). "
                    "Output so far:\n" + "".join(chunks)
                )
            if sentinel in line:
                # Strip the sentinel line entirely; everything before
                # is real gdb output.
                break
            chunks.append(line)
        return "".join(chunks)

    def execute(self, commands: str) -> dict[str, Any]:
        """Run `commands` (a multi-line gdb command string) and return
        an output dict shaped like LocalEnvironment.execute()'s
        return value: `{output, returncode, exception_info}`."""
        if self._closed or self.proc.poll() is not None:
            return {
                "output": "",
                "returncode": -1,
                "exception_info": (
                    f"gdb session is no longer running (exit_code="
                    f"{self.proc.returncode}). Earlier commands may have "
                    f"caused gdb to quit."
                ),
            }
        sentinel = f"___GDB_CMD_DONE_{uuid.uuid4().hex}___"
        # Ensure the trailing echo is on a separate line. Treat
        # whatever the model sent as opaque text.
        payload = commands.rstrip("\n") + "\n" + f"echo {sentinel}\\n\n"
        self._send_raw(payload)
        try:
            output = self._read_until(
                sentinel, timeout_s=self.config.command_timeout_s
            )
            return {"output": output, "returncode": 0, "exception_info": ""}
        except TimeoutError as e:
            # The inferior is stuck. Send Ctrl-C to interrupt gdb +
            # the inferior, then drain to a fresh prompt so the
            # session is still usable for the next call.
            self._interrupt_and_resync()
            return {
                "output": "",
                "returncode": -1,
                "exception_info": str(e),
                "extra": {"exception_type": "TimeoutError"},
            }
        except RuntimeError as e:
            self._closed = True
            return {
                "output": "",
                "returncode": -1,
                "exception_info": str(e),
                "extra": {"exception_type": "RuntimeError"},
            }

    def _interrupt_and_resync(self) -> None:
        """Send a SIGINT to gdb (which forwards it to the inferior),
        then read+discard until a fresh sentinel echoes back. Best
        effort — if it fails the session is marked closed."""
        try:
            self.proc.send_signal(2)  # SIGINT
        except (ProcessLookupError, OSError):
            self._closed = True
            return
        sentinel = f"___GDB_RESYNC_{uuid.uuid4().hex}___"
        self._send_raw(f"echo {sentinel}\\n\n")
        try:
            self._read_until(sentinel, timeout_s=5.0)
        except (TimeoutError, RuntimeError):
            self._closed = True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.proc.poll() is None:
            self._send_raw("quit\n")
            try:
                self.proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ----- custom mini parser, environment, model ----------------------------

def _build_dual_parser(format_error_template: str):
    """Closure capturing the format-error template — invoked by our
    custom `_parse_actions` override. Mirrors mini's
    parse_toolcall_actions but accepts BOTH `bash` and `gdb` tool
    names and tags each parsed action with a `tool` field."""
    from minisweagent.exceptions import FormatError
    from jinja2 import Template, StrictUndefined

    def parse(tool_calls: list) -> list[dict]:
        if not tool_calls:
            raise FormatError({
                "role": "user",
                "content": Template(format_error_template, undefined=StrictUndefined).render(
                    error="No tool calls found in the response. Every response MUST include at least one tool call.",
                    actions=[],
                ),
                "extra": {"interrupt_type": "FormatError"},
            })
        actions: list[dict] = []
        for tc in tool_calls:
            err = ""
            try:
                args = json.loads(tc.function.arguments)
            except Exception as e:
                args = {}
                err = f"Error parsing tool call arguments: {e}. "
            name = tc.function.name
            if name == "bash":
                if not isinstance(args, dict) or "command" not in args:
                    err += "Missing 'command' argument in bash tool call."
                if err:
                    raise FormatError({
                        "role": "user",
                        "content": Template(format_error_template, undefined=StrictUndefined).render(
                            actions=[], error=err.strip()
                        ),
                        "extra": {"interrupt_type": "FormatError"},
                    })
                actions.append({
                    "tool": "bash",
                    "command": args["command"],
                    "tool_call_id": tc.id,
                })
            elif name == "gdb":
                if not isinstance(args, dict) or "commands" not in args:
                    err += "Missing 'commands' argument in gdb tool call."
                if err:
                    raise FormatError({
                        "role": "user",
                        "content": Template(format_error_template, undefined=StrictUndefined).render(
                            actions=[], error=err.strip()
                        ),
                        "extra": {"interrupt_type": "FormatError"},
                    })
                actions.append({
                    "tool": "gdb",
                    "commands": args["commands"],
                    "tool_call_id": tc.id,
                })
            else:
                raise FormatError({
                    "role": "user",
                    "content": Template(format_error_template, undefined=StrictUndefined).render(
                        actions=[],
                        error=(f"Unknown tool '{name}'. Only 'bash' and 'gdb' are available."),
                    ),
                    "extra": {"interrupt_type": "FormatError"},
                })
        return actions

    return parse


def _make_dual_model(model_class_str: str, model_kwargs: dict, model_name: str):
    """Construct a mini model class instance whose `_query` exposes
    BOTH bash and gdb tools, and whose `_parse_actions` accepts
    either. We subclass at runtime to avoid having to mirror every
    LitellmModel init/method.
    """
    from minisweagent.models import get_model_class
    from minisweagent.models.utils.actions_toolcall import format_toolcall_observation_messages
    from minisweagent.models.utils.cache_control import set_cache_control
    from minisweagent.models.utils.anthropic_utils import _reorder_anthropic_thinking_blocks
    import litellm

    base_class = get_model_class(model_name, model_class_str)
    parser = _build_dual_parser(model_kwargs["format_error_template"])
    target_tools = [BASH_TOOL, GDB_TOOL]

    class DualToolModel(base_class):
        def _query(self, messages, **kwargs):
            try:
                return litellm.completion(
                    model=self.config.model_name,
                    messages=messages,
                    tools=target_tools,
                    **(self.config.model_kwargs | kwargs),
                )
            except litellm.exceptions.AuthenticationError as e:
                e.message += " You can permanently set your API key with `mini-extra config set KEY VALUE`."
                raise e

        def _parse_actions(self, response):
            tool_calls = response.choices[0].message.tool_calls or []
            return parser(tool_calls)

        def format_observation_messages(self, message, outputs, template_vars=None):
            actions = (message.get("extra") or {}).get("actions") or []
            return format_toolcall_observation_messages(
                actions=actions,
                outputs=outputs,
                observation_template=self.config.observation_template,
                template_vars=template_vars,
                multimodal_regex=self.config.multimodal_regex,
            )

    DualToolModel.__name__ = f"DualTool_{base_class.__name__}"
    return DualToolModel(**model_kwargs)


def _make_dual_environment(cwd: Path, env: dict[str, str], gdb_binary: Path,
                            gdb_args: list[str], bash_timeout: int = 30,
                            gdb_command_timeout: float = 30.0):
    """Construct a LocalEnvironment subclass that dispatches on
    action['tool']. bash actions go through the parent class (stateless
    subprocess.run). gdb actions go through a persistent GdbSession
    held as instance state."""
    from minisweagent.environments.local import LocalEnvironment

    class LocalGdbBashEnvironment(LocalEnvironment):
        def __init__(self):
            super().__init__(cwd=str(cwd), env=env, timeout=bash_timeout)
            self.gdb = GdbSession(GdbSessionConfig(
                binary=gdb_binary,
                args=gdb_args,
                cwd=cwd,
                command_timeout_s=gdb_command_timeout,
            ))

        def execute(self, action, cwd_override="", *, timeout=None):
            tool = action.get("tool", "bash")
            if tool == "gdb":
                output = self.gdb.execute(action.get("commands", ""))
                self._check_finished(output)
                return output
            return super().execute(action, cwd=cwd_override, timeout=timeout)

        def serialize(self):
            base = super().serialize()
            base["info"]["config"]["environment_extra"] = {
                "tier2_dual_tool": True,
                "gdb_binary": str(gdb_binary),
                "gdb_args": list(gdb_args),
            }
            return base

    return LocalGdbBashEnvironment()


# ----- collect.json synthesis (mirror Tier 1 / Tier 3) -------------------

def _action_text(a) -> str:
    """Pull the action's textual payload — `command` for bash, or
    `commands` for gdb. Always returns a string."""
    if isinstance(a, dict):
        for key in ("command", "commands", "text", "action"):
            v = a.get(key)
            if isinstance(v, str):
                return v
        return str(a)
    if isinstance(a, str):
        return a
    return ""


def _action_tool_name(a) -> str:
    if isinstance(a, dict):
        for key in ("tool", "tool_name"):
            v = a.get(key)
            if isinstance(v, str):
                return v
    return "bash"


def _extract_response(messages: list[dict]) -> str:
    """Concatenate all non-empty assistant content. Same rationale as
    Tier 1's runner — preserves the model's complete diagnostic prose
    regardless of which turn carried it."""
    parts: list[str] = []
    for m in messages:
        if m.get("role") == "assistant":
            c = (m.get("content") or "").strip()
            if c:
                parts.append(c)
    for m in reversed(messages):
        if m.get("role") == "exit":
            sub = ((m.get("extra") or {}).get("submission") or "").strip()
            if sub:
                parts.append(f"[submission]\n{sub}")
            break
    return "\n\n---\n\n".join(parts)


def _extract_actions(messages: list[dict]) -> list[dict]:
    """Pull every tool call (bash or gdb) the agent made, in order,
    paired with its observation length. Mirrors the schema written by
    Tier3Driver and Tier1Driver."""
    out: list[dict] = []
    pending: list = []
    for m in messages:
        role = m.get("role")
        if role == "assistant":
            for a in (m.get("extra") or {}).get("actions") or []:
                pending.append(a)
        elif role == "tool" and pending:
            obs_len = len(m.get("content") or "")
            a = pending.pop(0)
            cmd = _action_text(a)
            tool = _action_tool_name(a)
            verb = (cmd.strip().split() or [""])[0].split("/")[-1] or tool
            out.append({
                "tool_name": tool,        # "bash" or "gdb"
                "verb": verb,
                "call": cmd,
                "result_length": obs_len,
            })
    for a in pending:
        cmd = _action_text(a)
        tool = _action_tool_name(a)
        verb = (cmd.strip().split() or [""])[0].split("/")[-1] or tool
        out.append({"tool_name": tool, "verb": verb,
                    "call": cmd, "result_length": 0})
    return out


def _tally_tokens(messages: list[dict]) -> tuple[int, int]:
    p = c = 0
    for m in messages:
        if m.get("role") != "assistant":
            continue
        extra = m.get("extra") or {}
        usage = extra.get("usage") or {}
        if not usage:
            response = extra.get("response") or {}
            usage = response.get("usage") or {}
        p += int(usage.get("prompt_tokens", 0) or 0)
        c += int(usage.get("completion_tokens", 0) or 0)
    return p, c


# ----- main --------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", required=True, type=Path)
    p.add_argument("--model", required=True)
    p.add_argument("--task-file", required=True, type=Path)
    p.add_argument("--cwd", default=None,
                   help="Working directory for the agent's bash sandbox + "
                        "starting cwd for the gdb session. Default = run-dir.")
    p.add_argument("--gdb-binary", required=True, type=Path,
                   help="Path to the buggy binary that gdb will load.")
    p.add_argument("--gdb-args", default="[]",
                   help="JSON list of args passed to the inferior binary "
                        "(go after `gdb --args <binary>`).")
    p.add_argument("--step-limit", type=int, default=15)
    p.add_argument("--cost-limit", type=float, default=0.5)
    p.add_argument("--mini-model-class", default=None,
                   help="Override mini's auto model-class selection.")
    args = p.parse_args()

    run_dir = args.run_dir.resolve()
    task = args.task_file.read_text()
    agent_cwd = Path(args.cwd or run_dir)
    gdb_args = json.loads(args.gdb_args)

    # Late mini imports.
    from minisweagent.agents.default import DefaultAgent

    model_kwargs = {
        "model_name": args.model,
        "cost_tracking": "ignore_errors",
        "format_error_template": T2_FORMAT_ERROR,
        "model_kwargs": {
            "drop_params": True,
            "temperature": 0.0,
            "parallel_tool_calls": True,
        },
    }
    model = _make_dual_model(args.mini_model_class or "", model_kwargs, args.model)

    env = _make_dual_environment(
        cwd=agent_cwd,
        env={
            "PAGER": "cat", "MANPAGER": "cat", "LESS": "-R",
            "PIP_PROGRESS_BAR": "off", "TQDM_DISABLE": "1",
        },
        gdb_binary=args.gdb_binary.resolve(),
        gdb_args=[str(a) for a in gdb_args],
    )

    agent = DefaultAgent(
        model, env,
        system_template=T2_SYSTEM_TEMPLATE,
        instance_template=T2_INSTANCE_TEMPLATE,
        step_limit=args.step_limit,
        cost_limit=args.cost_limit,
        output_path=run_dir / "trajectory.json",
    )

    t0 = time.time()
    exit_status = "unknown"
    submission = ""
    try:
        result = agent.run(task=task)
        exit_status = result.get("exit_status", "unknown") if result else "unknown"
        submission = result.get("submission", "") if result else ""
    except Exception as e:
        exit_status = type(e).__name__
        sys.stderr.write(f"[tier2-runner] agent.run raised {exit_status}: {e}\n")
    elapsed = time.time() - t0

    # Best-effort cleanup of the gdb subprocess regardless of
    # whether the agent completed.
    try:
        env.gdb.close()
    except Exception:
        pass

    messages = agent.messages
    response = _extract_response(messages)
    tool_calls = _extract_actions(messages)
    p_tok, c_tok = _tally_tokens(messages)

    # Two-level frequency: outer key is tool_name (bash/gdb),
    # inner verb counts are reported separately so analysis can pivot.
    freq: dict[str, int] = {}
    by_tool: dict[str, dict[str, int]] = {}
    for tc in tool_calls:
        tname = tc.get("tool_name", "bash")
        verb = tc.get("verb", tname)
        freq[verb] = freq.get(verb, 0) + 1
        by_tool.setdefault(tname, {})
        by_tool[tname][verb] = by_tool[tname].get(verb, 0) + 1
    tool_name_counts = {k: sum(v.values()) for k, v in by_tool.items()}

    collect = {
        "meta": {
            "uid": run_dir.name,
            "time": datetime.now().isoformat(timespec="seconds"),
            "model": args.model,
            "tool_config": "tier2_gdb_plus_bash.json",
            "enabled_tools": ["bash", "gdb"],
            "agent": "mini-swe-agent",
            "agent_version": _mini_version(),
            "mini_model_class": type(model).__module__ + "." + type(model).__name__,
            "mini_model_kwargs": model_kwargs["model_kwargs"],
            "prompt_mode": "toolcalling",  # tier 2 is always tool-calling
            "tier": 2,
        },
        "instructions": T2_SYSTEM_TEMPLATE,
        "queries": [
            {
                "user_text": task,
                "prompt": task,
                "thinking": None,
                "response": response,
                "code_blocks": [],
                "total_code_length": 0,
                "num_tool_calls": len(tool_calls),
                "tool_calls": tool_calls,
                # Backward-compat: top-level tool_frequency by verb so
                # existing analyze_runs / heatmap scripts keep working.
                "tool_frequency": freq,
                # New: per-tool-name counts so Tier 2 analysis can
                # answer "how often did the agent reach for gdb?"
                "tool_name_counts": tool_name_counts,
                "tool_frequency_by_tool": by_tool,
                "stats": {
                    "completed": exit_status == "Submitted",
                    "model": args.model,
                    "cost": float(getattr(agent, "cost", 0.0) or 0.0),
                    "time": elapsed,
                    "tokens": p_tok + c_tok,
                    "prompt_tokens": p_tok,
                    "completion_tokens": c_tok,
                    "exit_status": exit_status,
                    "submission": submission,
                },
            }
        ],
    }
    (run_dir / "collect.json").write_text(json.dumps(collect, indent=2))

    print(
        f"[tier2-runner] exit_status={exit_status} elapsed={elapsed:.1f}s "
        f"steps={len(tool_calls)} bash={tool_name_counts.get('bash',0)} "
        f"gdb={tool_name_counts.get('gdb',0)} cost=${float(getattr(agent, 'cost', 0.0) or 0.0):.4f}"
    )
    return 0


def _mini_version() -> str:
    try:
        from importlib.metadata import version
        return version("mini-swe-agent")
    except Exception:
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
