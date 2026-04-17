import json
import os
import re
import sys
import uuid
from datetime import datetime

from ..assistant.listeners import BaseAssistantListener


class AblationDataCollector(BaseAssistantListener):
    """Listener that collects structured data from each query for ablation experiments.

    Outputs a JSON file per dialog with:
      - thinking output (if present in streamed text)
      - final response + suggested fix
      - input/output token counts
      - number of tool calls and per-tool frequency
      - length of code output in the response
    """

    def __init__(self, output_path="ablation_data.json", extra_metadata=None):
        self._output_path = output_path
        self._extra_metadata = extra_metadata or {}

        # Dialog-level state
        self._instructions = None
        self._queries = []

        # Per-query state
        self._current_stream = ""
        self._current_responses = []
        self._current_tool_calls = []

    # -- Dialog events --

    def on_begin_dialog(self, instructions):
        self._instructions = instructions
        self._queries = []

    def on_end_dialog(self):
        self._dump()

    # -- Query events --

    def on_begin_query(self, prompt, user_text):
        self._current_stream = ""
        self._current_responses = []
        self._current_tool_calls = []
        self._current_prompt = prompt
        self._current_user_text = user_text

    def on_begin_stream(self):
        self._current_stream = ""

    def on_stream_delta(self, text):
        self._current_stream += text

    def on_end_stream(self):
        pass

    def on_response(self, text):
        if text is not None:
            self._current_responses.append(text)

    def on_function_call(self, call, result):
        # call is a string like "debug p x" or "info some_func"
        tool_name = call.split()[0] if call else "unknown"
        self._current_tool_calls.append({
            "tool_name": tool_name,
            "call": call,
            "result_length": len(result) if result else 0,
        })

    def on_end_query(self, stats):
        full_response = "\n".join(self._current_responses)
        thinking, clean_response = self._extract_thinking(self._current_stream)
        code_blocks = self._extract_code_blocks(full_response)

        # Build per-tool frequency counts
        tool_frequency = {}
        for tc in self._current_tool_calls:
            name = tc["tool_name"]
            tool_frequency[name] = tool_frequency.get(name, 0) + 1

        query_data = {
            "user_text": self._current_user_text,
            "prompt": self._current_prompt,
            "thinking": thinking,
            "response": full_response,
            "code_blocks": code_blocks,
            "total_code_length": sum(len(c) for c in code_blocks),
            "num_tool_calls": len(self._current_tool_calls),
            "tool_calls": self._current_tool_calls,
            "tool_frequency": tool_frequency,
            "stats": {
                "completed": stats.get("completed", False),
                "model": stats.get("model", ""),
                "cost": stats.get("cost", 0),
                "time": stats.get("time", 0),
                "tokens": stats.get("tokens", 0),
                "prompt_tokens": stats.get("prompt_tokens", 0),
                "completion_tokens": stats.get("completion_tokens", 0),
            },
        }
        self._queries.append(query_data)

    # -- Extraction helpers --

    @staticmethod
    def _extract_thinking(streamed_text):
        """Extract thinking/reasoning content from the streamed response.

        Models like o1/o3 emit <thinking>...</thinking> blocks, and
        Claude emits <antThinking>...</antThinking>. Some models use
        ```thinking ... ``` fenced blocks.

        Returns (thinking_text, cleaned_response).
        """
        thinking_parts = []

        # <thinking>...</thinking> or <antThinking>...</antThinking>
        for tag in ["thinking", "antThinking"]:
            for match in re.finditer(
                rf"<{tag}>(.*?)</{tag}>", streamed_text, re.DOTALL
            ):
                thinking_parts.append(match.group(1).strip())

        # ```thinking ... ``` fenced blocks
        for match in re.finditer(
            r"```thinking\s*\n(.*?)```", streamed_text, re.DOTALL
        ):
            thinking_parts.append(match.group(1).strip())

        # Remove thinking blocks from text to get clean response
        cleaned = streamed_text
        for tag in ["thinking", "antThinking"]:
            cleaned = re.sub(rf"<{tag}>.*?</{tag}>", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"```thinking\s*\n.*?```", "", cleaned, flags=re.DOTALL)
        cleaned = cleaned.strip()

        return "\n\n".join(thinking_parts) if thinking_parts else None, cleaned

    @staticmethod
    def _extract_code_blocks(response_text):
        """Extract fenced code blocks from the response."""
        blocks = re.findall(r"```(?:\w*)\n(.*?)```", response_text, re.DOTALL)
        return [b.strip() for b in blocks]

    # -- Output --

    def _dump(self):
        data = {
            "meta": {
                "uid": str(uuid.uuid4()),
                "time": datetime.now().isoformat(),
                **self._extra_metadata,
            },
            "instructions": self._instructions,
            "queries": self._queries,
        }
        try:
            os.makedirs(os.path.dirname(self._output_path) or ".", exist_ok=True)
            with open(self._output_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            print(f"*** Ablation data written to {self._output_path}")
        except Exception as e:
            print(f"*** Failed to write ablation data: {e}", file=sys.stderr)
