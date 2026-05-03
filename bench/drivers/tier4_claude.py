"""Tier-4 driver: Claude Code (the CLI) as the agent.

The agent under test is the production `claude` CLI itself —
Anthropic's Claude Code product, which packages a tool registry
(Bash, Read, Edit, etc.), agent loop, and conversation management
into a single binary. Tier 4 lets us answer:

  "How does a frontier integrated agent product compare to
  mini-swe-agent (Tier 1, bash-only) and mini + persistent gdb
  (Tier 2) on this debugging benchmark?"

Architecture
------------
    Orchestrator (.venv-bench-39, host=macOS)
     └── Tier4Driver.run()
          ├── compile_case() / prepare_injected_workspace()  (same as Tier 3)
          └── subprocess: claude -p <task>                   (Claude Code CLI)
                 --output-format stream-json
                 [--bare]                        (optional clean baseline mode;
                                                  see "Bare mode" below)
                 --no-session-persistence        (don't pollute ~/.claude state)
                 --dangerously-skip-permissions  (sandbox is the run_dir)
                 --max-budget-usd <cost_limit>
                 --model <alias-or-full-name>
                 --add-dir <run_dir>             (allow tool access here)
              └── stdout: line-delimited JSON events (system/assistant/user/result)
                  Driver parses → claude_events.jsonl + collect.json (judge schema)

Auth — three working paths
--------------------------
Claude Code accepts auth from any of these sources (checked in
order):

  1. `ANTHROPIC_API_KEY`        — direct API key (pay-per-use billing)
  2. `ANTHROPIC_AUTH_TOKEN`     — alternative auth token
  3. `CLAUDE_CODE_OAUTH_TOKEN`  — long-lived OAuth token from
                                  `claude setup-token` (uses your
                                  Claude.ai subscription quota,
                                  e.g. Pro / Max)
  4. Keychain OAuth login       — `claude /login` interactive session
                                  (only honored when --bare is OFF)

For Pro / Max subscription users (#3 or #4), Tier 4 sweeps don't
incur additional API charges — they spend against the existing
subscription quota. For API-key users (#1, #2), each sweep bills the
key directly with the `--max-budget-usd` cap as a hard limit per run.

Bare mode
---------
By default the driver runs `claude --bare` for reproducibility:
- skip CLAUDE.md auto-discovery (no leaked project context)
- skip hooks (no surprise behaviors)
- skip plugins (consistent tool surface)
- skip auto-memory (no leaked previous-run state)
- strict env-var auth (#1, #2, #3 only; keychain ignored)

Trade-off: `--bare` blocks the keychain auth path (#4). If a
researcher only has a keychain OAuth session (no env var), the
driver auto-falls-back to NON-bare mode so the run can proceed.

Override via `--tier4-bare {auto,always,never}`:
  auto    (default) — bare if any env-var auth exists, else fall
                       back to keychain (non-bare)
  always  — fail with `missing_dep` if no env-var auth set
  never   — always disable bare, use whatever auth Claude finds

Output schema
-------------
Mirrors Tier 1 / Tier 2 / Tier 3 — judge consumes Tier-4
collect.json without per-tier branching:

    case.yaml         pinned (judge input)
    program.c         source (synthetic only)
    build/            compiled binary
    compile.log       compiler output
    task.md           prompt sent to Claude
    session.cmds      claude argv for hand-rerun
    claude_events.jsonl  raw stream-json events from Claude Code
    collect.json      our standardized schema
    stdout.log        full Claude Code stdout
    stderr.log        full Claude Code stderr
    result.json       run-level metadata
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from bench.common import (
    Case,
    DockerCase,
    REPO_DIR,
    RunSpec,
    compile_case,
    finalize_result,
    prepare_injected_workspace,
    write_docker_case_yaml,
)
from bench.drivers.container_session import ContainerSession, resolve_runtime
from bench.drivers.tier3_gdb import _run_debugger


# Default Claude Code CLI on PATH. If a researcher has multiple
# installs they can override via $CLAUDE_BIN.
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")


# Task prompt — same shape as the Tier-1 / Tier-2 prompts. Claude
# Code's own system prompt handles the "use bash to investigate"
# framing, so we just describe the bug-hunt task and require the
# structured ROOT CAUSE / LOCAL FIX / GLOBAL FIX final answer.
SYNTHETIC_TASK_TEMPLATE = """\
You're debugging a C/C++ bug. The buggy binary is at `./build/prog` \
and the source file is `{source_file}` in the current directory.

Run command: `{cmd}`

Expected behavior: {behavior}.

Use your bash tool to investigate (run the binary, run gdb / lldb in \
batch mode, read source). Identify the root cause and propose both a \
local fix and a structural global fix.

When done, your final response MUST include three labelled paragraphs:

  ROOT CAUSE: <file:line and what is wrong, in your own words>
  LOCAL FIX:  <minimal code change that resolves the symptom>
  GLOBAL FIX: <structural change preventing this CLASS of bug>

Do NOT modify the source file. Just investigate and produce the \
diagnosis as your final assistant message.
"""


BUGSCPP_TASK_TEMPLATE = """\
You're debugging a real-codebase bug in `{case_id}` (project `{project}`, \
an open-source C/C++ project from the BugsC++ corpus).

The buggy source tree is on the host at `{workspace_host}` and is also \
mounted at `/work` inside a Linux/amd64 container named \
`{container_name}` (gdb, the buggy binary, and all build deps live in \
that container; the binary is NOT runnable on this host directly).

Buggy binary inside the container: `/work/{buggy_binary}`
Failing test invocation:           `{trigger_argv}`
Observed behavior:                  `{bug_observed}`

How to investigate
------------------
* To READ source code, use Read / Grep / your normal tools — the source \
tree is at `{workspace_host}` (it's been added via `--add-dir`).
* To RUN the binary, run gdb, or execute anything else inside the build \
environment, use Bash with this template:

      {exec_template}

  e.g.
      {exec_example_ls}
      {exec_example_gdb}

  The container is dedicated to this case; it'll be torn down when this \
session ends, so don't worry about cleanup.

Final answer
------------
Identify the root cause in the source, propose both a local fix and a \
structural global fix.

Your final response MUST include three labelled paragraphs:

  ROOT CAUSE: <file:line and what is wrong>
  LOCAL FIX:  <minimal code change>
  GLOBAL FIX: <structural change preventing this CLASS of bug>

Do NOT modify the source files on disk. Just investigate and produce the \
diagnosis as your final assistant message.
"""


INJECTED_TASK_TEMPLATE = """\
You're debugging a real-codebase bug in `{case_id}` (an open-source \
C/C++ project). You're at the project root with the source tree \
cloned and patched.

The buggy binary is at `./{binary_rel}`.{stdin_note}

{description}

Use your bash tool to investigate. Identify the root cause and \
propose both a local fix and a structural global fix.

When done, your final response MUST include three labelled paragraphs:

  ROOT CAUSE: <file:line and what is wrong>
  LOCAL FIX:  <minimal code change>
  GLOBAL FIX: <structural change preventing this CLASS of bug>

Do NOT modify the source file. Just investigate and produce the \
diagnosis as your final assistant message.
"""


def _resolve_model(model_str: str) -> str:
    """Map an orchestrator-style model spec to a Claude Code `--model`
    argument. We accept three shapes:

      claude-sonnet-4-6    — full Claude model name → pass through
      sonnet|opus|haiku    — Claude alias → pass through
      claude/sonnet        — namespaced spec (clarifies tier intent
                             when the orchestrator sweeps mixed
                             tiers) → strip the prefix
      anthropic/claude-..  — LiteLLM/OpenRouter style → strip prefix

    Anything else is passed through as-is and Claude Code will reject
    it with a clear error if invalid."""
    if "/" in model_str:
        return model_str.split("/")[-1]
    return model_str


def _extract_response_and_tools(events: list[dict]) -> tuple[str, list[dict], dict]:
    """Walk stream-json events to build:
      response  — the model's final-answer text (last `result` event's
                  `result` field; falls back to concatenated assistant
                  text if no result event)
      tool_calls — list shaped like Tier 1/2/3's collect.json schema
      stats     — dict with prompt/completion tokens, cost, num_turns,
                  exit status

    Claude Code's stream-json events fall into 4 types:
      system    initial config dump
      assistant model turn (may contain text + tool_use blocks)
      user      tool_result blocks (response back to the model)
      result    one final summary event
    """
    final_text_parts: list[str] = []
    tool_calls: list[dict] = []
    stats = {
        "completed": False,
        "model": None,
        "cost": 0.0,
        "tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "num_turns": 0,
        "exit_status": "unknown",
    }
    # tool_use_id → action shape, so we can pair tool_use with the
    # following tool_result and capture the result_length.
    pending_tool_uses: dict[str, dict] = {}

    for ev in events:
        et = ev.get("type")
        if et == "system" and ev.get("subtype") == "init":
            stats["model"] = ev.get("model")
        elif et == "assistant":
            msg = ev.get("message") or {}
            for block in (msg.get("content") or []):
                btype = block.get("type")
                if btype == "text":
                    txt = block.get("text") or ""
                    if txt.strip():
                        final_text_parts.append(txt)
                elif btype == "tool_use":
                    name = block.get("name") or "?"
                    inp = block.get("input") or {}
                    # Try a few common keys to find the command/text
                    call = (inp.get("command") or inp.get("file_path")
                            or inp.get("path") or json.dumps(inp))
                    verb = (call.strip().split() or [name])[0].split("/")[-1] or name
                    tu_id = block.get("id") or ""
                    rec = {
                        "tool_name": name,
                        "verb": verb,
                        "call": call,
                        "result_length": 0,
                    }
                    pending_tool_uses[tu_id] = rec
                    tool_calls.append(rec)
            usage = msg.get("usage") or {}
            stats["prompt_tokens"] += int(usage.get("input_tokens", 0) or 0)
            stats["completion_tokens"] += int(usage.get("output_tokens", 0) or 0)
        elif et == "user":
            msg = ev.get("message") or {}
            for block in (msg.get("content") or []):
                if block.get("type") == "tool_result":
                    tu_id = block.get("tool_use_id") or ""
                    if tu_id in pending_tool_uses:
                        # The tool_result block's content is either a
                        # string or a list of {type:text,text:str}.
                        c = block.get("content")
                        if isinstance(c, str):
                            length = len(c)
                        elif isinstance(c, list):
                            length = sum(len(p.get("text") or "")
                                         for p in c if isinstance(p, dict))
                        else:
                            length = 0
                        pending_tool_uses[tu_id]["result_length"] = length
        elif et == "result":
            stats["num_turns"] = ev.get("num_turns", 0) or 0
            stats["cost"] = float(ev.get("total_cost_usd", 0.0) or 0.0)
            stats["completed"] = ev.get("subtype") == "success" and not ev.get("is_error")
            stats["exit_status"] = ("Submitted" if stats["completed"]
                                    else (ev.get("subtype") or "failed"))
            # Use the final result text as our response when present —
            # it's typically the model's last assistant turn.
            r = ev.get("result")
            if isinstance(r, str) and r.strip():
                final_text_parts = [r]  # prefer the result-event text
            usage = ev.get("usage") or {}
            # Result-event usage is the cumulative total; prefer it
            # over the per-message sums above when available.
            cum_in = int(usage.get("input_tokens", 0) or 0)
            cum_out = int(usage.get("output_tokens", 0) or 0)
            if cum_in or cum_out:
                stats["prompt_tokens"] = cum_in
                stats["completion_tokens"] = cum_out

    stats["tokens"] = stats["prompt_tokens"] + stats["completion_tokens"]
    response = "\n\n---\n\n".join(final_text_parts)
    return response, tool_calls, stats


def _build_synthetic_task(case: Case) -> str:
    args = case.meta.get("run", {}).get("args", []) or []
    args_str = " ".join(str(a) for a in args)
    expected_crash = case.meta.get("run", {}).get("expected_crash", True)
    behavior = (
        "crashes when run (likely a sanitizer report or signal)"
        if expected_crash else
        "runs to completion but the test oracle considers the output incorrect"
    )
    cmd = f"./build/prog {args_str}".rstrip()
    return SYNTHETIC_TASK_TEMPLATE.format(
        source_file=case.meta.get("source_file", "(none)"),
        cmd=cmd, behavior=behavior,
    )


def _build_injected_task(case: Case, workdir: Path, binary: Path,
                         *, stdin_file: Path | None = None) -> str:
    rel = binary.relative_to(workdir)
    stdin_note = ""
    if stdin_file is not None:
        stdin_note = (
            f"\n\nThe failing-input bytes are at `{stdin_file}`. "
            f"To reproduce: `cat {stdin_file} | ./{rel}`."
        )
    return INJECTED_TASK_TEMPLATE.format(
        case_id=case.case_id,
        binary_rel=rel,
        stdin_note=stdin_note,
        description=case.meta.get("description", "").strip(),
    )


# Auth env-var precedence — checked in order. Mirrors the order
# Claude Code itself uses internally (verified against the binary's
# embedded strings list).
AUTH_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
)


def _present_auth_env() -> str | None:
    """Return the name of the first auth env var that is set + non-empty,
    or None. Used to decide whether `--bare` mode is viable (it requires
    one of these) vs falling back to the keychain path."""
    for name in AUTH_ENV_VARS:
        if os.environ.get(name):
            return name
    return None


def _has_keychain_login() -> bool:
    """Probe `claude auth status` for an active keychain session.
    Returns False if claude isn't installed (caller surfaces that
    separately) or if the user isn't logged in."""
    try:
        out = subprocess.run(
            [CLAUDE_BIN, "auth", "status"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return False
        # `claude auth status` returns JSON; loggedIn=true means we
        # have a usable keychain session.
        try:
            data = json.loads(out.stdout or "{}")
        except json.JSONDecodeError:
            return False
        return bool(data.get("loggedIn"))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class Tier4Driver:
    """Same interface as Tier1Driver / Tier2Driver / Tier3Driver."""

    tier: int = 4

    def __init__(
        self,
        *,
        dry_run: bool = False,
        cost_limit: float = 0.5,
        bare: str = "auto",
        docker: bool = False,
        runtime: str | None = None,
    ):
        self.dry_run = dry_run
        self.cost_limit = cost_limit
        # bare ∈ {"auto", "always", "never"}
        self.bare = bare
        # docker=True wires the BugsCPP path. Claude itself runs on the
        # host (it's a Node CLI, not packaged for our amd64 Linux
        # containers); the driver opens a per-case ContainerSession and
        # bakes the container name into the task prompt so Claude's
        # Bash tool can `<runtime> exec` for any in-container execution.
        self.docker = docker
        # Container runtime: docker | apptainer | None=auto-resolve.
        self.runtime = runtime

    # ---- main entry ----------------------------------------------------

    def run(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        run_dir.mkdir(parents=True, exist_ok=True)
        # DockerCase has no case_dir; case.yaml synthesized at finalize
        # time by write_docker_case_yaml() inside _run_bugscpp.
        if spec.case.kind != "docker_bugscpp":
            shutil.copy(spec.case.case_dir / "case.yaml", run_dir / "case.yaml")

        if not spec.case.platform_supported():
            (run_dir / "skip.log").write_text(
                f"platform={spec.case.platforms}; host skipped\n"
            )
            return finalize_result(
                run_dir, spec,
                status="skipped_platform", exit_code=0, elapsed_s=0.0,
            )

        # Dry-run path skips the auth + CLI checks so researchers can
        # verify the dispatch / matrix without setting up credentials.
        if not self.dry_run:
            # Verify claude CLI is installed FIRST so the auth probe
            # (which calls `claude auth status`) doesn't error out
            # opaquely on machines without claude.
            try:
                ver = subprocess.run(
                    [CLAUDE_BIN, "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                if ver.returncode != 0:
                    raise RuntimeError(ver.stderr or "claude --version failed")
            except (FileNotFoundError, subprocess.TimeoutExpired, RuntimeError) as e:
                (run_dir / "error.log").write_text(
                    f"Claude Code CLI not found or not working: {e}\n\n"
                    f"Install:\n  npm install -g @anthropic-ai/claude-code\n"
                    f"Or set CLAUDE_BIN to the binary path."
                )
                return finalize_result(
                    run_dir, spec,
                    status="missing_dep", exit_code=-1, elapsed_s=0.0,
                )

            # Resolve which auth path is viable. Three options in
            # precedence order: env-var auth > keychain auth (if not
            # bare-only) > error.
            env_var = _present_auth_env()
            keychain = _has_keychain_login()
            if not env_var and not keychain:
                (run_dir / "error.log").write_text(
                    "Tier 4 requires Claude Code authentication. Three "
                    "options:\n\n"
                    "  1. ANTHROPIC_API_KEY=sk-ant-...      "
                    "(pay-per-use API key)\n"
                    "  2. ANTHROPIC_AUTH_TOKEN=...           "
                    "(alternative auth token)\n"
                    "  3. CLAUDE_CODE_OAUTH_TOKEN=...        "
                    "(long-lived OAuth — generate with `claude setup-token`,\n"
                    "                                          uses your Pro/Max\n"
                    "                                          subscription quota)\n"
                    "  4. `claude /login` (keychain session — only works\n"
                    "     when --tier4-bare={auto,never})\n"
                )
                return finalize_result(
                    run_dir, spec,
                    status="missing_dep", exit_code=-1, elapsed_s=0.0,
                )
            if self.bare == "always" and not env_var:
                (run_dir / "error.log").write_text(
                    "Tier 4 was invoked with --tier4-bare=always but no "
                    "Claude Code auth env var is set. --bare mode strictly "
                    "uses one of:\n"
                    f"  {', '.join(AUTH_ENV_VARS)}\n"
                    "Either set one of those, or pass "
                    "--tier4-bare=auto / --tier4-bare=never to allow the "
                    "keychain login path.\n"
                )
                return finalize_result(
                    run_dir, spec,
                    status="missing_dep", exit_code=-1, elapsed_s=0.0,
                )

        if spec.case.kind == "injected_repo":
            return self._run_injected(spec, run_dir, timeout=timeout)
        if spec.case.kind == "docker_bugscpp":
            return self._run_bugscpp(spec, run_dir, timeout=timeout)
        return self._run_synthetic(spec, run_dir, timeout=timeout)

    # ---- synthetic -----------------------------------------------------

    def _run_synthetic(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        shutil.copy(spec.case.source_path, run_dir / spec.case.source_path.name)
        build_dir = run_dir / "build"
        compile_result, binary = compile_case(spec.case, build_dir)
        (run_dir / "compile.log").write_text(
            "$ " + " ".join(compile_result.args) + "\n\n"
            + (compile_result.stdout or "") + "\n"
            + (compile_result.stderr or "")
        )
        if compile_result.returncode != 0:
            return finalize_result(
                run_dir, spec,
                status="compile_failed",
                exit_code=compile_result.returncode,
                elapsed_s=0.0,
            )
        if self.dry_run:
            return finalize_result(
                run_dir, spec, status="dry_run", exit_code=0, elapsed_s=0.0,
            )
        task = _build_synthetic_task(spec.case)
        (run_dir / "task.md").write_text(task)
        return self._invoke_claude(spec, run_dir, agent_cwd=run_dir,
                                    task=task, timeout=timeout)

    # ---- BugsCPP --------------------------------------------------------

    def _run_bugscpp(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        """T4 BugsCPP: Claude Code on the host with --add-dir on the
        workspace, plus a per-case Docker container for any execution
        the model wants to do. The task prompt teaches Claude the
        `docker exec <name> ...` template so its existing Bash tool
        suffices — no Claude-side modification."""
        case: DockerCase = spec.case  # type: ignore[assignment]
        if not case.workspace_path.exists():
            return finalize_result(
                run_dir, spec,
                status="workspace_missing", exit_code=-1, elapsed_s=0.0,
            )
        try:
            from pipeline2.ensure_image import ensure_gdb_image
            image_tag = ensure_gdb_image(case.project)
        except Exception as e:
            (run_dir / "docker_build.log").write_text(str(e))
            return finalize_result(
                run_dir, spec,
                status="docker_build_failed", exit_code=-1, elapsed_s=0.0,
            )

        if self.dry_run:
            return finalize_result(
                run_dir, spec,
                status="dry_run", exit_code=0, elapsed_s=0.0,
            )

        # Deterministic container name; baked into the task prompt so
        # Claude's `<runtime> exec` calls land here.
        import uuid as _uuid
        container_name = f"bench-t4-{_uuid.uuid4().hex[:20]}"

        runtime = resolve_runtime(self.runtime)

        trigger_str = (
            " ".join(case.buggy_binary_argv) if case.buggy_binary_argv
            else " ".join(case.trigger_argv) if case.trigger_argv
            else "(no trigger argv recorded)"
        )

        # ContainerSession copies workspace to a per-run scratch dir so
        # mutations (model-issued `make`, etc.) don't pollute the
        # canonical workspace. Claude reads source from the host
        # workspace (--add-dir below); execution is via the container.
        # Note: that means changes Claude makes IN the container don't
        # propagate to the host source it's reading. That's fine — we
        # explicitly tell Claude not to modify source files.
        session = ContainerSession(
            image=image_tag,
            workspace_src=case.workspace_path,
            run_dir=run_dir,
            runtime=runtime,
            platform="linux/amd64",
            ptrace=True,
            hermetic_workspace=True,
            name=container_name,
            env={
                **{k: os.environ[k] for k in (
                    "OPENROUTER_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_BASE",
                ) if k in os.environ},
            },
        )

        try:
            with session:
                # Build runtime-aware exec template so Claude's prompt
                # shows the right CLI for the host (docker on dev Macs,
                # apptainer on adroit/HPC). docker_exec_template gives
                # the abstract template; we also produce two concrete
                # examples so the model has a working pattern to copy.
                exec_template = session.docker_exec_template(cwd="/work")
                if runtime == "apptainer":
                    exec_example_ls = (
                        f"apptainer exec --pwd /work instance://{container_name} "
                        f"bash -c 'ls -la'"
                    )
                    exec_example_gdb = (
                        f"apptainer exec --pwd /work instance://{container_name} "
                        f"bash -c 'gdb -batch -ex run -ex bt --args {trigger_str}'"
                    )
                else:
                    exec_example_ls = (
                        f"docker exec -w /work {container_name} "
                        f"bash -c 'ls -la'"
                    )
                    exec_example_gdb = (
                        f"docker exec -w /work {container_name} "
                        f"bash -c 'gdb -batch -ex run -ex bt --args {trigger_str}'"
                    )
                task = BUGSCPP_TASK_TEMPLATE.format(
                    case_id=case.bug_id,
                    project=case.project,
                    workspace_host=str(case.workspace_path.resolve()),
                    container_name=container_name,
                    buggy_binary=case.buggy_binary_path or "(see /work for binary)",
                    trigger_argv=trigger_str,
                    bug_observed=case.bug_observed or "(unknown)",
                    exec_template=exec_template,
                    exec_example_ls=exec_example_ls,
                    exec_example_gdb=exec_example_gdb,
                )
                (run_dir / "task.md").write_text(task)
                write_docker_case_yaml(case, run_dir)
                # agent_cwd: a host directory Claude can navigate. Use
                # the canonical workspace (read-only enough — Claude
                # has --dangerously-skip-permissions for execution but
                # the task says not to modify source).
                return self._invoke_claude(
                    spec, run_dir,
                    agent_cwd=case.workspace_path,
                    task=task, timeout=timeout,
                    extra_dirs=[run_dir],
                )
        except RuntimeError as e:
            (run_dir / "docker_run.log").write_text(str(e))
            return finalize_result(
                run_dir, spec,
                status="docker_run_failed", exit_code=-1, elapsed_s=0.0,
            )

    # ---- injected_repo --------------------------------------------------

    def _run_injected(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        prep = prepare_injected_workspace(spec.case)
        (run_dir / "compile.log").write_text(prep.log)
        if prep.status != "ok" or prep.binary is None:
            return finalize_result(
                run_dir, spec,
                status=prep.status if prep.status != "ok" else "build_failed",
                exit_code=-1, elapsed_s=0.0,
            )
        if self.dry_run:
            return finalize_result(
                run_dir, spec, status="dry_run", exit_code=0, elapsed_s=0.0,
            )

        # debug.stdin_data → file the agent can `cat | ./prog`
        debug_cfg = spec.case.meta.get("debug", {}) or {}
        stdin_data = debug_cfg.get("stdin_data")
        stdin_file = None
        if stdin_data is not None:
            stdin_file = run_dir / "stdin.bin"
            stdin_file.write_bytes(
                stdin_data.encode() if isinstance(stdin_data, str) else stdin_data
            )

        task = _build_injected_task(spec.case, prep.workdir, prep.binary,
                                    stdin_file=stdin_file)
        (run_dir / "task.md").write_text(task)
        return self._invoke_claude(spec, run_dir, agent_cwd=prep.workdir,
                                    task=task, timeout=timeout,
                                    extra_dirs=[run_dir])

    # ---- shared Claude Code invocation --------------------------------

    def _invoke_claude(self, spec: RunSpec, run_dir: Path, *,
                       agent_cwd: Path, task: str, timeout: float,
                       extra_dirs: list[Path] | None = None) -> dict:
        model_arg = _resolve_model(spec.model)
        # Resolve --bare:
        #   "always" → always pass --bare (auth check guaranteed
        #               env-var present above)
        #   "never"  → never pass --bare (let claude use keychain or
        #               whatever it has)
        #   "auto"   → --bare iff an auth env var is set; otherwise
        #               drop --bare so keychain auth works
        env_var = _present_auth_env()
        if self.bare == "always":
            use_bare = True
        elif self.bare == "never":
            use_bare = False
        else:  # "auto"
            use_bare = env_var is not None
        auth_path = (
            f"env:{env_var}" if env_var else
            ("keychain" if not use_bare else "none")
        )

        argv = [
            CLAUDE_BIN, "-p", task,
            "--output-format", "stream-json",
        ]
        if use_bare:
            argv.append("--bare")
        argv += [
            "--no-session-persistence",
            "--dangerously-skip-permissions",
            "--verbose",
            "--max-budget-usd", str(self.cost_limit),
            "--model", model_arg,
            "--add-dir", str(agent_cwd.resolve()),
        ]
        for d in (extra_dirs or []):
            argv += ["--add-dir", str(d.resolve())]

        # session.cmds for hand-rerun. Document auth path so a
        # researcher reproducing the run knows which credential was used.
        (run_dir / "session.cmds").write_text(
            f"# Tier-4 (Claude Code) invocation. auth={auth_path}, "
            f"bare={'on' if use_bare else 'off'}.\n"
            f"# Auth options: ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN /\n"
            f"#               CLAUDE_CODE_OAUTH_TOKEN / `claude /login`.\n"
            + " ".join(shlex.quote(a) for a in argv) + "\n"
        )

        env = os.environ.copy()
        # Strip our PYTHONPATH so it can't shadow Node-side environment
        # if Claude Code shells out to anything Python.
        env.pop("PYTHONPATH", None)

        t0 = time.time()
        stdout, stderr, exit_code, timed_out = _run_debugger(
            argv,
            stdin_for_proc=None,
            env=env,
            run_dir=agent_cwd,
            timeout=timeout,
        )
        elapsed = time.time() - t0
        (run_dir / "stdout.log").write_text(stdout)
        (run_dir / "stderr.log").write_text(stderr)

        # Parse stream-json line-by-line. Even if claude crashed
        # mid-stream, partial events are useful for diagnosis.
        events: list[dict] = []
        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # claude occasionally prints non-JSON status text on
                # the same stream (e.g. "Shell cwd was reset to..."
                # at the tail). Skip these silently.
                continue
        (run_dir / "claude_events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + ("\n" if events else "")
        )

        if timed_out:
            return finalize_result(
                run_dir, spec,
                status="timeout", exit_code=-1, elapsed_s=elapsed,
            )

        response, tool_calls, stats = _extract_response_and_tools(events)

        # Build collect.json (judge-ready, schema-identical to T1/2/3).
        freq: dict[str, int] = {}
        by_tool: dict[str, dict[str, int]] = {}
        for tc in tool_calls:
            tname = tc.get("tool_name", "?")
            verb = tc.get("verb", tname)
            freq[verb] = freq.get(verb, 0) + 1
            by_tool.setdefault(tname, {})
            by_tool[tname][verb] = by_tool[tname].get(verb, 0) + 1
        tool_name_counts = {k: sum(v.values()) for k, v in by_tool.items()}

        collect = {
            "meta": {
                "uid": run_dir.name,
                "time": datetime.now().isoformat(timespec="seconds"),
                "model": spec.model,
                "tool_config": "tier4_claude_code.json",
                "enabled_tools": sorted(by_tool.keys()) if by_tool else ["Bash", "Read", "Edit"],
                "agent": "claude-code",
                "agent_version": _claude_version(),
                "tier": 4,
                "claude_resolved_model": stats.get("model"),
                "claude_cost_limit_usd": self.cost_limit,
                "claude_bare_mode": use_bare,
                "claude_auth_path": auth_path,
            },
            "instructions": "(Claude Code's built-in system prompt; see --bare mode docs)",
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
                    "tool_name_counts": tool_name_counts,
                    "tool_frequency_by_tool": by_tool,
                    "stats": {
                        "completed": stats["completed"],
                        "model": stats.get("model"),
                        "cost": stats["cost"],
                        "time": elapsed,
                        "tokens": stats["tokens"],
                        "prompt_tokens": stats["prompt_tokens"],
                        "completion_tokens": stats["completion_tokens"],
                        "exit_status": stats["exit_status"],
                        "submission": "",
                        "num_turns": stats["num_turns"],
                    },
                }
            ],
        }
        (run_dir / "collect.json").write_text(json.dumps(collect, indent=2))

        # status taxonomy aligned with the other tiers. The judge only
        # needs a non-empty response to score; a budget-exit ("error_max_
        # budget_usd") that still produced a complete diagnosis is "ok"
        # for grading purposes — distinguishing it from a true no_collect
        # (Claude crashed before any reasoning) avoids dropping
        # cost-limited cells from the pilot.
        if not events or not response.strip():
            status = "no_collect"
        elif exit_code != 0 and not stats["completed"] and not response.strip():
            status = "no_collect"
        else:
            status = "ok"
        return finalize_result(
            run_dir, spec,
            status=status, exit_code=exit_code, elapsed_s=elapsed,
        )


def _claude_version() -> str:
    try:
        out = subprocess.run([CLAUDE_BIN, "--version"],
                             capture_output=True, text=True, timeout=5)
        return (out.stdout or "").strip().split()[0] if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"
