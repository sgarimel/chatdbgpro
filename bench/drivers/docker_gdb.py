"""Docker driver: run ChatDBG inside a BugsCPP Docker container.

Works for any tier — the tier determines the tool config, not the
execution environment. The container provides gdb + the pre-built
buggy workspace; ChatDBG source is bind-mounted from the host.

Requires:
  - Docker daemon running
  - BugsCPP workspaces checked out under data/workspaces/
    (or set up via `bugscpp checkout`)
  - OPENROUTER_API_KEY (or OPENAI_API_KEY) in the host environment
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from bench.common import (
    REPO_DIR,
    DockerCase,
    RunSpec,
    build_oracle_strings,
    finalize_result,
    write_docker_case_yaml,
)


# Bash snippet executed inside the container. It:
#  1. Sets LD_LIBRARY_PATH so libtool-built .libs/ binaries find their .so's
#  2. Resolves libtool wrapper scripts to real ELFs
#  3. Writes a GDB session script that loads ChatDBG and asks "why"
#  4. Runs gdb
#
# Arguments after "bash" are the trigger command's argv (binary + args).
# The GDB_SESSION_COMMANDS placeholder is replaced by the driver before launch.
CONTAINER_SCRIPT = r"""
set -e

# LD_LIBRARY_PATH for libtool projects
export LD_LIBRARY_PATH="$(find /work -type d -name .libs -printf '%p:' 2>/dev/null)${LD_LIBRARY_PATH:-}"

# Resolve libtool wrappers
EXE="$1"; shift
if [ -f "$EXE" ] && head -c 4096 "$EXE" 2>/dev/null | grep -q libtool; then
  DIR="$(dirname "$EXE")"
  BASE="$(basename "$EXE")"
  ALT="${DIR:+$DIR/}.libs/$BASE"
  [ -f "$ALT" ] && EXE="$ALT"
fi

# Write GDB session commands (injected by the driver)
cat > /tmp/session.cmds << 'GDBEOF'
__GDB_SESSION_COMMANDS__
GDBEOF

exec gdb -nx -batch -x /tmp/session.cmds --args "$EXE" "$@"
"""


# Project-specific assertion / error-emission functions. When the project's
# error path doesn't go through libc abort()/__assert_fail (e.g. a custom
# interpreter that prints its own message and unwinds via setjmp before
# main returns to libc), the libc-only breakpoint family fires too late —
# every application frame is already gone. Breaking inside the project's
# own assertion function instead lets gdb stop with the full call stack
# intact. Discover entries by grepping the project's source for the
# literal failure-message string the bench's failing test produces.
PROJECT_ASSERT_BREAKS: dict[str, list[str]] = {
    "berry": ["be_raise"],
}


def _build_gdb_session(
    question: str,
    tool_config_name: str,
    *,
    buggy_binary_path: str | None = None,
    project: str | None = None,
    breakpoint_spec: str | None = None,
    structural_followup: str | None = None,
) -> str:
    """Build the GDB commands that load ChatDBG and ask the question.

    The breakpoints on abort / __assert_fail / exit / _exit ensure ChatDBG
    has a stack frame to inspect even for non-crashing bugs (assertion
    failures, clean exits, logical-error bugs). Most of the bugscpp corpus
    is non-crashing — without these breakpoints `why` would bail in
    `check_debugger_state` because gdb has no selected frame after the
    inferior exits.

    `set breakpoint pending on` lets us register the libc-resolved
    breakpoints before the program loads, so they bind once libc is in.

    When `buggy_binary_path` is supplied (e.g. "src/berry"), we additionally
    set `follow-exec-mode new` and `catch exec /work/<path>` so gdb stops
    when the deepest user binary in the trigger chain exec()s. We then
    `continue` past the catchpoint so the existing abort/assert/exit
    breakpoints can still fire inside that binary.

    `project` enables a per-project layer of application-level breakpoints
    (see PROJECT_ASSERT_BREAKS) that fire while the project's call stack
    is still intact, before the libc exit path unwinds it.

    S5(b): when `breakpoint_spec` is provided (formatted as
    "<file>:<line>"), set a breakpoint there before `run` so the
    debugger stops at the patch site instead of running to clean
    exit. This handles BugsC++ wrong-output bugs that don't crash —
    without it the lldb session shows only exit/__libc_start_main
    and the model has no defect frame to inspect.

    B3: when `structural_followup` is provided, issue a second `why`
    after the first one. ChatDBG records both as queries[] in
    collect.json so the judge can score the second answer separately.
    """
    lines = [
        "set pagination off",
        "set confirm off",
        # Required so gdb follows into the real binary when trigger_argv is
        # ["bash", "-c", ...] (the majority of bugscpp triggers).
        "set follow-fork-mode child",
        "set detach-on-fork on",
        # Allow breakpoints on libc symbols not yet resolved at startup.
        "set breakpoint pending on",
    ]
    if buggy_binary_path:
        # `set follow-exec-mode new` makes each exec() spawn a fresh inferior
        # with its own symbol table — so when the deep buggy binary loads,
        # gdb's selected inferior switches to it and the existing
        # break-exit/abort/assert breakpoints fire inside *that* binary
        # (with proper symbols) instead of the outer wrapper. `catch exec`
        # logs every exec for debugging; `commands ... continue` makes the
        # catchpoint silent (auto-resume). gdb 14 doesn't accept a path
        # argument to `catch exec`, so we let it fire on every exec rather
        # than filter — the auto-continue keeps it cheap.
        lines += [
            "set follow-exec-mode new",
            "catch exec",
            "commands",
            "continue",
            "end",
        ]
    # Project-specific application-level breakpoints first — they fire
    # earliest on the failure path and leave the application call stack
    # fully on the stack when gdb stops, which is what the model needs to
    # navigate. The libc fallbacks below stay registered as a safety net
    # in case the per-project entry doesn't fire (different bug type,
    # different code path, etc.).
    for fn in PROJECT_ASSERT_BREAKS.get(project or "", []):
        lines.append(f"break {fn}")
    lines += [
        # Stop on any failure-or-exit path so ChatDBG always has a frame.
        "break abort",
        "break __assert_fail",
        "break exit",
        "break _exit",
        "source /chatdbg-src/chatdbg/chatdbg_gdb.py",
    ]
    if breakpoint_spec:
        # `break <file>:<line>` then `run` will stop at the breakpoint
        # if the program reaches it; if the program crashes earlier,
        # the crash takes precedence (gdb stops on signal). Either way
        # ChatDBG sees a non-trivial state.
        lines.append(f"break {breakpoint_spec}")
    lines.append("run")
    lines.append(f"why {question}")
    if structural_followup:
        lines.append(f"why {structural_followup}")
    return "\n".join(lines)


def _docker_env() -> dict:
    """Inherit environment, but disable Git Bash / MSYS path munging so
    `-v /host:/container` bind-mounts aren't rewritten on Windows."""
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    env.setdefault("MSYS2_ARG_CONV_EXCL", "*")
    return env


class DockerDriver:
    """Run ChatDBG inside a BugsCPP Docker container at any tier."""

    def __init__(self, tier: int = 3, dry_run: bool = False):
        self.tier = tier
        self.dry_run = dry_run

    def run(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        run_dir.mkdir(parents=True, exist_ok=True)
        case: DockerCase = spec.case  # type: ignore[assignment]

        # Check workspace exists. pipeline2 stores the canonical absolute path
        # in corpus.db because workspaces can live outside bench/.
        workdir = case.workspace_path
        if not workdir.exists():
            return finalize_result(
                run_dir, spec,
                status="workspace_missing",
                exit_code=-1, elapsed_s=0.0,
            )

        # Ensure gdb-enabled Docker image exists.
        try:
            from pipeline2.ensure_image import ensure_gdb_image
            image_tag = ensure_gdb_image(case.project)
        except Exception as e:
            (run_dir / "docker_build.log").write_text(str(e))
            return finalize_result(
                run_dir, spec,
                status="docker_build_failed",
                exit_code=-1, elapsed_s=0.0,
            )
        if image_tag != case.gdb_image:
            (run_dir / "docker_build.log").write_text(
                f"DB image {case.gdb_image!r} differs from local tag {image_tag!r}\n"
            )
            image_tag = case.gdb_image

        if self.dry_run:
            return finalize_result(
                run_dir, spec,
                status="dry_run", exit_code=0, elapsed_s=0.0,
            )

        # Pick what gdb will actually run. Two regimes:
        #   1. We have buggy_binary_argv from the strace probe — run the
        #      buggy binary DIRECTLY with the captured test argv. This
        #      reproduces the failing test condition under gdb (no shell
        #      wrapper, no fork chain to fight).
        #   2. We don't (probe failed for this bug) — fall back to invoking
        #      the original trigger_argv, which means gdb attaches to the
        #      bash/make/ctest launcher and the model sees a degraded
        #      session. Same behavior as before solution 1.
        if case.buggy_binary_argv and case.buggy_binary_path:
            # argv[0] is the program-as-named (e.g. "./berry"); replace it
            # with the resolved /work/<path> so gdb can find the binary
            # regardless of cwd nuances. argv[1:] is the test arguments
            # exactly as captured by strace.
            run_argv = [f"/work/{case.buggy_binary_path}"] + list(case.buggy_binary_argv[1:])
        else:
            run_argv = case.trigger_argv

        if not run_argv:
            (run_dir / "error.log").write_text(
                f"Empty trigger command for {case.bug_id}\n"
            )
            return finalize_result(
                run_dir, spec,
                status="no_trigger",
                exit_code=-1, elapsed_s=0.0,
            )

        # Copy tool config into run_dir so it's accessible inside container
        shutil.copy(spec.tool_config_path, run_dir / "tool_config.json")

        # S5(b): for cases without a populated crash_signal, set a
        # breakpoint at patch_first_file:patch_first_line so the model
        # gets a defect-site frame to inspect instead of seeing the
        # program run to a clean exit. We also set the breakpoint when
        # the user explicitly opts in via --breakpoint-at-patch even
        # for crashing cases (covers cases where the crash is far from
        # the actual defect).
        bp_spec = None
        if spec.breakpoint_at_patch and case.patch_first_file and case.patch_first_line:
            bp_spec = f"{case.patch_first_file}:{case.patch_first_line}"

        STRUCTURAL_Q = ("Now propose a structural change that prevents this entire "
                        "class of bug — not just a patch at this line. Think about "
                        "API design, types, or invariants that would make the bug "
                        "inexpressible.")
        followup = STRUCTURAL_Q if spec.structural_fix_turn else None

        # Build GDB session commands. When the corpus knows the real buggy
        # binary path (populated by pipeline2/reprobe_buggy_binary.py), we
        # inject a `catch exec` so gdb stops when that binary loads. The
        # `project` arg enables PROJECT_ASSERT_BREAKS for projects whose
        # error path needs an application-level breakpoint (see berry).
        gdb_session = _build_gdb_session(
            spec.question,
            spec.tool_config_path.stem,
            buggy_binary_path=case.buggy_binary_path,
            project=case.project,
            breakpoint_spec=bp_spec,
            structural_followup=followup,
        )
        script = CONTAINER_SCRIPT.replace("__GDB_SESSION_COMMANDS__", gdb_session)

        # Build environment pass-through. CHATDBG_PROMPT_* vars override what
        # ChatDBG shows the LLM in the initial prompt (real binary path,
        # behavioral oracle, project context). Per-case oracle strings come
        # from build_oracle_strings(); the OPENROUTER/OPENAI keys come from
        # the host shell. Per-case values override host-shell defaults so a
        # researcher can still set CHATDBG_PROMPT_* by hand for debugging.
        oracle = build_oracle_strings(case)
        env_flags: list[str] = []
        for key in (
            "OPENROUTER_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_BASE",
        ):
            val = os.environ.get(key)
            if val:
                env_flags += ["-e", f"{key}={val}"]
        for key in ("CHATDBG_PROMPT_BINARY", "CHATDBG_PROMPT_ERROR", "CHATDBG_PROMPT_EXTRA"):
            val = oracle.get(key) or os.environ.get(key)
            if val:
                env_flags += ["-e", f"{key}={val}"]

        collect_path = run_dir / "collect.json"

        cmd = [
            "docker", "run", "--rm",
            "--platform", "linux/amd64",
            # Bind-mount workspace
            "-v", f"{workdir.resolve()}:/work",
            # Bind-mount ChatDBG source
            "-v", f"{REPO_DIR / 'src'}:/chatdbg-src:ro",
            # Bind-mount results dir for collect.json output
            "-v", f"{run_dir.resolve()}:/results",
            # Working directory
            "-w", "/work",
            # ChatDBG env vars
            "-e", f"CHATDBG_MODEL={spec.model}",
            "-e", "CHATDBG_TOOL_CONFIG=/results/tool_config.json",
            "-e", f"CHATDBG_COLLECT_DATA=/results/collect.json",
            "-e", f"CHATDBG_CONTEXT={spec.context_lines}",
            "-e", "CHATDBG_FORMAT=text",
            "-e", "CHATDBG_LOG=/results/chatdbg.log.yaml",
            # PYTHONPATH must include both the bind-mounted ChatDBG source
            # and the venv where gdb-base.Dockerfile installed ChatDBG's
            # runtime deps (litellm, openai, llm_utils, ...). The venv path
            # is fixed by the Dockerfile.
            "-e", "PYTHONPATH=/chatdbg-src:/opt/chatdbg-venv/lib/python3.11/site-packages",
            *env_flags,
            # Image
            image_tag,
            # Entrypoint: bash runs the script, remaining args are trigger argv
            "bash", "-c", script, "bash",
        ] + run_argv

        start = time.time()
        try:
            # encoding='utf-8' errors='replace' is required: on Windows the
            # default decoder is cp1252, and bugscpp triggers occasionally
            # emit non-ASCII bytes (TIFF dumps, test fixtures). cp1252 hits
            # UnicodeDecodeError in the reader thread → subprocess.communicate
            # hangs → the whole orchestrator stalls.
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                env=_docker_env(),
                encoding="utf-8",
                errors="replace",
            )
            status = "ok" if collect_path.exists() else "no_collect"
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as e:
            (run_dir / "stdout.log").write_text(e.stdout or "", encoding="utf-8")
            (run_dir / "stderr.log").write_text(e.stderr or "", encoding="utf-8")
            elapsed = time.time() - start
            # Always emit case.yaml + sliced source — the judge needs them
            # even when the run timed out, so partial responses (collect.json
            # already on disk if ChatDBG flushed any progress) can still be
            # scored. Without this, timeouts get silently dropped from
            # judging, hiding "model was working but didn't converge" cases.
            write_docker_case_yaml(case, run_dir)
            return finalize_result(
                run_dir, spec,
                status="timeout", exit_code=-1, elapsed_s=elapsed,
            )

        elapsed = time.time() - start
        (run_dir / "stdout.log").write_text(proc.stdout or "", encoding="utf-8")
        (run_dir / "stderr.log").write_text(proc.stderr or "", encoding="utf-8")

        # Write case.yaml + sliced source for the judge pipeline
        write_docker_case_yaml(case, run_dir)

        return finalize_result(
            run_dir, spec,
            status=status, exit_code=exit_code, elapsed_s=elapsed,
        )
