#!/usr/bin/env python3
"""ChatDBG ablation orchestrator.

Sweeps the (case × tier × model × tool_config × context × trial) matrix
and dispatches each cell to a tier-specific driver (see bench/drivers/).
Tier 3 (ChatDBG on lldb/gdb) is the only implemented tier today; tiers 1
and 2 will be added later per the three-tier plan.

Every run lands in bench/results/<run_name>/<run_id>/ — each driver owns
the exact contents, but at minimum emits result.json and (when a ChatDBG
session ran) collect.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Allow `python bench/orchestrator.py ...` as well as `python -m bench.orchestrator`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bench.common import (  # noqa: E402
    CONFIGS_DIR,
    RESULTS_DIR,
    build_matrix,
    discover_cases,
    discover_docker_cases,
    run_id_for,
)
from bench.drivers import get_driver  # noqa: E402
from bench.drivers.base import Driver  # noqa: E402


def _resolve_tool_configs(names: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for name in names:
        p = Path(name)
        if not p.exists():
            p = CONFIGS_DIR / name
            if p.suffix == "":
                p = p.with_suffix(".json")
        if not p.exists():
            sys.stderr.write(f"Tool-config not found: {name}\n")
            sys.exit(2)
        resolved.append(p.resolve())
    return resolved


def _driver_for_tier(
    tier: int,
    *,
    cache: dict[int, Driver],
    debugger_flag: str | None,
    dry_run: bool,
    docker: bool = False,
) -> Driver:
    cache_key = (tier, docker)
    if cache_key in cache:
        return cache[cache_key]
    if docker:
        driver = get_driver(tier, docker=True, dry_run=dry_run)
        print(f"[orchestrator] tier{tier} using Docker driver")
    elif tier == 3:
        from bench.drivers.tier3_gdb import pick_debugger
        debugger = pick_debugger(debugger_flag)
        print(f"[orchestrator] tier3 using debugger: {debugger}")
        driver = get_driver(3, debugger=debugger, dry_run=dry_run)
    else:
        driver = get_driver(tier)
    cache[cache_key] = driver
    return driver


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cases", nargs="*", default=None,
                   help="Case ids (or dir names) to run. Default: all.")
    p.add_argument("--models", nargs="+", required=True,
                   help="Model paths in LiteLLM format.")
    p.add_argument("--tool-configs", nargs="+", required=True,
                   help="Paths or names (under bench/configs/) of tool-config JSONs.")
    p.add_argument("--trials", type=int, default=1)
    p.add_argument("--context-lines", type=int, nargs="+", default=[10],
                   help="Enriched stack-trace depth(s). Paper default: 10.")
    p.add_argument("--tiers", type=int, nargs="+", default=[3],
                   help="Tier(s) to run: 1 = bash-only, 2 = bash+gdb, 3 = ChatDBG/gdb. Default: 3.")
    p.add_argument("--debugger", choices=["lldb", "gdb"], default=None,
                   help="Force a specific debugger for tier 3. Default: autodetect.")
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--name", default=None,
                   help="Results subdirectory name. Default: timestamp.")
    p.add_argument("--dry-run", action="store_true",
                   help="Compile only, skip debugger invocation.")
    p.add_argument("--docker", action="store_true",
                   help="Run BugsCPP corpus cases inside Docker containers.")
    p.add_argument("--db", default=None,
                   help="Path to corpus.db (only with --docker). Default: data/corpus.db")
    p.add_argument("--bug-ids", nargs="*", default=None,
                   help="Filter by bug_id (only with --docker, e.g. libtiff-2 jerryscript-1).")
    args = p.parse_args()

    if args.docker:
        db_path = Path(args.db) if args.db else None
        cases = discover_docker_cases(db_path, only=args.bug_ids)
    else:
        cases = discover_cases(only=args.cases)
    if not cases:
        sys.stderr.write("No cases match the filter.\n")
        return 2

    cfgs = _resolve_tool_configs(args.tool_configs)

    run_name = args.name or datetime.now().strftime("run-%Y%m%d-%H%M%S")
    out_root = RESULTS_DIR / run_name
    out_root.mkdir(parents=True, exist_ok=True)

    specs = build_matrix(
        cases, args.models, cfgs, args.trials, args.context_lines, args.tiers,
    )
    print(f"[orchestrator] {len(specs)} runs → {out_root}")

    driver_cache: dict = {}
    index: list[dict] = []

    for i, spec in enumerate(specs, 1):
        rid = run_id_for(spec)
        print(f"[{i}/{len(specs)}] {rid}")
        run_dir = out_root / rid
        try:
            driver = _driver_for_tier(
                spec.tier,
                cache=driver_cache,
                debugger_flag=args.debugger,
                dry_run=args.dry_run,
                docker=args.docker,
            )
            result = driver.run(spec, run_dir, timeout=args.timeout)
        except Exception as e:
            result = {
                "run_id": rid,
                "status": "error",
                "error": repr(e),
                "case_id": spec.case.case_id,
                "model": spec.model,
                "tool_config": spec.tool_config_path.name,
                "tier": spec.tier,
            }
        index.append(result)
        (out_root / "index.json").write_text(json.dumps(index, indent=2))

    print(f"[orchestrator] done. Index: {out_root / 'index.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
