"""scripts/persist_gdb_commands.py — between Step 2 and Step 3.

For every bug with a successful build, construct the exact gdb invocation
that reproduces its crash and persist it in test_cases.gdb_command.

Stored value is the COMPLETE shell command that runs inside the project's
chatdbgpro/gdb-<project>:latest container with workspace bind-mounted at
/work. crash_filter.py just wraps this with `docker run ... bash -c "<cmd>"`
and executes it 3x.

Does the libtool-wrapper swap and the bash-c unwrap AT PERSIST TIME, reading
the on-disk workspace once per bug. Previously these were re-derived on
every crash_filter run, which made small resolver bugs cascade. Having a
single persisted string also lets the operator paste-and-run the exact
line by hand for debugging.

Idempotent: re-running overwrites the column; only populates for bugs
with build_log.success=1. Run after build_filter.py finishes.
"""
from __future__ import annotations

import argparse
import shlex
import sqlite3
from pathlib import Path

from utils import (
    DB_PATH,
    get_db_connection,
    get_workspace_dir,
    tokenize_trigger,
)


GDB_PREAMBLE = (
    'export LD_LIBRARY_PATH="$(find /work -type d -name .libs -printf \'%p:\')${LD_LIBRARY_PATH:-}"'
)

GDB_FLAGS = [
    "-batch",
    "-ex", "set pagination off",
    "-ex", "set confirm off",
    "-ex", "set follow-fork-mode child",
    "-ex", "set detach-on-fork on",
    "-ex", "run",
    "-ex", "bt",
    "-ex", "quit",
]


def resolve_libtool_argv(workspace_dir: Path, argv: list[str]) -> list[str]:
    """Swap libtool wrapper shell scripts for their real .libs/ ELF
    binaries so gdb attaches directly without the wrapper's own fork."""
    if not argv:
        return argv
    exe = argv[0]
    exe_abs = workspace_dir / exe
    if not exe_abs.is_file():
        return argv
    try:
        head = exe_abs.read_bytes()[:4096]
    except Exception:
        return argv
    if b"libtool" not in head:
        return argv
    dirname, _, base = exe.rpartition("/")
    alt = f"{dirname}/.libs/lt-{base}" if dirname else f".libs/lt-{base}"
    if (workspace_dir / alt).is_file():
        return [alt] + argv[1:]
    # libtool sometimes drops the lt- prefix
    alt2 = f"{dirname}/.libs/{base}" if dirname else f".libs/{base}"
    if (workspace_dir / alt2).is_file():
        return [alt2] + argv[1:]
    return argv


def build_gdb_command(trigger_command: str | None,
                      workspace_dir: Path) -> tuple[str | None, str]:
    """Return (gdb_shell_command, explain). gdb_shell_command is the full
    container-internal shell string; explain is a short human note."""
    if not trigger_command:
        return None, "no trigger_command"

    argv = tokenize_trigger(trigger_command)
    if not argv:
        return None, "tokenize returned empty"

    # If the trigger is still wrapped in bash -c (because it had shell
    # metacharacters we couldn't unwrap), keep bash as the argv-0 and let
    # follow-fork-mode child handle the chain.
    if argv[:2] == ["bash", "-c"]:
        gdb_argv = argv
        explain = "bash wrapper (shell metachars)"
    else:
        gdb_argv = resolve_libtool_argv(workspace_dir, argv)
        if gdb_argv is not argv and gdb_argv != argv:
            explain = f"libtool: {argv[0]} -> {gdb_argv[0]}"
        else:
            explain = f"direct attach: {gdb_argv[0]}"

    gdb_cmd_parts = ["gdb"] + GDB_FLAGS + ["--args"] + gdb_argv
    gdb_cmd_str = " ".join(shlex.quote(p) for p in gdb_cmd_parts)
    full = f"{GDB_PREAMBLE}; exec {gdb_cmd_str}"
    return full, explain


def run(db_path: Path = DB_PATH, verbose: bool = False):
    con = get_db_connection(db_path)
    cur = con.cursor()

    # Every bug with at least one successful build_log row, plus its trigger.
    rows = cur.execute("""
        SELECT DISTINCT t.bug_id, t.project, t.bug_index, t.trigger_command
        FROM test_cases t
        JOIN build_log b ON t.bug_id = b.bug_id
        WHERE b.success = 1
        ORDER BY t.bug_id
    """).fetchall()

    stats = {"ok": 0, "no_trigger": 0, "no_workspace": 0}
    exemplars: list[tuple[str, str, str]] = []

    for row in rows:
        bug_id = row["bug_id"]
        ws = get_workspace_dir(row["project"], row["bug_index"], buggy=True)
        if not ws.exists():
            stats["no_workspace"] += 1
            if verbose:
                print(f"  [skip] {bug_id}: workspace missing")
            continue

        gdb_cmd, explain = build_gdb_command(row["trigger_command"], ws)
        if gdb_cmd is None:
            stats["no_trigger"] += 1
            if verbose:
                print(f"  [skip] {bug_id}: {explain}")
            continue

        cur.execute(
            "UPDATE test_cases SET gdb_command = ? WHERE bug_id = ?",
            (gdb_cmd, bug_id),
        )
        stats["ok"] += 1
        if len(exemplars) < 3:
            exemplars.append((bug_id, explain, gdb_cmd))

    con.commit()
    con.close()

    print(f"[persist_gdb_commands] {stats['ok']} persisted, "
          f"{stats['no_trigger']} skipped (no trigger), "
          f"{stats['no_workspace']} skipped (no workspace)")
    for bug_id, explain, cmd in exemplars:
        print(f"  {bug_id}  [{explain}]")
        print(f"    {cmd[:200]}{'...' if len(cmd) > 200 else ''}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    run(db_path=Path(args.db), verbose=args.verbose)
