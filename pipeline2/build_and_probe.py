"""Build each bug, probe it 3x under gdb, extract patch, emit case.yaml.

One container open per bug. Bugs are grouped by project; one worker
processes all bugs of a single project serially, so the fixed
`<project>-dpp` container name from the bugscpp CLI never collides.
Workers for distinct projects run concurrently.

Resumable via --resume (skips rows where probed_at IS NOT NULL).
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

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "corpus.db"
WORKSPACES_DIR = REPO_ROOT / "data" / "workspaces"
BACKTRACES_DIR = REPO_ROOT / "data" / "backtraces"

# Imported lazily to keep startup fast and avoid Windows multiprocessing pickling.
import sys as _sys
_sys.path.insert(0, str(REPO_ROOT / "pipeline2"))
from ensure_image import ensure_gdb_image, gdb_image_tag  # noqa: E402
from emit_case_yaml import write_case_yaml                # noqa: E402

DB_LOCK = threading.Lock()  # SQLite cross-thread serialization

# ─── BugsC++ CLI ─────────────────────────────────────────────────────────────

def bugscpp_repo() -> Path:
    repo = os.environ.get("BUGSCPP_REPO")
    return Path(repo) if repo else REPO_ROOT.parent / "bugscpp"


def run_bugscpp(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    cmd = ["python", str(bugscpp_repo() / "bugscpp" / "bugscpp.py"), *args]
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
    )


# ─── Docker bind-mount helpers ───────────────────────────────────────────────

def _docker_env() -> dict:
    """MSYS path-mangling kills bind-mount paths on Windows; disable it."""
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    env.setdefault("MSYS2_ARG_CONV_EXCL", "*")
    return env


def _bind_path(p: Path) -> str:
    """Return a host path string that docker can use as the source of -v."""
    return str(p.resolve())


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
) -> tuple[str | None, list[str]]:
    """Return (full docker-run shell string, resolved argv)."""
    if not trigger_argv:
        return None, trigger_argv

    if trigger_argv[:2] == ["bash", "-c"]:
        # Shell metacharacters present; let bash drive and rely on
        # follow-fork-mode child to step into the real binary.
        argv = trigger_argv
    else:
        argv = resolve_libtool_argv(workspace, trigger_argv)

    gdb_cmd_parts = ["gdb", *GDB_FLAGS, "--args", *argv]
    gdb_cmd_str = " ".join(shlex.quote(p) for p in gdb_cmd_parts)
    inner = f"{GDB_PREAMBLE}; exec {gdb_cmd_str}"

    docker_cmd = (
        f'docker run --rm -v "{_bind_path(workspace)}:/work" -w //work '
        f'{shlex.quote(gdb_image)} bash -c {shlex.quote(inner)}'
    )
    return docker_cmd, argv


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
    # Deduplicate by index, keep first occurrence
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


# ─── Patch extraction ────────────────────────────────────────────────────────

SRC_EXTS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".hxx"}


def diff_source_only(buggy: Path, fixed: Path) -> tuple[str, list[str]]:
    """Run `diff -ruN <buggy> <fixed>` filtered to source-extension files."""
    r = subprocess.run(
        ["diff", "-ruN", str(buggy), str(fixed)],
        capture_output=True, text=True, timeout=120,
    )
    out = r.stdout or ""
    if not out.strip():
        return "", []

    # Split into per-file hunks, keep only source-ext files.
    chunks: list[str] = []
    files: list[str] = []
    cur: list[str] = []
    cur_file: str | None = None

    def flush():
        if cur and cur_file:
            ext = Path(cur_file).suffix.lower()
            if ext in SRC_EXTS:
                chunks.append("".join(cur))
                files.append(cur_file)

    for line in out.splitlines(keepends=True):
        if line.startswith("diff "):
            flush()
            cur = [line]
            parts = line.split()
            cur_file = parts[-1] if parts else None
        elif line.startswith("--- ") or line.startswith("+++ "):
            cur.append(line)
            if line.startswith("+++ "):
                # Track the +++ path (fixed-side), strip leading prefix
                path = line[4:].split("\t")[0].strip()
                cur_file = path
        else:
            cur.append(line)
    flush()

    # Normalize file paths to be relative to the fixed/buggy root for clarity.
    norm_files = []
    fixed_str = str(fixed).replace("\\", "/")
    buggy_str = str(buggy).replace("\\", "/")
    for f in files:
        f_norm = f.replace("\\", "/")
        for prefix in (fixed_str + "/", buggy_str + "/"):
            if f_norm.startswith(prefix):
                f_norm = f_norm[len(prefix):]
                break
        norm_files.append(f_norm)

    return "".join(chunks), norm_files


# ─── Per-bug worker ──────────────────────────────────────────────────────────

def stderr_tail(r: subprocess.CompletedProcess, n: int = 2000) -> str:
    return ((r.stderr or "") + (r.stdout or ""))[-n:]


def buggy_workspace_path(case_id: str, project: str, idx: int) -> Path:
    return WORKSPACES_DIR / case_id / project / f"buggy-{idx}"


def fixed_workspace_path(case_id: str, project: str, idx: int) -> Path:
    return WORKSPACES_DIR / f"{case_id}-fixed" / project / f"fixed-{idx}"


def process_bug(con: sqlite3.Connection, bug: dict, log) -> None:
    case_id = bug["case_id"]
    project = bug["project"]
    idx = bug["bug_index"]
    trigger_argv = json.loads(bug["trigger_argv_json"]) if bug["trigger_argv_json"] else []

    update = {
        "workspace_path":     None,
        "gdb_command":        None,
        "build_ok":           0,
        "build_error":        None,
        "crash_signal":       None,
        "crash_reproducible": 0,
        "frame0_function":    None,
        "frame0_file":        None,
        "frame0_line":        None,
        "user_frame_function": None,
        "user_frame_file":    None,
        "user_frame_line":    None,
        "backtrace_path":     None,
        "patch_diff":         None,
        "patch_files_json":   None,
        "case_yaml_path":     None,
        "included_in_corpus": 0,
        "probed_at":          time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 1) Checkout buggy
    buggy_target = WORKSPACES_DIR / case_id
    if buggy_target.exists():
        shutil.rmtree(buggy_target, ignore_errors=True)
    r = run_bugscpp(
        ["checkout", project, str(idx), "--buggy", "--target", str(buggy_target)],
        timeout=300,
    )
    buggy = buggy_workspace_path(case_id, project, idx)
    if r.returncode != 0 or not buggy.exists():
        update["build_error"] = f"checkout failed: {stderr_tail(r, 1500)}"
        log(f"[{case_id}] CHECKOUT FAIL")
        write_update(con, case_id, update)
        return
    update["workspace_path"] = str(buggy.resolve())

    # 2) Build
    r = run_bugscpp(["build", str(buggy)], timeout=900)
    if r.returncode != 0:
        update["build_error"] = stderr_tail(r)
        log(f"[{case_id}] BUILD FAIL")
        write_update(con, case_id, update)
        return
    update["build_ok"] = 1

    # 3) Construct gdb_command
    if not trigger_argv:
        log(f"[{case_id}] BUILT, NO TRIGGER")
        write_update(con, case_id, update)
        return

    gdb_image = bug["gdb_image"]
    try:
        ensure_gdb_image(project)
    except Exception as e:
        update["build_error"] = f"gdb image build failed: {e}"
        log(f"[{case_id}] IMAGE FAIL")
        write_update(con, case_id, update)
        return

    gdb_cmd, resolved_argv = build_gdb_command(buggy, gdb_image, trigger_argv)
    if gdb_cmd is None:
        log(f"[{case_id}] BUILT, GDB CMD UNAVAILABLE")
        write_update(con, case_id, update)
        return
    update["gdb_command"] = gdb_cmd

    # 4) Run 3x
    signals: list[str | None] = []
    last_output = ""
    for i in range(3):
        try:
            r = subprocess.run(
                gdb_cmd, shell=True,
                capture_output=True, text=True, timeout=240,
                env=_docker_env(),
            )
            output = (r.stdout or "") + "\n" + (r.stderr or "")
        except subprocess.TimeoutExpired:
            output = ""
        signals.append(parse_signal(output))
        last_output = output

    # 5) Reproducibility
    nonnull = [s for s in signals if s]
    if len(nonnull) == 3 and len(set(nonnull)) == 1:
        update["crash_signal"] = nonnull[0]
        update["crash_reproducible"] = 1

    # 6) Parse last bt
    BACKTRACES_DIR.mkdir(parents=True, exist_ok=True)
    bt_path = BACKTRACES_DIR / f"{case_id}.txt"
    bt_path.write_text(last_output, encoding="utf-8", errors="replace")
    update["backtrace_path"] = f"backtraces/{case_id}.txt"

    frames = parse_frames(last_output)
    if frames:
        f0 = frames[0]
        update["frame0_function"] = f0.get("function")
        update["frame0_file"]     = f0.get("file")
        update["frame0_line"]     = f0.get("line")
        uf = find_user_frame(frames) or f0
        update["user_frame_function"] = uf.get("function")
        update["user_frame_file"]     = uf.get("file")
        update["user_frame_line"]     = uf.get("line")

    # 7) Patch extraction (fixed checkout, diff, cleanup)
    fixed_target = WORKSPACES_DIR / f"{case_id}-fixed"
    if fixed_target.exists():
        shutil.rmtree(fixed_target, ignore_errors=True)
    rfix = run_bugscpp(
        ["checkout", project, str(idx), "--target", str(fixed_target)],
        timeout=300,
    )
    fixed = fixed_workspace_path(case_id, project, idx)
    if rfix.returncode == 0 and fixed.exists():
        try:
            diff_text, files = diff_source_only(buggy, fixed)
            if diff_text:
                update["patch_diff"]       = diff_text
                update["patch_files_json"] = json.dumps(files)
        except Exception as e:
            log(f"[{case_id}] DIFF ERROR: {e}")
        finally:
            shutil.rmtree(fixed_target, ignore_errors=True)
    else:
        log(f"[{case_id}] FIXED CHECKOUT FAIL")

    # 8) Emit case.yaml
    try:
        merged = {**bug, **update, "trigger_argv": resolved_argv}
        yaml_path = write_case_yaml(merged)
        update["case_yaml_path"] = str(yaml_path.relative_to(REPO_ROOT)).replace("\\", "/")
    except Exception as e:
        log(f"[{case_id}] YAML EMIT ERROR: {e}")

    # 9) Gate
    if (update["build_ok"]
            and update["crash_reproducible"]
            and update["user_frame_file"]
            and update["patch_diff"]
            and update["case_yaml_path"]):
        update["included_in_corpus"] = 1

    write_update(con, case_id, update)
    sig = update["crash_signal"] or "no-crash"
    incl = "✓" if update["included_in_corpus"] else "✗"
    log(f"[{case_id}] {incl} {sig} user_frame={update['user_frame_file']}:{update['user_frame_line']}")


def write_update(con: sqlite3.Connection, case_id: str, u: dict) -> None:
    cols = ", ".join(f"{k} = ?" for k in u)
    vals = list(u.values()) + [case_id]
    with DB_LOCK:
        con.execute(f"UPDATE bugs SET {cols} WHERE case_id = ?", vals)
        con.commit()


# ─── Project worker ──────────────────────────────────────────────────────────

def process_project(con: sqlite3.Connection, project: str, bugs: list[dict], log) -> None:
    log(f"[project={project}] {len(bugs)} bugs")
    for bug in bugs:
        try:
            process_bug(con, bug, log)
        except Exception as e:
            tb = traceback.format_exc()[-800:]
            log(f"[{bug['case_id']}] EXCEPTION: {e}\n{tb}")
            with DB_LOCK:
                con.execute(
                    "UPDATE bugs SET build_error = ?, probed_at = ? WHERE case_id = ?",
                    (f"exception: {e}\n{tb}", time.strftime("%Y-%m-%d %H:%M:%S"), bug["case_id"]),
                )
                con.commit()


# ─── Entrypoint ──────────────────────────────────────────────────────────────

def fetch_bugs(con: sqlite3.Connection, project_filter: str | None, resume: bool) -> list[dict]:
    sql = "SELECT case_id, project, bug_index, language, gdb_image, trigger_argv_json FROM bugs"
    where = []
    params: list = []
    if project_filter:
        where.append("project = ?")
        params.append(project_filter)
    if resume:
        where.append("probed_at IS NULL")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY project, bug_index"
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--project", default=None,
                   help="Only build bugs from this project")
    p.add_argument("--workers", type=int, default=4,
                   help="Concurrent projects (default 4)")
    p.add_argument("--resume", action="store_true",
                   help="Skip rows where probed_at IS NOT NULL")
    args = p.parse_args()

    db = Path(args.db)
    if not db.exists():
        sys.exit(f"DB not found: {db}. Run pipeline2/seed.py first.")

    con = sqlite3.connect(str(db), check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row

    bugs = fetch_bugs(con, args.project, args.resume)
    if not bugs:
        print("[probe] nothing to do.")
        return

    # Group by project for project-serial / cross-project-parallel scheduling.
    by_project: dict[str, list[dict]] = {}
    for b in bugs:
        by_project.setdefault(b["project"], []).append(b)

    print(f"[probe] {len(bugs)} bugs across {len(by_project)} projects, "
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

    # Summary
    con.row_factory = sqlite3.Row
    stats = con.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(build_ok) AS built,
            SUM(crash_reproducible) AS reproducible,
            SUM(included_in_corpus) AS included
        FROM bugs
    """).fetchone()
    con.close()
    print(f"[probe] done: total={stats['total']} "
          f"built={stats['built']} reproducible={stats['reproducible']} "
          f"included={stats['included']}")


if __name__ == "__main__":
    main()
