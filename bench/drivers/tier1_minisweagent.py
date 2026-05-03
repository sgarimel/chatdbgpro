"""Tier-1 driver: mini-swe-agent (bash-only) wrapper.

Implements the same `RunSpec → result.json + collect.json` contract as
Tier3Driver, but the agent under test is mini-swe-agent v2 with bash as
its only tool. Tests the project's "agent scaffold matters" hypothesis:
same model, same case, no curated debugger interface.

Architecture:
  Orchestrator (.venv-bench-39, Py 3.9, Apple lldb)
    └── Tier1Driver.run()
        └── subprocess: .venv-bench/bin/python3 tier1_runner.py ...
                          ↑ (Py 3.14, mini-swe-agent installed)

Why two venvs: mini-swe-agent v2 requires Python ≥3.10. The
orchestrator can't drop Apple's lldb (Tier 3 needs Python 3.9 to embed
into Apple's lldb), so we shell out to the newer venv for Tier 1 only.
The runner writes both `trajectory.json` (mini's native serialization)
and `collect.json` (our standardized schema) into the run dir, so the
existing judge.py picks up Tier 1 runs without per-tier branching.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from bench.common import (
    Case,
    DockerCase,
    REPO_DIR,
    RunSpec,
    build_oracle_strings,
    compile_case,
    finalize_result,
    prepare_injected_workspace,
    write_docker_case_yaml,
)
from bench.drivers.container_session import ContainerSession, resolve_runtime
from bench.drivers.tier3_gdb import _run_debugger


# Mini-swe-agent v2 lives in the bench's secondary Python venv. The
# tier-3 driver uses .venv-bench-39 (Apple lldb pinned to Python 3.9);
# tier 1 uses .venv-bench (Python 3.14+), where `pip install mini-swe-agent`
# was run.
MINI_VENV_PYTHON = REPO_DIR / ".venv-bench" / "bin" / "python3"
TIER1_RUNNER = REPO_DIR / "bench" / "drivers" / "tier1_runner.py"


def _build_synthetic_task(case: Case) -> str:
    """Per-case task description for synthetic single-file cases.

    Mirrors the information the Tier3 ChatDBG prompt provides — buggy
    binary location, run args, expected behavior — so the model is
    asked the same *question* in both tiers, only the *interface*
    differs."""
    args = case.meta.get("run", {}).get("args", []) or []
    args_str = " ".join(str(a) for a in args)
    expected_crash = case.meta.get("run", {}).get("expected_crash", True)
    src_files = []
    sf = case.meta.get("source_file")
    if sf:
        src_files.append(sf)
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
        f"Use bash to investigate (run the binary, run gdb in batch mode, "
        f"read the source). Identify the root cause and propose both a "
        f"local fix and a structural global fix.\n"
    )


def _build_bugscpp_task(case: DockerCase) -> str:
    """Per-case task description for BugsCPP cases — the agent debugs an
    open-source C/C++ project's real bug inside a Linux container with
    the workspace mounted at /work. Mirrors the synthetic-task framing
    so the only varying axis is case content / exec surface."""
    binary_in = case.buggy_binary_path or "(see workspace)"
    if case.buggy_binary_argv:
        argv_str = " ".join(case.buggy_binary_argv)
    else:
        argv_str = " ".join(case.trigger_argv) if case.trigger_argv else "(none)"
    obs = case.bug_observed or "(unknown)"
    return (
        f"You're debugging a real-codebase bug in `{case.bug_id}` (project "
        f"`{case.project}`, an open-source C/C++ project from the BugsC++ "
        f"corpus).\n\n"
        f"You are inside a Linux/amd64 container at /work — that's the "
        f"project's source tree with the buggy binary already built. "
        f"Use bash to investigate: cd, ls, cat, run the binary, run gdb "
        f"in batch mode, etc.\n\n"
        f"The buggy binary in this case is `/work/{binary_in}`.\n"
        f"Failing test invocation: `{argv_str}`\n"
        f"Observed behavior: `{obs}`.\n\n"
        f"Investigate the failure, localize the defect in the source, "
        f"and propose both a local fix and a structural global fix.\n"
    )


def _build_injected_task(case: Case, workdir: Path, binary: Path) -> str:
    """Per-case task description for injected_repo cases — the agent
    works against a cloned upstream tree (e.g. cJSON) rather than a
    single file."""
    rel = binary.relative_to(workdir)
    return (
        f"You're debugging a real-codebase bug in `{case.case_id}` "
        f"(an open-source C/C++ project).\n\n"
        f"You are at the project root. The buggy binary is at `./{rel}`. "
        f"The bug was injected by a small patch — somewhere in the source "
        f"tree, a guard / check / initializer was removed or weakened.\n\n"
        f"Use bash to navigate the source tree, reproduce the failure, "
        f"localize the defect, and propose both a local fix and a "
        f"structural global fix.\n"
    )


def _check_mini_venv(run_dir: Path) -> bool:
    """Return True if mini-swe-agent's venv is set up and importable.

    Recording the failure mode in error.log is more useful than letting
    the subprocess crash with an opaque ImportError — researchers
    setting up the bench for the first time hit this exact path."""
    if not MINI_VENV_PYTHON.exists():
        (run_dir / "error.log").write_text(
            f"mini-swe-agent venv missing: {MINI_VENV_PYTHON}\n"
            f"Setup:\n"
            f"  python3.10+ -m venv .venv-bench\n"
            f"  .venv-bench/bin/pip install mini-swe-agent\n"
        )
        return False
    return True


class Tier1Driver:
    """Same interface as Tier3Driver — orchestrator dispatches via tier
    integer, every driver implements `run(spec, run_dir, *, timeout)`
    and returns the dict produced by `finalize_result()`."""

    tier: int = 1

    def __init__(
        self,
        *,
        dry_run: bool = False,
        step_limit: int = 15,
        cost_limit: float = 0.5,
        mini_model_class: str | None = None,
        docker: bool = False,
        runtime: str | None = None,
    ):
        self.dry_run = dry_run
        self.step_limit = step_limit
        self.cost_limit = cost_limit
        # Optional override for mini's auto model-class selection.
        # Empty/None means auto (LitellmModel, which is tool-calling).
        # Useful escape hatch for text-only models or for explicit
        # ablations across mini's model class taxonomy.
        self.mini_model_class = mini_model_class
        # docker=True means we're driving BugsCPP cases (kind ==
        # "docker_bugscpp"). The driver routes through _run_bugscpp,
        # which spins up a per-case ContainerSession and points mini's
        # bash sandbox at it via tier1_runner.py --docker-container.
        self.docker = docker
        # Container runtime ("docker" / "apptainer" / None=auto). Pinned
        # at sweep level via set_default_runtime() typically; per-driver
        # override available here.
        self.runtime = runtime

    def run(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        run_dir.mkdir(parents=True, exist_ok=True)
        # Mirror Tier3 archival: case.yaml gets a copy next to the run.
        # The judge consumes case.yaml for its criteria, so this is
        # load-bearing (not just for human inspection). DockerCase has
        # no case_dir on disk; _run_bugscpp synthesizes a case.yaml at
        # finalize time via write_docker_case_yaml().
        if spec.case.kind != "docker_bugscpp":
            shutil.copy(spec.case.case_dir / "case.yaml", run_dir / "case.yaml")

        # Platform gate (e.g. MSan on macOS) — same semantics as Tier3.
        if not spec.case.platform_supported():
            (run_dir / "skip.log").write_text(
                f"platform={spec.case.platforms}; host skipped\n"
            )
            return finalize_result(
                run_dir, spec,
                status="skipped_platform", exit_code=0, elapsed_s=0.0,
            )

        if spec.case.kind == "injected_repo":
            return self._run_injected(spec, run_dir, timeout=timeout)
        if spec.case.kind == "docker_bugscpp":
            return self._run_bugscpp(spec, run_dir, timeout=timeout)
        return self._run_synthetic(spec, run_dir, timeout=timeout)

    # ---- synthetic single-file path -------------------------------------

    def _run_synthetic(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        # Source archive + compile (identical to Tier3's synthetic path,
        # so judge.py reads the same `program.c` next to the run).
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
        # session.cmds analog: log the runner invocation so a human can
        # rerun the exact same agent session by hand.
        argv = self._runner_argv(spec, run_dir, agent_cwd=run_dir)
        (run_dir / "session.cmds").write_text(
            "# Tier-1 runner invocation (mini-swe-agent v2)\n"
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
        task = _build_injected_task(spec.case, workdir, prep.binary)
        (run_dir / "task.md").write_text(task)
        argv = self._runner_argv(spec, run_dir, agent_cwd=workdir)
        (run_dir / "session.cmds").write_text(
            "# Tier-1 runner invocation (mini-swe-agent v2, injected)\n"
            + " ".join(repr(a) if " " in a else a for a in argv)
            + "\n"
        )

        if not _check_mini_venv(run_dir):
            return finalize_result(
                run_dir, spec, status="missing_dep",
                exit_code=-1, elapsed_s=0.0,
            )

        return self._spawn_runner(spec, run_dir, argv, timeout=timeout)

    # ---- BugsCPP path --------------------------------------------------

    def _run_bugscpp(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        """T1 BugsCPP: spin up the per-project gdb container, point mini's
        bash sandbox at it via `docker exec`, and run the same agent loop
        we use for synthetic and injected_repo cases.

        Workspace handling: ContainerSession copies the workspace to a
        per-run scratch dir before mounting at /work, so a model that
        runs `make` or otherwise mutates files doesn't affect later runs.
        """
        case: DockerCase = spec.case  # type: ignore[assignment]
        if not case.workspace_path.exists():
            return finalize_result(
                run_dir, spec,
                status="workspace_missing", exit_code=-1, elapsed_s=0.0,
            )

        # Resolve runtime once: explicit driver setting > orchestrator
        # default > host PATH detection. Same value goes to ContainerSession,
        # ensure_gdb_image (returns docker tag for docker, registry URL
        # for apptainer), and the mini-runner subprocess (which can't
        # share the process-local _DEFAULT_RUNTIME).
        runtime = resolve_runtime(self.runtime)

        # Ensure the gdb-enabled image is available. For docker this
        # builds locally; for apptainer this just returns a docker://
        # registry URL that apptainer pulls + caches on first use.
        try:
            from pipeline2.ensure_image import ensure_gdb_image
            image_tag = ensure_gdb_image(case.project, runtime=runtime)
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

        # Task prompt is BugsCPP-specific so the model knows what
        # workspace it's looking at.
        task = _build_bugscpp_task(case)
        (run_dir / "task.md").write_text(task)

        # Mini-runner argv. Same as synthetic except the bash environment
        # is now a DockerExecEnvironment pointing at our container.
        # We pass --container-cwd=/work since the workspace lives there.
        # The container name is set by ContainerSession; we generate it
        # here so we can pass it to the runner.
        import uuid as _uuid
        container_name = f"bench-t1-{_uuid.uuid4().hex[:20]}"

        argv = [
            str(MINI_VENV_PYTHON), str(TIER1_RUNNER),
            "--run-dir", str(run_dir.resolve()),
            "--model", spec.model,
            "--task-file", str((run_dir / "task.md").resolve()),
            "--cwd", str(run_dir.resolve()),  # mini's local cwd; bash exec'd in container
            "--step-limit", str(self.step_limit),
            "--cost-limit", str(self.cost_limit),
            "--docker-container", container_name,
            "--container-cwd", "/work",
            "--container-runtime", runtime,
        ]
        if self.mini_model_class:
            argv += ["--mini-model-class", self.mini_model_class]
        (run_dir / "session.cmds").write_text(
            "# Tier-1 runner invocation (mini-swe-agent v2, BugsCPP)\n"
            f"# Docker container: {container_name} (image {image_tag})\n"
            + " ".join(repr(a) if " " in a else a for a in argv)
            + "\n"
        )

        if not _check_mini_venv(run_dir):
            return finalize_result(
                run_dir, spec,
                status="missing_dep", exit_code=-1, elapsed_s=0.0,
            )

        session = ContainerSession(
            image=image_tag,
            workspace_src=case.workspace_path,
            run_dir=run_dir,
            runtime=runtime,
            platform="linux/amd64",  # honored by docker; ignored by apptainer
            ptrace=True,  # T1 has bash only but ptrace=True lets the
                          # model run gdb itself if it chooses to.
            hermetic_workspace=True,
            name=container_name,
            env={
                # Forward API keys for tools the model might invoke.
                **{k: os.environ[k] for k in (
                    "OPENROUTER_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_BASE",
                ) if k in os.environ},
            },
        )

        try:
            with session:
                write_docker_case_yaml(case, run_dir)
                return self._spawn_runner(spec, run_dir, argv, timeout=timeout)
        except RuntimeError as e:
            (run_dir / "docker_run.log").write_text(str(e))
            return finalize_result(
                run_dir, spec,
                status="docker_run_failed", exit_code=-1, elapsed_s=0.0,
            )

    # ---- shared subprocess plumbing ------------------------------------

    def _runner_argv(self, spec: RunSpec, run_dir: Path, *,
                     agent_cwd: Path) -> list[str]:
        """Argv for the mini-side subprocess. Kept as one function so
        synthetic and injected paths share the contract — the judge
        treats both kinds of runs identically."""
        argv = [
            str(MINI_VENV_PYTHON), str(TIER1_RUNNER),
            "--run-dir", str(run_dir.resolve()),
            "--model", spec.model,
            "--task-file", str((run_dir / "task.md").resolve()),
            "--cwd", str(agent_cwd.resolve()),
            "--step-limit", str(self.step_limit),
            "--cost-limit", str(self.cost_limit),
        ]
        if self.mini_model_class:
            argv += ["--mini-model-class", self.mini_model_class]
        return argv

    def _spawn_runner(self, spec: RunSpec, run_dir: Path,
                      argv: list[str], *, timeout: float) -> dict:
        """Run the mini-venv subprocess with proper process-group
        isolation so a stuck mini step can be killed cleanly. Reuses
        Tier3's `_run_debugger` helper rather than re-implementing
        signal handling, because that path was already hardened against
        the lldb-attach hang and has the same lifecycle requirements
        (long-running child holding a process group)."""
        env = os.environ.copy()
        # litellm in the child venv reads OPENROUTER_API_KEY / OPENAI_API_KEY
        # / etc. from the inherited env. No extra plumbing needed.
        # Skip the .venv-bench-39's PYTHONPATH (which contains macOS-arm64
        # .so files); the mini venv is self-contained.
        env.pop("PYTHONPATH", None)

        t0 = time.time()
        stdout, stderr, exit_code, timed_out = _run_debugger(
            argv,
            stdin_for_proc=None,   # runner doesn't read stdin
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

        # status="ok" iff the runner produced a collect.json — same
        # rule as Tier3 (the runner only writes collect.json after
        # agent.run completes, so its absence means the runner crashed
        # before submission).
        status = "ok" if (run_dir / "collect.json").exists() else "no_collect"
        return finalize_result(
            run_dir, spec,
            status=status, exit_code=exit_code, elapsed_s=elapsed,
        )
