"""Top-level entry point: schema -> seed -> build_and_probe."""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "corpus.db"
SCHEMA = REPO_ROOT / "pipeline2" / "schema.sql"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--project", default=None)
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    print("[run_all] applying schema")
    con = sqlite3.connect(str(db))
    con.executescript(SCHEMA.read_text())
    con.close()

    print("[run_all] seeding bugs table")
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "pipeline2" / "seed.py"), "--db", str(db)],
    )
    if r.returncode != 0:
        sys.exit(f"seed failed: {r.returncode}")

    print("[run_all] build + probe")
    cmd = [
        sys.executable, str(REPO_ROOT / "pipeline2" / "build_and_probe.py"),
        "--db", str(db),
        "--workers", str(args.workers),
    ]
    if args.project:
        cmd += ["--project", args.project]
    if args.resume:
        cmd += ["--resume"]
    sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
