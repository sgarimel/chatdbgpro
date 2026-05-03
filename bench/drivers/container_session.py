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

# Container runtime override. If set, ContainerSession uses this runtime
# unless an instance passes `runtime=` explicitly. Set by the orchestrator
# (or by hand on HPC clusters where docker is unavailable). Valid values:
# "docker" or "apptainer". Falls back to auto-detect if None.
_DEFAULT_RUNTIME: str | None = None


def set_default_sweep_label(label: str | None) -> None:
    """Set the sweep label that subsequent ContainerSession instances
    will inherit if they don't pass `sweep_label=` explicitly. The
    orchestrator calls this once at sweep start."""
    global _DEFAULT_SWEEP_LABEL
    _DEFAULT_SWEEP_LABEL = label


def set_default_runtime(name: str | None) -> None:
    """Set the container runtime that subsequent ContainerSession
    instances will use unless they pass `runtime=` explicitly.
    Valid values: "docker", "apptainer", or None (auto-detect)."""
    global _DEFAULT_RUNTIME
    _DEFAULT_RUNTIME = name


def detect_runtime() -> str:
    """Pick a container runtime based on what's installed on PATH.
    Preference: docker (faster on dev machines) over apptainer/singularity
    (HPC fallback). `singularity` is treated as a synonym for `apptainer`
    since modern singularity ships as apptainer with the legacy CLI name.
    """
    if shutil.which("docker"):
        return "docker"
    if shutil.which("apptainer") or shutil.which("singularity"):
        return "apptainer"
    raise RuntimeError(
        "No container runtime found on PATH. Install docker, apptainer, "
        "or singularity, or pass runtime= explicitly."
    )


def _apptainer_cli() -> str:
    """Return the apptainer/singularity CLI on PATH. Apptainer is preferred;
    older HPC sites still ship `singularity` (which is now an apptainer
    alias on RHEL 9-era systems)."""
    return shutil.which("apptainer") or shutil.which("singularity") or "apptainer"


def resolve_runtime(explicit: str | None = None) -> str:
    """Public helper: resolve the runtime a driver should use.

    Resolution order:
      1. `explicit` arg (caller pinned)
      2. _DEFAULT_RUNTIME (orchestrator-set via set_default_runtime())
      3. detect_runtime() (PATH-based auto-pick)

    Driver code that spawns a subprocess needing to know the runtime
    (mini-swe-agent runners exec'ing into the per-case container) can
    use this to decide what --container-runtime to pass to the child.
    """
    return explicit or _DEFAULT_RUNTIME or detect_runtime()


def container_exec_argv(
    runtime: str, container_name: str, *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    interactive: bool = False,
) -> list[str]:
    """Build the bare-metal argv prefix for `<runtime> exec <container> ...`.

    Mirrors ContainerSession._exec_prefix but works WITHOUT a live
    session — useful for subprocess runners (tier1/tier2_runner.py) that
    only know the container name and a runtime string. Caller appends
    the actual command (e.g. `["bash", "-c", cmd]`).
    """
    if runtime == "docker":
        prefix = ["docker", "exec"]
        if interactive:
            prefix.append("-i")
        if cwd is not None:
            prefix += ["-w", cwd]
        for k, v in (env or {}).items():
            prefix += ["-e", f"{k}={v}"]
        prefix.append(container_name)
        return prefix
    if runtime == "apptainer":
        prefix = [_apptainer_cli(), "exec"]
        if cwd is not None:
            prefix += ["--pwd", cwd]
        for k, v in (env or {}).items():
            prefix += ["--env", f"{k}={v}"]
        prefix.append(f"instance://{container_name}")
        return prefix
    raise ValueError(f"Unknown runtime: {runtime!r}")


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
    """Configuration for a long-lived per-case Linux container.

    Two backends, same API:
      - runtime="docker"    — `docker run -d ... sleep infinity` + `docker exec`
      - runtime="apptainer" — `apptainer instance start <sif>` + `apptainer exec instance://`

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

    Image refs:
      - docker: standard docker tag, e.g. "chatdbgpro/gdb-yara:latest".
      - apptainer: either a SIF path (`/path/to/img.sif`), a registry
        URI (`docker://docker.io/foo/bar:tag`), or a local docker daemon
        ref (`docker-daemon://foo/bar:tag`). The `image` field carries
        whichever string apptainer's CLI accepts.
    """
    image: str
    workspace_src: Path
    run_dir: Path

    # --- Runtime ---------------------------------------------------------
    # "docker", "apptainer", or "" (resolve via _DEFAULT_RUNTIME or detect_runtime()).
    runtime: str = ""

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
    # Apptainer in user-namespace mode allows ptrace by default for the
    # user's own processes — the flag still propagates so docker can do
    # the right thing.
    ptrace: bool = False
    # Memory cap to prevent runaway model-issued processes.
    # Apptainer doesn't enforce cgroup limits in unprivileged mode; this
    # is silently ignored for runtime="apptainer".
    memory_limit: str = "4g"
    # Pids cap — same reason. Same caveat for apptainer.
    pids_limit: int = 512
    # Apptainer-only: enable --writable-tmpfs so the container rootfs
    # gets a tmpfs overlay (allows `apt-get install` etc. inside an
    # otherwise read-only squashfs image). Tmpfs is wiped on instance
    # stop. Default True since the cost is small and it makes the harness
    # work with stock images that need on-the-fly tool installs.
    writable_tmpfs: bool = True

    # --- Workspace hermeticity --------------------------------------------
    # If True, copy workspace_src to a per-run scratch dir and mount that
    # instead of the original. Strongly recommended for benchmarking.
    hermetic_workspace: bool = True
    # Override the scratch parent (default: tempfile.gettempdir()).
    scratch_parent: Path | None = None

    # --- Identification / fleet management --------------------------------
    # Container/instance name. Auto-generated if None. Visible to the
    # agent (T4's prompt mentions it for `docker exec` / `apptainer exec`).
    name: str | None = None
    # Optional sweep-level label. Docker uses --label; apptainer doesn't
    # expose labels, so we encode it in the instance name suffix (`-l-X`)
    # so prune_sweep can still find orphans by name pattern.
    sweep_label: str | None = None

    # --- Env vars passed to `docker run` / `apptainer instance start` -----
    env: dict[str, str] = field(default_factory=dict)

    # --- Internal state (filled at __enter__) -----------------------------
    _container_id: str | None = field(default=None, init=False, repr=False)
    _scratch_dir: Path | None = field(default=None, init=False, repr=False)
    _started: bool = field(default=False, init=False, repr=False)
    _resolved_runtime: str = field(default="", init=False, repr=False)

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

        # Resolve runtime once and pin it for the session's lifetime.
        rt = self.runtime or _DEFAULT_RUNTIME or detect_runtime()
        if rt not in ("docker", "apptainer"):
            raise ValueError(f"Unknown runtime: {rt!r}")
        self._resolved_runtime = rt

        if self.name is None:
            # Container/instance name: alnum + - + _, ≤64 chars.
            base = f"bench-{uuid.uuid4().hex[:24]}"
            label = self.sweep_label or _DEFAULT_SWEEP_LABEL
            if label and rt == "apptainer":
                # Apptainer has no --label; encode in name so prune_sweep
                # can match it via name pattern.
                # Sanitize label for instance-name compatibility.
                safe_label = "".join(c if c.isalnum() else "-" for c in label)[:30]
                base = f"bench-{safe_label}-{uuid.uuid4().hex[:12]}"
            self.name = base

        self._maybe_copy_workspace()

        try:
            if rt == "docker":
                self._enter_docker()
            else:
                self._enter_apptainer()
        except Exception:
            self._maybe_remove_scratch()
            raise

        self._started = True
        with _CLEANUP_LOCK:
            _LIVE_SESSIONS.add(self)
        return self

    def _enter_docker(self) -> None:
        argv: list[str] = [
            "docker", "run", "-d", "--rm",
            "--name", self.name,
            "-v", f"{self.workspace_mount_path().resolve()}:{self.workspace_in_container}",
            "-v", f"{self.run_dir.resolve()}:{self.run_dir_in_container}",
            "--memory", self.memory_limit,
            "--pids-limit", str(self.pids_limit),
        ]
        if self.platform:
            argv += ["--platform", self.platform]
        for mnt in self.extra_mounts:
            spec = f"{mnt.host.resolve()}:{mnt.container}"
            if mnt.readonly:
                spec += ":ro"
            argv += ["-v", spec]
        if self.ptrace:
            argv += [
                "--cap-add", "SYS_PTRACE",
                "--security-opt", "seccomp=unconfined",
            ]
        for k, v in self.env.items():
            argv += ["-e", f"{k}={v}"]
        effective_label = self.sweep_label or _DEFAULT_SWEEP_LABEL
        if effective_label:
            argv += ["--label", f"bench-runner={effective_label}"]
        argv += ["-w", self.workspace_in_container]
        argv += [self.image, "sleep", "infinity"]

        proc = subprocess.run(
            argv, capture_output=True, text=True, env=_docker_env(),
            timeout=120.0,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"docker run failed (exit {proc.returncode}):\n"
                f"  argv: {' '.join(shlex.quote(a) for a in argv)}\n"
                f"  stderr: {proc.stderr.strip()}"
            )
        self._container_id = (proc.stdout or "").strip()

    def _enter_apptainer(self) -> None:
        """Start a long-lived apptainer instance.

        Apptainer's lifecycle: `apptainer instance start <image> <name>`
        runs the image's startup script in the background; subsequent
        `apptainer exec instance://<name> ...` calls execute commands
        inside it. Mounts, env, and ptrace mostly map 1:1, but the
        flags differ:
          docker -v src:dst     →   apptainer --bind src:dst
          docker -e K=V         →   apptainer --env K=V
          docker -w PATH        →   apptainer --pwd PATH
          docker --cap-add ...  →   (none — userns gives ptrace by default)
          docker --memory ...   →   (none — only with --apply-cgroups, root only)
          docker --label ...    →   (none — encoded in instance name)
        """
        cli = _apptainer_cli()
        argv: list[str] = [cli, "instance", "start"]
        if self.writable_tmpfs:
            argv += ["--writable-tmpfs"]
        # Bind mounts. Apptainer auto-binds $HOME, /tmp, /sys, /proc; our
        # explicit binds are layered on top.
        argv += [
            "--bind",
            f"{self.workspace_mount_path().resolve()}:{self.workspace_in_container}",
        ]
        argv += [
            "--bind",
            f"{self.run_dir.resolve()}:{self.run_dir_in_container}",
        ]
        for mnt in self.extra_mounts:
            spec = f"{mnt.host.resolve()}:{mnt.container}"
            if mnt.readonly:
                spec += ":ro"
            argv += ["--bind", spec]
        # Env vars pass via --env K=V (apptainer ≥1.1).
        for k, v in self.env.items():
            argv += ["--env", f"{k}={v}"]
        # Note: `apptainer instance start` does NOT accept --pwd (unlike
        # `apptainer exec`). The startup process's cwd is whatever the
        # caller's pwd was; per-exec cwd is set on each `apptainer exec
        # --pwd ...` call (handled in _exec_prefix). The host pwd
        # generally doesn't matter since we only use the instance for
        # exec'ing in defined working dirs.
        # Image ref + instance name. apptainer accepts:
        #   /path/to/img.sif
        #   docker://docker.io/foo/bar:tag
        #   docker-daemon://foo/bar:tag (only if local docker daemon present)
        argv += [self.image, self.name]

        proc = subprocess.run(
            argv, capture_output=True, text=True, env=_docker_env(),
            timeout=300.0,  # apptainer pull from registry can take minutes
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"apptainer instance start failed (exit {proc.returncode}):\n"
                f"  argv: {' '.join(shlex.quote(a) for a in argv)}\n"
                f"  stderr: {proc.stderr.strip()}\n"
                f"  stdout: {proc.stdout.strip()}"
            )
        # Apptainer instances aren't identified by a hash like docker; the
        # name IS the canonical handle. Store it consistently.
        self._container_id = self.name

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
        rt = self._resolved_runtime or "docker"
        if self.name:
            try:
                if rt == "docker":
                    subprocess.run(
                        ["docker", "rm", "-f", self.name],
                        capture_output=True, text=True, env=_docker_env(),
                        timeout=15.0,
                    )
                else:  # apptainer
                    subprocess.run(
                        [_apptainer_cli(), "instance", "stop", self.name],
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
        rt = self._resolved_runtime or "docker"
        if rt == "docker":
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
        # apptainer
        prefix = [_apptainer_cli(), "exec"]
        # apptainer exec needs no -i flag — it's always pipe-friendly.
        if cwd is not None:
            prefix += ["--pwd", cwd]
        # Apptainer's `instance start --env K=V` does NOT propagate to
        # subsequent `apptainer exec` calls — each exec is a fresh
        # process with its own env. Re-pass the session-level env on
        # every exec so the container actually sees it. Per-call env
        # (passed via the env= arg) is layered on top.
        merged: dict[str, str] = {}
        if self.env:
            merged.update(self.env)
        if env:
            merged.update(env)
        for k, v in merged.items():
            prefix += ["--env", f"{k}={v}"]
        prefix.append(f"instance://{self.container_name}")
        return prefix

    # ------------------------------------------------------------------
    def gdb_command_prefix(
        self, *, cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> list[str]:
        """Return the argv prefix to launch a long-lived gdb subprocess
        inside the session. Used by T2's `GdbSessionConfig.command_prefix`
        so the same `gdb -q -nx --args ...` invocation works under both
        docker and apptainer.

        Caller appends the gdb executable + args. Example:
            cfg.command_prefix = session.gdb_command_prefix(cwd="/work")
            argv = cfg.command_prefix + ["gdb", "-q", "--args", binary, ...]
        """
        # The prefix needs an interactive-style stdio setup. Docker needs
        # explicit `-i`; apptainer's exec is always interactive. Reuse
        # _exec_prefix to keep the cwd/env logic in one place.
        return self._exec_prefix(cwd=cwd, env=env, interactive=True)

    # ------------------------------------------------------------------
    def docker_exec_template(self, *, cwd: str | None = "/work") -> str:
        """Return a human-readable shell template for the agent's task
        prompt, e.g. 'docker exec -w /work <name> bash -c ...' or
        'apptainer exec --pwd /work instance://<name> bash -c ...'.

        Used by T4's prompt builder so Claude's Bash tool can target the
        container correctly regardless of runtime."""
        prefix = self._exec_prefix(cwd=cwd, interactive=True)
        return " ".join(shlex.quote(p) for p in prefix) + " bash -c '<cmd>'"

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
    """Remove every bench-* container/instance for the given sweep.

    Docker: filtered by label. Apptainer: filtered by instance-name
    pattern (since apptainer has no labels — see _enter_apptainer's
    note on encoding the label in the name).

    Returns the total count removed across runtimes.
    """
    if not sweep_label:
        return 0
    removed = 0

    # Docker side.
    if shutil.which("docker"):
        r = subprocess.run(
            ["docker", "ps", "-aq", "--filter", f"label=bench-runner={sweep_label}"],
            capture_output=True, text=True, env=_docker_env(),
        )
        ids = [x for x in (r.stdout or "").split() if x]
        if ids:
            subprocess.run(
                ["docker", "rm", "-f", *ids],
                capture_output=True, text=True, env=_docker_env(),
            )
            removed += len(ids)

    # Apptainer side.
    cli = shutil.which("apptainer") or shutil.which("singularity")
    if cli:
        # `apptainer instance list` prints columns with header. Match
        # instance names that start with bench-<safe_label>-.
        r = subprocess.run(
            [cli, "instance", "list"],
            capture_output=True, text=True, env=_docker_env(),
        )
        safe_label = "".join(c if c.isalnum() else "-" for c in sweep_label)[:30]
        prefix = f"bench-{safe_label}-"
        names: list[str] = []
        for line in (r.stdout or "").splitlines():
            tok = line.split()
            if not tok:
                continue
            if tok[0].startswith(prefix):
                names.append(tok[0])
        for n in names:
            subprocess.run(
                [cli, "instance", "stop", n],
                capture_output=True, text=True, env=_docker_env(),
            )
        removed += len(names)

    return removed
