"""Re-probe `buggy_binary_path` for already-built workspaces.

`pipeline2.build` does {checkout, build, probe} as one atomic step,
which is wasteful when workspaces already exist on disk and we just
want to re-run the strace probe (e.g. corpus.db got
`included_in_corpus=1` set manually without going through build's probe
path — the yara case in our adroit pilot).

Probe-only flow per bug:
  1. Skip if `buggy_binary_path IS NOT NULL` unless `--force`.
  2. Skip if workspace doesn't exist on disk (no probe possible).
  3. ensure the gdb image (apptainer-pull or docker-build).
  4. Run trigger under strace via the matching runtime
     (apptainer exec on adroit, docker run on Linux). NB: under
     Apple-Silicon-Rosetta amd64 emulation this is broken — strace
     hits "PTRACE_TRACEME: Function not implemented", same as gdb.
     Run on a host with native amd64 ptrace.
  5. parse_exec_calls + pick_buggy_binary → workspace-relative path
     of the deepest user binary that exec'd.
  6. UPDATE corpus.db with `buggy_binary_path` and
     `buggy_binary_argv_json`.

Usage:
  python -m pipeline2.probe_only --project yara
  python -m pipeline2.probe_only --bug-ids yara-1 yara-3
  python -m pipeline2.probe_only --runtime apptainer --project yara
  python -m pipeline2.probe_only --force --project yara   # re-probe even probed
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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "corpus.db"
WORKSPACES_DIR = REPO_ROOT / "data" / "workspaces"

# Reuse pipeline2/build.py helpers — they encapsulate the strace
# argv construction and exec-call parsing logic. Importing rather than
# duplicating keeps the strace command in one place.
sys.path.insert(0, str(REPO_ROOT / "pipeline2"))
from build import (  # noqa: E402
    _docker_env, build_strace_docker_argv, parse_exec_calls,
    pick_buggy_binary,
)


def _run_strace_apptainer(
    workspace: Path, image: str, trigger_argv: list[str], *,
    project: str | None = None, bug_index: int | None = None,
) -> subprocess.CompletedProcess:
    """Apptainer-flavored equivalent of build_strace_docker_argv.

    Mirrors the docker version's logic (apt-install strace if needed,
    then run trigger under strace -f -e execve) but uses
    `apptainer exec --writable-tmpfs --bind workspace:/work` so it
    works on HPC clusters that lack docker.

    Image refs accepted: docker:// URLs, .sif paths, or daemon refs —
    whatever the apptainer CLI takes for `apptainer exec`.
    """
    docker_argv = build_strace_docker_argv(
        workspace, image, trigger_argv,
        project=project, bug_index=bug_index,
    )
    if docker_argv is None:
        return subprocess.CompletedProcess(args=[], returncode=2,
                                            stdout="", stderr="empty trigger")
    # build_strace_docker_argv returns a `docker run ...` argv. We need
    # the inner command (after the image arg) and the bind path. Find
    # the image position to split.
    # Docker argv shape:
    #   docker run --rm -v <ws>:/work -w //work <image> bash -c <inner>
    try:
        i_image = docker_argv.index(image)
    except ValueError:
        # If image arg shape differs, fall back to docker
        return subprocess.run(docker_argv, capture_output=True, text=True,
                               env=_docker_env(), encoding="utf-8",
                               errors="replace")
    inner_argv = docker_argv[i_image + 1:]
    cli = shutil.which("apptainer") or shutil.which("singularity") or "apptainer"
    apt_argv = [
        cli, "exec", "--writable-tmpfs",
        "--bind", f"{workspace.resolve()}:/work",
        "--pwd", "/work",
        image,
        *inner_argv,
    ]
    return subprocess.run(
        apt_argv, capture_output=True, text=True,
        env=_docker_env(), timeout=240,
        encoding="utf-8", errors="replace",
    )


def _ensure_image(project: str, runtime: str) -> str:
    """Returns the image ref (docker tag for runtime=docker, registry
    URL for runtime=apptainer)."""
    from ensure_image import ensure_gdb_image
    return ensure_gdb_image(project, runtime=runtime)


def probe_one(con: sqlite3.Connection, bug: dict, runtime: str, log) -> dict:
    """Run the strace probe against an existing workspace. Returns a
    dict with `bug_id`, `status` (probed | skipped | failed), and
    `buggy_binary_path` if found.
    """
    bug_id = bug["bug_id"]
    project = bug["project"]
    workspace = Path(bug["workspace_path"])

    if not workspace.exists():
        log(f"[{bug_id}] SKIP: workspace not on disk: {workspace}")
        return {"bug_id": bug_id, "status": "no-workspace"}

    trigger = json.loads(bug["trigger_argv_json"]) if bug["trigger_argv_json"] else []
    if not trigger:
        log(f"[{bug_id}] SKIP: no trigger_argv")
        return {"bug_id": bug_id, "status": "no-trigger"}

    image = _ensure_image(project, runtime=runtime)

    # Build + run the strace command via the chosen runtime.
    if runtime == "docker":
        argv = build_strace_docker_argv(
            workspace, image, trigger,
            project=project, bug_index=bug["bug_index"],
        )
        if argv is None:
            return {"bug_id": bug_id, "status": "failed",
                    "error": "couldn't build strace argv"}
        log(f"[{bug_id}] strace via docker (image={image})")
        proc = subprocess.run(
            argv, capture_output=True, text=True, env=_docker_env(),
            timeout=240, encoding="utf-8", errors="replace",
        )
    else:  # apptainer
        log(f"[{bug_id}] strace via apptainer (image={image})")
        proc = _run_strace_apptainer(
            workspace, image, trigger,
            project=project, bug_index=bug["bug_index"],
        )

    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    # Detect the Rosetta / QEMU ptrace failure mode early.
    if "PTRACE_TRACEME" in output and "Function not implemented" in output:
        log(f"[{bug_id}] FAIL: amd64 ptrace blocked (Rosetta/QEMU). "
            f"Run on a Linux/amd64 native host.")
        return {"bug_id": bug_id, "status": "ptrace-blocked",
                "stderr_tail": (proc.stderr or "")[-500:]}

    exec_calls = parse_exec_calls(output)
    if not exec_calls:
        log(f"[{bug_id}] FAIL: strace produced no parseable execve()s. "
            f"rc={proc.returncode}.")
        return {"bug_id": bug_id, "status": "no-execs",
                "stderr_tail": (proc.stderr or "")[-500:]}

    picked = pick_buggy_binary(workspace, exec_calls)
    if picked is None:
        log(f"[{bug_id}] FAIL: no /work/* binary found in exec chain "
            f"(saw {len(exec_calls)} execve()s but none in workspace)")
        return {"bug_id": bug_id, "status": "no-binary"}

    rel, argv = picked
    log(f"[{bug_id}] OK: {rel} (argv={argv[:3]}{'...' if len(argv) > 3 else ''})")

    # Persist
    con.execute(
        "UPDATE bugs SET buggy_binary_path = ?, buggy_binary_argv_json = ?, "
        "                probed_at = ? WHERE bug_id = ?",
        (rel, json.dumps(argv), time.strftime("%Y-%m-%d %H:%M:%S"), bug_id),
    )
    con.commit()
    return {"bug_id": bug_id, "status": "probed",
            "buggy_binary_path": rel, "buggy_binary_argv": argv}


def fetch_bugs(
    con: sqlite3.Connection, *, projects: list[str] | None,
    bug_ids: list[str] | None, force: bool,
) -> list[dict]:
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
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--project", action="append", default=None,
                   help="Restrict to projects (repeatable)")
    p.add_argument("--bug-ids", nargs="+", default=None,
                   help="Restrict to specific bug_ids")
    p.add_argument("--runtime", choices=("docker", "apptainer"),
                   default=None, help="Container runtime (default: auto-detect)")
    p.add_argument("--force", action="store_true",
                   help="Re-probe even bugs that already have buggy_binary_path")
    args = p.parse_args()

    if args.runtime is None:
        if shutil.which("docker"):
            args.runtime = "docker"
        elif shutil.which("apptainer") or shutil.which("singularity"):
            args.runtime = "apptainer"
        else:
            sys.exit("No container runtime on PATH (need docker or apptainer)")

    con = sqlite3.connect(str(args.db), check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row

    bugs = fetch_bugs(con, projects=args.project, bug_ids=args.bug_ids,
                     force=args.force)
    if not bugs:
        print("[probe_only] no bugs match (or all already probed; --force to re-probe)")
        return 0

    print(f"[probe_only] {len(bugs)} bug(s) to probe via {args.runtime}")
    def log(msg: str) -> None:
        print(msg, flush=True)

    summary = {"probed": 0, "skipped": 0, "failed": 0}
    for b in bugs:
        try:
            r = probe_one(con, b, args.runtime, log)
            if r["status"] == "probed":
                summary["probed"] += 1
            elif r["status"].startswith(("no-", "skip")):
                summary["skipped"] += 1
            else:
                summary["failed"] += 1
        except Exception as e:
            log(f"[{b['bug_id']}] EXCEPTION: {e}")
            summary["failed"] += 1

    con.close()
    print(f"[probe_only] done: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
