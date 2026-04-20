"""
scripts/finalize_corpus.py  —  Pipeline Step 6
Sets included_in_corpus = 1 for bugs that pass ALL four filters:
  1. Built successfully (build_log.success = 1)
  2. Crashed reproducibly with a catchable signal (crash_reproducible = 1)
  3. Backtrace was parsed and user frame extracted (user_frame_function IS NOT NULL)
  4. Ground-truth patch was extracted AND validated (patch_validated = 1)

Run this LAST, after all other scripts complete.

Usage:
    python scripts/finalize_corpus.py

Prints a summary breakdown after marking the corpus.
"""

import sqlite3
from utils import DB_PATH, get_db_connection


def finalize(db_path=DB_PATH):
    con = get_db_connection(db_path)
    cur = con.cursor()

    # First reset any previous finalization (safe to re-run)
    cur.execute("UPDATE test_cases SET included_in_corpus = 0")

    # Mark bugs that pass every filter
    cur.execute("""
        UPDATE test_cases
        SET included_in_corpus = 1
        WHERE crash_reproducible  = 1
          AND user_frame_function IS NOT NULL
          AND patch_validated     = 1
          AND bug_id IN (
              SELECT bug_id FROM build_log WHERE success = 1
          )
    """)

    total = cur.execute(
        "SELECT COUNT(*) FROM test_cases WHERE included_in_corpus = 1"
    ).fetchone()[0]

    # Breakdown by signal
    by_signal = cur.execute("""
        SELECT crash_signal, COUNT(*) as n
        FROM test_cases WHERE included_in_corpus = 1
        GROUP BY crash_signal ORDER BY n DESC
    """).fetchall()

    # Breakdown by project (top 10)
    by_project = cur.execute("""
        SELECT project, COUNT(*) as n
        FROM test_cases WHERE included_in_corpus = 1
        GROUP BY project ORDER BY n DESC LIMIT 10
    """).fetchall()

    # How many were excluded and why
    build_fail = cur.execute("""
        SELECT COUNT(*) FROM test_cases t
        WHERE NOT EXISTS (SELECT 1 FROM build_log b WHERE b.bug_id = t.bug_id AND b.success = 1)
    """).fetchone()[0]

    crash_fail = cur.execute("""
        SELECT COUNT(*) FROM test_cases
        WHERE included_in_corpus = 0 AND crash_reproducible = 0
    """).fetchone()[0]

    frame_fail = cur.execute("""
        SELECT COUNT(*) FROM test_cases
        WHERE included_in_corpus = 0 AND user_frame_function IS NULL
          AND crash_reproducible = 1
    """).fetchone()[0]

    patch_fail = cur.execute("""
        SELECT COUNT(*) FROM test_cases
        WHERE included_in_corpus = 0 AND patch_validated = 0
          AND crash_reproducible = 1
    """).fetchone()[0]

    con.commit()
    con.close()

    print(f"\n{'='*50}")
    print(f"Final corpus: {total} bugs included")
    print(f"{'='*50}")
    print("\nBy signal:")
    for row in by_signal:
        print(f"  {row['crash_signal']:10s}  {row['n']}")
    print("\nBy project (top 10):")
    for row in by_project:
        print(f"  {row['project']:20s}  {row['n']}")
    print("\nExclusion reasons (non-exclusive):")
    print(f"  Build failed:              {build_fail}")
    print(f"  Crash not reproducible:    {crash_fail}")
    print(f"  Frame parse failed:        {frame_fail}")
    print(f"  Patch invalid/missing:     {patch_fail}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    finalize()
