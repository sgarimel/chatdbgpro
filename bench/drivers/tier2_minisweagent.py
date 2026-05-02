"""Tier-2 driver: mini-swe-agent (bash + persistent gdb).

Tier 2 sits between Tier 1 (bash only — mini's canonical scaffold)
and Tier 3 (ChatDBG's curated multi-tool agent on top of gdb). The
agent under test is mini-swe-agent v2 with TWO tools registered:
`bash` (mini's stateless subprocess) and `gdb` (a stateful gdb
session preloaded with the buggy binary).

Tests the project's "what does adding a real debugger to a generic
bash agent buy?" sub-hypothesis. With Tier 1 vs Tier 2 we hold the
agent scaffold constant (mini) and vary the tool surface (bash vs
bash+gdb). With Tier 2 vs Tier 3 we hold the tool surface roughly
constant (both have a stateful gdb) and vary the scaffold (mini's
flat tool registry vs ChatDBG's curated interface).

Architecture:
  Orchestrator (.venv-bench-39, Py 3.9, Apple lldb pinned for Tier 3)
   └── Tier2Driver.run()
        ├── compile_case() / prepare_injected_workspace()  (same as Tier3)
        ├── write task.md, session.cmds (runner argv for hand-rerun)
        └── subprocess: .venv-bench/bin/python3 tier2_runner.py
                         (Py 3.14, mini-swe-agent installed)
                          └── DefaultAgent(DualToolModel, LocalGdbBashEnvironment)
                               ├── gdb subprocess (persistent, in agent.env.gdb)
                               ├── trajectory.json     (mini's native format)
                               └── collect.json        (judge-ready schema)

Logging fidelity matches Tier 1 / Tier 3 — `bench/judge.py` consumes
Tier 2 runs without per-tier branching.
"""
from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from bench.common import (
    Case,
    REPO_DIR,
    RunSpec,
    compile_case,
    finalize_result,
    prepare_injected_workspace,
)
from bench.drivers.tier3_gdb import _run_debugger


MINI_VENV_PYTHON = REPO_DIR / ".venv-bench" / "bin" / "python3"
TIER2_RUNNER = REPO_DIR / "bench" / "drivers" / "tier2_runner.py"

# Linux-container path constants. On macOS arm64, gdb cannot run native
# binaries (the darwin-aarch64 native target is unavailable in
# Homebrew gdb 17.x), so the model's gdb tool calls all return
# "Don't know how to run". To preserve Tier 2's experimental purpose
# we transparently route every Darwin-host run through a linux/amd64
# Docker container where gdb has full native target support.
TIER2_DOCKER_IMAGE = "chatdbg-tier2-runner"
TIER2_DOCKERFILE = REPO_DIR / "bench" / "drivers" / "tier2_runner.Dockerfile"


def _need_linux_container(prefer_linux: str | None) -> bool:
    """Decide whether to run Tier 2 inside a Linux container.

    `prefer_linux` is the orchestrator-level override:
      - "always" → use Docker even on Linux hosts
      - "never"  → use the native runner regardless of platform
      - "auto" / None → use Docker only on Darwin (where gdb is
        broken for native binaries)
    """
    if prefer_linux == "always":
        return True
    if prefer_linux == "never":
        return False
    return platform.system() == "Darwin"


def _ensure_image() -> tuple[bool, str]:
    """Build the chatdbg-tier2-runner image if not already present.
    Returns (ok, message). Cached by image tag so repeat sweeps pay
    the build cost only once."""
    inspect = subprocess.run(
        ["docker", "image", "inspect", TIER2_DOCKER_IMAGE],
        capture_output=True, text=True,
    )
    if inspect.returncode == 0:
        return True, "image already present"
    # No --platform pin: Apple Silicon needs linux/arm64 native (Rosetta
    # breaks gdb's ptrace probes). On linux/amd64 hosts Docker still
    # picks the right arch automatically.
    build = subprocess.run(
        ["docker", "build",
         "-t", TIER2_DOCKER_IMAGE,
         "-f", str(TIER2_DOCKERFILE), str(REPO_DIR)],
        capture_output=True, text=True,
    )
    if build.returncode != 0:
        return False, (build.stderr or build.stdout or "docker build failed")[-2000:]
    return True, "image built"


def _build_synthetic_task(case: Case) -> str:
    """Per-case task description for synthetic single-file cases.

    The model is told the binary AND source file paths; it can choose
    bash for source inspection and gdb for runtime debugging."""
    args = case.meta.get("run", {}).get("args", []) or []
    args_str = " ".join(str(a) for a in args)
    expected_crash = case.meta.get("run", {}).get("expected_crash", True)
    sf = case.meta.get("source_file") or "(none — explore!)"
    behavior = (
        "crashes when run (likely a sanitizer report or signal)"
        if expected_crash else
        "runs to completion but the test oracle considers the output incorrect"
    )
    cmd = f"./build/prog {args_str}".rstrip()

    return (
        f"You're debugging a C/C++ bug. The buggy binary is at `./build/prog` "
        f"and the source file is `{sf}` in the current directory.\n\n"
        f"Run command: `{cmd}`\n\n"
        f"Expected behavior: {behavior}.\n\n"
        f"You have a stateful gdb session pre-loaded with `./build/prog` "
        f"(argv already configured). Use `gdb` for runtime debugging, "
        f"`bash` for source inspection. Identify the root cause and propose "
        f"both a local fix and a structural global fix.\n"
    )


def _build_injected_task(case: Case, workdir: Path, binary: Path) -> str:
    rel = binary.relative_to(workdir)
    return (
        f"You're debugging a real-codebase bug in `{case.case_id}`.\n\n"
        f"You are at the project root. The buggy binary is at `./{rel}` "
        f"and a stateful gdb session is pre-loaded with it.\n\n"
        f"Use `gdb` for runtime debugging (set breakpoints, step, "
        f"print). Use `bash` for source-tree navigation. Identify the "
        f"root cause and propose both a local fix and a structural "
        f"global fix.\n"
    )


def _check_mini_venv(run_dir: Path) -> bool:
    if not MINI_VENV_PYTHON.exists():
        (run_dir / "error.log").write_text(
            f"mini-swe-agent venv missing: {MINI_VENV_PYTHON}\n"
            f"Setup:\n"
            f"  python3.10+ -m venv .venv-bench\n"
            f"  .venv-bench/bin/pip install mini-swe-agent\n"
        )
        return False
    return True


class Tier2Driver:
    """Same interface as Tier1Driver / Tier3Driver — orchestrator
    dispatches via tier integer; every driver implements
    `run(spec, run_dir, *, timeout)` and returns `finalize_result(...)`."""

    tier: int = 2

    def __init__(
        self,
        *,
        dry_run: bool = False,
        step_limit: int = 15,
        cost_limit: float = 0.5,
        mini_model_class: str | None = None,
        prefer_linux: str | None = None,
    ):
        self.dry_run = dry_run
        self.step_limit = step_limit
        self.cost_limit = cost_limit
        self.mini_model_class = mini_model_class
        self.prefer_linux = prefer_linux  # "always" | "never" | "auto"/None
        # Cache the "should I use Docker?" decision so we only print
        # the platform-detection message once per sweep.
        self._use_linux_container = _need_linux_container(prefer_linux)

    def run(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(spec.case.case_dir / "case.yaml", run_dir / "case.yaml")

        if not spec.case.platform_supported():
            (run_dir / "skip.log").write_text(
                f"platform={spec.case.platforms}; host skipped\n"
            )
            return finalize_result(
                run_dir, spec,
                status="skipped_platform", exit_code=0, elapsed_s=0.0,
            )

        # Linux-container path (Darwin host by default, or
        # `--tier2-linux always`). gdb on macOS arm64 cannot run
        # native binaries — without this branch every gdb call from
        # the model would return "Don't know how to run", silently
        # degrading Tier 2 to "bash + dead gdb". See HARNESS_AUDIT
        # Round 5 for the validation evidence.
        if self._use_linux_container:
            if spec.case.kind == "injected_repo":
                # Injected cases need their build commands to run on
                # Linux too. prepare_injected_workspace currently uses
                # macOS subprocess.run and would produce a mach-o
                # binary the container can't execute. Out of scope
                # for this PR; report cleanly so sweeps don't crash.
                (run_dir / "error.log").write_text(
                    "Tier 2 + injected_repo + Linux container is not yet "
                    "supported. The repo build commands run on the host "
                    "(macOS clang); the container's Linux clang would need "
                    "to rebuild via prepare_injected_workspace, which is "
                    "macOS-host-bound today. For real-codebase Tier 2 "
                    "experiments, run from a Linux host.\n"
                )
                return finalize_result(
                    run_dir, spec,
                    status="unsupported_combo",
                    exit_code=-1, elapsed_s=0.0,
                )
            return self._run_in_linux_container(spec, run_dir, timeout=timeout)

        if spec.case.kind == "injected_repo":
            return self._run_injected(spec, run_dir, timeout=timeout)
        return self._run_synthetic(spec, run_dir, timeout=timeout)

    # ---- synthetic single-file path -------------------------------------

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

        # gdb session args come from the case's run.args
        gdb_args = spec.case.meta.get("run", {}).get("args", []) or []

        task = _build_synthetic_task(spec.case)
        (run_dir / "task.md").write_text(task)
        argv = self._runner_argv(spec, run_dir, agent_cwd=run_dir,
                                 gdb_binary=binary, gdb_args=gdb_args)
        (run_dir / "session.cmds").write_text(
            "# Tier-2 runner invocation (mini-swe-agent v2 + bash + persistent gdb)\n"
            + " ".join(repr(a) if " " in a else a for a in argv)
            + "\n"
        )

        if not _check_mini_venv(run_dir):
            return finalize_result(
                run_dir, spec, status="missing_dep",
                exit_code=-1, elapsed_s=0.0,
            )
        return self._spawn_runner(spec, run_dir, argv, timeout=timeout)

    # ---- injected_repo path --------------------------------------------

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

        workdir = prep.workdir
        # Injected cases may have explicit debug args / stdin in the
        # case's debug section (Tier 3 also reads this); plumb args
        # through to gdb. stdin_data is harder — defer (file an issue).
        debug_cfg = spec.case.meta.get("debug", {}) or {}
        gdb_args = debug_cfg.get("args", []) or []

        task = _build_injected_task(spec.case, workdir, prep.binary)
        (run_dir / "task.md").write_text(task)
        argv = self._runner_argv(spec, run_dir, agent_cwd=workdir,
                                 gdb_binary=prep.binary, gdb_args=gdb_args)
        (run_dir / "session.cmds").write_text(
            "# Tier-2 runner invocation (mini-swe-agent v2 + bash + persistent gdb, injected)\n"
            + " ".join(repr(a) if " " in a else a for a in argv)
            + "\n"
        )

        if not _check_mini_venv(run_dir):
            return finalize_result(
                run_dir, spec, status="missing_dep",
                exit_code=-1, elapsed_s=0.0,
            )
        return self._spawn_runner(spec, run_dir, argv, timeout=timeout)

    # ---- shared subprocess plumbing ------------------------------------

    def _runner_argv(self, spec: RunSpec, run_dir: Path, *,
                     agent_cwd: Path, gdb_binary: Path,
                     gdb_args: list) -> list[str]:
        argv = [
            str(MINI_VENV_PYTHON), str(TIER2_RUNNER),
            "--run-dir", str(run_dir.resolve()),
            "--model", spec.model,
            "--task-file", str((run_dir / "task.md").resolve()),
            "--cwd", str(agent_cwd.resolve()),
            "--gdb-binary", str(gdb_binary.resolve()),
            "--gdb-args", json.dumps([str(a) for a in gdb_args]),
            "--step-limit", str(self.step_limit),
            "--cost-limit", str(self.cost_limit),
        ]
        if self.mini_model_class:
            argv += ["--mini-model-class", self.mini_model_class]
        return argv

    # ---- Linux-container path (Darwin host) -----------------------------

    def _run_in_linux_container(self, spec: RunSpec, run_dir: Path,
                                 *, timeout: float) -> dict:
        """Compile + run the agent inside a linux/amd64 Docker container.

        The host's clang produces mach-o binaries gdb-on-Linux can't
        execute, so the binary must be built INSIDE the container by
        Linux clang. Single `docker run` invocation handles both:

          1. clang <flags> <source> -o <build/prog>
          2. python3 tier2_runner.py --gdb-binary <build/prog> ...

        The repo is bind-mounted at /work so paths translate trivially:
        host `<repo>/bench/results/X` ↔ container `/work/bench/results/X`.

        Run-dir bind-mount means the runner's collect.json /
        trajectory.json / stdout.log / stderr.log all surface to the
        host without rsync gymnastics.
        """
        # Source archival (parity with native synthetic path).
        shutil.copy(spec.case.source_path, run_dir / spec.case.source_path.name)
        build_dir = run_dir / "build"
        build_dir.mkdir(parents=True, exist_ok=True)

        if self.dry_run:
            return finalize_result(
                run_dir, spec, status="dry_run", exit_code=0, elapsed_s=0.0,
            )

        ok, msg = _ensure_image()
        if not ok:
            (run_dir / "error.log").write_text(
                f"Failed to build {TIER2_DOCKER_IMAGE} image:\n{msg}\n"
            )
            return finalize_result(
                run_dir, spec,
                status="docker_build_failed", exit_code=-1, elapsed_s=0.0,
            )

        # Container-side absolute paths. `_REPO_AT_HOST` ↔ `/work`.
        repo_str = str(REPO_DIR)
        def to_container(host_path: Path) -> str:
            s = str(host_path.resolve())
            if not s.startswith(repo_str):
                raise ValueError(
                    f"Path {s} is outside the repo ({repo_str}); cannot "
                    f"bind-mount it into the container."
                )
            return "/work" + s[len(repo_str):]

        c_run_dir = to_container(run_dir)
        c_source = to_container(run_dir / spec.case.source_path.name)
        c_binary = to_container(build_dir / "prog")
        c_task = to_container(run_dir / "task.md")

        # Compile flags: case.yaml lists them. Use clang/clang++ from the
        # case's `build.compiler` setting; default to clang for C, clang++
        # for cpp / c++.
        build_cfg = spec.case.meta.get("build", {})
        default_compiler = "clang++" if spec.case.language in ("cpp", "c++") else "clang"
        compiler = build_cfg.get("compiler", default_compiler)
        flags: list[str] = list(build_cfg.get("flags", []))

        # Write task.md (analog of session.cmds in the native path)
        task = _build_synthetic_task(spec.case)
        (run_dir / "task.md").write_text(task)

        # Build the in-container shell script. We use `bash -c` rather
        # than CMD/ENTRYPOINT because the docker invocation needs to
        # interleave compile + runner in one container lifetime.
        gdb_args = spec.case.meta.get("run", {}).get("args", []) or []
        runner_args_inside = [
            "python3", "/work/bench/drivers/tier2_runner.py",
            "--run-dir", c_run_dir,
            "--model", spec.model,
            "--task-file", c_task,
            "--cwd", c_run_dir,
            "--gdb-binary", c_binary,
            "--gdb-args", json.dumps([str(a) for a in gdb_args]),
            "--step-limit", str(self.step_limit),
            "--cost-limit", str(self.cost_limit),
        ]
        if self.mini_model_class:
            runner_args_inside += ["--mini-model-class", self.mini_model_class]

        compile_cmd = " ".join(shlex.quote(s) for s in
            [compiler, *flags, c_source, "-o", c_binary])
        runner_cmd = " ".join(shlex.quote(s) for s in runner_args_inside)
        # 2>&1 keeps the compile log inside the container's stdout
        # so debug failures surface in stdout.log on the host.
        in_container_script = (
            f"set -o pipefail\n"
            f"echo '$ {compile_cmd}'\n"
            f"{compile_cmd} 2>&1 || {{ echo '[tier2-linux] compile failed'; exit 11; }}\n"
            f"{runner_cmd}\n"
        )

        # Write the in-container script for replay / debugging
        (run_dir / "session.cmds").write_text(
            "# Tier-2 Linux-container invocation (synthetic case).\n"
            "# Build image:\n"
            f"#   docker build --platform=linux/amd64 -t {TIER2_DOCKER_IMAGE} \\\n"
            f"#     -f bench/drivers/tier2_runner.Dockerfile .\n"
            "# Then run inside the container:\n"
            + in_container_script
        )

        # Pass through API keys the agent needs
        env_flags: list[str] = []
        for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY",
                    "OPENROUTER_API_BASE", "ANTHROPIC_API_KEY"):
            val = os.environ.get(key)
            if val:
                env_flags += ["-e", f"{key}={val}"]

        docker_argv = [
            "docker", "run", "--rm",
            # SYS_PTRACE so gdb can attach to the inferior. On Linux
            # hosts the default capability set lacks ptrace; without
            # this gdb's `run` would fail with "ptrace: Operation not
            # permitted". Apple Silicon runs the container natively
            # in linux/arm64 (no Rosetta), so ptrace works once the
            # capability is added.
            "--cap-add=SYS_PTRACE",
            # ASan / UBSan need the ability to mmap large regions
            # (tagged shadow memory). Default seccomp profile blocks
            # some of those syscalls; loosen it.
            "--security-opt", "seccomp=unconfined",
            "--user", f"{os.getuid()}:{os.getgid()}",
            # HOME must be writable: mini-swe-agent's __init__ creates
            # ~/.config/mini-swe-agent on first import. The container's
            # `--user` mode runs as numeric uid with no /etc/passwd
            # entry, so HOME defaults to / which is read-only.
            "-e", "HOME=/tmp",
            "-v", f"{REPO_DIR.resolve()}:/work",
            *env_flags,
            TIER2_DOCKER_IMAGE,
            "bash", "-c", in_container_script,
        ]

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)

        t0 = time.time()
        stdout, stderr, exit_code, timed_out = _run_debugger(
            docker_argv,
            stdin_for_proc=None,
            env=env,
            run_dir=run_dir,
            timeout=timeout,
        )
        elapsed = time.time() - t0
        (run_dir / "stdout.log").write_text(stdout)
        (run_dir / "stderr.log").write_text(stderr)

        if timed_out:
            return finalize_result(
                run_dir, spec,
                status="timeout", exit_code=-1, elapsed_s=elapsed,
            )

        # Map status the same way as the native path. The compile
        # error path returns exit 11 (set in the in-container script);
        # surface that as compile_failed for analysis.
        if exit_code == 11:
            (run_dir / "compile.log").write_text(stdout)
            return finalize_result(
                run_dir, spec,
                status="compile_failed", exit_code=11, elapsed_s=elapsed,
            )

        status = "ok" if (run_dir / "collect.json").exists() else "no_collect"
        return finalize_result(
            run_dir, spec,
            status=status, exit_code=exit_code, elapsed_s=elapsed,
        )

    def _spawn_runner(self, spec: RunSpec, run_dir: Path,
                      argv: list[str], *, timeout: float) -> dict:
        env = os.environ.copy()
        # Skip macOS-arm64 .so files in the host venv that would
        # crash the Linux/x86_64 mini interpreter on bind-mount runs.
        # Same caveat as Tier 1.
        env.pop("PYTHONPATH", None)

        t0 = time.time()
        stdout, stderr, exit_code, timed_out = _run_debugger(
            argv,
            stdin_for_proc=None,
            env=env,
            run_dir=run_dir,
            timeout=timeout,
        )
        elapsed = time.time() - t0
        (run_dir / "stdout.log").write_text(stdout)
        (run_dir / "stderr.log").write_text(stderr)

        if timed_out:
            return finalize_result(
                run_dir, spec,
                status="timeout", exit_code=-1, elapsed_s=elapsed,
            )
        status = "ok" if (run_dir / "collect.json").exists() else "no_collect"
        return finalize_result(
            run_dir, spec,
            status=status, exit_code=exit_code, elapsed_s=elapsed,
        )
