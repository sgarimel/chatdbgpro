#!/usr/bin/env python3
"""Run non-BugsC++ C/C++ cases without Docker.

This is the dedicated runner for `bench/cases/external/*` and other
synthetic/injected cases. It intentionally never passes `docker=True`, never
uses the synthetic-runner image, and forces Tier 2 to use native gdb.

Recommended host: Linux or WSL with clang/gcc, gdb, bash, and the bench Python
envs installed. macOS can run T1/T3(lldb)/T4 natively, but T2 needs native gdb
and is best run from Linux/WSL/VM.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import dotenv
    dotenv.load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

from bench.common import (  # noqa: E402
    CONFIGS_DIR,
    RESULTS_DIR,
    RunSpec,
    discover_cases,
    finalize_result,
    run_id_for,
)
from bench.drivers import get_driver  # noqa: E402


TIER_CONFIG = {
    1: CONFIGS_DIR / "tier1_bash_only.json",
    2: CONFIGS_DIR / "tier2_gdb_plus_bash.json",
    3: CONFIGS_DIR / "tier3_gdb_only.json",
    4: CONFIGS_DIR / "tier4_claude_code.json",
}


def _compiler_for(case) -> str:
    build = case.meta.get("build", {}) or {}
    default = "clang++" if case.language in ("cpp", "c++") else "clang"
    return build.get("compiler", default)


def _which(name: str) -> str | None:
    return shutil.which(name)


def preflight(cases, tiers: list[int], *, dry_run: bool) -> list[str]:
    problems: list[str] = []
    system = platform.system()
    if system == "Windows":
        problems.append(
            "This runner is intentionally native/no-Docker. Run it inside WSL "
            "or another Unix-like shell; Windows lacks the required gdb/bash "
            "execution model."
        )

    if any(getattr(c, "kind", "") == "docker_bugscpp" for c in cases):
        problems.append("external_runner refuses BugsC++ DockerCase inputs.")

    compilers = sorted({_compiler_for(c) for c in cases})
    for compiler in compilers:
        if not _which(compiler):
            problems.append(f"Missing compiler on PATH: {compiler}")

    if 1 in tiers or 2 in tiers:
        if not _which("bash"):
            problems.append("Missing bash on PATH.")
        from bench.drivers.tier1_minisweagent import MINI_VENV_PYTHON
        if not MINI_VENV_PYTHON.exists() and not dry_run:
            problems.append(
                f"Missing mini-swe-agent Python env: {MINI_VENV_PYTHON}. "
                "Create .venv-bench or set CHATDBG_MINI_PY."
            )

    if 2 in tiers:
        if not _which("gdb"):
            problems.append(
                "Tier 2 requires native gdb on PATH. For macOS teammates, run "
                "this tier from Linux/WSL/VM rather than Docker."
            )

    if 3 in tiers:
        if not (_which("gdb") or _which("lldb")):
            problems.append("Tier 3 requires native gdb or lldb on PATH.")

    if 4 in tiers and not dry_run:
        if not _which("claude"):
            problems.append("Tier 4 requires Claude Code CLI on PATH: claude")

    return problems


def _resolve_config_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = CONFIGS_DIR / value
    if not path.exists():
        raise FileNotFoundError(f"Tool config not found: {path}")
    return path


def build_specs(cases, tiers, models, tier4_models, trials, context_lines, tier_config):
    specs: list[RunSpec] = []
    for case in cases:
        for tier in tiers:
            model_list = tier4_models if tier == 4 and tier4_models else models
            for model in model_list:
                for ctx in context_lines:
                    for trial in range(1, trials + 1):
                        specs.append(RunSpec(
                            case=case,
                            model=model,
                            tool_config_path=tier_config[tier],
                            trial=trial,
                            context_lines=ctx,
                            tier=tier,
                        ))
    return specs


def driver_for_tier(tier: int, *, cache: dict, args):
    if tier in cache:
        return cache[tier]
    if tier == 1:
        kwargs = {"dry_run": args.dry_run}
        if args.mini_model_class:
            kwargs["mini_model_class"] = args.mini_model_class
        driver = get_driver(1, docker=False, **kwargs)
        print("[external_runner] T1 native mini-swe-agent bash")
    elif tier == 2:
        kwargs = {"dry_run": args.dry_run, "prefer_linux": "never"}
        if args.mini_model_class:
            kwargs["mini_model_class"] = args.mini_model_class
        driver = get_driver(2, docker=False, **kwargs)
        print("[external_runner] T2 native mini-swe-agent bash+gdb (Docker disabled)")
    elif tier == 3:
        from bench.drivers.tier3_gdb import pick_debugger
        debugger = pick_debugger(args.debugger)
        driver = get_driver(
            3,
            docker=False,
            debugger=debugger,
            dry_run=args.dry_run,
            containerize=False,
        )
        print(f"[external_runner] T3 native ChatDBG via {debugger} (Docker disabled)")
    elif tier == 4:
        driver = get_driver(
            4,
            docker=False,
            dry_run=args.dry_run,
            bare=args.tier4_bare,
        )
        print(f"[external_runner] T4 native Claude Code (bare={args.tier4_bare})")
    else:
        raise ValueError(f"Unknown tier: {tier}")
    cache[tier] = driver
    return driver


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="*", default=None,
                        help="Case ids. Default: all non-BugsC++ cases.")
    parser.add_argument("--models", nargs="+", required=True,
                        help="Model paths for T1/T2/T3.")
    parser.add_argument("--tier4-models", nargs="*", default=None,
                        help="Claude Code model aliases/ids for T4. Defaults to --models.")
    parser.add_argument("--tiers", nargs="+", type=int, default=[1, 2, 3, 4],
                        choices=(1, 2, 3, 4))
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--context-lines", nargs="+", type=int, default=[10])
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--name", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--strict-schema", action="store_true")
    parser.add_argument("--debugger", choices=("gdb", "lldb"), default=None,
                        help="Force T3 debugger. Default: autodetect.")
    parser.add_argument("--tier3-config", default=TIER_CONFIG[3].name,
                        help=(
                            "Tool config for Tier 3, as a bench/configs filename "
                            "or absolute path. Default: tier3_gdb_only.json."
                        ))
    parser.add_argument("--mini-model-class", default=None)
    parser.add_argument("--tier4-bare", default="auto",
                        choices=("auto", "always", "never"))
    parser.add_argument("--ignore-preflight", action="store_true",
                        help="Run even if native-tool checks fail.")
    args = parser.parse_args()

    cases = discover_cases(only=args.cases, strict_schema=args.strict_schema)
    cases = [c for c in cases if getattr(c, "kind", "") != "docker_bugscpp"]
    if not cases:
        sys.stderr.write("No non-BugsC++ cases match the filter.\n")
        return 2

    problems = preflight(cases, args.tiers, dry_run=args.dry_run)
    if problems and not args.ignore_preflight:
        sys.stderr.write("[external_runner] Native preflight failed:\n")
        for problem in problems:
            sys.stderr.write(f"  - {problem}\n")
        sys.stderr.write("\nRun from WSL/Linux, install the missing native tools, or pass --ignore-preflight.\n")
        return 2

    run_name = args.name or datetime.now().strftime("external-%Y%m%d-%H%M%S")
    out_root = RESULTS_DIR / run_name
    out_root.mkdir(parents=True, exist_ok=True)

    tier_config = dict(TIER_CONFIG)
    try:
        tier_config[3] = _resolve_config_path(args.tier3_config)
    except FileNotFoundError as exc:
        sys.stderr.write(f"[external_runner] {exc}\n")
        return 2

    specs = build_specs(
        cases,
        args.tiers,
        args.models,
        args.tier4_models or [],
        args.trials,
        args.context_lines,
        tier_config,
    )
    print(f"[external_runner] {len(specs)} native runs -> {out_root}")
    print("[external_runner] Docker is disabled for this runner.")
    if 3 in args.tiers:
        print(f"[external_runner] T3 tool config: {tier_config[3]}")

    driver_cache: dict = {}
    index: list[dict] = []
    for i, spec in enumerate(specs, 1):
        rid = run_id_for(spec)
        run_dir = out_root / rid
        if args.skip_existing and (run_dir / "result.json").exists():
            try:
                prior = json.loads((run_dir / "result.json").read_text())
                if prior.get("status") == "ok":
                    print(f"[{i}/{len(specs)}] {rid} [skipped prior ok]")
                    index.append(prior)
                    (out_root / "index.json").write_text(json.dumps(index, indent=2))
                    continue
            except Exception:
                pass

        print(f"[{i}/{len(specs)}] {rid}")
        try:
            driver = driver_for_tier(spec.tier, cache=driver_cache, args=args)
            result = driver.run(spec, run_dir, timeout=args.timeout)
        except Exception as exc:
            run_dir.mkdir(parents=True, exist_ok=True)
            result = {
                "run_id": rid,
                "status": "error",
                "error": repr(exc),
                "case_id": spec.case.case_id,
                "model": spec.model,
                "tool_config": spec.tool_config_path.name,
                "tier": spec.tier,
            }
            (run_dir / "result.json").write_text(json.dumps(result, indent=2))
        index.append(result)
        (out_root / "index.json").write_text(json.dumps(index, indent=2))

    print(f"[external_runner] done. Index: {out_root / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
