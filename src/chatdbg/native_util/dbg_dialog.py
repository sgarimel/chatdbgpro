from __future__ import annotations

import subprocess
import sys

from . import clangd_lsp_integration
from ..util.prompts import (
    build_followup_prompt,
    build_initial_prompt,
    initial_instructions,
)

from ..assistant.assistant import Assistant
from ..util.config import chatdbg_config
from ..util.history import CommandHistory
from ..util.log import ChatDBGLog
from .stacks import build_enriched_stacktrace
from ..util.check_my_work import (
    CheckMyWorkState,
    call_judge,
    load_criteria_from_case_yaml,
)


class DBGError(Exception):

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class DBGDialog:
    # The log file used by the listener on the Assistant
    _log = ChatDBGLog(
        log_filename=chatdbg_config.log,
        config=chatdbg_config.to_json(),
        capture_streams=False,  # don't have access to target's stdout/stderr here.
    )

    def __init__(self, prompt) -> None:
        self._prompt = prompt
        self._history = CommandHistory(self._prompt)
        self._unsafe_cmd = False
        # Check-my-work state: initialized lazily when the tool is enabled.
        self._cmw_state: CheckMyWorkState | None = None
        self._cmw_criteria: dict | None = None

    def query_and_print(self, assistant, user_text, is_followup):
        prompt = self.build_prompt(user_text, is_followup)

        self._history.clear()
        print(assistant.query(prompt, user_text)["message"])
        if self._unsafe_cmd:
            self.warn(
                f"Warning: One or more debugger commands were blocked as potentially unsafe.\nWarning: You can disable sanitizing with `config --unsafe` and try again at your own risk."
            )
            self._unsafe_cmd = False

    def dialog(self, user_text):
        assistant = self._make_assistant()
        self.check_debugger_state()

        self.query_and_print(assistant, user_text, False)

        # Check-my-work forced loop: if CMW is enabled, the harness
        # drives a judge→feedback→retry cycle regardless of whether the
        # model voluntarily called check_my_work during its tool loop.
        if self._cmw_enabled():
            self._cmw_forced_loop(assistant)

        while True:
            try:
                command = input("(ChatDBG chatting) ").strip()
                if command in ["exit", "quit"]:
                    break
                if command in ["chat", "why"]:
                    self.query_and_print(assistant, command, True)
                elif command == "history":
                    print(self._history)
                else:
                    # Send the next input as an LLDB command
                    result = self._run_one_command(command)
                    if self._message_is_a_bad_command_error(result):
                        # If result is not a recognized command, pass it as a query
                        self.query_and_print(assistant, command, True)
                    else:
                        if command != "test_prompt":
                            self._history.append(command, result)
                        print(result)
            except EOFError:
                # If it causes an error, break
                break

        # Flush check_my_work summary to any AblationDataCollector listeners
        self._flush_cmw_to_collectors(assistant)
        assistant.close()

    def _cmw_enabled(self) -> bool:
        return bool(
            chatdbg_config.enable_check_my_work
            and chatdbg_config.cmw_case_yaml
        )

    def _cmw_forced_loop(self, assistant: Assistant) -> None:
        """After the model's initial answer, force a judge check and
        send feedback as follow-up prompts until perfect or stale.

        This works even when the model ignores the check_my_work tool
        instruction — the harness drives the loop externally."""
        # Initialize CMW state if the model didn't call the tool itself
        if self._cmw_criteria is None:
            self._cmw_criteria = load_criteria_from_case_yaml(
                chatdbg_config.cmw_case_yaml
            )
            self._cmw_state = CheckMyWorkState(
                max_stale_checks=chatdbg_config.cmw_max_stale,
            )

        state = self._cmw_state

        # If model already called check_my_work and got perfect, done
        if state.is_perfect:
            return

        while not state.is_perfect and not state.is_stale:
            # Extract the model's latest response from the conversation
            last_response = self._extract_last_assistant_response(assistant)
            if not last_response:
                break

            # Call the judge
            crit = self._cmw_criteria
            result = call_judge(
                last_response,
                source=crit["source"],
                source_file=crit["source_file"],
                language=crit["language"],
                criteria=crit["criteria"],
                judge_model=chatdbg_config.cmw_judge_model,
                check_number=state.num_checks + 1,
            )
            state.record(result)

            s = result.scores
            f = result.feedback
            total = result.total_score()
            print(f"\n*** [Check #{result.check_number}] Score: {total}/3 "
                  f"(rc={s['root_cause']} lf={s['local_fix']} gf={s['global_fix']})")

            if total == 3:
                print("*** Perfect score — accepting answer.")
                break

            if state.is_stale:
                print(f"*** No improvement for {state.max_stale_checks} "
                      f"consecutive checks — stopping.")
                break

            # Build feedback prompt and send as follow-up
            lines = [
                "A judge reviewed your diagnosis and found issues:",
                "",
            ]
            for axis in ("root_cause", "local_fix", "global_fix"):
                status = "PASS" if s[axis] == 1 else "NEEDS WORK"
                hint = f.get(axis, "")
                lines.append(f"  {axis}: [{status}] {hint}")
            lines.append("")
            lines.append(
                "Use the debugger to investigate further and provide a "
                "corrected diagnosis. Be specific about file, line, and "
                "exact code changes."
            )
            feedback_text = "\n".join(lines)
            print(f"*** Sending feedback to model...\n")
            self.query_and_print(assistant, feedback_text, True)

    def _extract_last_assistant_response(self, assistant: Assistant) -> str | None:
        """Get the last assistant message content from the conversation."""
        for msg in reversed(assistant._conversation):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                content = msg.get("content")
                if content and len(content.strip()) > 20:
                    return content
            # litellm sometimes returns message objects
            elif hasattr(msg, "role") and msg.role == "assistant":
                content = getattr(msg, "content", None)
                if content and len(content.strip()) > 20:
                    return content
        return None

    # Return string for valid command.  None if the command is not valid.
    def _run_one_command(self, command):
        pass

    def _message_is_a_bad_command_error(self, message):
        pass

    def check_debugger_state(self):
        pass

    def _get_frame_summaries(self, max_entries: int = 20):
        pass

    def initial_prompt_instructions(self):
        functions = self._supported_functions()
        return initial_instructions(functions)

    def _initial_prompt_enchriched_stack_trace(self):
        return build_enriched_stacktrace(self._get_frame_summaries())

    def _initial_prompt_error_message(self):
        return None

    def _initial_prompt_error_details(self):
        """Anything more beyond the initial error message to include."""
        return None

    def _initial_prompt_command_line(self):
        return None

    def _initial_prompt_input(self):
        return None

    def _prompt_stack(self):
        """
        Return a simple backtrace to show the LLM where we are on the stack
        in followup prompts.
        """
        return None

    def _prompt_history(self):
        return str(self._history)

    def build_prompt(self, arg, conversing):
        if not conversing:
            return build_initial_prompt(
                self._initial_prompt_enchriched_stack_trace(),
                self._initial_prompt_error_message(),
                self._initial_prompt_error_details(),
                self._initial_prompt_command_line(),
                self._initial_prompt_input(),
                self._prompt_history(),
                user_text=arg,
            )
        else:
            return build_followup_prompt(
                self._prompt_history(), self._prompt_stack(), arg
            )

    def llm_debug(self, command: str) -> str:
        pass

    def llm_get_code_surrounding(self, filename: str, line_number: int) -> str:
        """
        {
            "name": "get_code_surrounding",
            "description": "The `get_code_surrounding` function returns the source code in the given file surrounding and including the provided line number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The filename to read from."
                    },
                    "line_number": {
                        "type": "integer",
                        "description": "The line number to focus on. Some context before and after that line will be provided."
                    }
                },
                "required": [ "filename", "line_number" ]
            }
        }
        """
        return f"code {filename}:{line_number}", self._run_one_command(
            f"code {filename}:{line_number}"
        )

    def llm_find_definition(self, filename: str, line_number: int, symbol: str) -> str:
        """
        {
            "name": "find_definition",
            "description": "The `find_definition` function returns the source code for the definition for the given symbol at the given source line number.  Call `find_definition` on every symbol that could be linked to the issue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The filename the symbol is from."
                    },
                    "line_number": {
                        "type": "integer",
                        "description": "The line number where the symbol is present."
                    },
                    "symbol": {
                        "type": "string",
                        "description": "The symbol to lookup."
                    }
                },
                "required": [ "filename", "line_number", "symbol" ]
            }
        }
        """
        return f"definition {filename}:{line_number} {symbol}", self._run_one_command(
            f"definition {filename}:{line_number} {symbol}"
        )

    def llm_ask_oracle(self, question: str) -> str:
        """
        {
            "name": "ask_oracle",
            "description": "Escalate a hard reasoning question to a frontier 'oracle' model. Use this ONLY when you are stuck and cannot resolve a specific question using the debugger. The oracle has NO access to the program, the debugger, or the stack — you must include any code snippets, values, or state it needs in the `question` field verbatim. Keep the question tight: the oracle is expensive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "A self-contained question including all code / state the oracle needs to answer it."
                    }
                },
                "required": ["question"]
            }
        }
        """
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import litellm

        try:
            resp = litellm.completion(
                model=chatdbg_config.oracle_model,
                messages=[
                    {"role": "system",
                     "content": "You are a senior C/C++ debugging oracle. Answer precisely and briefly. Point to the single most likely root cause if asked."},
                    {"role": "user", "content": question},
                ],
                temperature=0.0,
                timeout=60,
            )
            content = (resp.choices[0].message.content or "").strip()
            usage = getattr(resp, "usage", None) or {}
            ptok = getattr(usage, "prompt_tokens", None) or (
                usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0)
            ctok = getattr(usage, "completion_tokens", None) or (
                usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0)
            header = f"[oracle:{chatdbg_config.oracle_model} in={ptok} out={ctok}]\n"
            return f"ask_oracle", header + content
        except Exception as e:
            return f"ask_oracle", f"[oracle call failed: {e}]"

    def llm_bash(self, command: str) -> str:
        """
        {
            "name": "bash",
            "description": "Execute a POSIX shell command in the debugger's working directory and return combined stdout/stderr plus the exit code. Use this for file inspection (ls, cat, grep, find, head, tail, wc), running or re-running the program with different inputs, comparing files (diff), or any workflow that is cheaper to do in a shell than in the debugger. Pipelines, redirections, and `&&` are supported. A 30-second timeout applies per call and output longer than 8 KB is truncated. Do not use interactive programs (editors, pagers).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "A single shell command line."
                    }
                },
                "required": ["command"]
            }
        }
        """
        _OUTPUT_LIMIT = 8192
        _TIMEOUT_S = 30

        try:
            proc = subprocess.run(
                command,
                shell=True,
                text=True,
                capture_output=True,
                timeout=_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return f"bash: {command}", f"[bash timed out after {_TIMEOUT_S}s]"
        except Exception as e:
            return f"bash: {command}", f"[bash call failed: {e}]"

        out = proc.stdout or ""
        err = proc.stderr or ""
        parts = []
        if out:
            parts.append(out.rstrip("\n"))
        if err:
            parts.append(f"[stderr]\n{err.rstrip(chr(10))}")
        body = "\n".join(parts) if parts else "[no output]"
        if len(body) > _OUTPUT_LIMIT:
            body = (
                body[:_OUTPUT_LIMIT]
                + f"\n... [truncated, {len(body) - _OUTPUT_LIMIT} bytes elided]"
            )
        return f"bash: {command}", f"{body}\n[exit={proc.returncode}]"

    def llm_check_my_work(self, diagnosis: str) -> str:
        """
        {
            "name": "check_my_work",
            "description": "Submit your current diagnosis and proposed fix to a judge for feedback. The judge scores three axes (root_cause, local_fix, global_fix) and gives targeted hints for any axis you haven't satisfied yet. Call this when you believe you have identified the bug and have a fix proposal. You MUST include: (1) your root cause explanation, (2) the specific code change for a local fix, and (3) the specific code change for a global/structural fix. The session continues after the judge responds so you can refine your answer using the debugger. If you make no progress after repeated checks, the judge will tell you to stop.",
            "parameters": {
                "type": "object",
                "properties": {
                    "diagnosis": {
                        "type": "string",
                        "description": "Your complete current diagnosis including: root cause explanation, proposed local fix (specific code change), and proposed global fix (structural change). Be as specific as possible — cite lines, variables, and exact code changes."
                    }
                },
                "required": ["diagnosis"]
            }
        }
        """
        # Lazy init: load criteria on first call
        if self._cmw_criteria is None:
            case_yaml = chatdbg_config.cmw_case_yaml
            if not case_yaml:
                return "check_my_work", "[check_my_work unavailable: no case.yaml configured]"
            self._cmw_criteria = load_criteria_from_case_yaml(case_yaml)
            self._cmw_state = CheckMyWorkState(
                max_stale_checks=chatdbg_config.cmw_max_stale,
            )

        state = self._cmw_state

        # Already perfect — tell model to finalize
        if state.is_perfect:
            return "check_my_work", (
                "You already achieved a perfect score (3/3). "
                "Please provide your final answer now."
            )

        # Stale — no improvement for too many checks
        if state.is_stale:
            last = state.checks[-1]
            return "check_my_work", (
                f"No improvement after {state.max_stale_checks} consecutive checks "
                f"(current: rc={last.scores['root_cause']} lf={last.scores['local_fix']} "
                f"gf={last.scores['global_fix']}). "
                f"Please provide your FINAL answer now — no more checks allowed."
            )

        crit = self._cmw_criteria
        result = call_judge(
            diagnosis,
            source=crit["source"],
            source_file=crit["source_file"],
            language=crit["language"],
            criteria=crit["criteria"],
            judge_model=chatdbg_config.cmw_judge_model,
            check_number=state.num_checks + 1,
        )
        state.record(result)

        # Format feedback for the model
        s = result.scores
        f = result.feedback
        total = result.total_score()
        lines = [
            f"[Check #{result.check_number}] Score: {total}/3 "
            f"(root_cause={s['root_cause']}, local_fix={s['local_fix']}, global_fix={s['global_fix']})",
            "",
        ]
        for axis in ("root_cause", "local_fix", "global_fix"):
            status = "PASS" if s[axis] == 1 else "FAIL"
            lines.append(f"  {axis}: [{status}] {f.get(axis, '')}")

        if total == 3:
            lines.append("")
            lines.append("Perfect score! Please provide your final answer now.")
        elif state.is_stale:
            lines.append("")
            lines.append(
                f"WARNING: No improvement for {state.max_stale_checks} checks. "
                f"This is your last chance — provide your FINAL answer now."
            )
        else:
            remaining = state.max_stale_checks - state._stale_count
            lines.append("")
            lines.append(
                f"You may continue debugging and check again. "
                f"({remaining} check(s) remaining before forced stop if no improvement.)"
            )

        return "check_my_work", "\n".join(lines)

    def _supported_functions(self):
        functions = []
        if chatdbg_config.enable_native_debug:
            functions.append(self.llm_debug)
        if chatdbg_config.enable_get_code_surrounding:
            functions.append(self.llm_get_code_surrounding)
        if chatdbg_config.enable_find_definition and clangd_lsp_integration.is_available():
            functions.append(self.llm_find_definition)
        if chatdbg_config.enable_oracle:
            functions.append(self.llm_ask_oracle)
        if chatdbg_config.enable_bash:
            functions.append(self.llm_bash)
        if chatdbg_config.enable_check_my_work and chatdbg_config.cmw_case_yaml:
            functions.append(self.llm_check_my_work)
        return functions

    def _flush_cmw_to_collectors(self, assistant: Assistant) -> None:
        """Copy check_my_work summary to any AblationDataCollector listeners."""
        if self._cmw_state and self._cmw_state.num_checks > 0:
            from ..util.collector import AblationDataCollector
            for listener in assistant._clients:
                if isinstance(listener, AblationDataCollector):
                    listener._cmw_summary = self._cmw_state.summary()

    def _make_assistant(self) -> Assistant:
        chatdbg_config.apply_tool_config()
        functions = self._supported_functions()
        instruction_prompt = self.initial_prompt_instructions()

        # gdb overwrites sys.stdin to be a file object that doesn't seem
        # to support colors or streaming.  So, just use the original stdout
        # here for all subclasses.
        printer = chatdbg_config.make_printer(sys.__stdout__, self._prompt, "   ", 80)

        listeners = [
            printer,
            self._log,
        ]

        if chatdbg_config.collect_data:
            from ..util.collector import AblationDataCollector
            listeners.append(AblationDataCollector(
                output_path=chatdbg_config.collect_data,
                extra_metadata={
                    "model": chatdbg_config.model,
                    "tool_config": chatdbg_config.tool_config,
                    "enabled_tools": [f.__name__ for f in functions],
                },
            ))

        assistant = Assistant(
            instruction_prompt,
            model=chatdbg_config.model,
            functions=functions,
            listeners=listeners,
        )

        return assistant

    def warn(self, message):
        print(message)

    def fail(self, message):
        raise DBGError(message)
