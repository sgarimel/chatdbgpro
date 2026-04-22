"""Emit a bench/cases/<case_id>/case.yaml + bug.patch for one probed bug.

Output shape matches the contract bench/common.py::discover_cases +
bench/drivers/tier3_gdb.py + bench/judge.py expect, with two
BugsC++-specific extensions inside `repo` and `run`:

  repo.prebuilt_workspace  — absolute host path to the already-built tree
                              (skips git-clone + build inside the driver)
  run.gdb_image            — chatdbgpro/gdb-<project>:latest tag
  run.gdb_command          — full `docker run ... bash -c "..."` shell string

Both fields are read by the BugsC++ branch in tier3_gdb (one minimal
edit there). Synthetic and standard injected_repo cases are unaffected.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = REPO_ROOT / "bench" / "cases"


def _yaml_block_scalar(text: str, indent: int = 4) -> str:
    """Render multi-line string as a YAML literal block (|)."""
    pad = " " * indent
    if not text:
        return '""'
    lines = text.splitlines() or [""]
    return "|\n" + "\n".join(pad + ln for ln in lines)


def _yaml_str(s: str | None) -> str:
    if s is None:
        return "null"
    if "\n" in s:
        return _yaml_block_scalar(s)
    safe = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{safe}"'


def _yaml_list(items: list) -> str:
    if not items:
        return "[]"
    return "[" + ", ".join(_yaml_str(str(x)) for x in items) + "]"


def render_case_yaml(bug: dict) -> str:
    case_id   = bug["case_id"]
    project   = bug["project"]
    bug_index = bug["bug_index"]
    language  = bug["language"]
    bug_type  = bug.get("bug_type") or "unknown"
    cve_id    = bug.get("cve_id")
    workspace = bug["workspace_path"]
    gdb_image = bug["gdb_image"]
    gdb_cmd   = bug["gdb_command"]
    crash_sig = bug.get("crash_signal") or "unknown"

    trigger_argv: list[str] = bug.get("trigger_argv") or []
    binary = trigger_argv[0] if trigger_argv else ""
    debug_args = trigger_argv[1:] if len(trigger_argv) > 1 else []

    uf_func = bug.get("user_frame_function") or "unknown"
    uf_file = bug.get("user_frame_file") or "unknown"
    uf_line = bug.get("user_frame_line")
    f0_func = bug.get("frame0_function") or "unknown"
    f0_file = bug.get("frame0_file") or "unknown"
    f0_line = bug.get("frame0_line")
    patch_files = json.loads(bug["patch_files_json"]) if bug.get("patch_files_json") else []

    cve_part = f" {cve_id}." if cve_id else ""
    description = (
        f"BugsC++ {project}-{bug_index}.{cve_part} "
        f"Crash: {crash_sig} at {uf_file}:{uf_line} in {uf_func}."
    )

    root_cause = (
        f"Identify that the crash originates at {uf_file}:{uf_line} inside "
        f"{uf_func}. The frame-0 location reported by gdb is "
        f"{f0_file}:{f0_line} in {f0_func}, but the shallowest frame in "
        f"project source code is the user frame above."
    )
    local_fix = (
        f"Apply a targeted change at {uf_file} around line {uf_line} that "
        f"prevents the {crash_sig} observed in the backtrace, without "
        f"altering surrounding control flow."
    )
    global_fix = (
        f"Address the root cause reflected in the developer's patch "
        f"(see bug.patch). The fix touches: {', '.join(patch_files) or 'unknown'}."
    )

    yaml_text = f"""\
id: {case_id}
language: {language}
kind: injected_repo
description: {_yaml_str(description)}

repo:
  prebuilt_workspace: {_yaml_str(workspace)}

build:
  prepare: []
  commands: []
  binary: {_yaml_str(binary)}

run:
  gdb_image: {_yaml_str(gdb_image)}
  gdb_command: {_yaml_str(gdb_cmd)}
  expected_crash: true
  env: {{}}
  clean_env: false

debug:
  args: {_yaml_list(debug_args)}
  stdin_data: ""

bug:
  patch_file: bug.patch
  root_cause_file: {_yaml_str(uf_file)}
  root_cause_lines: {_yaml_list([uf_line] if uf_line is not None else [])}
  frame0_file: {_yaml_str(f0_file)}
  frame0_line: {f0_line if f0_line is not None else "null"}
  frame0_function: {_yaml_str(f0_func)}
  category: {_yaml_str(bug_type)}
  error_type: {_yaml_str(crash_sig)}

criteria:
  root_cause: {_yaml_block_scalar(root_cause)}
  local_fix: {_yaml_block_scalar(local_fix)}
  global_fix: {_yaml_block_scalar(global_fix)}

verified: true
"""
    return yaml_text


def write_case_yaml(bug: dict) -> Path:
    """Materialize bench/cases/<case_id>/{case.yaml, bug.patch}. Returns yaml path."""
    case_id = bug["case_id"]
    case_dir = CASES_DIR / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    yaml_path = case_dir / "case.yaml"
    yaml_path.write_text(render_case_yaml(bug), encoding="utf-8")

    patch = bug.get("patch_diff") or ""
    if patch:
        (case_dir / "bug.patch").write_text(patch, encoding="utf-8")

    return yaml_path
