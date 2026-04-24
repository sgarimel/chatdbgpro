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
    finalize_result,
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

exec gdb -nx -batch-silent -x /tmp/session.cmds --args "$EXE" "$@"
"""


def _build_gdb_session(question: str, tool_config_name: str) -> str:
    """Build the GDB commands that load ChatDBG and ask the question."""
    lines = [
        "set pagination off",
        "set confirm off",
        "source /chatdbg-src/chatdbg/chatdbg_gdb.py",
        "run",
        f"why {question}",
    ]
    return "\n".join(lines)


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

        trigger_argv = case.trigger_argv
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
