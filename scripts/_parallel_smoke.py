"""Smoke test for _parallel.py. Not part of the pipeline."""
import sqlite3
import time
from _parallel import BugResult, run_pipeline_step
from utils import IssueTracker


def work(row, ctx):
    time.sleep(0.1)  # simulate real work; parallel gain should be visible
    r = BugResult(bug_id=row["bug_id"])
    r.db_updates.append(
        ("INSERT INTO t (bug_id, ok) VALUES (?, ?)",
         (row["bug_id"], row["ok"])))
    if row["ok"]:
        r.counters["success"] = 1
        r.log_lines.append(f"  [OK] {row['bug_id']}")
    else:
        r.counters["fail"] = 1
        r.issue_records.append(("fake_fail", row["bug_id"], "stub"))
    return r


if __name__ == "__main__":
    rows = [{"bug_id": f"b{i}", "ok": i % 3 != 0} for i in range(12)]

    for workers in (1, 4):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE t (bug_id TEXT, ok INT)")
        tr = IssueTracker("test")
        t0 = time.time()
        c = run_pipeline_step(rows, work, {}, workers=workers,
                              desc=f"w={workers}", con=con, issue_tracker=tr)
        dt = time.time() - t0
        n = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        print(f"\n[workers={workers}] elapsed={dt:.2f}s counters={c} rows_in_db={n}")
        tr.print_summary()
