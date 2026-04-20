# ChatDBG Ablation Framework

This fork of [ChatDBG](https://github.com/plasma-umass/ChatDBG) adds infrastructure for ablation studies — systematically enabling/disabling tools and swapping LLM backends to measure their contribution to debugging performance.

> **End-to-end bench pipeline:** see [`bench/README.md`](./bench/README.md) for the sweep/judge/analyze harness built on top of this framework (test-case database with proximate/root-cause criteria, LLM-as-judge evaluator, and CSV/markdown rollups). The rest of this document describes the per-session ablation knobs those tools use.

## Overview

Two axes of ablation:

- **Tools** — which debugger tools (functions) the LLM can call
- **Models** — which LLM backend is used via LiteLLM/OpenRouter

---

## Tool Ablation

### How tools work

Every tool is a Python method in `chatdbg_pdb.py` whose docstring is a JSON schema (the OpenAI function-calling schema). The `Assistant` class passes these schemas to the LLM automatically via LiteLLM. The method returns a `(call_description, result_text)` tuple.

Built-in tools:

| Flag | Tool | Description |
|---|---|---|
| `enable_debug` | `debug` (pdb) | Run arbitrary pdb commands |
| `enable_info` | `info` (pdb) | Get docs/source for symbols |
| `enable_slice` | `slice` (pdb) | Data-flow slicing |
| `enable_native_debug` | `debug` (gdb/lldb) | Run arbitrary debugger commands |
| `enable_get_code_surrounding` | `get_code_surrounding` | Print source around a location |
| `enable_find_definition` | `find_definition` | clangd LSP symbol lookup |
| `enable_oracle` | `ask_oracle` | Escalate a single hard question to a frontier model (set via `CHATDBG_ORACLE_MODEL`, default `openrouter/openai/gpt-5`) |

### Configuring tool ablation

Set `--tool_config` (or `CHATDBG_TOOL_CONFIG`) to one of:

| Value | Behavior |
|---|---|
| `""` (default) | All tools enabled, no prompting |
| `"interactive"` | Y/N prompt for each tool at session start |
| `"/path/to/config.json"` | Load from a JSON file |

### JSON config format

Only include the flags you want to override — anything omitted stays `true`.

**All tools (baseline):**
```json
{}
```

**No tools (zero-shot, LLM only):**
```json
{
    "enable_debug": false,
    "enable_info": false,
    "enable_slice": false
}
```

**Debug only:**
```json
{
    "enable_debug": true,
    "enable_info": false,
    "enable_slice": false
}
```

**Debug + info (no slice):**
```json
{
    "enable_debug": true,
    "enable_info": true,
    "enable_slice": false
}
```

Then run:
```bash
chatdbg --tool_config ./configs/no_tools.json script.py
# or
CHATDBG_TOOL_CONFIG=./configs/no_tools.json chatdbg script.py
```

> **Note:** The config file must be created by the user before running. If the file is not found, ChatDBG will print a warning and fall back to all tools enabled.

### Adding a custom tool

**1. Define the method in `chatdbg_pdb.py`:**

```python
def my_custom_tool(self, query):
    """
    {
        "name": "my_custom_tool",
        "description": "Describe what this tool does so the LLM knows when to call it.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The input to the tool."
                }
            },
            "required": ["query"]
        }
    }
    """
    result = "whatever your tool computes"
    return f"my_custom_tool {query}", result
```

**2. Add a flag in `config.py`'s `_tool_flags` dict:**

```python
_tool_flags = {
    "enable_debug": "Enable the `debug` tool (run pdb commands)",
    "enable_info": "Enable the `info` tool (get docs/source for symbols)",
    "enable_slice": "Enable the `slice` tool (data-flow slicing)",
    "enable_my_custom_tool": "Enable the `my_custom_tool` tool",
}
```

**3. Wire it into `_supported_functions()` in `chatdbg_pdb.py`:**

```python
def _supported_functions(self):
    if chatdbg_config.take_the_wheel:
        functions = []
        if chatdbg_config.enable_debug:
            functions.append(self.debug)
        if chatdbg_config.enable_info:
            functions.append(self.info)
        if chatdbg_config.enable_slice and self._supports_flow:
            functions.append(self.slice)
        if chatdbg_config.enable_my_custom_tool:   # <-- add this
            functions.append(self.my_custom_tool)
    else:
        functions = []
    return functions
```

**4. Ablate it via JSON:**

```json
{
    "enable_debug": true,
    "enable_info": false,
    "enable_slice": false,
    "enable_my_custom_tool": true
}
```

---

## Model Ablation

Models are swapped via [LiteLLM](https://github.com/BerriAI/litellm) with direct routing through [OpenRouter](https://openrouter.ai/).

### Setting the model

**Option 1 — environment variable:**
```bash
export CHATDBG_MODEL=openrouter/moonshotai/kimi-k2.5
```

**Option 2 — CLI flag:**
```bash
chatdbg --model openrouter/moonshotai/kimi-k2.5 script.py
```

### Model path format

```
openrouter/<provider>/<model-name>
```

Browse available models at [openrouter.ai/models](https://openrouter.ai/models).

**Examples:**
```bash
# Kimi K2.5
chatdbg --model openrouter/moonshotai/kimi-k2.5 -c continue script.py

# Default (OpenAI GPT-4o)
chatdbg script.py
```

You will need an `OPENROUTER_API_KEY` set in your environment for OpenRouter models:
```bash
export OPENROUTER_API_KEY=<your-key>
```

---

## Data Collection

Use `--collect_data` to save structured per-session output (tool calls, token counts, responses) for analysis:

```bash
chatdbg --collect_data ./results/my_run.json --tool_config ./configs/debug_only.json --model openrouter/moonshotai/kimi-k2.5 -c continue script.py
```

The output directory is created automatically if it doesn't exist. The file is written at the end of each session.

Output format (per session):
```json
{
  "meta": { "uid": "...", "time": "...", "model": "...", "tool_config": "...", "enabled_tools": [...] },
  "instructions": "...",
  "queries": [
    {
      "prompt": "...",
      "responses": [...],
      "tool_calls": [...],
      "input_tokens": 0,
      "output_tokens": 0
    }
  ]
}
```

---

## Quick-start example

```bash
# Activate the venv
source .venv/bin/activate

# Run with debug-only tools, Kimi model, collect data
chatdbg \
  --tool_config ./configs/debug_only.json \
  --collect_data ./results/debug_only.json \
  --model openrouter/moonshotai/kimi-k2.5 \
  -c continue \
  samples/python/testme.py
```
