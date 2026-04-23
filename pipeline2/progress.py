"""Quick progress snapshot for the pipeline2 build run."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB = REPO_ROOT / "data" / "corpus.db"


def main() -> None:
    if not DB.exists():
        sys.exit(f"DB not found: {DB}")

    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row

    s = con.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN built_at IS NOT NULL THEN 1 ELSE 0 END) AS done,
               SUM(build_ok) AS built,
               SUM(CASE WHEN bug_observed LIKE 'crash:%' THEN 1 ELSE 0 END) AS crashed,
               SUM(included_in_corpus) AS incl
        FROM bugs
    """).fetchone()
    pct = (s["done"] or 0) * 100 // s["total"] if s["total"] else 0
    print(f"overall: {s['done'] or 0}/{s['total']} processed ({pct}%)  "
          f"built={s['built'] or 0}  crashed={s['crashed'] or 0}  "
          f"included={s['incl'] or 0}")

    print()
    print(f"{'project':20} {'total':>5} {'done':>5} {'built':>5} {'incl':>5}")
    for r in con.execute("""
        SELECT project,
               COUNT(*) AS total,
               SUM(CASE WHEN built_at IS NOT NULL THEN 1 ELSE 0 END) AS done,
               SUM(build_ok) AS built,
               SUM(included_in_corpus) AS incl
        FROM bugs GROUP BY project ORDER BY project
    """):
        flag = "" if (r["done"] or 0) == r["total"] else " <"
        print(f"{r['project']:20} {r['total']:>5} {r['done'] or 0:>5} "
              f"{r['built'] or 0:>5} {r['incl'] or 0:>5}{flag}")

    print()
    print("last 5 updates:")
    for r in con.execute("""
        SELECT bug_id, built_at, build_ok, bug_observed, included_in_corpus
        FROM bugs WHERE built_at IS NOT NULL
        ORDER BY built_at DESC LIMIT 5
    """):
        print(f"  {r['built_at']}  {r['bug_id']:28}  "
              f"ok={r['build_ok']}  {r['bug_observed']}  "
              f"incl={r['included_in_corpus']}")

    con.close()

    print()
    print("active containers:")
    try:
        out = subprocess.run(
            ["docker", "ps", "--filter", "name=-dpp",
             "--format", "  {{.Names}}  {{.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
        print(out.stdout.rstrip() or "  (none)")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  (docker unavailable: {e})")


if __name__ == "__main__":
    main()
