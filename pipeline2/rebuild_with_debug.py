"""Rebuild already-built BugsCPP buggy workspaces with DWARF debug info.

Pipeline2/build.py delegates to `bugscpp build`, which uses each project's
upstream Makefile/cmake/configure defaults. Most ship `-O2` with no `-g`,
so the compiled binaries have function symbols but no DWARF — which means
gdb can't show source lines, locals, or variable types. That cripples
ChatDBG's ability to inspect program state.

This script does NOT touch the bugscpp checkout/build pipeline. It assumes
a workspace has already been built (build_ok=1) and re-runs the project's
build with `-O2 -g` injected so DWARF gets emitted. We keep `-O2` (not
`-O0`) on purpose: a number of bugs in the corpus are integer-overflow /
UB-driven and only manifest under optimization. `-O2 -g` keeps the bug
behaviour and adds debug info; some locals will read as "optimized out"
in gdb but stack traces and source lines remain.

Per-project recipes live in REBUILD_RECIPES below. Add new projects as
needed. Each recipe is a single bash snippet executed inside the project's
gdb image (`chatdbgpro/gdb-<project>:latest`) with /work bind-mounted to
the buggy workspace.

Usage:
    python pipeline2/rebuild_with_debug.py --bug-ids berry-1
    python pipeline2/rebuild_with_debug.py --project berry
    python pipeline2/rebuild_with_debug.py --all
"""
from __future__ import annotations

import argparse
import shlex
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline2"))

from build import _bind_path, _docker_env, stderr_tail  # noqa: E402

DEFAULT_DB = REPO_ROOT / "data" / "corpus.db"

# Each recipe runs inside chatdbgpro/gdb-<project>:latest with /work bind-
# mounted to the buggy workspace. The snippet must:
#   1. Land in the right build directory
#   2. Clean prior artefacts
#   3. Re-build with -O2 -g (or equivalent) added to the C/C++ flags
# Original CFLAGS contents must be preserved — `make CFLAGS=...` *replaces*
# the variable wholesale, so each recipe spells out the project's full
# original flag set plus -g.
REBUILD_RECIPES: dict[str, str] = {
    "berry": (
        "cd /work && "
        "make clean && "
        "make -j$(nproc) "
        "CFLAGS='-Wall -Wextra -std=c99 -pedantic-errors -O2 -g'"
    ),
}


def workspace_for(bug: dict) -> Path:
    """Resolve the on-disk buggy workspace path."""
    if bug.get("workspace_path"):
        p = Path(bug["workspace_path"])
        if p.exists():
            return p
    return (
        REPO_ROOT / "data" / "workspaces"
        / bug["bug_id"] / bug["project"] / f"buggy-{bug['bug_index']}"
    )


def has_debug_info(workspace: Path, image: str, rel_path: str) -> bool:
    """True iff the ELF at <workspace>/<rel_path> carries DWARF.

    Runs readelf inside the project's docker image so this works on Windows
    hosts (no host-side readelf needed)."""
    argv = [
        "docker", "run", "--rm",
        "-v", f"{_bind_path(workspace)}:/work",
        "-w", "//work",
        image,
        "bash", "-c",
        f"readelf -S {shlex.quote(rel_path)} 2>/dev/null "
        f"| grep -E '\\.debug_(info|line)' >/dev/null && echo HAS || echo NO",
    ]
    r = subprocess.run(
        argv, capture_output=True, text=True, env=_docker_env(),
    )
    return "HAS" in (r.stdout or "")


PRIMARY_BINARIES: dict[str, list[str]] = {
    # Workspace-relative paths; first one that exists wins.
    "berry": ["berry"],
}


def find_main_binary(workspace: Path, project: str) -> str | None:
    """Best-effort workspace-relative path of the project's primary
    binary, used for the post-rebuild DWARF verification."""
    for rel in PRIMARY_BINARIES.get(project, []):
        if (workspace / rel).is_file():
            return rel
    return None


def rebuild_one(bug: dict, *, timeout: int = 1800) -> tuple[bool, str]:
    """Re-run the project's build with -g injected. Returns (ok, message)."""
    project = bug["project"]
    bug_id = bug["bug_id"]

    snippet = REBUILD_RECIPES.get(project)
    if not snippet:
        return False, f"no rebuild recipe for project={project}"

    workspace = workspace_for(bug)
    if not workspace.is_dir():
        return False, f"workspace missing: {workspace}"

    image = bug.get("gdb_image") or f"chatdbgpro/gdb-{project}:latest"

    argv = [
        "docker", "run", "--rm",
        "-v", f"{_bind_path(workspace)}:/work",
        "-w", "//work",
        image,
        "bash", "-c", snippet,
    ]

    t0 = time.time()
    r = subprocess.run(
        argv, capture_output=True, text=True,
        timeout=timeout, env=_docker_env(),
    )
    elapsed = time.time() - t0

    if r.returncode != 0:
        return False, f"rebuild failed in {elapsed:.1f}s: {stderr_tail(r, 800)}"

    rel = find_main_binary(workspace, project)
    if rel is None:
        return True, f"rebuilt in {elapsed:.1f}s (no DWARF check — unknown primary binary)"
    if not has_debug_info(workspace, image, rel):
        return False, f"rebuilt in {elapsed:.1f}s but {rel} still lacks DWARF"
    return True, f"rebuilt in {elapsed:.1f}s, DWARF present in {rel}"


def fetch_bugs(
    con: sqlite3.Connection,
    bug_ids: list[str] | None,
    project: str | None,
    only_built: bool,
) -> list[dict]:
    sql = (
        "SELECT bug_id, project, bug_index, gdb_image, workspace_path "
        "FROM bugs"
    )
    where: list[str] = []
    params: list = []
    if only_built:
        where.append("build_ok = 1")
    if bug_ids:
        placeholders = ", ".join(["?"] * len(bug_ids))
        where.append(f"bug_id IN ({placeholders})")
        params.extend(bug_ids)
    if project:
        where.append("project = ?")
        params.append(project)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY project, bug_index"
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--bug-ids", nargs="+", default=None,
                   help="Specific bug IDs (e.g. berry-1 berry-2)")
    p.add_argument("--project", default=None,
                   help="All bugs for one project (e.g. berry)")
    p.add_argument("--all", action="store_true",
                   help="Every bug whose project has a rebuild recipe")
    p.add_argument("--include-unbuilt", action="store_true",
                   help="Also process rows with build_ok=0 (default: skip)")
    p.add_argument("--timeout", type=int, default=1800)
    args = p.parse_args()

    if not (args.bug_ids or args.project or args.all):
        sys.exit("specify --bug-ids, --project, or --all")

    db = Path(args.db)
    if not db.exists():
        sys.exit(f"DB not found: {db}")

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row

    bugs = fetch_bugs(
        con, args.bug_ids, args.project,
        only_built=not args.include_unbuilt,
    )
    if args.all:
        bugs = [b for b in bugs if b["project"] in REBUILD_RECIPES]

    if not bugs:
        print("[rebuild] nothing to do.")
        return

    missing = sorted({b["project"] for b in bugs if b["project"] not in REBUILD_RECIPES})
    if missing:
        print(f"[rebuild] no recipe for: {', '.join(missing)} (will skip)")
        bugs = [b for b in bugs if b["project"] in REBUILD_RECIPES]

    print(f"[rebuild] {len(bugs)} bug(s)")
    ok = 0
    for bug in bugs:
        bug_d = dict(bug)
        success, msg = rebuild_one(bug_d, timeout=args.timeout)
        marker = "OK" if success else "FAIL"
        print(f"[{bug_d['bug_id']}] {marker}: {msg}")
        if success:
            ok += 1

    print(f"[rebuild] done: {ok}/{len(bugs)} succeeded")


if __name__ == "__main__":
    main()
