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
import shutil
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
    ):
        self.dry_run = dry_run
        self.step_limit = step_limit
        self.cost_limit = cost_limit
        self.mini_model_class = mini_model_class

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
