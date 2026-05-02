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
    mini_model_class: str | None = None,
    tier2_linux: str | None = None,
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
    elif tier == 1:
        # Tier 1 = mini-swe-agent (bash-only). Driver shells out to
        # .venv-bench (Py 3.14, where mini is installed) — the
        # orchestrator's own .venv-bench-39 is too old for mini v2.
        # The optional model-class override propagates from the
        # `--mini-model-class` flag through to the runner subprocess.
        kwargs = {"dry_run": dry_run}
        if mini_model_class:
            kwargs["mini_model_class"] = mini_model_class
        driver = get_driver(1, **kwargs)
        klass_label = mini_model_class or "auto"
        print(f"[orchestrator] tier1 using mini-swe-agent (bash-only, model_class={klass_label})")
    elif tier == 2:
        # Tier 2 = mini-swe-agent + persistent gdb session. Same
        # subprocess plumbing as Tier 1 (.venv-bench shell-out), with
        # an extra gdb child process the runner manages. On macOS
        # arm64 (where gdb can't run native binaries) the driver
        # transparently routes through a linux/amd64 Docker container.
        kwargs = {"dry_run": dry_run}
        if mini_model_class:
            kwargs["mini_model_class"] = mini_model_class
        if tier2_linux:
            kwargs["prefer_linux"] = tier2_linux
        driver = get_driver(2, **kwargs)
        klass_label = mini_model_class or "auto"
        linux_label = tier2_linux or "auto"
        print(f"[orchestrator] tier2 using mini-swe-agent (bash + gdb, "
              f"model_class={klass_label}, linux={linux_label})")
    elif tier == 4:
        # Tier 4 = Claude Code (the CLI) as the agent. No debugger
        # kwarg, no mini config; just budget-capped invocation of the
        # `claude` binary in --bare mode.
        driver = get_driver(4, dry_run=dry_run)
        print("[orchestrator] tier4 using Claude Code (CLI, --bare)")
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
    p.add_argument("--trials", type=int, default=3,
                   help="Number of trials per (case, model, config). Default 3 — the previous "
                        "default of 1 produced single-shot scores with high variance from "
                        "stochastic models. [S2]")
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
    p.add_argument("--skip-existing", action="store_true",
                   help="Skip runs whose <run_dir>/result.json already exists with status=ok. "
                        "Other statuses (timeout, no_collect, ...) are still re-run. [A3]")
    p.add_argument("--include-unverified", action="store_true",
                   help="Include cases marked verified: false in case.yaml. By default these "
                        "are skipped at discovery time to avoid wasting API calls on stub "
                        "cases that don't actually inject the bug. [A5]")
    p.add_argument("--crash-only", action="store_true",
                   help="(--docker only) Only schedule BugsC++ cases that pipeline2/probe.py "
                        "confirmed actually crash. Drops wrong-output bugs that ChatDBG's "
                        "lldb-runs-until-crash session can't debug. [S5(a)]")
    p.add_argument("--skip-system-triggers", action="store_true",
                   help="(--docker only) Skip BugsC++ cases whose trigger_argv[0] is a shell "
                        "wrapper (bash/sed/find/make). gdb would attach to the wrapper, not "
                        "the bug. [S1]")
    p.add_argument("--breakpoint-at-patch", action="store_true",
                   help="(--docker only) For non-crashing BugsC++ cases, set a breakpoint at "
                        "patch_first_file:patch_first_line before `run`. Lets the model "
                        "inspect locals at the defect site instead of seeing only "
                        "exit/__libc_start_main. [S5(b)]")
    p.add_argument("--structural-fix-turn", action="store_true",
                   help="After the model's first answer, ask a follow-up: 'now propose a "
                        "structural change that prevents this class of bug'. Stored as a "
                        "second query in collect.json. [B3]")
    p.add_argument("--strict-schema", action="store_true",
                   help="Fail at discovery time if any case.yaml fails schema validation. "
                        "Default is to warn and skip the offending case. [C7]")
    p.add_argument("--mini-model-class", default=None,
                   help="(--tiers 1 only) Override mini-swe-agent's automatic model-class "
                        "selection. One of: 'litellm' (default — tool-calling), "
                        "'litellm_textbased' (regex-extracted fenced bash), "
                        "'litellm_response' (Responses API), 'openrouter', "
                        "'openrouter_textbased', 'openrouter_response', 'portkey', "
                        "'portkey_response', 'requesty'. Default = auto-select via "
                        "mini's get_model_class(model_name).")
    p.add_argument("--tier2-linux", default="auto",
                   choices=["auto", "always", "never"],
                   help="(--tiers 2 only) Whether to run Tier 2 inside a Linux/amd64 "
                        "Docker container. 'auto' (default) = Docker on macOS, native "
                        "elsewhere; 'always' = Docker even on Linux (reproducibility); "
                        "'never' = native gdb regardless of platform. Required on "
                        "macOS because gdb cannot run native arm64 binaries — see "
                        "bench/analysis_artifacts/HARNESS_AUDIT.md Round 5 for "
                        "validation evidence.")
    args = p.parse_args()

    if args.docker:
        db_path = Path(args.db) if args.db else None
        cases = discover_docker_cases(
            db_path, only=args.bug_ids,
            crash_only=args.crash_only,
            skip_system_triggers=args.skip_system_triggers,
        )
    else:
        cases = discover_cases(only=args.cases, strict_schema=args.strict_schema)
    if not cases:
        sys.stderr.write("No cases match the filter.\n")
        return 2

    # A5: drop unverified injected stubs unless explicitly opted in.
    # These ship with `verified: false` and a placeholder bug.patch
    # whose line numbers don't match upstream — running them burns API
    # quota without producing a real bug to debug.
    if not args.include_unverified:
        kept, dropped = [], []
        for c in cases:
            meta = getattr(c, "meta", {}) or {}
            if meta.get("verified") is False:
                dropped.append(getattr(c, "case_id", "?"))
            else:
                kept.append(c)
        if dropped:
            print(f"[orchestrator] skipping {len(dropped)} unverified case(s): "
                  f"{dropped}. Pass --include-unverified to run them anyway.")
        cases = kept
        if not cases:
            sys.stderr.write("All matching cases are unverified.\n")
            return 2

    cfgs = _resolve_tool_configs(args.tool_configs)

    run_name = args.name or datetime.now().strftime("run-%Y%m%d-%H%M%S")
    out_root = RESULTS_DIR / run_name
    out_root.mkdir(parents=True, exist_ok=True)

    specs = build_matrix(
        cases, args.models, cfgs, args.trials, args.context_lines, args.tiers,
        breakpoint_at_patch=args.breakpoint_at_patch,
        structural_fix_turn=args.structural_fix_turn,
    )
    print(f"[orchestrator] {len(specs)} runs -> {out_root}")

    driver_cache: dict = {}
    index: list[dict] = []

    for i, spec in enumerate(specs, 1):
        rid = run_id_for(spec)
        run_dir = out_root / rid
        # A3: --skip-existing reuses a prior status=ok run instead of
        # re-running. Other statuses (timeout, no_collect) are re-run
        # because they're typically transient lldb attach flakes.
        if args.skip_existing and (run_dir / "result.json").exists():
            try:
                prior = json.loads((run_dir / "result.json").read_text())
                if prior.get("status") == "ok":
                    print(f"[{i}/{len(specs)}] {rid}  [skipped — prior ok]")
                    index.append(prior)
                    (out_root / "index.json").write_text(json.dumps(index, indent=2))
                    continue
            except Exception:
                pass
        print(f"[{i}/{len(specs)}] {rid}")
        try:
            driver = _driver_for_tier(
                spec.tier,
                cache=driver_cache,
                debugger_flag=args.debugger,
                dry_run=args.dry_run,
                docker=args.docker,
                mini_model_class=args.mini_model_class,
                tier2_linux=args.tier2_linux,
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
