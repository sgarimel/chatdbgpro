"""Tier-3 driver: ChatDBG on lldb/gdb, no bash tool.

This is the original ablation path — compile the single-file case,
launch it under the native debugger with ChatDBG's script module loaded,
and drive one `why ...` query to EOF. The body is the verbatim behaviour
previously implemented inline in bench/orchestrator.py::execute_run.
"""
from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from bench.common import (
    REPO_DIR,
    Case,
    InjectedPrepResult,
    RunSpec,
    compile_case,
    finalize_result,
    prepare_injected_workspace,
)


def build_lldb_script(binary: Path, case: Case, question: str) -> str:
    args = case.meta.get("run", {}).get("args", [])
    lines = ["command script import chatdbg.chatdbg_lldb"]
    if args:
        quoted = " ".join(shlex.quote(str(a)) for a in args)
        lines.append(f"settings set target.run-args {quoted}")
    stdin_path = case.meta.get("run", {}).get("stdin_file")
    if stdin_path:
        lines.append(f"settings set target.input-path {stdin_path}")
    lines.append("run")
    lines.append(f"why {question}")
    # Intentionally omit `quit`: the follow-up input() in DBGDialog.dialog
    # sees EOF and breaks; lldb then sees EOF on its command stream and
    # exits cleanly.
    return "\n".join(lines) + "\n"


def build_gdb_script(binary: Path, case: Case, question: str) -> str:
    args = case.meta.get("run", {}).get("args", [])
    lines = ["source -s chatdbg.chatdbg_gdb"]
    if args:
        quoted = " ".join(shlex.quote(str(a)) for a in args)
        lines.append(f"set args {quoted}")
    lines.append("run")
    lines.append(f"why {question}")
    return "\n".join(lines) + "\n"


def pick_debugger(explicit: str | None) -> str:
    if explicit:
        return explicit
    if platform.system() == "Darwin":
        if shutil.which("lldb") or Path("/opt/homebrew/opt/llvm/bin/lldb").exists():
            return "lldb"
    if shutil.which("gdb"):
        return "gdb"
    if shutil.which("lldb"):
        return "lldb"
    raise RuntimeError("No supported debugger (lldb / gdb) found on PATH.")


def lldb_binary() -> str:
    """Return the lldb executable to invoke.

    On macOS arm64 we deliberately prefer Apple's /usr/bin/lldb over
    Homebrew's llvm lldb. Reason: macOS only honours the
    `com.apple.security.cs.debugger` entitlement when the binary is
    signed by a real (non-adhoc) identity. Homebrew ships its lldb
    adhoc-signed, so even though it embeds a much newer Python, it
    can't actually control a launched process — `run` exec()s the
    target and lldb loses the handle. Apple's lldb is properly
    signed by Apple. We pay for that with Python 3.9, which is why
    .venv-bench-39 exists with the older deps."""
    if Path("/usr/bin/lldb").exists():
        return "/usr/bin/lldb"
    return "lldb"


def _repo_venv_site_packages() -> str | None:
    """Return the bench venv's site-packages path, if a venv exists.

    Two layouts are supported:
      `.venv-bench-39` — built against Python 3.9 (Apple's bundled lldb).
                         Holds ChatDBG's deps with `ipython<9` etc., the
                         only versions that import on 3.9.
      `.venv-bench`     — built against a newer Python (e.g. for a future
                         lldb that ships with one).

    The 3.9 venv is preferred when present, since Apple's lldb is the
    one we actually launch on macOS arm64 (see `lldb_binary` above)."""
    for name in (".venv-bench-39", ".venv-bench"):
        venv = REPO_DIR / name
        if not venv.exists():
            continue
        matches = list((venv / "lib").glob("python*/site-packages"))
        if matches:
            return str(matches[0])
    return None


class Tier3Driver:
    tier: int = 3

    def __init__(self, debugger: str, dry_run: bool = False):
        self.debugger = debugger
        self.dry_run = dry_run

    def run(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        run_dir.mkdir(parents=True, exist_ok=True)

        # Archive metadata next to the run so the judge sees exactly what
        # the model saw. Source archiving differs by kind: synthetic cases
        # have one file to copy; injected cases pull sources from a cached
        # workspace that the judge can inspect separately.
        shutil.copy(spec.case.case_dir / "case.yaml", run_dir / "case.yaml")

        # Platform gate (e.g. MSan cases on non-Linux hosts). Return early
        # with a dedicated status so the judge / aggregator can exclude the
        # cell cleanly instead of treating it as a failure.
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
                run_dir, spec,
                status="dry_run", exit_code=0, elapsed_s=0.0,
            )

        collect_path = run_dir / "collect.json"

        env = os.environ.copy()
        env["CHATDBG_MODEL"] = spec.model
        env["CHATDBG_TOOL_CONFIG"] = str(spec.tool_config_path)
        env["CHATDBG_COLLECT_DATA"] = str(collect_path)
        env["CHATDBG_CONTEXT"] = str(spec.context_lines)
        env["CHATDBG_FORMAT"] = "text"
        env["CHATDBG_LOG"] = str(run_dir / "chatdbg.log.yaml")
        src_path = str(REPO_DIR / "src")
        # If the repo-local venv exists (created by us for brew llvm's Python),
        # prepend its site-packages so the debugger's embedded interpreter
        # finds litellm / openai / PyYAML / ... without needing a system install.
        parts = [src_path]
        venv_sp = _repo_venv_site_packages()
        if venv_sp:
            parts.append(venv_sp)
        existing = env.get("PYTHONPATH", "")
        if existing:
            parts.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(parts)

        if spec.case.meta.get("run", {}).get("clean_env"):
            for k in list(env.keys()):
                if k.startswith("USER") or k in ("LOGNAME", "ADMIN_USER"):
                    env.pop(k, None)

        if self.debugger == "lldb":
            script = build_lldb_script(binary, spec.case, spec.question)
            # We must pass the script via `-s session.cmds`, NOT via stdin.
            # If lldb's command stream comes from stdin then the launched
            # target inherits the same stdin, which (a) lets it consume
            # bytes meant for lldb and (b) keeps lldb in async mode where
            # stop events never surface — `run` returns immediately and
            # the crash is reported nowhere. With -s, lldb reads commands
            # from the file and the target gets the parent's tty / devnull.
            (run_dir / "session.cmds").write_text(script)
            argv = [
                lldb_binary(),
                "-o", "settings set use-color false",
                "-s", str(run_dir / "session.cmds"),
                "--", str(binary),
            ]
            stdin_for_proc = subprocess.DEVNULL
        elif self.debugger == "gdb":
            script = build_gdb_script(binary, spec.case, spec.question)
            (run_dir / "session.cmds").write_text(script)
            argv = ["gdb", "-nx", "-batch-silent"]
            argv += ["-ex", "source /dev/stdin", str(binary)]
            stdin_for_proc = script
        else:
            raise ValueError(f"Unknown debugger: {self.debugger}")

        start = time.time()
        try:
            proc = subprocess.run(
                argv,
                input=stdin_for_proc if isinstance(stdin_for_proc, str) else None,
                stdin=stdin_for_proc if not isinstance(stdin_for_proc, str) else None,
                text=True,
                capture_output=True,
                env=env,
                cwd=run_dir,
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

    def _run_injected(self, spec: RunSpec, run_dir: Path, *, timeout: float) -> dict:
        """Tier-3 path for `kind: injected_repo` cases.

        Differences from the synthetic path:
        - No compile_case; the whole build lives inside
          prepare_injected_workspace (which clones, patches, runs
          `build.commands` inside the cloned tree).
        - The debugged binary is the one `build.binary` produced, and
          lldb runs from the workspace root so stack-trace paths resolve
          relative to the checked-out source.
        - Debug args / stdin come from `case.meta["debug"]`, not the
          top-level `run` section. `run.repro` remains a
          reference-only artifact (`./bench-repro.sh`) for humans."""
        prep = prepare_injected_workspace(spec.case)
        (run_dir / "compile.log").write_text(prep.log)
        if prep.status != "ok" or prep.binary is None:
            return finalize_result(
                run_dir, spec,
                status=prep.status if prep.status != "ok" else "build_failed",
                exit_code=-1, elapsed_s=0.0,
            )
        workdir = prep.workdir
        binary = prep.binary

        if self.dry_run:
            return finalize_result(
                run_dir, spec,
                status="dry_run", exit_code=0, elapsed_s=0.0,
            )

        collect_path = run_dir / "collect.json"
        env = self._chatdbg_env(spec, run_dir, collect_path)

        if self.debugger != "lldb":
            # gdb for injected cases is plausible (we'd need to call
            # `file <binary>` from the cwd) but not wired in the pilot.
            raise ValueError(
                f"injected_repo only supports lldb for now, got {self.debugger}"
            )

        debug_cfg = spec.case.meta.get("debug", {})
        args = debug_cfg.get("args", [])
        stdin_data = debug_cfg.get("stdin_data")

        lines = ["command script import chatdbg.chatdbg_lldb"]
        if args:
            lines.append("settings set target.run-args "
                         + " ".join(shlex.quote(str(a)) for a in args))
        if stdin_data is not None:
            stdin_file = run_dir / "stdin.bin"
            stdin_file.write_bytes(stdin_data.encode() if isinstance(stdin_data, str)
                                   else stdin_data)
            lines.append(f"settings set target.input-path {stdin_file}")
        lines.append("run")
        lines.append(f"why {spec.question}")
        script = "\n".join(lines) + "\n"
        (run_dir / "session.cmds").write_text(script)

        argv = [
            lldb_binary(),
            "-o", "settings set use-color false",
            "-s", str(run_dir / "session.cmds"),
            "--", str(binary),
        ]

        start = time.time()
        try:
            proc = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                text=True, capture_output=True,
                env=env, cwd=workdir, timeout=timeout,
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

    def _chatdbg_env(self, spec: RunSpec, run_dir: Path, collect_path: Path) -> dict:
        """Build the child env dict shared by synthetic + injected runs.

        Only the PYTHONPATH-prepending is load-bearing on macOS arm64
        where Apple's lldb embeds Python 3.9 (see lldb_binary()); the
        rest is just ChatDBG's normal runtime config surfaced via env."""
        env = os.environ.copy()
        env["CHATDBG_MODEL"] = spec.model
        env["CHATDBG_TOOL_CONFIG"] = str(spec.tool_config_path)
        env["CHATDBG_COLLECT_DATA"] = str(collect_path)
        env["CHATDBG_CONTEXT"] = str(spec.context_lines)
        env["CHATDBG_FORMAT"] = "text"
        env["CHATDBG_LOG"] = str(run_dir / "chatdbg.log.yaml")
        parts = [str(REPO_DIR / "src")]
        venv_sp = _repo_venv_site_packages()
        if venv_sp:
            parts.append(venv_sp)
        existing = env.get("PYTHONPATH", "")
        if existing:
            parts.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(parts)
        return env
