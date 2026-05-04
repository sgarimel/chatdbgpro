"""Rebuild every BugsCPP workspace with debug symbols, then re-probe.

The original `pipeline2.build` runs each project's bugscpp recipe AS-IS,
which for many projects produces `-O2` or `-O3` binaries with no DWARF
debug info. Gdb on those shows raw addresses, no source lines, no
local variables — useless for the T2/T3 tiers.

This script reads each project's build recipe from bugscpp's
``taxonomy/<project>/meta.json`` (the same metadata the bugscpp CLI
consumes), substitutes the @DPP_*@ placeholders, injects `CFLAGS=
"-g -O0 ..."` / `CXXFLAGS=...`, runs the recipe inside the project's
container (apptainer or docker), then re-runs the strace probe to
populate corpus.db's `buggy_binary_path` and `buggy_binary_argv_json`.
Finally it `readelf -S`s the resolved binary to verify DWARF was
actually emitted.

Compatible with both runtimes (`--runtime docker|apptainer`). On
Apple-Silicon hosts the strace probe is broken under amd64 emulation
(PTRACE_TRACEME blocked); run on a linux/amd64 native host like adroit.

Usage:
    python -m pipeline2.rebuild_with_debug --project yara
    python -m pipeline2.rebuild_with_debug --bug-ids yara-1 yara-3
    python -m pipeline2.rebuild_with_debug --all --workers 4 --runtime apptainer
    python -m pipeline2.rebuild_with_debug --project yara --force
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "corpus.db"

# Reuse pipeline2/build.py helpers — strace argv construction +
# exec-call parsing are non-trivial and live there.
sys.path.insert(0, str(REPO_ROOT / "pipeline2"))
from build import (  # noqa: E402
    _docker_env,
    build_strace_docker_argv,
    parse_exec_calls,
    pick_buggy_binary,
)


def bugscpp_taxonomy_dir() -> Path:
    repo = os.environ.get("BUGSCPP_REPO")
    base = Path(repo) if repo else REPO_ROOT.parent / "bugscpp"
    return base / "bugscpp" / "taxonomy"


def load_recipe(project: str) -> list[str]:
    """Return the shell commands bugscpp uses to BUILD the buggy
    workspace for `project`. Concatenates every `lines:` list under
    `common.build.commands[*]`."""
    meta = bugscpp_taxonomy_dir() / project / "meta.json"
    if not meta.exists():
        raise FileNotFoundError(f"No taxonomy meta.json for {project} at {meta}")
    data = json.loads(meta.read_text())
    blocks = (data.get("common") or {}).get("build", {}).get("commands", [])
    if not blocks:
        raise RuntimeError(f"{project}: meta.json has no common.build.commands")
    out: list[str] = []
    for blk in blocks:
        out.extend(blk.get("lines", []))
    return out


def render_recipe(lines: list[str], parallel: int = 4) -> list[str]:
    """Substitute the @DPP_*@ placeholders bugscpp uses internally so
    the recipe runs outside its CLI:
      @DPP_PARALLEL_BUILD@ → integer parallelism count
      @DPP_COMPILATION_DB_TOOL@ → empty (we don't need bear/intercept-build)
      @DPP_TEST_INDEX@ is per-bug (handled at probe time, not here)
    """
    rendered = []
    for ln in lines:
        ln = ln.replace("@DPP_PARALLEL_BUILD@", str(parallel))
        ln = ln.replace("@DPP_COMPILATION_DB_TOOL@", "")
        rendered.append(ln.strip())
    return [r for r in rendered if r]


def inject_debug_into_assignment(line: str) -> str:
    """If `line` contains `CFLAGS=…` or `CXXFLAGS=…`, prepend `-g -O0`.

    Heuristic: bugscpp recipes are conventional autotools/cmake calls.
    Projects whose recipe sets CFLAGS twice are doing it on purpose,
    so we only mutate the first occurrence per variable. Projects with
    exotic build tooling can be handled via _PROJECT_OVERRIDES below.
    """
    for var in ("CFLAGS", "CXXFLAGS"):
        if f"{var}=" not in line:
            continue
        head, _, rest = line.partition(f"{var}=")
        if rest.startswith('"'):
            end = rest.index('"', 1)
            inner = rest[1:end]
            if "-g" not in inner.split():
                inner = f"-g -O0 {inner}".strip()
            line = f'{head}{var}="{inner}"{rest[end + 1:]}'
        elif rest.startswith("'"):
            end = rest.index("'", 1)
            inner = rest[1:end]
            if "-g" not in inner.split():
                inner = f"-g -O0 {inner}".strip()
            line = f"{head}{var}='{inner}'{rest[end + 1:]}"
        else:
            space = rest.find(" ")
            inner = rest if space == -1 else rest[:space]
            tail = "" if space == -1 else rest[space:]
            if "-g" not in inner.split():
                inner = f"-g -O0 {inner}".strip()
            line = f"{head}{var}={shlex.quote(inner)}{tail}"
    return line


# Per-project escape hatches. Add here when a project's default recipe
# is missing a critical flag (libs, defines) we discovered the hard
# way during pilot runs.
_PROJECT_OVERRIDES: dict[str, dict[str, str]] = {
    # yara's defects4cpp.h calls lua_* without the recipe linking lua.
    # bugscpp's meta.json includes LDFLAGS=-llua5.3 for yara already,
    # so this is mostly a defensive belt-and-braces.
    "yara": {"export": "LDFLAGS=-llua5.3"},
}


def compose_inner_script(project: str, lines: list[str]) -> str:
    """Build the shell script that runs the recipe inside the
    container. Sets `CFLAGS=-g -O0 …` / `CXXFLAGS=…` as exports so
    every step inherits them, plus splices `-g -O0` into any explicit
    CFLAGS=… assignment in the recipe.
    """
    munged = [inject_debug_into_assignment(ln) for ln in lines]
    overrides = _PROJECT_OVERRIDES.get(project, {})
    pre = ["set -e"]
    if overrides.get("export"):
        pre.append(f"export {overrides['export']}")
    pre.append('export CFLAGS="-g -O0 ${CFLAGS:-}"')
    pre.append('export CXXFLAGS="-g -O0 ${CXXFLAGS:-}"')
    return "\n".join(pre) + "\n" + "\n".join(munged) + "\n"


def run_in_container(
    workspace: Path,
    image: str,
    runtime: str,
    inner_script: str,
    *,
    timeout: int = 2400,
) -> subprocess.CompletedProcess:
    """Run `inner_script` inside the project's container with /work
    bind-mounted to `workspace`."""
    if runtime == "docker":
        argv = [
            "docker", "run", "--rm",
            "-v", f"{workspace.resolve()}:/work",
            "-w", "/work",
            image,
            "bash", "-c", inner_script,
        ]
    elif runtime == "apptainer":
        cli = shutil.which("apptainer") or shutil.which("singularity") or "apptainer"
        argv = [
            cli, "exec", "--writable-tmpfs",
            "--bind", f"{workspace.resolve()}:/work",
            "--pwd", "/work",
            image,
            "bash", "-c", inner_script,
        ]
    else:
        raise ValueError(f"Unknown runtime {runtime!r}")
    return subprocess.run(
        argv, capture_output=True, text=True,
        env=_docker_env(), timeout=timeout,
        encoding="utf-8", errors="replace",
    )


def has_debug_info(workspace: Path, rel_binary: str | None) -> bool:
    """True if the resolved binary has a `.debug_info` ELF section."""
    if not rel_binary:
        return False
    p = workspace / rel_binary
    if not p.exists():
        return False
    r = subprocess.run(
        ["readelf", "-S", str(p)],
        capture_output=True, text=True,
    )
    return ".debug_info" in (r.stdout or "")


def rebuild_one(bug: dict, runtime: str, log_dir: Path) -> dict:
    """Rebuild + re-probe a single bug. Returns a dict the caller
    persists to corpus.db."""
    bug_id = bug["bug_id"]
    project = bug["project"]
    workspace = Path(bug["workspace_path"])
    log = log_dir / f"{bug_id}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log_w = log.open("w")

    def L(msg: str) -> None:
        print(f"[{bug_id}] {msg}", file=log_w, flush=True)

    L(f"=== START {time.strftime('%FT%TZ', time.gmtime())} project={project} ws={workspace}")
    if not workspace.exists():
        L("workspace not on disk")
        return {"bug_id": bug_id, "status": "no-workspace"}

    try:
        recipe_lines = load_recipe(project)
    except Exception as e:
        L(f"recipe-load FAILED: {e}")
        return {"bug_id": bug_id, "status": "no-recipe", "error": str(e)}
    rendered = render_recipe(recipe_lines, parallel=4)
    inner_script = compose_inner_script(project, rendered)
    L("recipe lines:\n  " + "\n  ".join(rendered))

    from ensure_image import ensure_gdb_image
    image = ensure_gdb_image(project, runtime=runtime)
    L(f"image: {image}")

    L(f"rebuild via {runtime}")
    proc = run_in_container(workspace, image, runtime, inner_script,
                            timeout=2400)
    log_w.write("--- rebuild stdout (last 80 lines) ---\n")
    log_w.write("\n".join((proc.stdout or "").splitlines()[-80:]) + "\n")
    log_w.write("--- rebuild stderr (last 30 lines) ---\n")
    log_w.write("\n".join((proc.stderr or "").splitlines()[-30:]) + "\n")
    if proc.returncode != 0:
        L(f"REBUILD FAILED rc={proc.returncode}")
        return {"bug_id": bug_id, "status": "rebuild-failed",
                "rc": proc.returncode}

    trigger = json.loads(bug["trigger_argv_json"]) if bug["trigger_argv_json"] else []
    if not trigger:
        L("no trigger_argv → skip probe")
        return {"bug_id": bug_id, "status": "no-trigger"}

    argv = build_strace_docker_argv(
        workspace, image, trigger,
        project=project, bug_index=bug["bug_index"],
    )
    if argv is None:
        return {"bug_id": bug_id, "status": "probe-argv-empty"}
    if runtime == "apptainer":
        # Translate the docker argv to apptainer exec — same approach
        # as pipeline2/probe_only.py.
        try:
            i = argv.index(image)
        except ValueError:
            return {"bug_id": bug_id, "status": "probe-argv-shape"}
        inner = argv[i + 1:]
        cli = shutil.which("apptainer") or shutil.which("singularity") or "apptainer"
        argv = [
            cli, "exec", "--writable-tmpfs",
            "--bind", f"{workspace.resolve()}:/work",
            "--pwd", "/work",
            image,
            *inner,
        ]
    L(f"probe via {runtime}")
    proc = subprocess.run(
        argv, capture_output=True, text=True, env=_docker_env(),
        timeout=300, encoding="utf-8", errors="replace",
    )
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if "PTRACE_TRACEME" in output and "Function not implemented" in output:
        L("ptrace blocked (Rosetta/QEMU); needs native amd64 host")
        return {"bug_id": bug_id, "status": "ptrace-blocked"}

    exec_calls = parse_exec_calls(output)
    if not exec_calls:
        L(f"no execve()s parsed; rc={proc.returncode}")
        return {"bug_id": bug_id, "status": "no-execs"}

    picked = pick_buggy_binary(workspace, exec_calls)
    if picked is None:
        L(f"no /work/* in exec chain ({len(exec_calls)} execve()s)")
        return {"bug_id": bug_id, "status": "no-binary"}

    rel, argv_b = picked
    debug_ok = has_debug_info(workspace, rel)
    L(f"OK: {rel} (debug={debug_ok}) argv={argv_b[:3]}")

    return {
        "bug_id": bug_id,
        "status": "rebuilt-and-probed",
        "buggy_binary_path": rel,
        "buggy_binary_argv": argv_b,
        "has_debug_info": debug_ok,
    }


def fetch_bugs(
    db_path: Path,
    *,
    projects: list[str] | None,
    bug_ids: list[str] | None,
    force: bool,
) -> list[dict]:
    con = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    sql = (
        "SELECT bug_id, project, bug_index, gdb_image, "
        "       trigger_argv_json, workspace_path, "
        "       buggy_binary_path "
        "FROM bugs WHERE included_in_corpus = 1 "
        "  AND trigger_argv_json IS NOT NULL"
    )
    params: list = []
    if projects:
        sql += " AND project IN (" + ",".join("?" * len(projects)) + ")"
        params.extend(projects)
    if bug_ids:
        sql += " AND bug_id IN (" + ",".join("?" * len(bug_ids)) + ")"
        params.extend(bug_ids)
    if not force:
        sql += " AND buggy_binary_path IS NULL"
    sql += " ORDER BY project, bug_index"
    rows = [dict(r) for r in con.execute(sql, params).fetchall()]
    con.close()
    return rows


def persist(db_path: Path, result: dict) -> None:
    if result.get("status") != "rebuilt-and-probed":
        return
    con = sqlite3.connect(str(db_path), timeout=30)
    con.execute(
        "UPDATE bugs SET buggy_binary_path = ?, "
        "                buggy_binary_argv_json = ?, "
        "                probed_at = ? "
        "WHERE bug_id = ?",
        (
            result["buggy_binary_path"],
            json.dumps(result["buggy_binary_argv"]),
            time.strftime("%Y-%m-%d %H:%M:%S"),
            result["bug_id"],
        ),
    )
    con.commit()
    con.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--project", action="append",
                   help="Restrict to projects (repeatable)")
    p.add_argument("--bug-ids", nargs="+", default=None)
    p.add_argument("--all", action="store_true",
                   help="Rebuild every included bug (same as default if --project/--bug-ids omitted)")
    p.add_argument("--runtime", choices=("docker", "apptainer"), default=None)
    p.add_argument("--force", action="store_true",
                   help="Rebuild even bugs that already have buggy_binary_path")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--log-dir", type=Path,
                   default=REPO_ROOT / "data" / "rebuild-logs")
    args = p.parse_args()

    if args.runtime is None:
        if shutil.which("docker"):
            args.runtime = "docker"
        elif shutil.which("apptainer") or shutil.which("singularity"):
            args.runtime = "apptainer"
        else:
            sys.exit("Need docker or apptainer on PATH")

    bugs = fetch_bugs(
        args.db,
        projects=args.project,
        bug_ids=args.bug_ids,
        force=args.force,
    )
    if not bugs:
        print("[rebuild] nothing to do (use --force to re-probe)")
        return 0

    print(f"[rebuild] {len(bugs)} bug(s) via {args.runtime} × workers={args.workers}",
          flush=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, int] = {}

    def bucket(status: str) -> None:
        summary[status] = summary.get(status, 0) + 1

    if args.workers <= 1:
        for b in bugs:
            r = rebuild_one(b, args.runtime, args.log_dir)
            persist(args.db, r)
            print(f"[{b['bug_id']}] {r['status']}", flush=True)
            bucket(r["status"])
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(rebuild_one, b, args.runtime, args.log_dir): b
                for b in bugs
            }
            for f in as_completed(futures):
                b = futures[f]
                try:
                    r = f.result()
                except Exception as e:
                    r = {"bug_id": b["bug_id"], "status": "exception",
                         "error": str(e)}
                persist(args.db, r)
                print(f"[{b['bug_id']}] {r['status']}", flush=True)
                bucket(r["status"])

    print(f"[rebuild] done: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
