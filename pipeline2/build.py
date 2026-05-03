"""Build each bug's buggy workspace; probe once for optional gdb metadata.

Pipeline2 per-bug steps (post-seed, which has already populated ground-truth
patch fields):

  1. Checkout buggy into data/workspaces/<bug_id>/<project>/buggy-<idx>/
  2. Build via bugscpp
  3. Optional single gdb probe (for the judge's structured-field rubric) —
     captures crash_signal + user_frame_*; if no crash, runs the trigger
     once outside gdb for exit_code
  4. Apply inclusion gate: build_ok AND patch_first_file AND patch_path.
     (Crash is NOT required — non-crash logical-error bugs are still
     debuggable via state inspection.)

Projects schedule in parallel (--workers); bugs within a project are serial
because bugscpp's CLI reuses the fixed `<project>-dpp` container name.
Resumable via --resume (skips rows where built_at IS NOT NULL).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "corpus.db"
WORKSPACES_DIR = REPO_ROOT / "data" / "workspaces"
BACKTRACES_DIR = REPO_ROOT / "data" / "backtraces"

sys.path.insert(0, str(REPO_ROOT / "pipeline2"))
from ensure_image import ensure_gdb_image  # noqa: E402

DB_LOCK = threading.Lock()


def bugscpp_repo() -> Path:
    repo = os.environ.get("BUGSCPP_REPO")
    return Path(repo) if repo else REPO_ROOT.parent / "bugscpp"


def _bugscpp_python() -> str:
    """Resolve the python interpreter that has bugscpp's deps installed.

    Priority:
      1. $BUGSCPP_PYTHON if set (explicit override)
      2. <BUGSCPP_REPO>/.venv/bin/python (created by `python -m venv .venv`
         inside the bugscpp clone, our standard setup on Mac/Linux)
      3. <BUGSCPP_REPO>/.venv/Scripts/python.exe (Windows venv layout)
      4. bare `python` (legacy — assumes system python has docker, GitPython, etc.)
    """
    env = os.environ.get("BUGSCPP_PYTHON")
    if env:
        return env
    repo = bugscpp_repo()
    for cand in (repo / ".venv" / "bin" / "python", repo / ".venv" / "Scripts" / "python.exe"):
        if cand.exists():
            return str(cand)
    return "python"


def run_bugscpp(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    cmd = [_bugscpp_python(), str(bugscpp_repo() / "bugscpp" / "bugscpp.py"), *args]
    # Pass _docker_env() so DOCKER_DEFAULT_PLATFORM=linux/amd64 reaches
    # bugscpp's internal `docker build` calls on Apple Silicon hosts.
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=_docker_env(),
    )


def _docker_env() -> dict:
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    env.setdefault("MSYS2_ARG_CONV_EXCL", "*")
    # Apple Silicon: bugscpp's `checkout` builds Dockerfiles whose
    # base image (hschoe/defects4cpp-ubuntu:<project>) is amd64-only,
    # and bugscpp itself doesn't pass --platform. DOCKER_DEFAULT_PLATFORM
    # is Docker's standard env var for this; honored by every docker
    # subprocess in the chain (build, run, exec) without modifying
    # bugscpp's source.
    env.setdefault("DOCKER_DEFAULT_PLATFORM", "linux/amd64")
    return env


def _bind_path(p: Path) -> str:
    return str(p.resolve())


def force_rmtree(path: Path) -> None:
    if not path.exists():
        return

    def _onerror(func, p, exc_info):
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass

    try:
        shutil.rmtree(path, onexc=_onerror)
    except TypeError:
        shutil.rmtree(path, onerror=_onerror)


# ─── gdb_command construction ────────────────────────────────────────────────

GDB_PREAMBLE = (
    'export LD_LIBRARY_PATH="$(find /work -type d -name .libs -printf \'%p:\')'
    '${LD_LIBRARY_PATH:-}"'
)
GDB_FLAGS = [
    "-batch",
    "-ex", "set pagination off",
    "-ex", "set confirm off",
    "-ex", "set follow-fork-mode child",
    "-ex", "set detach-on-fork on",
    "-ex", "run",
    "-ex", "bt full",
    "-ex", "quit",
]


def trigger_binary_path(workspace: Path, trigger_argv: list[str]) -> Path | None:
    """Best-effort host path of the trigger executable, or None if we can't
    statically determine one.

    Returns a Path only when we're confident the binary should physically
    exist in the workspace tree:
      - direct argv[0] with a `/` in it (e.g. `tools/tiffcrop`)
      - `./X` style relative paths
      - `bash -c "<inner>"` (or nested) when the first real token is one of
        the above

    Returns None (skip the existence check) for:
      - absolute paths (resolve inside container, not host)
      - bare names (`make`, `python`, `bash`) — system tools on $PATH
      - shell expansions (`$(find ...)`, redirects, pipes)
      - empty / unparseable triggers

    The caller treats None as "don't enforce" so the binary check only
    fires when we have a positive path expectation.
    """
    if not trigger_argv:
        return None

    candidate: str | None = None
    if trigger_argv[:2] == ["bash", "-c"] and len(trigger_argv) >= 3:
        import shlex
        try:
            inner = shlex.split(trigger_argv[2])
        except ValueError:
            return None
        if inner[:2] == ["bash", "-c"] and len(inner) >= 3:
            try:
                inner = shlex.split(inner[2])
            except ValueError:
                return None
        for tok in inner:
            if tok in ("bash", "sh", "exec", "env", "cd"):
                continue
            # KEY=VAL env-prefix tokens (only if the key looks like an identifier)
            if "=" in tok and tok.split("=", 1)[0].replace("_", "").isalnum():
                continue
            candidate = tok
            break
    else:
        candidate = trigger_argv[0]

    if not candidate:
        return None
    # Shell metacharacters → dynamically-resolved binary, don't enforce.
    if any(c in candidate for c in "$();<>|&`*?"):
        return None
    # Absolute paths resolve inside the container, can't be checked from host.
    if candidate.startswith("/"):
        return None
    # Bare name with no path component → system tool on the container's $PATH.
    if "/" not in candidate and not candidate.startswith("./"):
        return None

    candidate = candidate.lstrip("./")
    return workspace / candidate


def resolve_libtool_argv(workspace: Path, argv: list[str]) -> list[str]:
    """Swap a libtool wrapper shell-script for its real .libs/ ELF."""
    if not argv:
        return argv
    exe = argv[0]
    if exe.startswith("/") or exe.startswith("./"):
        exe_rel = exe.lstrip("./") if exe.startswith("./") else exe.lstrip("/")
    else:
        exe_rel = exe
    exe_abs = workspace / exe_rel
    if not exe_abs.is_file():
        return argv
    try:
        head = exe_abs.read_bytes()[:4096]
    except OSError:
        return argv
    if b"libtool" not in head:
        return argv
    dirname, _, base = exe_rel.rpartition("/")
    for cand in (
        f"{dirname}/.libs/lt-{base}" if dirname else f".libs/lt-{base}",
        f"{dirname}/.libs/{base}" if dirname else f".libs/{base}",
    ):
        if (workspace / cand).is_file():
            prefix = "./" if exe.startswith("./") else ""
            return [prefix + cand] + argv[1:]
    return argv


def build_gdb_command(
    workspace: Path,
    gdb_image: str,
    trigger_argv: list[str],
) -> tuple[str | None, list[str] | None, list[str]]:
    if not trigger_argv:
        return None, None, trigger_argv

    if trigger_argv[:2] == ["bash", "-c"]:
        argv = trigger_argv
    else:
        argv = resolve_libtool_argv(workspace, trigger_argv)

    gdb_cmd_parts = ["gdb", *GDB_FLAGS, "--args", *argv]
    gdb_cmd_str = " ".join(shlex.quote(p) for p in gdb_cmd_parts)
    inner = f"{GDB_PREAMBLE}; exec {gdb_cmd_str}"

    docker_shell = (
        f'docker run --rm -v "{_bind_path(workspace)}:/work" -w //work '
        f'{shlex.quote(gdb_image)} bash -c {shlex.quote(inner)}'
    )
    docker_argv = [
        "docker", "run", "--rm",
        "-v", f"{_bind_path(workspace)}:/work",
        "-w", "//work",
        gdb_image,
        "bash", "-c", inner,
    ]
    return docker_shell, docker_argv, argv


def get_bugscpp_test_recipe(project: str, bug_index: int) -> tuple[list[str], int] | None:
    """Read the canonical bugscpp test recipe from upstream meta.json.

    Returns (raw_lines, case_index) where:
      - raw_lines: the un-substituted `common.test.commands[].lines` list
        (e.g. ['bash -c "./berry $(find ... | awk \"NR==$(cat DPP_TEST_INDEX)\")"']).
        These are the same lines bugscpp's own framework runs.
      - case_index: the test-case number for this bug, taken from
        `defects[bug_index-1].case[0]`. Bugscpp writes this number into a
        file named `DPP_TEST_INDEX` before running the lines, and the lines
        substitute `$(cat DPP_TEST_INDEX)` to pick the failing test.

    Returns None if the upstream taxonomy isn't available locally or the
    bug_index doesn't resolve.

    Why this matters: our seed.py pre-substituted DPP_TEST_INDEX into the
    stored trigger, but the substitution went through nested `bash -c`
    quoting and got mangled for projects with complex shell pipelines (e.g.
    berry's `find ... -name \"*.be\"` ends up with literal quote chars in
    find's argv). Reading the upstream raw lines and using bugscpp's own
    DPP_TEST_INDEX-file protocol bypasses that.
    """
    bugscpp_root = bugscpp_repo()
    meta_path = bugscpp_root / "bugscpp" / "taxonomy" / project / "meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    defects = meta.get("defects") or []
    if not (1 <= bug_index <= len(defects)):
        return None
    cases = defects[bug_index - 1].get("case") or []
    if not cases:
        return None
    try:
        case_index = int(cases[0])
    except (TypeError, ValueError):
        return None
    test = (meta.get("common") or {}).get("test") or {}
    commands = test.get("commands") or []
    raw_lines: list[str] = []
    for cmd in commands:
        for line in (cmd.get("lines") or []):
            if line and line.strip():
                raw_lines.append(line)
    if not raw_lines:
        return None
    return raw_lines, case_index


def build_strace_docker_argv(
    workspace: Path,
    gdb_image: str,
    trigger_argv: list[str],
    *,
    project: str | None = None,
    bug_index: int | None = None,
) -> list[str] | None:
    """Build a `docker run` argv that traces the test under strace.

    Two regimes:

    1. **Bugscpp protocol (preferred).** When `project` and `bug_index` are
       supplied AND we can read the upstream meta.json, run the test exactly
       as bugscpp does: write the case index into `/work/DPP_TEST_INDEX`,
       then exec each `common.test.commands.lines` line under `bash -c`,
       chained with `&&`. This gets the canonical, un-mangled test
       invocation and is the only way to get clean argv for projects with
       complex shell pipelines (berry, libtiff, libxml2, ...).

    2. **Trigger fallback.** Otherwise (no project/index, or meta.json
       unavailable), run the pre-rendered trigger_argv from corpus.db.
       This works for projects with simple triggers but produces empty
       argv for shell-pipeline-heavy projects.

    strace -f -e trace=execve emits one line per execve() call regardless
    of fork topology, so we capture argv from every process in the chain.
    The base image doesn't ship strace; we apt-install it inline (one-time
    ~5-10s cost per probe).
    """
    recipe = None
    if project is not None and bug_index is not None:
        recipe = get_bugscpp_test_recipe(project, bug_index)

    if recipe is not None:
        raw_lines, case_index = recipe
        # Bugscpp runs each line via `docker exec_run(<line>)`, which
        # shlex-splits the line into argv. For a line like
        # `bash -c "./berry $(find ... -name \"*.be\" ...)"`, shlex.split
        # consumes one level of quoting, producing
        # `['bash', '-c', './berry $(find ... -name "*.be" ...)']`. Bash
        # then runs the third token as a fresh shell command, where
        # `"*.be"` is an ordinary double-quoted glob pattern and find gets
        # `*.be`.
        #
        # If we instead just pasted the raw line into a shell script, bash
        # would re-process `\"`-escapes inside double-quoted regions and
        # find would end up with literal `"` characters in its argv. So we
        # explicitly shlex-split every line, then re-shell-quote the parts
        # for our outer `bash -c '...'` wrapper. For each line, we end up
        # exec-ing the same argv bugscpp's framework would.
        rebuilt: list[str] = []
        for line in raw_lines:
            try:
                tokens = shlex.split(line)
            except ValueError:
                # Unparseable line — fall through with the raw form. Will
                # likely fail downstream but at least won't crash the
                # probe.
                rebuilt.append(line)
                continue
            rebuilt.append(" ".join(shlex.quote(t) for t in tokens))
        chained = "\n".join(rebuilt)
        bugscpp_block = (
            f'printf %s {case_index} > /work/DPP_TEST_INDEX\n'
            f'{chained}'
        )
        cmd_to_strace = bugscpp_block
    else:
        if not trigger_argv:
            return None
        if trigger_argv[:2] == ["bash", "-c"]:
            argv = trigger_argv
        else:
            argv = resolve_libtool_argv(workspace, trigger_argv)
        cmd_to_strace = " ".join(shlex.quote(p) for p in argv)

    # apt install + GDB_PREAMBLE setup, then strace the actual test.
    inner = (
        'apt-get update -qq >/dev/null 2>&1 && '
        'apt-get install -y --no-install-recommends strace >/dev/null 2>&1; '
        f'{GDB_PREAMBLE}; '
        f'strace -f -s 4096 -e trace=execve -- bash -c {shlex.quote(cmd_to_strace)}'
    )
    return [
        "docker", "run", "--rm",
        "-v", f"{_bind_path(workspace)}:/work",
        "-w", "//work",
        gdb_image,
        "bash", "-c", inner,
    ]


def build_trigger_docker_argv(
    workspace: Path,
    gdb_image: str,
    trigger_argv: list[str],
) -> list[str] | None:
    """Same as build_gdb_command but runs the trigger raw (no gdb). Used to
    capture an exit code for non-crash bugs."""
    if not trigger_argv:
        return None
    if trigger_argv[:2] == ["bash", "-c"]:
        argv = trigger_argv
    else:
        argv = resolve_libtool_argv(workspace, trigger_argv)
    raw = " ".join(shlex.quote(p) for p in argv)
    inner = f"{GDB_PREAMBLE}; exec {raw}"
    return [
        "docker", "run", "--rm",
        "-v", f"{_bind_path(workspace)}:/work",
        "-w", "//work",
        gdb_image,
        "bash", "-c", inner,
    ]


# ─── Backtrace parsing ───────────────────────────────────────────────────────

SYSTEM_PREFIXES = ("/usr/", "/lib/", "/build/", "??")
FRAME_RE = re.compile(
    r"#(\d+)\s+"
    r"(?:0x[0-9a-f]+\s+in\s+)?"
    r"(\S+)\s+"
    r"\(.*?\)"
    r"(?:\s+at\s+([^:]+):(\d+))?"
)
SIGNAL_RE = re.compile(r"Program received signal (SIG[A-Z]+)")
# strace -f -e trace=execve emits lines like:
#   12345 execve("/work/berry", ["./berry", "test.be"], 0x7ffd...) = 0
# The leading PID and "[pid 12345]" variants both appear. Capture both the
# program path AND the argv array; the latter is what we need to reproduce
# the failing test invocation under gdb. Skip failed calls (= -1 ENOENT).
# `<unfinished ...>` continuations don't appear in this regex (they have no
# trailing `= 0`); the `<... execve resumed>` form sometimes does — those
# don't carry the argv on the resumed line, so we'll naturally skip them.
EXEC_CALL_RE = re.compile(
    r'execve\("([^"]+)",\s*\[(.*?)\][^)]*\)\s*=\s*0\b',
)
# Wrappers we never want to surface as "the buggy binary" even if they're
# the only /work/* exec we saw — explicit list keeps the heuristic honest.
LAUNCHER_BASENAMES = {
    "bash", "sh", "dash", "make", "cmake", "ctest", "find", "xargs", "env",
    "python", "python3", "python3.11", "perl", "ruby", "node",
    "awk", "gawk", "sed", "tr", "cat", "ls", "grep", "head", "tail",
    "sort", "cut", "tee", "wc", "test", "true", "false",
    "gcc", "g++", "clang", "ld", "as", "ar", "ranlib",
    "libtool", "pkg-config",
}


def parse_signal(output: str) -> str | None:
    m = SIGNAL_RE.search(output)
    return m.group(1) if m else None


# Splits an strace argv list element by element. Tolerates:
#   - normal `"foo"` quoted strings
#   - escaped quotes: `"foo\"bar"`
#   - per-element truncation: `"long..."` (treated as opaque arg)
#   - whole-array truncation marker: bare `...` (stop processing)
def _parse_argv_list(raw: str) -> list[str]:
    args: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        while i < n and raw[i] in " ,":
            i += 1
        if i >= n:
            break
        if raw[i] == '"':
            i += 1
            buf: list[str] = []
            while i < n:
                ch = raw[i]
                if ch == '\\' and i + 1 < n:
                    buf.append(raw[i + 1])
                    i += 2
                elif ch == '"':
                    i += 1
                    break
                else:
                    buf.append(ch)
                    i += 1
            args.append("".join(buf))
        elif raw[i:i + 3] == '...':
            break  # whole-list truncation
        else:
            j = raw.find(',', i)
            if j < 0:
                break
            i = j
    return args


def parse_exec_calls(output: str) -> list[tuple[str, list[str]]]:
    """Return [(path, argv), ...] from strace -f output."""
    out = []
    for m in EXEC_CALL_RE.finditer(output):
        out.append((m.group(1), _parse_argv_list(m.group(2))))
    return out


def parse_exec_paths(output: str) -> list[str]:
    """Backward-compat: return just the paths."""
    return [p for p, _ in parse_exec_calls(output)]


SYSTEM_PATH_PREFIXES = ("/usr/", "/bin/", "/sbin/", "/lib/", "/lib64/", "/opt/")


def pick_buggy_binary(
    workspace: Path,
    exec_calls: "list[tuple[str, list[str]]] | list[str]",
) -> "tuple[str, list[str]] | None":
    """Pick the deepest user-binary exec from the trigger's exec chain.

    Accepts either a list of (path, argv) tuples or, for backward
    compatibility, a list of bare paths. Returns (rel_path, argv) where
    rel_path is workspace-relative (e.g. "src/split") and argv is the full
    argument list as exec'd (argv[0] = the program-as-named, then the test
    arguments). Returns None if no user binary was seen.

    The argv is what makes the difference between "tell the model what
    binary is buggy" (current behavior) and "tell the model the exact
    command the failing test ran" (what we need so the model can reproduce
    the failing condition).
    """
    # Normalize: legacy callers pass list[str]; convert to list[(path, [])]
    if exec_calls and isinstance(exec_calls[0], str):
        exec_calls = [(p, []) for p in exec_calls]  # type: ignore[list-item]

    for path, argv in reversed(exec_calls):
        if any(path.startswith(p) for p in SYSTEM_PATH_PREFIXES):
            continue
        if path.startswith("/work/"):
            rel = path[len("/work/"):].lstrip("/")
        elif path.startswith("./"):
            rel = path[2:]
        elif "/" in path and not path.startswith("/"):
            rel = path
        elif "/" not in path:
            rel = path
        else:
            continue

        if not rel:
            continue
        base = rel.rsplit("/", 1)[-1]
        if base in LAUNCHER_BASENAMES:
            continue
        if not (workspace / rel).exists():
            continue
        return rel, argv
    return None


def parse_frames(output: str) -> list[dict]:
    frames = []
    for line in output.splitlines():
        m = FRAME_RE.search(line)
        if not m:
            continue
        frames.append({
            "index":    int(m.group(1)),
            "function": m.group(2),
            "file":     m.group(3).strip() if m.group(3) else None,
            "line":     int(m.group(4)) if m.group(4) else None,
        })
    seen = set()
    unique = []
    for f in frames:
        if f["index"] not in seen:
            unique.append(f)
            seen.add(f["index"])
    return sorted(unique, key=lambda f: f["index"])


def is_system_frame(file_path: str | None) -> bool:
    if not file_path:
        return True
    return any(file_path.startswith(p) for p in SYSTEM_PREFIXES)


def find_user_frame(frames: list[dict]) -> dict | None:
    for f in frames:
        if not is_system_frame(f.get("file")):
            return f
    return None


def stderr_tail(r: subprocess.CompletedProcess, n: int = 2000) -> str:
    return ((r.stderr or "") + (r.stdout or ""))[-n:]


# ─── Per-bug worker ──────────────────────────────────────────────────────────

def buggy_workspace_path(bug_id: str, project: str, idx: int) -> Path:
    return WORKSPACES_DIR / bug_id / project / f"buggy-{idx}"


def cleanup_stale_dpp_container(project: str, log) -> None:
    name = f"{project}-dpp"
    r = subprocess.run(
        ["docker", "rm", "-f", name],
        capture_output=True, text=True, env=_docker_env(),
    )
    if r.returncode == 0 and r.stdout.strip():
        log(f"[project={project}] removed stale container {name}")


def process_bug(con: sqlite3.Connection, bug: dict, log) -> None:
    bug_id = bug["bug_id"]
    project = bug["project"]
    idx = bug["bug_index"]
    trigger_argv = json.loads(bug["trigger_argv_json"]) if bug["trigger_argv_json"] else []
    patch_first_file = bug.get("patch_first_file")
    patch_path = bug.get("patch_path")

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    update = {
        "workspace_path":      bug.get("workspace_path"),
        "gdb_command":         None,
        "build_ok":            0,
        "build_error":         None,
        "crash_signal":        None,
        "crash_reproducible":  0,
        "frame0_function":     None,
        "frame0_file":         None,
        "frame0_line":         None,
        "user_frame_function": None,
        "user_frame_file":     None,
        "user_frame_line":     None,
        "backtrace_path":      None,
        "bug_observed":        "no_observation",
        "buggy_binary_path":      None,
        "buggy_binary_argv_json": None,
        "included_in_corpus":  0,
        "built_at":            now,
        "probed_at":           now,
    }

    # 1) Checkout buggy
    buggy_target = WORKSPACES_DIR / bug_id
    force_rmtree(buggy_target)
    r = run_bugscpp(
        ["checkout", project, str(idx), "--buggy", "--target", str(buggy_target)],
        timeout=900,
    )
    buggy = buggy_workspace_path(bug_id, project, idx)
    if r.returncode != 0 or not buggy.exists():
        update["build_error"] = f"checkout failed: {stderr_tail(r, 1500)}"
        log(f"[{bug_id}] CHECKOUT FAIL")
        write_update(con, bug_id, update)
        return
    update["workspace_path"] = str(buggy.resolve())

    # 2) Build
    cleanup_stale_dpp_container(project, log)
    r = run_bugscpp(["build", str(buggy)], timeout=5400)
    if r.returncode != 0:
        update["build_error"] = stderr_tail(r)
        log(f"[{bug_id}] BUILD FAIL")
        write_update(con, bug_id, update)
        return
    update["build_ok"] = 1

    # 3) Optional informational probe
    if trigger_argv:
        gdb_image = bug["gdb_image"]
        try:
            ensure_gdb_image(project)
            image_ok = True
        except Exception as e:
            log(f"[{bug_id}] IMAGE FAIL: {e}")
            image_ok = False

        if image_ok:
            gdb_shell, gdb_argv, _ = build_gdb_command(buggy, gdb_image, trigger_argv)
            update["gdb_command"] = gdb_shell

            signal_seen: str | None = None
            output = ""
            if gdb_argv:
                try:
                    r = subprocess.run(
                        gdb_argv,
                        capture_output=True, text=True, timeout=240,
                        env=_docker_env(),
                    )
                    output = (r.stdout or "") + "\n" + (r.stderr or "")
                    signal_seen = parse_signal(output)
                except subprocess.TimeoutExpired:
                    output = ""

            BACKTRACES_DIR.mkdir(parents=True, exist_ok=True)
            bt_path = BACKTRACES_DIR / f"{bug_id}.txt"
            bt_path.write_text(output, encoding="utf-8", errors="replace")
            update["backtrace_path"] = f"backtraces/{bug_id}.txt"

            # Identify the deepest /work/* binary + the argv it was exec'd
            # with — needed so the harness can reproduce the failing test
            # condition under gdb. Note: this gdb-output path doesn't carry
            # `execve("...")` lines (it would need `catch exec` plus
            # `commands` to log them, which fights with the existing
            # backtrace probe). The strace-based reprobe in
            # reprobe_buggy_binary.py is what actually populates these
            # columns; this call gracefully no-ops on gdb output.
            picked = pick_buggy_binary(buggy, parse_exec_calls(output))
            if picked:
                update["buggy_binary_path"] = picked[0]
                update["buggy_binary_argv_json"] = json.dumps(picked[1])

            if signal_seen:
                update["crash_signal"] = signal_seen
                update["crash_reproducible"] = 1
                update["bug_observed"] = f"crash:{signal_seen}"
                frames = parse_frames(output)
                if frames:
                    f0 = frames[0]
                    update["frame0_function"] = f0.get("function")
                    update["frame0_file"]     = f0.get("file")
                    update["frame0_line"]     = f0.get("line")
                    uf = find_user_frame(frames) or f0
                    update["user_frame_function"] = uf.get("function")
                    update["user_frame_file"]     = uf.get("file")
                    update["user_frame_line"]     = uf.get("line")
            else:
                # No crash — run the trigger outside gdb to capture exit_code.
                raw_argv = build_trigger_docker_argv(buggy, gdb_image, trigger_argv)
                if raw_argv:
                    try:
                        rc = subprocess.run(
                            raw_argv,
                            capture_output=True, text=True, timeout=240,
                            env=_docker_env(),
                        )
                        update["bug_observed"] = f"exit_code:{rc.returncode}"
                    except subprocess.TimeoutExpired:
                        update["bug_observed"] = "timeout"

    # 4) Verify trigger binary actually landed on disk. bugscpp build can
    #    return 0 (so build_ok=1) while Windows ↔ Docker bind-mount quirks
    #    silently drop the build outputs. Without this check the row was
    #    being marked included_in_corpus=1 but DockerDriver later fails with
    #    "No such file or directory" because the binary is missing.
    if update["build_ok"] and trigger_argv:
        bp = trigger_binary_path(buggy, trigger_argv)
        if bp is not None and not bp.exists():
            update["build_ok"] = 0
            update["build_error"] = (
                f"bugscpp build returned 0 but trigger binary missing on disk: "
                f"expected {bp} (likely a Windows ↔ Docker bind-mount issue)"
            )

    # 5) Inclusion gate
    if update["build_ok"] and patch_first_file and patch_path:
        update["included_in_corpus"] = 1

    write_update(con, bug_id, update)
    incl = "OK" if update["included_in_corpus"] else "--"
    log(f"[{bug_id}] {incl} build_ok={update['build_ok']} {update['bug_observed']}")


def write_update(con: sqlite3.Connection, bug_id: str, u: dict) -> None:
    cols = ", ".join(f"{k} = ?" for k in u)
    vals = list(u.values()) + [bug_id]
    with DB_LOCK:
        con.execute(f"UPDATE bugs SET {cols} WHERE bug_id = ?", vals)
        con.commit()


# ─── Project worker ──────────────────────────────────────────────────────────

def process_project(con: sqlite3.Connection, project: str, bugs: list[dict], log) -> None:
    log(f"[project={project}] {len(bugs)} bugs")
    cleanup_stale_dpp_container(project, log)
    for bug in bugs:
        try:
            process_bug(con, bug, log)
        except Exception as e:
            tb = traceback.format_exc()[-800:]
            log(f"[{bug['bug_id']}] EXCEPTION: {e}\n{tb}")
            with DB_LOCK:
                con.execute(
                    "UPDATE bugs SET build_error = ?, built_at = ? WHERE bug_id = ?",
                    (f"exception: {e}\n{tb}",
                     time.strftime("%Y-%m-%d %H:%M:%S"),
                     bug["bug_id"]),
                )
                con.commit()


# ─── Entrypoint ──────────────────────────────────────────────────────────────

def fetch_bugs(con: sqlite3.Connection, project_filter: str | None, resume: bool) -> list[dict]:
    sql = (
        "SELECT bug_id, project, bug_index, language, gdb_image, "
        "       trigger_argv_json, workspace_path, "
        "       patch_first_file, patch_path "
        "FROM bugs"
    )
    where = []
    params: list = []
    if project_filter:
        where.append("project = ?")
        params.append(project_filter)
    if resume:
        where.append("built_at IS NULL")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY project, bug_index"
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--project", default=None)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()

    db = Path(args.db)
    if not db.exists():
        sys.exit(f"DB not found: {db}. Run pipeline2/seed.py first.")

    con = sqlite3.connect(str(db), check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row

    bugs = fetch_bugs(con, args.project, args.resume)
    if not bugs:
        print("[build] nothing to do.")
        return

    by_project: dict[str, list[dict]] = {}
    for b in bugs:
        by_project.setdefault(b["project"], []).append(b)

    print(f"[build] {len(bugs)} bugs across {len(by_project)} projects, "
          f"workers={args.workers}")

    log_lock = threading.Lock()
    def log(msg: str) -> None:
        with log_lock:
            print(msg, flush=True)

    workers = max(1, min(args.workers, len(by_project)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(process_project, con, project, project_bugs, log): project
            for project, project_bugs in by_project.items()
        }
        for fut in as_completed(futs):
            project = futs[fut]
            try:
                fut.result()
            except Exception as e:
                log(f"[project={project}] FATAL: {e}")

    stats = con.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(build_ok) AS built,
            SUM(CASE WHEN bug_observed LIKE 'crash:%' THEN 1 ELSE 0 END) AS crashed,
            SUM(included_in_corpus) AS included
        FROM bugs
    """).fetchone()
    con.close()
    print(f"[build] done: total={stats['total']} "
          f"built={stats['built']} crashed={stats['crashed']} "
          f"included={stats['included']}")


if __name__ == "__main__":
    main()
