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

        assistant.close()

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
        return functions

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
