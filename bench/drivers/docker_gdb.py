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
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from bench.common import (
    DATA_DIR,
    REPO_DIR,
    DockerCase,
    RunSpec,
    finalize_result,
)

# Re-use the libtool resolution logic from the pipeline scripts.
# Imported as a standalone function so we don't pull in the full
# scripts/ package (which has its own relative imports).
WORKSPACES_DIR = DATA_DIR / "workspaces"


def _workspace_dir(project: str, bug_index: int) -> Path:
    """Expected checkout path for a BugsCPP workspace."""
    return WORKSPACES_DIR / f"{project}-{bug_index}" / project / f"buggy-{bug_index}"


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

exec gdb -nx -batch-silent -x /tmp/session.cmds --args "$EXE" "$@"
"""


def _build_gdb_session(question: str, tool_config_name: str) -> str:
    """Build the GDB commands that load ChatDBG and ask the question."""
    lines = [
        "set pagination off",
        "set confirm off",
        "source chatdbg.chatdbg_gdb",
        "run",
        f"why {question}",
    ]
    return "\n".join(lines)


def _parse_trigger(trigger_command: str) -> list[str]:
    """Parse a BugsCPP trigger command into argv.

    Trigger commands come in two forms:
      - Plain: tools/gif2tiff input.tif /dev/null
      - Wrapped: bash -c "tools/gif2tiff input.tif /dev/null"
      - Wrapped with exit check: bash -c "cmd ; [ $? -eq 1 ]"

    For the wrapped forms, we unwrap to get the inner command and
    split it, dropping any trailing exit-code checks."""
    trigger = trigger_command.strip()

    # Unwrap bash -c "..."
    if trigger.startswith("bash -c "):
        # Extract the quoted inner command
        inner = trigger[len("bash -c "):]
        # Strip outer quotes
        if (inner.startswith('"') and inner.endswith('"')) or \
           (inner.startswith("'") and inner.endswith("'")):
            inner = inner[1:-1]
        # Drop trailing exit-code checks like "; [ $? -eq 1 ]"
        for sep in [" ; [", " ;[", " && ["]:
            idx = inner.find(sep)
            if idx != -1:
                inner = inner[:idx]
        return shlex.split(inner.strip())

    return shlex.split(trigger)


class DockerDriver:
    """Run ChatDBG inside a BugsCPP Docker container at any tier."""

    def __init__(self, tier: int = 3, dry_run: bool = False):
        self.tier = tier
        self.dry_run = dry_run

    def run(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        run_dir.mkdir(parents=True, exist_ok=True)
        case: DockerCase = spec.case  # type: ignore[assignment]

        # Check workspace exists
        workdir = _workspace_dir(case.project, case.bug_index)
        if not workdir.exists():
            return finalize_result(
                run_dir, spec,
                status="workspace_missing",
                exit_code=-1, elapsed_s=0.0,
            )

        # Ensure gdb-enabled Docker image exists.
        # Uses Anika's ensure_gdb_image.py (scripts/) which builds from
        # docker/gdb-base.Dockerfile with the per-project base image.
        scripts_dir = str(REPO_DIR / "scripts")
        import sys
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from ensure_gdb_image import ensure
        try:
            if not ensure(case.project):
                (run_dir / "docker_build.log").write_text(
                    f"ensure_gdb_image failed for {case.project}\n"
                )
                return finalize_result(
                    run_dir, spec,
                    status="docker_build_failed",
                    exit_code=-1, elapsed_s=0.0,
                )
        except Exception as e:
            (run_dir / "docker_build.log").write_text(str(e))
            return finalize_result(
                run_dir, spec,
                status="docker_build_failed",
                exit_code=-1, elapsed_s=0.0,
            )
        from utils import gdb_image_for
        image_tag = gdb_image_for(case.project)

        if self.dry_run:
            return finalize_result(
                run_dir, spec,
                status="dry_run", exit_code=0, elapsed_s=0.0,
            )

        # Parse trigger command into argv
        trigger_argv = _parse_trigger(case.trigger_command)
        if not trigger_argv:
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

        # Build GDB session commands
        gdb_session = _build_gdb_session(spec.question, spec.tool_config_path.stem)
        script = CONTAINER_SCRIPT.replace("__GDB_SESSION_COMMANDS__", gdb_session)

        # Build environment pass-through
        env_flags: list[str] = []
        for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_BASE"):
            val = os.environ.get(key)
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
            "-e", "PYTHONPATH=/chatdbg-src",
            *env_flags,
            # Image
            image_tag,
            # Entrypoint: bash runs the script, remaining args are trigger argv
            "bash", "-c", script, "bash",
        ] + trigger_argv

        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            status = "ok" if collect_path.exists() else "no_collect"
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as e:
            (run_dir / "stdout.log").write_text(e.stdout or "")
            (run_dir / "stderr.log").write_text(e.stderr or "")
            elapsed = time.time() - start
            return finalize_result(
                run_dir, spec,
                status="timeout", exit_code=-1, elapsed_s=elapsed,
            )

        elapsed = time.time() - start
        (run_dir / "stdout.log").write_text(proc.stdout or "")
        (run_dir / "stderr.log").write_text(proc.stderr or "")
        return finalize_result(
            run_dir, spec,
            status=status, exit_code=exit_code, elapsed_s=elapsed,
        )
