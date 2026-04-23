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


def run_bugscpp(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    cmd = ["python", str(bugscpp_repo() / "bugscpp" / "bugscpp.py"), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _docker_env() -> dict:
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    env.setdefault("MSYS2_ARG_CONV_EXCL", "*")
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


def parse_signal(output: str) -> str | None:
    m = SIGNAL_RE.search(output)
    return m.group(1) if m else None


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
        "included_in_corpus":  0,
        "built_at":            now,
        "probed_at":           now,
    }

    # 1) Checkout buggy
    buggy_target = WORKSPACES_DIR / bug_id
    force_rmtree(buggy_target)
    r = run_bugscpp(
        ["checkout", project, str(idx), "--buggy", "--target", str(buggy_target)],
        timeout=300,
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
    r = run_bugscpp(["build", str(buggy)], timeout=1800)
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

    # 4) Inclusion gate
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
