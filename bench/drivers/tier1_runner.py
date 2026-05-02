"""Tier-1 runner — invoked as a subprocess by Tier1Driver.

Runs in the `.venv-bench` Python where `mini-swe-agent` (>=v2.2.8) is
installed. Reads the task description from a file, instantiates a
`DefaultAgent` with `LocalEnvironment` and `LitellmModel`, runs the
agent until it submits or hits a step/cost limit, and writes two files
into the run directory:

    trajectory.json    mini-swe-agent's native serialize() format
                       (full message list + cost + exit_status)
    collect.json       our standardized schema, identical to what
                       Tier3Driver's ChatDBG run produces — so the
                       existing judge.py can score it without any
                       per-tier branching.

Standalone: this module does NOT import from bench.* — it runs in
mini's venv where bench.common may not import (different Python
version, different deps). All marshalling lives here.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime


# Strict bash-only system template. Mini's default template encourages
# the agent to also write/edit files; for a debugging benchmark we want
# investigation, not patching, so the workflow guidance is rewritten.
DEBUG_SYSTEM_TEMPLATE = """\
You are an expert software engineer debugging a C/C++ program. You
have a single tool: bash.

Your response must contain exactly ONE bash code block with ONE command
(or commands connected with && or ||). Include a THOUGHT section before
your command where you explain your reasoning process. Format your
response as shown in <format_example>.

<format_example>
Your reasoning and analysis here. Explain why you want to perform the action.

```mswea_bash_command
your_command_here
```
</format_example>

Useful tools available via bash:
  ls, cat, head, tail, grep, find, file, nm, objdump, strings, wc
  ./build/prog [args...]                 — run the buggy binary
  gdb -batch -ex 'run' -ex 'bt' --args ./build/prog [args]   — get a backtrace
  lldb -batch -o 'run' -o 'bt' ./build/prog                  — alternative
  nl -ba <file> | sed -n 'N,Mp'           — read source lines

DO NOT use interactive programs (vim, less, top, etc). Each command runs
in a fresh subshell so `cd` and exported environment variables do not
persist between commands. Use `cd /path && cmd` or `VAR=val cmd` if you
need to chain.

Failure to follow these rules will cause your response to be rejected.
"""


# Instance template injects the per-case task. Final-answer extraction
# expects the model to put its diagnosis in a THOUGHT block before
# issuing the COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT command.
DEBUG_INSTANCE_TEMPLATE = """\
{{task}}

Use bash to investigate. Run the binary, run gdb in batch mode if it
crashes, read source files. After 3-8 steps you should have enough
evidence.

To finish, submit with this exact bash command (and write your
diagnosis BEFORE it, in the same response):

```mswea_bash_command
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```

Your final response must include three labelled paragraphs in the
THOUGHT before the submit bash command:

ROOT CAUSE: <file:line and what is wrong, in your own words>
LOCAL FIX: <minimal patch>
GLOBAL FIX: <structural change preventing this class of bug>

Reminder: every response must contain exactly one bash code block. If
you write only prose without a bash block, your response is rejected.
Each command runs in a fresh subshell.

<system_information>
{{system}} {{release}} {{machine}}
</system_information>
"""


def _action_text(a) -> str:
    """Pull the bash command out of a mini action record. Mini v2.2.x
    uses dicts with a `command` key; older versions used `text`. Always
    return a string, even if the field is None or the action is malformed."""
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
    prose regardless of which turn carries the diagnosis — early-turn
    THOUGHT (often the model's overall plan) is included alongside the
    final-turn THOUGHT (the structured ROOT CAUSE / LOCAL FIX /
    GLOBAL FIX block).

    Why concatenate rather than pick one turn:
    - Models that use OpenAI tool-calling sometimes emit empty content
      on their FINAL action (the submit), putting the diagnosis on a
      prior turn instead.
    - Models following mini's fenced-bash format put the diagnosis
      THOUGHT directly before each action.
    - The judge's prompt asks "did the response satisfy the criteria?"
      — concatenated prose preserves all the model's claims so the
      judge has the full picture.

    Mini's `submission` field is included when non-empty (preferred for
    SWE-bench-style tasks where the submission carries the patch); for
    debugging tasks it's typically empty.
    """
    parts: list[str] = []
    for m in messages:
        if m.get("role") == "assistant":
            c = (m.get("content") or "").strip()
            if c:
                parts.append(c)
    # Append the exit submission if non-empty (it's redundant for our
    # use-case, but cheap and lets the format generalize).
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
      role='assistant' with extra.actions = [{command: str, tool_call_id: str}, ...]
      role='tool' with content = the observation
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
            # In v2 each tool message corresponds to ONE action; flush
            # actions_pending in order and pair each with this tool's
            # observation length. Multi-action assistant messages are
            # rare but possible; pairing left-to-right is the
            # least-wrong approximation.
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
    p.add_argument("--model", required=True)
    p.add_argument("--task-file", required=True, type=Path)
    p.add_argument("--cwd", default=None,
                   help="Working directory for the agent's bash sandbox. "
                        "Default = run-dir (synthetic cases). For injected "
                        "cases, pass the workspace cache path so the agent "
                        "lands in the cloned source tree.")
    p.add_argument("--step-limit", type=int, default=30)
    p.add_argument("--cost-limit", type=float, default=0.5)
    args = p.parse_args()

    run_dir = args.run_dir.resolve()
    task = args.task_file.read_text()
    agent_cwd = args.cwd or str(run_dir)

    # Mini imports — must happen in the .venv-bench Python. The two
    # PydanticUndefined defaults (system_template, instance_template)
    # are filled in via kwargs.
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.environments.local import LocalEnvironment
    from minisweagent.models.litellm_model import LitellmModel

    # cost_tracking="ignore_errors" because litellm's price database
    # doesn't include every model on OpenRouter (e.g. openai/gpt-5.5,
    # google/gemini-3.1-flash-lite-preview as of mini 2.2.8). Without
    # this, mini's default `cost_tracking="default"` raises a
    # RuntimeError before the first model call and the run dies with
    # 0 tool calls. We track tokens directly via message['extra']['usage']
    # below, so losing mini's cost field is acceptable.
    model = LitellmModel(model_name=args.model, cost_tracking="ignore_errors")
    env = LocalEnvironment(
        cwd=agent_cwd,
        env={
            # Tame interactive helpers that pollute output streams
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
        system_template=DEBUG_SYSTEM_TEMPLATE,
        instance_template=DEBUG_INSTANCE_TEMPLATE,
        step_limit=args.step_limit,
        cost_limit=args.cost_limit,
        # Save mini's native trajectory format alongside our collect.json
        output_path=run_dir / "trajectory.json",
    )

    t0 = time.time()
    exit_status = "unknown"
    submission = ""
    try:
        result = agent.run(
            task=task,
            cost_limit_dollar=f"${args.cost_limit:.2f}",
        )
        exit_status = result.get("exit_status", "unknown") if result else "unknown"
        submission = result.get("submission", "") if result else ""
    except Exception as e:
        exit_status = type(e).__name__
        sys.stderr.write(f"[tier1-runner] agent.run raised {exit_status}: {e}\n")
        # save() is invoked in agent.run's finally clause, so trajectory
        # should already be on disk; bubble exception non-fatally.
    elapsed = time.time() - t0

    messages = agent.messages
    response = _extract_response(messages)
    tool_calls = _extract_actions(messages)
    p_tok, c_tok = _tally_tokens(messages)

    # tool_frequency over `verb` (the first token of the command) so it's
    # actually informative — same shape Tier3 uses for ChatDBG tool names.
    freq: dict[str, int] = {}
    for tc in tool_calls:
        freq[tc.get("verb", "bash")] = freq.get(tc.get("verb", "bash"), 0) + 1

    collect = {
        "meta": {
            "uid": run_dir.name,
            "time": datetime.now().isoformat(timespec="seconds"),
            "model": args.model,
            "tool_config": "tier1_bash_only.json",   # informational only
            "enabled_tools": ["bash"],
            "agent": "mini-swe-agent",
            "agent_version": _mini_version(),
        },
        "instructions": DEBUG_SYSTEM_TEMPLATE,
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
        f"steps={len(tool_calls)} cost=${float(getattr(agent, 'cost', 0.0) or 0.0):.4f}"
    )
    # Non-zero exit ONLY for genuine harness failures, not "model didn't
    # submit" — Tier3 uses status=ok even when the model gave up, so
    # match that.
    return 0


def _mini_version() -> str:
    try:
        from importlib.metadata import version
        return version("mini-swe-agent")
    except Exception:
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
