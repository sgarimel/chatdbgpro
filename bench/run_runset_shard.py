"""Run one panel-tier-tagged shard of the locked runset.

Reads bench/results/final_paper_bench/_runset_locked.tsv (produced by
bench/build_runset.py), filters to a panel (--panel synthetic|realworld) and
optionally a tier (--tiers 1 3), then groups rows by (tier, model) and shells
out to bench.parallel_run once per group.

Always passes --timeout 600 (the canonical paper-final wall) and --trials 1
(matches the existing single-trial sweep convention; cell dirs end in `__t1`).

Usage (Anika, Windows/WSL, synthetic):
    python -m bench.run_runset_shard \
        --runset bench/results/final_paper_bench/_runset_locked.tsv \
        --panel synthetic \
        --owner anika \
        --runtime docker

Usage (Ibraheem, Adroit, realworld, gdb-only first then bash-only):
    python -m bench.run_runset_shard \
        --runset bench/results/final_paper_bench/_runset_locked.tsv \
        --panel realworld \
        --tiers 3 1 \
        --owner ibraheem \
        --runtime apptainer

Output: per (tier, model) group, one sweep dir at:
    bench/results/<owner>-paper-final-<panel>-<YYYYMMDD>-T<tier>-<modelslug>/
The orchestrator's --skip-existing makes each call idempotent — re-running this
script picks up where a crashed/killed worker left off.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _slugify(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")


def _read_runset(path: Path):
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            yield row["panel"], row["case"], int(row["tier"]), row["model"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runset", required=True, type=Path)
    p.add_argument("--panel", required=True, choices=("synthetic", "realworld"))
    p.add_argument("--tiers", nargs="+", type=int, default=None,
                   help="Codebase tier numbers to run (e.g. 1 3). Default: all tiers in the runset for this panel.")
    p.add_argument("--models", nargs="+", default=None,
                   help="Model IDs to run. Default: all models in the runset for this panel.")
    p.add_argument("--owner", required=True,
                   help="Tag for the output sweep dir (e.g. 'anika' or 'ibraheem').")
    p.add_argument("--runtime", default="apptainer",
                   choices=("docker", "apptainer"))
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--date", default=None,
                   help="Date tag for the sweep dir. Default: today YYYYMMDD.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    date_tag = args.date or dt.date.today().strftime("%Y%m%d")
    by_tier_model: dict[tuple[int, str], list[str]] = defaultdict(list)
    for panel, case, tier, model in _read_runset(args.runset):
        if panel != args.panel:
            continue
        if args.tiers is not None and tier not in args.tiers:
            continue
        if args.models is not None and model not in args.models:
            continue
        by_tier_model[(tier, model)].append(case)

    if not by_tier_model:
        print(f"[shard] no cells matched panel={args.panel} tiers={args.tiers} models={args.models}",
              file=sys.stderr)
        return 1

    total_cells = sum(len(v) for v in by_tier_model.values())
    print(f"[shard] panel={args.panel} owner={args.owner} runtime={args.runtime} "
          f"timeout={args.timeout}s -> {len(by_tier_model)} (tier,model) groups, "
          f"{total_cells} cells")

    rc_overall = 0
    for (tier, model), cases in sorted(by_tier_model.items()):
        sweep = f"{args.owner}-paper-final-{args.panel}-{date_tag}-T{tier}-{_slugify(model)}"
        cases_sorted = sorted(set(cases))
        cmd = [
            sys.executable, "-m", "bench.parallel_run",
            "--bug-ids", *cases_sorted,
            "--tiers", str(tier),
            "--models", model,
            "--name", sweep,
            "--runtime", args.runtime,
            "--timeout", str(args.timeout),
            "--workers", str(args.workers),
        ]
        if args.panel == "synthetic":
            # Synthetic case ids are case.yaml manifests under bench/cases/,
            # not rows in corpus.db. Force the orchestrator's on-disk
            # --cases path; --runtime is ignored downstream in this mode.
            cmd.append("--no-docker")
        if args.dry_run:
            cmd.append("--dry-run")
        print(f"[shard] >>> T{tier} {model}: {len(cases_sorted)} cases -> sweep={sweep}",
              flush=True)
        print(f"        {' '.join(cmd)}", flush=True)
        r = subprocess.run(cmd, cwd=str(REPO_ROOT))
        if r.returncode != 0:
            rc_overall = r.returncode
            print(f"[shard] !!! group T{tier} {model} returned rc={r.returncode}; "
                  f"continuing with next group", file=sys.stderr)
    return rc_overall


if __name__ == "__main__":
    sys.exit(main())
