"""ContainerSession: long-lived per-case Linux container as the agent's exec surface.

The unifying primitive for BugsCPP runs (and synthetic-T3 in-container runs).
A single `docker run -d --rm sleep infinity` per case provides a stable
shell environment with the buggy workspace bind-mounted at /work and the
run_dir at /run. Tier drivers route all execution through this session
via .exec() (one-shot bash) or .exec_streaming() (piped, e.g. gdb-mi).

Why per-case instead of per-command:
  - Preserves cwd, env, files written across commands (a model that does
    `cd build && make && ./prog` mustn't have its cwd reset per command).
  - Persistent gdb (T2/T3) needs a long-lived stdin/stdout pipe.
  - Container startup is ~1-2s; amortizing across 50-100 model commands
    drops per-command overhead from ~1s to ~50ms.

Workspace hermeticity: workspaces are deep-copied to a per-run scratch
dir before mounting. Models that run `make`, apply patches, or mutate
files do not pollute the canonical workspace (and therefore future runs).
The copy uses `cp -a` for speed (APFS clonefile / reflinks where
available), falling back to shutil.copytree.

Cleanup robustness (belt + suspenders):
  1. `docker run --rm` — kernel removes container on exit.
  2. `__exit__` calls `docker rm -f` explicitly.
  3. atexit handler removes any sessions that escaped scope.
  4. SIGTERM/SIGINT handlers — same path as atexit.
  5. Sweep-level fleet cleanup via `--label bench-runner=<sweep_id>`.

Thread/process safety: each ContainerSession owns one Docker container.
The same Python process can hold many sessions concurrently (one per
in-flight case in a parallel sweep); their docker CLI calls don't share
state.
"""
from __future__ import annotations

import atexit
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO


# Track every live session so atexit / signal handlers can clean up
# orphans (e.g. when a driver crashes between __enter__ and __exit__).
_LIVE_SESSIONS: "weakref.WeakSet[ContainerSession]" = weakref.WeakSet()
_CLEANUP_LOCK = threading.Lock()
_HANDLERS_INSTALLED = False

# Sweep label set by the orchestrator at sweep start. Every
# ContainerSession created during the sweep auto-tags its container with
# this label so a single `prune_sweep(run_name)` at sweep end can clean
# any orphans. Drivers don't need to know about it.
_DEFAULT_SWEEP_LABEL: str | None = None


def set_default_sweep_label(label: str | None) -> None:
    """Set the sweep label that subsequent ContainerSession instances
    will inherit if they don't pass `sweep_label=` explicitly. The
    orchestrator calls this once at sweep start."""
    global _DEFAULT_SWEEP_LABEL
    _DEFAULT_SWEEP_LABEL = label


def _docker_env() -> dict:
    """subprocess env for docker calls — disables Git Bash / MSYS path
    munging so bind-mount paths aren't rewritten on Windows."""
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    env.setdefault("MSYS2_ARG_CONV_EXCL", "*")
    return env


def _install_global_handlers() -> None:
    """Register one-shot atexit + signal handlers that nuke any live
    container sessions. Idempotent across multiple sessions in the same
    process."""
    global _HANDLERS_INSTALLED
    if _HANDLERS_INSTALLED:
        return
    _HANDLERS_INSTALLED = True

    def _cleanup_all(*_):
        # Snapshot under lock to avoid mutation during iteration.
        with _CLEANUP_LOCK:
            sessions = list(_LIVE_SESSIONS)
        for s in sessions:
            try:
                s._force_remove()
            except Exception:  # noqa: BLE001 — cleanup is best-effort
                pass

    atexit.register(_cleanup_all)
    # Don't replace existing signal handlers if the orchestrator (or
    # pytest) installed its own — chain instead.
    for sig in (signal.SIGTERM, signal.SIGINT):
        prev = signal.getsignal(sig)

        def _handler(signum, frame, _prev=prev):
            _cleanup_all()
            if callable(_prev):
                _prev(signum, frame)
            elif _prev == signal.SIG_DFL:
                # Re-raise default behavior (terminate).
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)

        try:
            signal.signal(sig, _handler)
        except ValueError:
            # signal() can only be called from the main thread. The
            # atexit handler is sufficient for non-main-thread invocations.
            pass


@dataclass
class ExecResult:
    """One-shot exec result. Mirrors subprocess.CompletedProcess shape
    but always carries elapsed time and a `timed_out` flag."""
    returncode: int
    stdout: str
    stderr: str
    elapsed_s: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass
class Mount:
    host: Path
    container: str  # absolute path inside container
    readonly: bool = False


# eq=False so instances hash by identity — a ContainerSession is a
# stateful resource (a live container), not a value, and we put live
# sessions in a WeakSet for cleanup.
@dataclass(eq=False)
class ContainerSession:
    """Configuration for a long-lived per-case Docker container.

    Use as a context manager:

        with ContainerSession(image="chatdbgpro/gdb-yara:latest",
                              workspace_src=ws_path,
                              run_dir=run_dir,
                              ptrace=True) as session:
            r = session.exec("gdb --version")
            ...

    The container is started on __enter__ and removed on __exit__ (and
    via atexit/signal as a safety net). Do NOT cache or reuse a session
    across cases — workspace mounts are per-case.
    """
    image: str
    workspace_src: Path
    run_dir: Path

    # --- Mount layout ------------------------------------------------------
    # Workspace is bind-mounted at this path inside the container.
    workspace_in_container: str = "/work"
    # run_dir is bind-mounted RW at this path (collect.json, logs, etc.).
    run_dir_in_container: str = "/run"
    # Additional mounts (host_path, container_path, readonly).
    extra_mounts: list[Mount] = field(default_factory=list)

    # --- Container behavior -----------------------------------------------
    platform: str = "linux/amd64"
    # gdb / debuggers need ptrace; seccomp must be relaxed too.
    ptrace: bool = False
    # Memory cap to prevent runaway model-issued processes.
    memory_limit: str = "4g"
    # Pids cap — same reason.
    pids_limit: int = 512

    # --- Workspace hermeticity --------------------------------------------
    # If True, copy workspace_src to a per-run scratch dir and mount that
    # instead of the original. Strongly recommended for benchmarking.
    hermetic_workspace: bool = True
    # Override the scratch parent (default: tempfile.gettempdir()).
    scratch_parent: Path | None = None

    # --- Identification / fleet management --------------------------------
    # Container name. Auto-generated if None. Visible to the agent (e.g.
    # T4's prompt mentions it for `docker exec`).
    name: str | None = None
    # Optional sweep-level label so a single `docker container prune
    # --filter label=bench-runner=<sweep_id>` cleans the fleet.
    sweep_label: str | None = None

    # --- Env vars passed to `docker run` (visible to processes inside) ----
    env: dict[str, str] = field(default_factory=dict)

    # --- Internal state (filled at __enter__) -----------------------------
    _container_id: str | None = field(default=None, init=False, repr=False)
    _scratch_dir: Path | None = field(default=None, init=False, repr=False)
    _started: bool = field(default=False, init=False, repr=False)

    # ------------------------------------------------------------------
    def workspace_mount_path(self) -> Path:
        """Host-side path actually bind-mounted at workspace_in_container.
        Equals `workspace_src` if hermetic=False, else the scratch copy."""
        if self.hermetic_workspace:
            assert self._scratch_dir is not None, "session not started"
            return self._scratch_dir
        return self.workspace_src

    @property
    def container_name(self) -> str:
        assert self.name is not None
        return self.name

    # ------------------------------------------------------------------
    def __enter__(self) -> "ContainerSession":
        if self._started:
            raise RuntimeError("ContainerSession already started")
        _install_global_handlers()

        if self.name is None:
            # Docker name: alnum + - + _, max 64 chars.
            self.name = f"bench-{uuid.uuid4().hex[:24]}"

        self._maybe_copy_workspace()

        argv: list[str] = [
            "docker", "run", "-d", "--rm",
            "--name", self.name,
            "-v", f"{self.workspace_mount_path().resolve()}:{self.workspace_in_container}",
            "-v", f"{self.run_dir.resolve()}:{self.run_dir_in_container}",
            "--memory", self.memory_limit,
            "--pids-limit", str(self.pids_limit),
        ]
        # Pass --platform only when non-empty. An empty string means
        # "let docker pick the native arch" — useful for synthetic
        # runners that need to avoid emulation.
        if self.platform:
            argv += ["--platform", self.platform]
        for mnt in self.extra_mounts:
            spec = f"{mnt.host.resolve()}:{mnt.container}"
            if mnt.readonly:
                spec += ":ro"
            argv += ["-v", spec]
        if self.ptrace:
            # gdb needs ptrace + relaxed seccomp. Without seccomp tweak
            # the default Docker profile blocks personality(ADDR_NO_RANDOMIZE)
            # which gdb 14 issues at attach time.
            argv += [
                "--cap-add", "SYS_PTRACE",
                "--security-opt", "seccomp=unconfined",
            ]
        for k, v in self.env.items():
            argv += ["-e", f"{k}={v}"]
        # Auto-inherit the sweep-wide label if the caller didn't set one.
        # Set by orchestrator via set_default_sweep_label() at sweep start.
        effective_label = self.sweep_label or _DEFAULT_SWEEP_LABEL
        if effective_label:
            argv += ["--label", f"bench-runner={effective_label}"]
        # Workdir defaults to /work for ergonomics.
        argv += ["-w", self.workspace_in_container]
        argv += [self.image, "sleep", "infinity"]

        proc = subprocess.run(
            argv, capture_output=True, text=True, env=_docker_env(),
            timeout=120.0,
        )
        if proc.returncode != 0:
            self._maybe_remove_scratch()
            raise RuntimeError(
                f"docker run failed (exit {proc.returncode}):\n"
                f"  argv: {' '.join(shlex.quote(a) for a in argv)}\n"
                f"  stderr: {proc.stderr.strip()}"
            )
        self._container_id = (proc.stdout or "").strip()
        self._started = True
        with _CLEANUP_LOCK:
            _LIVE_SESSIONS.add(self)
        return self

    def _maybe_copy_workspace(self) -> None:
        if not self.hermetic_workspace:
            return
        parent = self.scratch_parent or Path(tempfile.gettempdir())
        parent.mkdir(parents=True, exist_ok=True)
        # Use a unique subdir to avoid collisions across concurrent runs.
        scratch = parent / f"bench-ws-{uuid.uuid4().hex[:12]}"
        # Prefer `cp -a` for CoW on APFS / reflinks on btrfs/xfs. Fall
        # back to shutil.copytree on platforms without `cp` (Windows).
        cp_cmd = self._cp_command(self.workspace_src.resolve(), scratch)
        if cp_cmd is not None:
            r = subprocess.run(cp_cmd, capture_output=True, text=True)
            if r.returncode != 0:
                shutil.rmtree(scratch, ignore_errors=True)
                # Fall through to shutil.
                shutil.copytree(self.workspace_src, scratch, symlinks=True)
        else:
            shutil.copytree(self.workspace_src, scratch, symlinks=True)
        self._scratch_dir = scratch

    @staticmethod
    def _cp_command(src: Path, dst: Path) -> list[str] | None:
        """Best `cp` invocation for the host. Returns None on Windows
        (no native `cp`)."""
        if sys.platform == "win32":
            return None
        if sys.platform == "darwin":
            # APFS clonefile via `cp -c` (BSD `cp`). -R recursive, -p
            # preserve attrs. `-c` does CoW where possible (APFS only).
            return ["cp", "-cRp", str(src), str(dst)]
        # Linux: GNU cp with --reflink=auto (CoW on btrfs/xfs).
        return ["cp", "-a", "--reflink=auto", str(src), str(dst)]

    def _maybe_remove_scratch(self) -> None:
        if self._scratch_dir is not None and self._scratch_dir.exists():
            shutil.rmtree(self._scratch_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._force_remove()

    def _force_remove(self) -> None:
        """Idempotent cleanup: removes container + scratch workspace.
        Safe to call from atexit/signal context."""
        with _CLEANUP_LOCK:
            try:
                _LIVE_SESSIONS.discard(self)
            except Exception:  # noqa: BLE001
                pass
        if not self._started:
            self._maybe_remove_scratch()
            return
        self._started = False
        if self.name:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", self.name],
                    capture_output=True, text=True, env=_docker_env(),
                    timeout=15.0,
                )
            except Exception:  # noqa: BLE001
                pass  # best effort — atexit/signal still fires
        self._maybe_remove_scratch()

    # ------------------------------------------------------------------
    def exec(
        self, cmd: str, *,
        timeout: float | None = 60.0,
        stdin_data: str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Run a single bash command inside the container. Returns an
        ExecResult capturing stdout, stderr, returncode, elapsed time
        and a timed_out flag."""
        if not self._started or self._container_id is None:
            raise RuntimeError("ContainerSession not started")
        argv = self._exec_prefix(cwd=cwd, env=env)
        argv += ["bash", "-c", cmd]
        return self._run(argv, timeout=timeout, stdin_data=stdin_data)

    def exec_argv(
        self, argv: list[str], *,
        timeout: float | None = 60.0,
        stdin_data: str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Run an argv directly (no `bash -c` shell parsing). Use when
        the caller has already tokenized and wants exact argv semantics."""
        if not self._started or self._container_id is None:
            raise RuntimeError("ContainerSession not started")
        prefix = self._exec_prefix(cwd=cwd, env=env)
        return self._run(prefix + argv, timeout=timeout, stdin_data=stdin_data)

    def exec_streaming(
        self, argv: list[str], *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: int | IO | None = subprocess.PIPE,
        stdout: int | IO | None = subprocess.PIPE,
        stderr: int | IO | None = subprocess.STDOUT,
        bufsize: int = 1,
        text: bool = True,
    ) -> subprocess.Popen:
        """Spawn a docker exec process for piped interactive use. The
        returned Popen is owned by the caller — they must close stdin /
        wait() on it. Used by T2/T3 to run gdb inside the container with
        the model driving its stdin.

        Note: text=True / bufsize=1 give line-buffered stdio, which is
        what GdbSession's sentinel-line protocol assumes."""
        if not self._started or self._container_id is None:
            raise RuntimeError("ContainerSession not started")
        full_argv = self._exec_prefix(cwd=cwd, env=env, interactive=True) + argv
        return subprocess.Popen(
            full_argv,
            stdin=stdin, stdout=stdout, stderr=stderr,
            bufsize=bufsize, text=text, env=_docker_env(),
        )

    # ------------------------------------------------------------------
    def _exec_prefix(
        self, *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        interactive: bool = False,
    ) -> list[str]:
        prefix = ["docker", "exec"]
        if interactive:
            prefix.append("-i")
        if cwd is not None:
            prefix += ["-w", cwd]
        if env:
            for k, v in env.items():
                prefix += ["-e", f"{k}={v}"]
        prefix.append(self.container_name)
        return prefix

    def _run(
        self, argv: list[str], *,
        timeout: float | None,
        stdin_data: str | None,
    ) -> ExecResult:
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_docker_env(),
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired as e:
            elapsed = time.monotonic() - t0
            return ExecResult(
                returncode=-1,
                stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
                stderr=(e.stderr or "") if isinstance(e.stderr, str) else "",
                elapsed_s=elapsed,
                timed_out=True,
            )
        elapsed = time.monotonic() - t0
        return ExecResult(
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            elapsed_s=elapsed,
        )


# ---------------------------------------------------------------------------
# Sweep-level fleet cleanup
# ---------------------------------------------------------------------------

def prune_sweep(sweep_label: str) -> int:
    """Remove every container labeled bench-runner=<sweep_label>. Useful
    at orchestrator end as a final safety net. Returns the number of
    containers removed."""
    if not sweep_label:
        return 0
    r = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=bench-runner={sweep_label}"],
        capture_output=True, text=True, env=_docker_env(),
    )
    ids = [x for x in (r.stdout or "").split() if x]
    if not ids:
        return 0
    subprocess.run(
        ["docker", "rm", "-f", *ids],
        capture_output=True, text=True, env=_docker_env(),
    )
    return len(ids)
