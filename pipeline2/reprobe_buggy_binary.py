"""Re-probe `buggy_binary_path` on already-built bugs.

`pipeline2/build.py --resume` skips rows where `built_at IS NOT NULL`, which
means existing rows won't get the new `buggy_binary_path` column populated by
a normal resume. This script runs *only* the gdb probe step against rows
that are already built (build_ok=1) but missing buggy_binary_path, so we
don't have to redo the slow checkout+build cycle.

Usage:
    python pipeline2/reprobe_buggy_binary.py             # all eligible rows
    python pipeline2/reprobe_buggy_binary.py --bug-ids berry-1 coreutils-1
    python pipeline2/reprobe_buggy_binary.py --limit 10  # smoke test
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline2"))

from build import (  # noqa: E402
    DEFAULT_DB,
    _docker_env,
    build_strace_docker_argv,
    parse_exec_calls,
    pick_buggy_binary,
)


def fetch_eligible(con: sqlite3.Connection, bug_ids: list[str] | None,
                    overwrite: bool) -> list[dict]:
    sql = (
        "SELECT bug_id, project, bug_index, gdb_image, "
        "       trigger_argv_json, workspace_path "
        "FROM bugs WHERE build_ok = 1"
    )
    params: list = []
    if not overwrite:
        # When NOT overwriting, eligible = needs argv populated. After the
        # argv extension, rows with buggy_binary_path set but argv NULL are
        # leftovers from the path-only first pass and need re-probing.
        sql += " AND (buggy_binary_path IS NULL OR buggy_binary_argv_json IS NULL)"
    if bug_ids:
        placeholders = ", ".join(["?"] * len(bug_ids))
        sql += f" AND bug_id IN ({placeholders})"
        params.extend(bug_ids)
    sql += " ORDER BY bug_id"
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def probe_one(bug: dict, timeout: int) -> tuple[str, str | None, list[str] | None, str]:
    """Return (bug_id, path_or_None, argv_or_None, output_tail)."""
    bug_id = bug["bug_id"]
    workspace = Path(bug["workspace_path"])
    if not workspace.exists():
        return bug_id, None, None, f"workspace missing: {workspace}"

    trigger_argv = json.loads(bug["trigger_argv_json"]) if bug["trigger_argv_json"] else []
    if not trigger_argv:
        return bug_id, None, None, "no trigger argv"

    strace_argv = build_strace_docker_argv(
        workspace,
        bug["gdb_image"],
        trigger_argv,
        project=bug.get("project"),
        bug_index=bug.get("bug_index"),
    )
    if not strace_argv:
        return bug_id, None, None, "could not build strace argv"

    try:
        r = subprocess.run(
            strace_argv,
            capture_output=True, text=True, timeout=timeout,
            env=_docker_env(),
        )
        # strace writes to stderr by default; keep both for safety.
        output = (r.stderr or "") + "\n" + (r.stdout or "")
    except subprocess.TimeoutExpired as e:
        out = (e.stderr or b"") if isinstance(e.stderr, (bytes, bytearray)) else (e.stderr or "")
        if isinstance(out, (bytes, bytearray)):
            out = out.decode("utf-8", errors="replace")
        output = out or ""

    picked = pick_buggy_binary(workspace, parse_exec_calls(output))
    if picked is None:
        return bug_id, None, None, output[-400:]
    path, argv = picked
    return bug_id, path, argv, output[-400:]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--bug-ids", nargs="*", default=None,
                   help="Restrict to these bug ids (default: all eligible).")
    p.add_argument("--limit", type=int, default=None,
                   help="Probe at most N bugs (handy for smoke tests).")
    p.add_argument("--workers", type=int, default=2,
                   help="Concurrent docker invocations (default: 2).")
    p.add_argument("--timeout", type=int, default=240)
    p.add_argument("--overwrite", action="store_true",
                   help="Re-probe rows that already have buggy_binary_path set.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print findings, don't write to DB.")
    args = p.parse_args()

    db = Path(args.db)
    if not db.exists():
        sys.exit(f"DB not found: {db}")

    con = sqlite3.connect(str(db), check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row

    bugs = fetch_eligible(con, args.bug_ids, args.overwrite)
    if args.limit:
        bugs = bugs[:args.limit]
    if not bugs:
        print("[reprobe] nothing to do.")
        return

    print(f"[reprobe] probing {len(bugs)} bugs, workers={args.workers}, "
          f"timeout={args.timeout}s")

    found = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(probe_one, b, args.timeout): b for b in bugs}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                bug_id, bbp, argv, tail = fut.result()
            except Exception as e:
                errors += 1
                print(f"[{i}/{len(bugs)}] EXCEPTION: {e}", flush=True)
                continue

            argv_json = json.dumps(argv) if argv is not None else None
            if bbp:
                found += 1
                argv_preview = " ".join(argv or [])[:80]
                print(f"[{i}/{len(bugs)}] {bug_id} -> {bbp}  argv: {argv_preview}", flush=True)
            else:
                print(f"[{i}/{len(bugs)}] {bug_id} -> (none)", flush=True)

            if not args.dry_run:
                con.execute(
                    "UPDATE bugs SET buggy_binary_path = ?, "
                    "buggy_binary_argv_json = ?, probed_at = ? WHERE bug_id = ?",
                    (bbp, argv_json, time.strftime("%Y-%m-%d %H:%M:%S"), bug_id),
                )
                con.commit()

    print(f"[reprobe] done: found={found} missing={len(bugs)-found-errors} "
          f"errors={errors}")


if __name__ == "__main__":
    main()
