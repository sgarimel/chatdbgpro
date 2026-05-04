import json
import os
from chatdbg.util.config import chatdbg_config
from .text import truncate_proportionally
from typing import Any, Callable, List


def _wrap_it(before: str, text: str, after: str = "", maxlen: int = 2048) -> str:
    if text:
        text = truncate_proportionally(text, maxlen, 0.5)
        before = before + ":\n" if before else ""
        after = after + "\n" if after else ""
        return f"{before}```\n{text}\n```\n{after}"
    else:
        return ""


def _concat_prompt(*args) -> str:
    args = [a for a in args if len(a) > 0]
    return "\n".join(args)


def _user_text_it(user_text: str) -> str:
    return user_text if len(user_text) > 0 else (
        "Identify the root cause of this failure and propose both a "
        "local fix and a structural global fix."
    )


def _case_metadata_block() -> str:
    """Build a case-metadata section from CHATDBG_PROMPT_* env vars.

    These are set by the tier3 driver so the model receives the same
    informational context that T1/T2/T4 prompts provide: source file
    name, expected behavior, and case description."""
    parts = []
    sf = os.environ.get("CHATDBG_PROMPT_SOURCE_FILE", "")
    if sf:
        parts.append(f"Source file: `{sf}`")
    behavior = os.environ.get("CHATDBG_PROMPT_BEHAVIOR", "")
    if behavior:
        parts.append(f"Expected behavior: {behavior}")
    desc = os.environ.get("CHATDBG_PROMPT_DESCRIPTION", "")
    if desc:
        parts.append(f"Description: {desc}")
    if parts:
        return "\n".join(parts) + "\n"
    return ""


def build_initial_prompt(
    stack: str,
    error: str,
    details: str,
    command_line: str,
    inputs: str,
    history: str,
    extra: str = "",
    user_text: str = "",
) -> str:
    return _concat_prompt(
        _case_metadata_block(),
        _wrap_it("The program has this stack trace", stack),
        _wrap_it("The program encountered the following error", error, details),
        _wrap_it("This was the command line", command_line),
        _wrap_it("This was the program's input", inputs),
        _wrap_it("This is the history of some debugger commands I ran", history),
        _wrap_it("", extra),
        _user_text_it(user_text),
    )


def build_followup_prompt(history: str, extra: str, user_text: str) -> str:
    return _concat_prompt(
        _wrap_it("This is the history of some debugger commands I ran", history),
        _wrap_it("", extra),
        _user_text_it(user_text),
    )


_CMW_INSTRUCTIONS = """

CRITICAL REQUIREMENT — CHECK YOUR WORK:
You have a `check_my_work` tool. You are REQUIRED to call it at least
once before writing your final answer. Do NOT skip this step.

Workflow:
1. Investigate the bug using the debugger and other tools.
2. When you have a hypothesis, call `check_my_work` with your full
   diagnosis: root cause explanation, local fix (specific code change),
   and global/structural fix (specific code change).
3. The judge scores each axis and gives hints for what you're missing.
4. If any axis scored 0, use the debugger to gather more evidence,
   refine your diagnosis, and call `check_my_work` again.
5. Only write your final answer AFTER the judge confirms 3/3 or you've
   exhausted your checks.

If you write a final answer without calling `check_my_work` first,
your response will be scored as incomplete."""


def initial_instructions(functions: List[Callable[[Any], Any]]) -> str:
    if chatdbg_config.instructions == "":
        file_path = os.path.join(
            os.path.dirname(__file__), f"instructions/{chatdbg_config.model}.txt"
        )
        if not os.path.exists(file_path):
            file_path = os.path.join(
                os.path.dirname(__file__), f"instructions/default.txt"
            )
    else:
        file_path = chatdbg_config.instructions

    function_instructions = [json.loads(f.__doc__)["description"] for f in functions]
    with open(file_path, "r") as file:
        template = file.read()
        result = template.format_map({"functions": "\n\n".join(function_instructions)})

    # Append check-my-work instructions when the tool is enabled
    if chatdbg_config.enable_check_my_work and chatdbg_config.cmw_case_yaml:
        result += _CMW_INSTRUCTIONS

    return result
