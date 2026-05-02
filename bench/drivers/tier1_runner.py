"""Tier-1 runner — invoked as a subprocess by Tier1Driver.

Runs in the `.venv-bench` Python where `mini-swe-agent` (>=v2.2.8) is
installed. Reads the task description from a file, instantiates a
`DefaultAgent` with `LocalEnvironment` and a `mini-swe-agent`-selected
model class, runs the agent until it submits or hits a step/cost
limit, and writes two files into the run directory:

    trajectory.json    mini-swe-agent's native serialize() format
                       (full message list + cost + exit_status)
    collect.json       our standardized schema, identical to what
                       Tier3Driver's ChatDBG run produces — so the
                       existing judge.py can score it without any
                       per-tier branching.

## Robustness across models

This runner mirrors the tool-calling pattern from mini's canonical
`swebench.yaml` config. The key choices:

  * **Tool-calling, not fenced bash blocks.** Mini's `LitellmModel`
    (the default class returned by `get_model()`) calls
    `litellm.completion(tools=[BASH_TOOL])` and parses the response's
    `tool_calls` field. Modern API models — gpt, claude, gemini, qwen
    via OpenRouter — all support this protocol natively, so the agent
    works without per-model prompt engineering.

  * **`get_model()` (not `LitellmModel(...)` directly).** Mini's
    `get_model_class()` chooses the optimal class from the model name
    string ('claude' → caching enabled; 'response' models → Responses
    API). Bypassing this loses Anthropic prompt-cache savings and
    forces every model down the LiteLLM Chat Completions path. Defer
    to mini.

  * **`drop_params=True` and `parallel_tool_calls=True` model kwargs.**
    Same as `swebench.yaml`. `drop_params` lets LiteLLM silently drop
    arguments unsupported by a given backend (e.g. some local-served
    models reject `parallel_tool_calls`); `parallel_tool_calls` lets
    capable models batch multiple bash commands per turn.

  * **`--mini-model-class` override.** For text-completion-only models
    (rare today) or for explicitly testing alternative protocols
    (`litellm_textbased`, `litellm_response`, `openrouter`), the
    orchestrator can pass a class hint that bypasses the auto-routing.

Standalone: this module does NOT import from bench.* — it runs in
mini's venv where bench.common may not import (different Python
version, different deps). All marshalling lives here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime


# System template — concise. Heavy lifting is in the instance template
# so per-case task framing carries the full context. Modeled after
# `mini.yaml` and `swebench.yaml`'s system templates: short identity
# statement, no format guidance (format guidance belongs in the
# instance template where the task lives, not in the system message
# whose prefix is cached for many turns).
DEBUG_SYSTEM_TEMPLATE = """\
You are an expert software engineer debugging C/C++ programs. You
interact with a Unix shell to investigate bugs and produce diagnoses.
"""


# Instance template — patterned after `swebench.yaml`'s instance
# template (which mini uses for production SWE-bench evaluations).
# Tool-calling first, with explicit per-step rules and a CRITICAL
# REQUIREMENTS block that all the model providers we tested respect.
DEBUG_INSTANCE_TEMPLATE = """\
{{task}}

<instructions>
# Task Instructions

## Overview

You're a software engineer interacting continuously with a computer
shell to debug a C/C++ program. Your job is to investigate and produce
a structured diagnosis — NOT to write a patch into the source tree.

For each response:

1. Include a THOUGHT section explaining your reasoning and analysis.
2. Provide ONE OR MORE `bash` tool calls to execute commands.

## Recommended Workflow

1. List the files in the working directory and read the relevant source.
2. Run the binary to observe the failure (stack trace, sanitizer
   report, exit code, etc.).
3. If the program crashes, run gdb in batch mode for a backtrace
   (`gdb -batch -ex 'run' -ex 'bt' --args ./build/prog`).
4. Read source around the failing frame; understand the data flow.
5. Form a diagnosis grounded in the evidence you collected.

3-8 investigation steps is typical. Don't over-explore — the judge
scores diagnosis quality, not step count.

## Command Execution Rules

You operate in an environment where:
1. You issue at least one `bash` tool call per response.
2. The system executes the command(s) in a subshell.
3. You see the result(s).
4. You write your next response.

**CRITICAL REQUIREMENTS:**

- Your response SHOULD include reasoning text explaining your analysis.
- Your response MUST include AT LEAST ONE `bash` tool call. You can
  emit multiple tool calls in one response when commands are
  independent (e.g. `ls -la` and `cat program.c` in parallel).
- Each command runs in a new subshell — `cd` and `export` don't
  persist. Prefix with `cd /path && ...` to chain.
- Use non-interactive flags. Avoid editors / pagers (`vi`, `less`).

## Submission

When you've finished investigating, submit your diagnosis. Your final
response MUST include all three labelled paragraphs in the THOUGHT
text BEFORE the submit `bash` call:

  ROOT CAUSE: <file:line and what is wrong, in your own words. Don't
              just paraphrase the sanitizer report — explain why the
              defect produces this failure.>

  LOCAL FIX:  <minimal code change that resolves the immediate
              symptom. Show the diff or replacement code.>

  GLOBAL FIX: <structural design change that prevents this CLASS of
              bug — e.g. type changes, API redesign, compile-time
              check, RAII wrapper, bounded view type, invariant.
              NOT just a bigger version of the local fix.>

Then submit using this exact `bash` tool call:

    bash tool: {"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}

The judge reads your THOUGHT prose. If you submit without writing the
three labelled sections, your run scores 0.

<system_information>
{{system}} {{release}} {{machine}}
</system_information>
</instructions>
"""


# Format-error template — used when the model's response can't be
# parsed (no tool calls found, malformed action, unknown tool name).
# Mirrors `swebench.yaml`'s template: explicit reminder that the bash
# tool is the ONLY path forward, with a worked example. Without this
# (the LitellmModel default is the bare `{{ error }}` template which
# echoes the parser error text), the model gets a cryptic re-prompt
# and often loops.
TOOLCALL_FORMAT_ERROR = """\
Tool call error:

<error>
{{error}}
</error>

Every response must include at least one `bash` tool call. Call the
`bash` tool with your shell command as the `command` argument:

  Tool: bash
  Arguments: {"command": "your_command_here"}

If you have completed your investigation and are ready to submit your
diagnosis, your final response MUST include the structured ROOT CAUSE
/ LOCAL FIX / GLOBAL FIX paragraphs followed by:

  Tool: bash
  Arguments: {"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}
"""


# ----- Text-based-mode templates -----
# When the resolved model class is textbased (litellm_textbased,
# openrouter_textbased), the parser regex-extracts ```mswea_bash_command```
# blocks from message content. Tool-calling-style prompts produce zero
# matches, so we substitute prompt + format-error templates that match
# the parser. Patterned after mini's own `mini_textbased.yaml`.
TEXTBASED_SYSTEM_TEMPLATE = """\
You are an expert software engineer debugging C/C++ programs. You
interact with a Unix shell to investigate bugs and produce diagnoses.

Your response must contain exactly ONE bash code block with ONE
command (or commands connected with && or ||). Include a THOUGHT
section before your command where you explain your reasoning process.
Format your response as shown in <format_example>.

<format_example>
Your reasoning and analysis here. Explain why you want to perform the action.

```mswea_bash_command
your_command_here
```
</format_example>

Failure to follow these rules will cause your response to be rejected.
"""


TEXTBASED_INSTANCE_TEMPLATE = """\
{{task}}

## Workflow

1. Read the source files and understand the program.
2. Run the binary to observe the failure.
3. If a crash, run gdb in batch mode for a backtrace:
   `gdb -batch -ex 'run' -ex 'bt' --args ./build/prog`
4. Read source around the failing line.
5. Form a diagnosis grounded in the evidence you collected.

## Final response (REQUIRED FORMAT)

When you've finished investigating, your final response must contain
the structured diagnosis BEFORE the submit bash block, in the SAME
response, like this:

  ROOT CAUSE: <file:line and what is wrong, in your own words>

  LOCAL FIX:  <minimal code change>

  GLOBAL FIX: <structural change preventing this CLASS of bug>

  ```mswea_bash_command
  echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
  ```

The diagnosis prose must be in the THOUGHT (text outside the bash
block). The submit command must be the bash block in the SAME
response. If you submit without writing all three labelled paragraphs
your run scores 0.

## Rules

1. Every response must contain exactly one bash code block.
2. Each command runs in a new subshell — `cd` and `export` don't
   persist. Prefix with `cd /path && ...` to chain.
3. Use non-interactive flags. Avoid editors / pagers (`vi`, `less`).

<system_information>
{{system}} {{release}} {{machine}}
</system_information>
"""


TEXTBASED_FORMAT_ERROR = """\
Format error:

<error>
{{error}}
</error>

Please always provide EXACTLY ONE action in triple backticks. Format
your response like this:

  THOUGHT: your reasoning and analysis

  ```mswea_bash_command
  your_command_here
  ```

If you want to submit your diagnosis, write the structured ROOT CAUSE
/ LOCAL FIX / GLOBAL FIX paragraphs as your THOUGHT, then end with:

  ```mswea_bash_command
  echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
  ```
"""


def _is_textbased(model_class_name: str) -> bool:
    """Mini's textbased model classes use regex extraction of fenced
    bash blocks instead of tool-calling. Detect by class-name suffix
    so we cover both litellm_textbased and openrouter_textbased."""
    return "Textbased" in model_class_name


def _action_text(a) -> str:
    """Pull the bash command out of a mini action record. Mini v2.2.x
    uses dicts with a `command` key (tool-calling mode) or `text` key
    (text-based mode). Always return a string, even if the field is
    None or the action is malformed."""
    if isinstance(a, dict):
        for key in ("command", "text", "action"):
            v = a.get(key)
            if isinstance(v, str):
                return v
        return str(a)
    if isinstance(a, str):
        return a
    return ""


def _extract_response(messages: list[dict]) -> str:
    """Build the response text the judge will score. We concatenate ALL
    non-empty assistant THOUGHT content in order, joined with a
    separator. This way the judge sees the model's complete diagnostic
    prose regardless of which turn carries the diagnosis — the early
    turn's THOUGHT (often the model's overall plan) is included
    alongside the final-turn THOUGHT (structured ROOT CAUSE / LOCAL FIX
    / GLOBAL FIX block).

    Why concatenate rather than pick one turn:
    - Tool-calling models often have NO content on submit-only turns
      (the message body is empty when emitting just a tool call).
    - The diagnostic prose may live on the second-to-last assistant
      turn (where the THOUGHT was) while the last turn is just the
      submit tool call.
    - The judge's prompt asks "did the response satisfy the criteria?"
      — concatenated prose preserves all model claims so the judge
      sees the full diagnostic picture.
    """
    parts: list[str] = []
    for m in messages:
        if m.get("role") == "assistant":
            c = (m.get("content") or "").strip()
            if c:
                parts.append(c)
    # Append the exit submission if non-empty (cheap, generalizes to
    # SWE-bench-style tasks where submission carries the final patch).
    for m in reversed(messages):
        if m.get("role") == "exit":
            sub = ((m.get("extra") or {}).get("submission") or "").strip()
            if sub:
                parts.append(f"[submission]\n{sub}")
            break
    return "\n\n---\n\n".join(parts)


def _extract_actions(messages: list[dict]) -> list[dict]:
    """Pull every bash command the agent ran, in order, paired with the
    size of the resulting tool-message observation. Mirrors the shape
    Tier3Driver writes into collect.json so analyze_runs.py /
    heatmap_real.py / judge.py all consume tier-1 runs without
    per-tier branching.

    Mini message structure (v2.2.x):
      role='assistant' with extra.actions = [{command: str, ...}, ...]
      role='tool'      with content = the observation
      role='user'      with content = format-error / interrupt
    """
    out: list[dict] = []
    actions_pending: list = []
    for m in messages:
        role = m.get("role")
        if role == "assistant":
            extras = m.get("extra") or {}
            for a in (extras.get("actions") or []):
                actions_pending.append(a)
        elif role == "tool" and actions_pending:
            obs_len = len(m.get("content") or "")
            # In tool-calling mode each tool message corresponds to ONE
            # action — pop FIFO so multi-action assistant turns pair
            # left-to-right with their observation messages.
            a = actions_pending.pop(0)
            cmd = _action_text(a)
            first = (cmd.strip().split() or [""])[0].split("/")[-1] or "bash"
            out.append({
                "tool_name": "bash",
                "verb": first,
                "call": cmd,
                "result_length": obs_len,
            })
    # Trailing actions never observed (agent exited mid-step) — record
    # with length 0 so tool_frequency stays accurate.
    for a in actions_pending:
        cmd = _action_text(a)
        first = (cmd.strip().split() or [""])[0].split("/")[-1] or "bash"
        out.append({"tool_name": "bash", "verb": first,
                    "call": cmd, "result_length": 0})
    return out


def _tally_tokens(messages: list[dict]) -> tuple[int, int]:
    """Sum prompt + completion tokens across all assistant turns.

    Mini v2 stashes the full LiteLLM ChatCompletion response in
    message['extra']['response']; tokens live in response['usage'].
    Older versions used message['extra']['usage'] directly. Try both
    shapes; missing fields silently contribute 0."""
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


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", required=True, type=Path)
    p.add_argument("--model", required=True,
                   help="LiteLLM-style model name, e.g. "
                        "'openrouter/openai/gpt-5.5'. Passed to mini's "
                        "get_model() for class auto-selection.")
    p.add_argument("--task-file", required=True, type=Path)
    p.add_argument("--cwd", default=None,
                   help="Working directory for the agent's bash sandbox. "
                        "Default = run-dir (synthetic cases). For injected "
                        "cases, pass the workspace cache path.")
    p.add_argument("--step-limit", type=int, default=15)
    p.add_argument("--cost-limit", type=float, default=0.5)
    p.add_argument("--mini-model-class", default=None,
                   help="Mini model-class shortcut to override auto-selection. "
                        "One of: litellm, litellm_textbased, litellm_response, "
                        "openrouter, openrouter_textbased, openrouter_response, "
                        "portkey, portkey_response, requesty. "
                        "Empty string means auto.")
    args = p.parse_args()

    run_dir = args.run_dir.resolve()
    task = args.task_file.read_text()
    agent_cwd = args.cwd or str(run_dir)

    # Imports must happen here (mini's own globals print on first import)
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.environments.local import LocalEnvironment
    from minisweagent.models import get_model

    # ----- model selection -----
    # Build the config dict mini's get_model() expects. The model_class
    # field is popped out by get_model() itself; the rest is passed to
    # the resolved class's constructor.
    #
    # cost_tracking="ignore_errors" — litellm's price DB doesn't include
    # every OpenRouter route (gpt-5.5, gemini-3.1-flash-lite-preview,
    # nemotron-3-nano-* as of mini 2.2.8). Without this, mini raises
    # RuntimeError before the first turn. Tokens are still counted via
    # message['extra']['response']['usage'] so we don't lose accuracy
    # on token usage; we just don't get a $ figure for unmapped models.
    model_config: dict = {
        "cost_tracking": "ignore_errors",
        # model_kwargs passed straight to litellm.completion. Same set
        # as swebench.yaml — drop_params for backend compatibility,
        # parallel_tool_calls so capable models can batch.
        "model_kwargs": {
            "drop_params": True,
            "temperature": 0.0,
            "parallel_tool_calls": True,
        },
    }
    if args.mini_model_class:
        model_config["model_class"] = args.mini_model_class

    # Resolve the model class first (without constructing yet) so we can
    # pick the matching prompt set. The textbased classes use a regex
    # parser; the default tool-calling classes use the API tool_calls
    # field. Prompts must match the parser or the model loops on
    # FormatError ad infinitum.
    from minisweagent.models import get_model_class
    klass = get_model_class(args.model, args.mini_model_class or "")
    is_textbased = _is_textbased(klass.__name__)
    if is_textbased:
        system_template = TEXTBASED_SYSTEM_TEMPLATE
        instance_template = TEXTBASED_INSTANCE_TEMPLATE
        model_config["format_error_template"] = TEXTBASED_FORMAT_ERROR
    else:
        system_template = DEBUG_SYSTEM_TEMPLATE
        instance_template = DEBUG_INSTANCE_TEMPLATE
        model_config["format_error_template"] = TOOLCALL_FORMAT_ERROR

    # get_model adds Anthropic prompt-caching when the model name
    # contains 'claude'/'sonnet'/'opus'. We delegate auto-selection
    # logic to mini rather than reimplementing it.
    model = get_model(args.model, model_config)

    env = LocalEnvironment(
        cwd=agent_cwd,
        env={
            # Tame interactive helpers — same set as swebench.yaml.
            "PAGER": "cat",
            "MANPAGER": "cat",
            "LESS": "-R",
            "PIP_PROGRESS_BAR": "off",
            "TQDM_DISABLE": "1",
        },
        timeout=30,
    )

    agent = DefaultAgent(
        model, env,
        system_template=system_template,
        instance_template=instance_template,
        step_limit=args.step_limit,
        cost_limit=args.cost_limit,
        # Save mini's native trajectory format alongside collect.json
        # so trajectory inspection tools (mini's `inspector` UI) work.
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
        sys.stderr.write(f"[tier1-runner] agent.run raised {exit_status}: {e}\n")
    elapsed = time.time() - t0

    messages = agent.messages
    response = _extract_response(messages)
    tool_calls = _extract_actions(messages)
    p_tok, c_tok = _tally_tokens(messages)

    freq: dict[str, int] = {}
    for tc in tool_calls:
        freq[tc.get("verb", "bash")] = freq.get(tc.get("verb", "bash"), 0) + 1

    # Capture which model class mini actually instantiated. This is the
    # robustness story we're telling — model_class is the routing
    # decision that determines tool-calling vs text-mode.
    model_class_used = type(model).__module__ + "." + type(model).__name__

    collect = {
        "meta": {
            "uid": run_dir.name,
            "time": datetime.now().isoformat(timespec="seconds"),
            "model": args.model,
            "tool_config": "tier1_bash_only.json",
            "enabled_tools": ["bash"],
            "agent": "mini-swe-agent",
            "agent_version": _mini_version(),
            "mini_model_class": model_class_used,
            "mini_model_kwargs": model_config["model_kwargs"],
            "prompt_mode": "textbased" if is_textbased else "toolcalling",
        },
        "instructions": system_template,
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
                "tool_frequency": freq,
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
        f"[tier1-runner] exit_status={exit_status} elapsed={elapsed:.1f}s "
        f"steps={len(tool_calls)} cost=${float(getattr(agent, 'cost', 0.0) or 0.0):.4f} "
        f"model_class={type(model).__name__}"
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
