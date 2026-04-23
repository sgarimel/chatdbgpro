"""
scripts/_parallel.py
Shared multiprocess runner for pipeline Steps 2–5.

Design contract:
  * Workers never touch the SQLite DB. They do subprocess calls + file I/O
    only and return a BugResult describing what the main process should
    record (DB writes, IssueTracker records, log lines, counter bumps).
  * The main process owns the single DB connection, applies all writes
    in-order, and commits once per bug. No concurrent-writer / WAL dance
    needed — contention is impossible by construction.
  * Serial fallback (workers <= 1) runs the same per-bug function inline,
    so the refactored scripts stay testable without spawning a pool.

Public surface:
  BugResult       — dataclass returned by each per-bug worker
  run_pipeline_step(bug_rows, work_fn, ctx, workers, desc, con, issue_tracker)

`work_fn` must be a module-level function (picklable under Windows spawn).
`bug_rows` items must be plain dicts (not sqlite3.Row — Rows don't pickle
cleanly across a spawn boundary).
"""
from __future__ import annotations

import multiprocessing as mp
from dataclasses import dataclass, field
from typing import Any, Callable

from tqdm import tqdm


@dataclass
class BugResult:
    bug_id: str
    db_updates: list[tuple[str, tuple]] = field(default_factory=list)
    issue_records: list[tuple[str, str | None, str]] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)


def _worker_entry(args):
    """Top-level so it's picklable on Windows spawn."""
    work_fn, row, ctx = args
    try:
        return work_fn(row, ctx)
    except Exception as e:
        bug_id = row.get("bug_id", "?")
        return BugResult(
            bug_id=bug_id,
            issue_records=[("worker_exception", bug_id, repr(e)[:200])],
            log_lines=[f"  [WORKER ERROR] {bug_id}: {e}"],
        )


def run_pipeline_step(
    bug_rows: list[dict],
    work_fn: Callable[[dict, dict], BugResult],
    ctx: dict,
    workers: int,
    *,
    desc: str,
    con: Any,
    issue_tracker: Any,
) -> dict[str, int]:
    """
    Run work_fn once per bug, dispatching to N worker processes when workers>1.

    Applies each BugResult.db_updates via con, commits per bug, routes log
    lines through tqdm.write so the progress bar stays coherent, and bumps
    the aggregate counter dict that is returned.
    """
    counters: dict[str, int] = {}
    cur = con.cursor()

    def _apply(res: BugResult):
        for sql, params in res.db_updates:
            cur.execute(sql, params)
        con.commit()
        for kind, bid, detail in res.issue_records:
            issue_tracker.record(kind, bid, detail)
        for line in res.log_lines:
            tqdm.write(line)
        for k, v in res.counters.items():
            counters[k] = counters.get(k, 0) + v

    if workers <= 1 or len(bug_rows) <= 1:
        for row in tqdm(bug_rows, desc=desc, unit="bug"):
            _apply(_worker_entry((work_fn, row, ctx)))
        return counters

    payloads = [(work_fn, row, ctx) for row in bug_rows]
    with mp.Pool(processes=workers) as pool:
        for res in tqdm(
            pool.imap_unordered(_worker_entry, payloads),
            total=len(bug_rows),
            desc=desc,
            unit="bug",
        ):
            _apply(res)

    return counters
