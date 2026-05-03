"""Tier-3 driver: ChatDBG on gdb (containerized) or lldb/gdb (host, legacy).

This is the original ablation path — compile the single-file case,
launch it under the debugger with ChatDBG's script module loaded, and
drive one `why ...` query to EOF.

Two execution modes:

  containerize=True (default after the GDB-everywhere migration):
      Runs ChatDBG-on-gdb inside chatdbgpro/synthetic-runner:latest,
      regardless of host platform. Same debugger interface as the
      BugsCPP T3 path (chatdbgpro/gdb-<project>) — no
      "T3 macOS lldb vs T3 Linux gdb" confounder in cross-tier
      comparisons. The synthetic source is compiled inside the
      container with clang.

  containerize=False (legacy / opt-out via --tier3-host):
      Runs the debugger natively on the host. lldb on macOS (Apple's
      signed lldb), gdb where available. Preserved for users who
      need the previous behaviour or cannot run Docker.
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
from bench.drivers.container_session import ContainerSession, Mount


SYNTHETIC_RUNNER_IMAGE = "chatdbgpro/synthetic-runner:latest"


def _native_docker_platform() -> str:
    """Return the linux/<arch> Docker platform string matching the host.
    Used by the T3-synthetic-in-container path so gdb runs without
    Rosetta/QEMU emulation (which has known ptrace bugs)."""
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "linux/arm64"
    if m in ("x86_64", "amd64"):
        return "linux/amd64"
    # Fallback: let docker pick. Newer arches (ppc64le etc.) propagate.
    return ""


STRUCTURAL_FIX_QUESTION = (
    "Now propose a structural change that prevents this entire class of "
    "bug — not just a patch at this line. Think about API design, types, "
    "or invariants that would make the bug inexpressible."
)


def build_lldb_script(binary: Path, case: Case, question: str,
                      *, breakpoint_spec: str | None = None,
                      structural_followup: bool = False) -> str:
    args = case.meta.get("run", {}).get("args", [])
    lines = ["command script import chatdbg.chatdbg_lldb"]
    if args:
        quoted = " ".join(shlex.quote(str(a)) for a in args)
        lines.append(f"settings set target.run-args {quoted}")
    stdin_path = case.meta.get("run", {}).get("stdin_file")
    if stdin_path:
        lines.append(f"settings set target.input-path {stdin_path}")
    if breakpoint_spec:
        lines.append(f"breakpoint set --file {breakpoint_spec.split(':')[0]} "
                     f"--line {breakpoint_spec.split(':')[1]}")
    lines.append("run")
    lines.append(f"why {question}")
    if structural_followup:
        lines.append(f"why {STRUCTURAL_FIX_QUESTION}")
    # Intentionally omit `quit`: the follow-up input() in DBGDialog.dialog
    # sees EOF and breaks; lldb then sees EOF on its command stream and
    # exits cleanly.
    return "\n".join(lines) + "\n"


def build_gdb_script(binary: Path, case: Case, question: str,
                     *, breakpoint_spec: str | None = None,
                     structural_followup: bool = False) -> str:
    args = case.meta.get("run", {}).get("args", [])
    lines = ["source -s chatdbg.chatdbg_gdb"]
    if args:
        quoted = " ".join(shlex.quote(str(a)) for a in args)
        lines.append(f"set args {quoted}")
    if breakpoint_spec:
        lines.append(f"break {breakpoint_spec}")
    lines.append("run")
    lines.append(f"why {question}")
    if structural_followup:
        lines.append(f"why {STRUCTURAL_FIX_QUESTION}")
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
    """Return the bench venv's site-packages path, if a venv exists
    AND its compiled extensions match the current platform.

    Two layouts are supported:
      `.venv-bench-39` — built against Python 3.9 (Apple's bundled lldb).
                         Holds ChatDBG's deps with `ipython<9` etc., the
                         only versions that import on 3.9.
      `.venv-bench`     — built against a newer Python (e.g. for a future
                         lldb that ships with one).

    Cross-platform safety [A8]: when this driver runs inside a Linux
    container with the host repo bind-mounted, a macOS-arm64 .so on
    PYTHONPATH crashes the embedded interpreter with a misleading
    ImportError ("circular import in tiktoken"). Detect the platform of
    the venv's first compiled .so and only return the path if it
    matches the running interpreter.
    """
    import sysconfig
    host_ext_suffix = sysconfig.get_config_var("EXT_SUFFIX") or ""
    for name in (".venv-bench-39", ".venv-bench"):
        venv = REPO_DIR / name
        if not venv.exists():
            continue
        matches = list((venv / "lib").glob("python*/site-packages"))
        if not matches:
            continue
        site_packages = matches[0]
        # Walk a small set of .so files to confirm platform compatibility.
        sample_so = next(site_packages.rglob("*.so"), None)
        if sample_so is None:
            return str(site_packages)
        try:
            magic = sample_so.open("rb").read(4)
        except OSError:
            return str(site_packages)
        # ELF: 0x7F 'E' 'L' 'F'. Mach-O: 0xCFFA EDFE / 0xFEED FACF / etc.
        is_elf = magic[:4] == b"\x7fELF"
        is_macho = magic[:4] in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xce",
                                  b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe")
        running_on_linux = platform.system() == "Linux"
        if running_on_linux and not is_elf:
            return None  # macOS .so on Linux interpreter
        if not running_on_linux and is_elf:
            return None  # ELF .so on macOS interpreter
        # Stronger check: ext suffix should match if we have one.
        if host_ext_suffix and not list(site_packages.rglob(f"*{host_ext_suffix}")):
            # Sample present but no match for our specific suffix —
            # likely Python version mismatch. Skip rather than crash.
            return None
        return str(site_packages)
    return None


def _run_debugger(
    argv: list[str],
    stdin_for_proc,
    env: dict,
    run_dir: Path,
    timeout: float,
) -> tuple[str, str, int, bool]:
    """Spawn the debugger in its own process group so we can kill the whole
    tree on timeout. Returns (stdout, stderr, exit_code, timed_out).

    A1: setsid + killpg ensures a stuck lldb child doesn't outlive the
    Python parent's timeout. We previously observed the orchestrator
    blocked for 47 minutes despite a 240s subprocess.run timeout because
    lldb owned its own process group and ignored the SIGTERM Python sent.
    """
    import os, signal
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if isinstance(stdin_for_proc, str)
              else (stdin_for_proc if stdin_for_proc is not None else subprocess.DEVNULL),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=run_dir,
        start_new_session=True,
    )
    try:
        if isinstance(stdin_for_proc, str):
            stdout, stderr = proc.communicate(input=stdin_for_proc, timeout=timeout)
        else:
            stdout, stderr = proc.communicate(timeout=timeout)
        return (stdout or "", stderr or "", proc.returncode, False)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        return (stdout or "", stderr or "", -1, True)


class Tier3Driver:
    tier: int = 3

    def __init__(
        self, debugger: str = "gdb", dry_run: bool = False,
        containerize: bool = True,
        synthetic_runner_image: str = SYNTHETIC_RUNNER_IMAGE,
    ):
        # `debugger` controls the host-mode legacy path. When
        # containerize=True (default), we always run gdb inside the
        # synthetic-runner container — `debugger` is ignored for
        # synthetic cases. The argument is kept for backward
        # compatibility and for the host-mode opt-out.
        self.debugger = debugger
        self.dry_run = dry_run
        self.containerize = containerize
        self.synthetic_runner_image = synthetic_runner_image

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

        if self.containerize:
            return self._run_synthetic_in_container(spec, run_dir, timeout=timeout)

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
            # S5(b)/B3: synthetic cases can opt into a breakpoint at
            # bug.root_cause_lines[0] (uses source_file as the file)
            # and/or a structural-fix follow-up turn.
            bp_spec = None
            if spec.breakpoint_at_patch:
                rcl = spec.case.meta.get("bug", {}).get("root_cause_lines") or []
                if rcl:
                    bp_spec = f"{spec.case.meta.get('source_file')}:{rcl[0]}"
            script = build_lldb_script(
                binary, spec.case, spec.question,
                breakpoint_spec=bp_spec,
                structural_followup=spec.structural_fix_turn,
            )
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
            bp_spec = None
            if spec.breakpoint_at_patch:
                rcl = spec.case.meta.get("bug", {}).get("root_cause_lines") or []
                if rcl:
                    bp_spec = f"{spec.case.meta.get('source_file')}:{rcl[0]}"
            script = build_gdb_script(
                binary, spec.case, spec.question,
                breakpoint_spec=bp_spec,
                structural_followup=spec.structural_fix_turn,
            )
            (run_dir / "session.cmds").write_text(script)
            argv = ["gdb", "-nx", "-batch-silent"]
            argv += ["-ex", "source /dev/stdin", str(binary)]
            stdin_for_proc = script
        else:
            raise ValueError(f"Unknown debugger: {self.debugger}")

        # Run the debugger session, with up to one retry on the
        # macOS-arm64 lldb attach race (A2). Each attempt enforces the
        # outer timeout via a process-group kill (A1).
        start = time.time()
        attempts = 0
        proc = None
        status = "no_collect"
        exit_code = -1
        while attempts < 2:
            attempts += 1
            stdout_text, stderr_text, exit_code, timed_out = _run_debugger(
                argv, stdin_for_proc, env, run_dir, timeout)
            (run_dir / "stdout.log").write_text(stdout_text)
            (run_dir / "stderr.log").write_text(stderr_text)
            if timed_out:
                elapsed = time.time() - start
                return finalize_result(
                    run_dir, spec,
                    status="timeout", exit_code=-1, elapsed_s=elapsed,
                )
            if collect_path.exists():
                status = "ok"
                break
            # Retry only on the specific lldb attach race.
            attach_failed = (
                "attach failed" in stderr_text and "could not pause" in stderr_text
            )
            if attach_failed and attempts < 2:
                # Wipe stale build/-internal state lldb may have cached.
                continue
            status = "no_collect"
            break

        elapsed = time.time() - start
        return finalize_result(
            run_dir, spec,
            status=status, exit_code=exit_code, elapsed_s=elapsed,
        )

    def _run_synthetic_in_container(
        self, spec: RunSpec, run_dir: Path, *, timeout: float,
    ) -> dict:
        """GDB-everywhere synthetic path: compile + run-under-ChatDBG-gdb
        inside chatdbgpro/synthetic-runner. Mirrors the BugsCPP T3 path
        (DockerDriver) so the only axis varying between synthetic and
        BugsCPP is case content, not debugger or platform."""
        # Stage source + tool config in run_dir so the container sees them.
        # The container has run_dir mounted at both /work (compile here)
        # and /run (artifacts: collect.json, logs, session.cmds).
        source_in_run = run_dir / spec.case.source_path.name
        shutil.copy(spec.case.source_path, source_in_run)
        shutil.copy(spec.tool_config_path, run_dir / "tool_config.json")

        # Compile command — same flags the host-mode path used; clang in
        # the synthetic-runner image accepts the same `-fsanitize=address`
        # / `-std=...` flags. Macros that depend on macOS-only headers
        # (e.g. `-isysroot`) won't work; case authors should avoid them.
        build_cfg = spec.case.meta.get("build", {})
        default_compiler = "clang++" if spec.case.language in ("cpp", "c++") else "clang"
        compiler = build_cfg.get("compiler", default_compiler)
        flags = list(build_cfg.get("flags", []))
        src_in_container = f"/work/{spec.case.source_path.name}"
        bin_in_container = "/work/prog"
        compile_cmd = [compiler, *flags, src_in_container, "-o", bin_in_container]

        # gdb session script. We can't reuse host-mode build_gdb_script's
        # `source -s chatdbg.chatdbg_gdb` syntax — that's gdb's directory-
        # search form, which doesn't do Python module resolution and so
        # never finds the script. Use the absolute /chatdbg-src path
        # instead (same pattern as DockerDriver's _build_gdb_session).
        bp_spec = None
        if spec.breakpoint_at_patch:
            rcl = spec.case.meta.get("bug", {}).get("root_cause_lines") or []
            if rcl:
                bp_spec = f"{spec.case.meta.get('source_file')}:{rcl[0]}"
        script_lines = [
            "set pagination off",
            "set confirm off",
            "set breakpoint pending on",
            "source /chatdbg-src/chatdbg/chatdbg_gdb.py",
        ]
        args = spec.case.meta.get("run", {}).get("args", [])
        if args:
            script_lines.append(
                "set args " + " ".join(shlex.quote(str(a)) for a in args)
            )
        if bp_spec:
            script_lines.append(f"break {bp_spec}")
        script_lines.append("run")
        script_lines.append(f"why {spec.question}")
        if spec.structural_fix_turn:
            script_lines.append(f"why {STRUCTURAL_FIX_QUESTION}")
        script = "\n".join(script_lines) + "\n"
        (run_dir / "session.cmds").write_text(script)

        # Container env — CHATDBG_* paths in /run since that's the artifact
        # mount; PYTHONPATH points at /chatdbg-src (REPO_DIR/src bind-mount)
        # plus the chatdbg-venv site-packages baked into the image.
        # PYTHONPATH covers both the bespoke 3.11 venv layout (gdb-base
        # parent images) and the system-Python 3.12 venv layout (standalone
        # synthetic-runner.Dockerfile). The non-existent path no-ops.
        container_env: dict[str, str] = {
            "CHATDBG_MODEL": spec.model,
            "CHATDBG_TOOL_CONFIG": "/run/tool_config.json",
            "CHATDBG_COLLECT_DATA": "/run/collect.json",
            "CHATDBG_CONTEXT": str(spec.context_lines),
            "CHATDBG_FORMAT": "text",
            "CHATDBG_LOG": "/run/chatdbg.log.yaml",
            "PYTHONPATH": ":".join([
                "/chatdbg-src",
                "/opt/chatdbg-venv/lib/python3.12/site-packages",
                "/opt/chatdbg-venv/lib/python3.11/site-packages",
            ]),
        }
        for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_BASE"):
            v = os.environ.get(key)
            if v:
                container_env[key] = v
        if spec.case.meta.get("run", {}).get("clean_env"):
            for k in list(container_env.keys()):
                if k.startswith("USER") or k in ("LOGNAME", "ADMIN_USER"):
                    container_env.pop(k, None)

        # /work mount = run_dir (compile lands binary here), /run mount =
        # run_dir too (artifacts). Two binds of the same host path to
        # different container paths — fine kernel-wise. hermetic=False
        # because run_dir is already per-run; copying would just hide the
        # compile output from the host.
        #
        # Platform: native (host arch). On Apple Silicon this is
        # linux/arm64 where gdb's ptrace works natively. The BugsCPP T3
        # path is forced to linux/amd64 by hschoe images and requires
        # Docker Desktop's Rosetta-off setting on M-series Macs; this
        # synthetic path sidesteps that by running native.
        # Override via BENCH_T3_SYNTHETIC_PLATFORM=linux/amd64 if you
        # want to compare arches deliberately.
        session_platform = (
            os.environ.get("BENCH_T3_SYNTHETIC_PLATFORM")
            or _native_docker_platform()
        )
        session = ContainerSession(
            image=self.synthetic_runner_image,
            workspace_src=run_dir,
            run_dir=run_dir,
            extra_mounts=[Mount(host=REPO_DIR / "src", container="/chatdbg-src", readonly=True)],
            platform=session_platform,
            ptrace=True,
            hermetic_workspace=False,
            env=container_env,
        )

        if self.dry_run:
            return finalize_result(
                run_dir, spec, status="dry_run", exit_code=0, elapsed_s=0.0,
            )

        start = time.time()
        try:
            with session:
                # Compile
                cr = session.exec_argv(compile_cmd, timeout=60.0)
                (run_dir / "compile.log").write_text(
                    "$ " + " ".join(shlex.quote(c) for c in compile_cmd) + "\n\n"
                    + (cr.stdout or "") + "\n" + (cr.stderr or "")
                )
                if cr.returncode != 0:
                    return finalize_result(
                        run_dir, spec,
                        status="compile_failed", exit_code=cr.returncode,
                        elapsed_s=time.time() - start,
                    )
                # Run gdb under ChatDBG. -batch quits on EOF after the
                # session script's `why` queries.
                gdb_argv = [
                    "gdb", "-nx", "-batch",
                    "-x", "/run/session.cmds",
                    bin_in_container,
                ]
                r = session.exec_argv(gdb_argv, timeout=timeout)
            (run_dir / "stdout.log").write_text(r.stdout)
            (run_dir / "stderr.log").write_text(r.stderr)
            elapsed = r.elapsed_s
            if r.timed_out:
                return finalize_result(
                    run_dir, spec, status="timeout", exit_code=-1, elapsed_s=elapsed,
                )
            collect_path = run_dir / "collect.json"
            status = "ok" if collect_path.exists() else "no_collect"
            return finalize_result(
                run_dir, spec,
                status=status, exit_code=r.returncode, elapsed_s=elapsed,
            )
        except RuntimeError as e:
            (run_dir / "docker_run.log").write_text(str(e))
            return finalize_result(
                run_dir, spec,
                status="docker_run_failed", exit_code=-1,
                elapsed_s=time.time() - start,
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
            # subprocess.TimeoutExpired.stdout/stderr are bytes even when the
            # original call used text=True. Coerce so write_text doesn't
            # TypeError out and mask the real status as "error".
            def _decode(x):
                if isinstance(x, bytes):
                    return x.decode("utf-8", errors="replace")
                return x or ""
            (run_dir / "stdout.log").write_text(_decode(e.stdout))
            (run_dir / "stderr.log").write_text(_decode(e.stderr))
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
