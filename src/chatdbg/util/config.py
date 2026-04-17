import argparse
import json
import os
import sys

from traitlets import Bool, Int, Unicode
from traitlets.config import Configurable

from chatdbg.assistant.listeners import BaseAssistantListener
from chatdbg.util.markdown import ChatDBGMarkdownPrinter
from chatdbg.util.printer import ChatDBGPrinter

from io import TextIOWrapper
from typing import Union

from chatdbg.util.jupyter import ChatDBGJupyterPrinter


def _chatdbg_get_env(
    option_name: str, default_value: Union[bool, int, str]
) -> Union[bool, int, str]:
    env_name = "CHATDBG_" + option_name.upper()
    v = os.getenv(env_name, str(default_value))
    if type(default_value) == int:
        return int(v)
    elif type(default_value) == bool:
        return v.lower() == "true" or v.lower() == "1"
    else:
        return v


class DBGParser(argparse.ArgumentParser):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def error(self, message):
        raise Exception(f"Error: {message}\n")


class ChatDBGConfig(Configurable):
    model = Unicode(_chatdbg_get_env("model", "gpt-4o"), help="The LLM model").tag(
        config=True
    )

    log = Unicode(_chatdbg_get_env("log", "log.yaml"), help="The log file").tag(
        config=True
    )

    tag = Unicode(_chatdbg_get_env("tag", ""), help="Any extra info for log file").tag(
        config=True
    )

    rc_lines = Unicode(
        _chatdbg_get_env("rc_lines", "[]"), help="lines to run at startup"
    ).tag(config=True)

    context = Int(
        _chatdbg_get_env("context", 10),
        help="lines of source code to show when displaying stacktrace information",
    ).tag(config=True)

    show_locals = Bool(
        _chatdbg_get_env("show_locals", True),
        help="show local var values in stacktrace",
    ).tag(config=True)

    show_libs = Bool(
        _chatdbg_get_env("show_libs", False), help="show library frames in stacktrace"
    ).tag(config=True)

    show_slices = Bool(
        _chatdbg_get_env("show_slices", True), help="support the `slice` command"
    ).tag(config=True)

    take_the_wheel = Bool(
        _chatdbg_get_env("take_the_wheel", True), help="Let LLM take the wheel"
    ).tag(config=True)

    format = Unicode(
        _chatdbg_get_env("format", "md"),
        help="The output format (text or md or md:simple or jupyter)",
    ).tag(config=True)

    instructions = Unicode(
        _chatdbg_get_env("instructions", ""),
        help="The file for the initial instructions to the LLM, or '' for the default (possibly-model specific) version",
    ).tag(config=True)

    module_whitelist = Unicode(
        _chatdbg_get_env("module_whitelist", ""), help="The module whitelist file"
    ).tag(config=True)

    unsafe = Bool(
        _chatdbg_get_env("unsafe", False),
        help="Disable any protections against GPT running harmful code or commands",
    ).tag(config=True)

    # Tool config: 'interactive' to prompt at startup, or path to a JSON file.
    # If empty (default), all tools are enabled.
    tool_config = Unicode(
        _chatdbg_get_env("tool_config", ""),
        help="Tool config: '' (all enabled), 'interactive' (prompt at startup), or path to a JSON config file",
    ).tag(config=True)

    # Ablation data collection: path for output JSON, or '' to disable.
    collect_data = Unicode(
        _chatdbg_get_env("collect_data", ""),
        help="Path for ablation data output JSON, or '' to disable collection",
    ).tag(config=True)

    _user_configurable = [
        log,
        model,
        instructions,
        format,
        module_whitelist,
        unsafe,
        tool_config,
        collect_data,
    ]

    # Per-tool ablation state (not exposed as env vars / traitlets).
    # Only modified by interactive mode or JSON config file.
    _tool_flags = {
        "enable_debug": "Enable the `debug` tool (run pdb commands)",
        "enable_info": "Enable the `info` tool (get docs/source for symbols)",
        "enable_slice": "Enable the `slice` tool (data-flow slicing)",
        "enable_native_debug": "Enable the native `debug` tool (run debugger commands)",
        "enable_get_code_surrounding": "Enable the `get_code_surrounding` tool",
        "enable_find_definition": "Enable the `find_definition` tool (LSP lookup)",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Initialize all tool flags to True (all enabled by default)
        for flag_name in self._tool_flags:
            setattr(self, flag_name, True)

    def apply_tool_config(self):
        """Apply tool configuration based on tool_config mode."""
        mode = self.tool_config
        if mode == "":
            return
        elif mode == "interactive":
            self._interactive_tool_config()
        else:
            self._load_tool_config_file(mode)

    def _interactive_tool_config(self):
        """Prompt the user Y/N for each tool flag."""
        print("Configure tools for this session:")
        for flag_name, description in self._tool_flags.items():
            current = getattr(self, flag_name)
            try:
                answer = input(f"  {description}? [{'Y/n' if current else 'y/N'}] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if answer == "":
                pass  # keep current value
            elif answer in ("y", "yes"):
                setattr(self, flag_name, True)
            elif answer in ("n", "no"):
                setattr(self, flag_name, False)
            else:
                print(f"    Unrecognized input '{answer}', keeping {'Y' if current else 'N'}")
        print()

    def _load_tool_config_file(self, path):
        """Load tool flags from a JSON file.

        Expected format:
        {
            "enable_debug": true,
            "enable_info": false,
            "enable_slice": true,
            ...
        }
        Any flag not present in the file keeps its current value (True).
        """
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            print(f"*** Tool config file not found: {path}", file=sys.stderr)
            return
        except json.JSONDecodeError as e:
            print(f"*** Invalid JSON in tool config file {path}: {e}", file=sys.stderr)
            return

        for flag_name in self._tool_flags:
            if flag_name in data:
                value = data[flag_name]
                if isinstance(value, bool):
                    setattr(self, flag_name, value)
                else:
                    print(f"*** Ignoring non-boolean value for {flag_name}: {value}", file=sys.stderr)

    def _parser(self):
        parser = DBGParser(add_help=False)

        for trait in self._user_configurable:
            name = f"--{trait.name}"
            value = self._trait_values[trait.name]
            t = type(value)
            if t == bool:
                parser.add_argument(name, default=value, action="store_true")
            else:
                parser.add_argument(name, default=value, type=t)

        return parser

    def to_json(self) -> dict[str, Union[int, str, bool]]:
        """Serialize the object to a JSON string."""
        return {
            "model": self.model,
            "log": self.log,
            "tag": self.tag,
            "rc_lines": self.rc_lines,
            "context": self.context,
            "show_locals": self.show_locals,
            "show_libs": self.show_libs,
            "show_slices": self.show_slices,
            "take_the_wheel": self.take_the_wheel,
            "format": self.format,
            "instructions": self.instructions,
            "module_whitelist": self.module_whitelist,
            "tool_config": self.tool_config,
            "collect_data": self.collect_data,
        }

    def parse_user_flags(self, argv: list[str]) -> None:

        args, unknown_args = self._parser().parse_known_args(argv)

        for x in self._user_configurable:
            self.set_trait(x.name, getattr(args, x.name))

        return unknown_args

    def user_flags_help(self) -> str:
        return "\n".join(
            [
                self.class_get_trait_help(x, self).replace("ChatDBGConfig.", "")
                for x in self._user_configurable
            ]
        )

    def user_flags(self) -> str:
        return "\n".join(
            [
                f"  --{x.name:10}{self._trait_values[x.name]}"
                for x in self._user_configurable
            ]
        )

    def parse_only_user_flags(self, args: list[str]) -> str:
        try:
            unknown = chatdbg_config.parse_user_flags(args)
            if unknown:
                return (
                    f"Unrecognized arguments: {' '.join(unknown)}\n\n"
                    + f"ChatDBG arguments:\n\n{self.user_flags_help()}"
                )
            return chatdbg_config.user_flags()
        except Exception as e:
            return str(e) + f"\nChatDBG arguments:\n\n{self.user_flags_help()}"

    def make_printer(
        self, stdout: TextIOWrapper, prompt: str, prefix: str, width: int
    ) -> BaseAssistantListener:
        format = chatdbg_config.format
        split = format.split(":")
        if split[0] == "md":
            theme = split[1] if len(split) == 2 else None
            return ChatDBGMarkdownPrinter(stdout, prompt, prefix, width, theme=theme)
        elif format == "text":
            return ChatDBGPrinter(stdout, prompt, prefix, width)
        elif format == "jupyter":
            return ChatDBGJupyterPrinter(prompt, prefix, width)
        else:
            print("*** Unknown format '{format}'.  Defaulting to 'text'", file=stdout)
            return ChatDBGPrinter(stdout, prompt, prefix, width)

    def get_module_whitelist(self) -> str:
        if self.module_whitelist == "":
            file_path = os.path.join(os.path.dirname(__file__), f"module_whitelist.txt")
        else:
            file_path = self.module_whitelist

        with open(file_path, "r") as file:
            return [module.rstrip() for module in file if module.rstrip() != ""]


chatdbg_config: ChatDBGConfig = ChatDBGConfig()
