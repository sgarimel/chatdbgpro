#!/usr/bin/env python3
"""Backfill case.yaml + sliced source into existing DockerDriver run dirs.

Usage:
    python -m bench.backfill_case_yamls bench/results/<run_name>/

Walks every child directory that has a result.json, looks up the case_id
in corpus.db, and writes case.yaml + the sliced source file so that
judge.py can score the run.

Idempotent: skips directories that already have a case.yaml unless
--overwrite is passed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bench.common import (
    discover_docker_cases,
    write_docker_case_yaml,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_dir", help="bench/results/<run_name>/ to backfill")
    p.add_argument("--db", default=None, help="Path to corpus.db (default: data/corpus.db)")
    p.add_argument("--overwrite", action="store_true",
                   help="Overwrite existing case.yaml files.")
    args = p.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        sys.stderr.write(f"Not a directory: {run_dir}\n")
        return 2

    # Load all docker cases keyed by bug_id
    db_path = Path(args.db) if args.db else None
    all_cases = discover_docker_cases(db_path=db_path)
    case_map = {c.bug_id: c for c in all_cases}

    child_dirs = sorted([
        d for d in run_dir.iterdir()
        if d.is_dir() and (d / "result.json").exists()
    ])
    if not child_dirs:
        sys.stderr.write(f"No run directories found under {run_dir}\n")
        return 2

    wrote = 0
    skipped = 0
    missing = 0
    for d in child_dirs:
        if (d / "case.yaml").exists() and not args.overwrite:
            skipped += 1
            continue

        result = json.loads((d / "result.json").read_text())
        case_id = result.get("case_id", "")
        case = case_map.get(case_id)
        if case is None:
            print(f"  {d.name}: case_id={case_id!r} not in corpus DB, skipping")
            missing += 1
            continue

        if write_docker_case_yaml(case, d):
            wrote += 1
        else:
            print(f"  {d.name}: could not write case.yaml (missing source?)")
            missing += 1

    print(f"[backfill] wrote={wrote}  skipped={skipped}  missing={missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
