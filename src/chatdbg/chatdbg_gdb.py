import os
import atexit
from typing import List, Optional, Union

import gdb

from chatdbg.native_util import clangd_lsp_integration
from chatdbg.native_util.code import code
from chatdbg.native_util.dbg_dialog import DBGDialog
from chatdbg.native_util.stacks import (
    _ArgumentEntry,
    _FrameSummaryEntry,
    _SkippedFramesEntry,
)
from chatdbg.util.config import chatdbg_config
from chatdbg.native_util.safety import command_is_safe
from chatdbg.util.exit_message import chatdbg_was_called, print_exit_message

# The file produced by the panic handler if the Rust program is using the chatdbg crate.
RUST_PANIC_LOG_FILENAME = "panic_log.txt"
PROMPT = "(ChatDBG gdb) "

# Set the prompt to ChatDBG gdb
gdb.prompt_hook = lambda current_prompt: PROMPT


last_error_type = ""

atexit.register(print_exit_message)


def stop_handler(event):
    """Sets last error type so we can report it later."""
    # Check if the event is a stop event
    global last_error_type
    if not hasattr(event, "stop_signal"):
        last_error_type = ""  # Not a real error (e.g., a breakpoint)
        return
    if event.stop_signal is not None:
        last_error_type = event.stop_signal


gdb.events.stop.connect(stop_handler)


class Code(gdb.Command):

    def __init__(self):
        gdb.Command.__init__(self, "code", gdb.COMMAND_USER)

    def invoke(self, command, from_tty):
        print(code(command))
        return


Code()


class Definition(gdb.Command):

    def __init__(self):
        gdb.Command.__init__(self, "definition", gdb.COMMAND_USER)

    def invoke(self, command, from_tty):
        print(clangd_lsp_integration.native_definition(command))
        return


Definition()


class Config(gdb.Command):

    def __init__(self):
        gdb.Command.__init__(self, "config", gdb.COMMAND_USER)

    def invoke(self, command, from_tty):
        args = command.split()
        message = chatdbg_config.parse_only_user_flags(args)
        print(message)
        return


Config()


# Implement the command `why`
class Why(gdb.Command):
    """Provides root cause analysis for a failure."""

    def __init__(self):
        gdb.Command.__init__(self, "why", gdb.COMMAND_USER)

    def invoke(self, command, from_tty):
        try:
            dialog = GDBDialog(PROMPT)
            dialog.dialog(command)
        except Exception as e:
            print(str(e))
            return


Why()

gdb.execute("alias chat = why")


class GDBDialog(DBGDialog):

    def __init__(self, prompt) -> None:
        chatdbg_was_called()
        super().__init__(prompt)

    def _message_is_a_bad_command_error(self, message):
        return message.strip().startswith("Undefined command:")

    def _run_one_command(self, command):
        try:
            return gdb.execute(command, to_string=True)
        except Exception as e:
            return str(e)

    def check_debugger_state(self):
        global last_error_type
        if not last_error_type:
            # No signal — could be a breakpoint stop (abort, exit, ...) or
            # a clean exit reached via `break _exit`. The harness can supply
            # a richer label (e.g., a behavioral test-oracle string) via the
            # CHATDBG_PROMPT_ERROR env var; otherwise fall back to a generic
            # tag so the LLM at least knows there's no signal.
            last_error_type = os.environ.get("CHATDBG_PROMPT_ERROR") \
                or "stopped (no-signal)"
        try:
            frame = gdb.selected_frame()
        except gdb.error:
            # Inferior already exited and gdb has no live frame. Rather
            # than bail, let ChatDBG run a degraded session — the prompt
            # and any captured stdout/stderr the harness passes via the
            # question still give the LLM something to reason about. This
            # is what enables ablation on logical-error bugs that don't
            # crash but still represent real defects.
            return

        # Walk older frames until we find one with debug info and a source
        # mapping. The crash site often lands in stripped system code
        # (libc memcpy, abort's raise, etc.) while the bug lives one or
        # more frames up in user code. Pre-select that user frame so every
        # downstream call to gdb.selected_frame() (source extraction,
        # locals, frame summaries) sees it instead of the stripped frame.
        original_frame = frame
        user_frame = None
        while frame is not None:
            try:
                frame.block()
                if frame.find_sal().symtab is not None:
                    user_frame = frame
                    break
            except RuntimeError:
                pass
            frame = frame.older()

        if user_frame is None:
            # No debug info available, but we still have a frame. Let the
            # session proceed against the original (likely stripped) frame
            # rather than blocking the ablation entirely.
            return

        if user_frame is not original_frame:
            user_frame.select()

    def _get_frame_summaries(
        self, max_entries: int = 20
    ) -> Optional[List[Union[_FrameSummaryEntry, _SkippedFramesEntry]]]:
        thread = gdb.selected_thread()
        if not thread:
            return None

        skipped = 0
        summaries: List[Union[_FrameSummaryEntry, _SkippedFramesEntry]] = []

        try:
            frame = gdb.selected_frame()
        except gdb.error:
            # No live frame — inferior exited cleanly. Caller (ChatDBG
            # session) handles the empty-summary case as "no stack".
            return None

        index = -1
        # Walk the stack and build up the frames list.
        while frame is not None:
            index += 1

            name = frame.name()
            if not name:
                skipped += 1
                frame = frame.older()
                continue
            symtab_and_line = frame.find_sal()

            # Get frame file path
            if symtab_and_line.symtab is not None:
                file_path = symtab_and_line.symtab.fullname()
                if file_path == None:
                    file_path = "[unknown]"
                else:
                    # If we are in a subdirectory, use a relative path instead.
                    if file_path.startswith(os.getcwd()):
                        file_path = os.path.relpath(file_path)
                    # Skip frames for which we have no source -- likely system frames.
                    if not os.path.exists(file_path):
                        skipped += 1
                        frame = frame.older()
                        continue
            else:
                file_path = None

            # Get frame lineno
            if symtab_and_line.line is not None:
                lineno = symtab_and_line.line
            else:
                lineno = None

            # Get arguments
            arguments: List[_ArgumentEntry] = []
            block = gdb.Block
            try:
                block = frame.block()
            except Exception:
                skipped += 1
                frame = frame.older()
                continue
            for symbol in block:
                if symbol.is_argument:
                    typename = symbol.type
                    name = symbol.name
                    value = str(frame.read_var(name))
                    arguments.append(_ArgumentEntry(typename, name, value))

            if skipped > 0:
                summaries.append(_SkippedFramesEntry(skipped))
                skipped = 0

            summaries.append(
                _FrameSummaryEntry(index, name, arguments, file_path, lineno)
            )
            if len(summaries) >= max_entries:
                break
            frame = frame.older()

        if skipped > 0:
            summaries.append(_SkippedFramesEntry(skipped))

        # Fallback: if every frame got filtered (typical when gdb is parked
        # on a non-user binary like /bin/bash or libc-only frames after a
        # `break exit` stop), the LLM is left staring at "[N skipped frames...]"
        # alone — no signal at all. Re-walk the stack and emit the frames as
        # best-effort entries (no source, no args) so the LLM at least sees
        # function names and addresses.
        if summaries and all(isinstance(s, _SkippedFramesEntry) for s in summaries):
            try:
                frame = gdb.selected_frame()
            except gdb.error:
                return summaries
            fallback: List[Union[_FrameSummaryEntry, _SkippedFramesEntry]] = []
            fb_index = -1
            while frame is not None and len(fallback) < max_entries:
                fb_index += 1
                name = frame.name() or "??"
                sal = frame.find_sal()
                file_path = None
                lineno = None
                if sal.symtab is not None:
                    try:
                        file_path = sal.symtab.fullname()
                        if file_path and file_path.startswith(os.getcwd()):
                            file_path = os.path.relpath(file_path)
                    except Exception:
                        file_path = None
                    if sal.line:
                        lineno = sal.line
                fallback.append(
                    _FrameSummaryEntry(fb_index, name, [], file_path, lineno)
                )
                frame = frame.older()
            if fallback:
                return fallback

        return summaries

    def _initial_prompt_error_message(self):
        # If the Rust panic log exists, append it to the error reason.
        global last_error_type
        try:
            with open(RUST_PANIC_LOG_FILENAME, "r") as log:
                panic_log = log.read()
            last_error_type = panic_log + "\n" + last_error_type
        except:
            pass
        return last_error_type

    def _initial_prompt_error_details(self):
        """Anything more beyond the initial error message to include.

        The harness can supply free-form context (workspace summary, build
        system, etc.) via CHATDBG_PROMPT_EXTRA — useful for telling the LLM
        what kind of project it's looking at without leaking the bug site.
        """
        return os.environ.get("CHATDBG_PROMPT_EXTRA") or None

    def _initial_prompt_command_line(self):
        # The harness can override the cmdline shown to the LLM via
        # CHATDBG_PROMPT_BINARY. This matters when gdb was launched on a
        # wrapper (bash/make/ctest) but the buggy binary is several execs
        # deep — `progspace.filename` points at the wrapper, not the actual
        # program under test.
        override = os.environ.get("CHATDBG_PROMPT_BINARY")
        if override:
            return override

        executable_path = gdb.selected_inferior().progspace.filename

        if executable_path.startswith(os.getcwd()):
            executable_path = os.path.join(".", os.path.relpath(executable_path))

        prefix = "Argument list to give program being debugged when it is started is "
        args = gdb.execute("show args", to_string=True).strip()
        if args.startswith(prefix):
            args = args[len(prefix) :].strip('."')

        return executable_path + " " + args

    def _initial_prompt_input(self):
        prefix = "Argument list to give program being debugged when it is started is "
        args = gdb.execute("show args", to_string=True).strip()
        if args.startswith(prefix):
            args = args[len(prefix) :].strip('."')

        input_pipe = args.find("<")
        if input_pipe != -1:
            input_file = args[input_pipe + 1 :].strip()
            try:
                content = open(input_file, "r").read()
                return content
            except Exception:
                self.fail(f"The detected input file {input_file} could not be read.")

    def _prompt_stack(self):
        """
        Return a simple backtrace to show the LLM where we are on the stack
        in followup prompts.
        """
        return None

    def llm_debug(self, command: str):
        """
        {
            "name": "debug",
            "description": "The `debug` function runs a GDB command on the stopped program and gets the response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The GDB command to run, possibly with arguments."
                    }
                },
                "required": [ "command" ]
            }
        }
        """
        if not chatdbg_config.unsafe and not command_is_safe(command):
            self._unsafe_cmd = True
            return command, f"Command `{command}` is not allowed."
        return command, self._run_one_command(command)
