"""Smoke test for the F5 case-trigger resolver. Not part of the pipeline.

Runs entirely on local data — no Docker, no built workspace required.
Asserts on:
  * _render_test_command_template handles each real BugsC++ harness shape
    (ctest, automake, kyua, dpp_test_list)
  * resolve_case_trigger picks Tier-2 templated when no workspace is available
  * _extract_ctest_command_from_json parses real json-v1 output shape
  * resolve_case_trigger emits "unsupported" when test commands missing

Run from project root:
    python scripts/_resolver_smoke.py
"""
from __future__ import annotations

import json
import shlex
import sys
import traceback
from pathlib import Path

import utils
from utils import (
    BUGSCPP_TAXONOMY_DIR,
    SKIP_PROJECTS,
    TriggerResolution,
    _extract_ctest_command_from_json,
    _extract_trigger_resolution,
    _render_test_command_template,
    resolve_case_trigger,
)


_FAILED = 0
_PASSED = 0


def check(name: str, cond: bool, detail: str = ""):
    global _FAILED, _PASSED
    if cond:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}: {detail}")


# ── Tier-2 template renderer ────────────────────────────────────────────────

def test_render_substitutes_dpp_test_index():
    cmd = [{"lines": ["bash -c 'ctest --tests-regex $(cat DPP_TEST_INDEX) --test-dir build'"]}]
    out = _render_test_command_template(cmd, 7)
    check("render: ctest substitutes index", "7" in out and "$(cat DPP_TEST_INDEX)" not in out,
          out)
    check("render: returns bash -c wrapper", out.startswith("bash -c "), out)


def test_render_substitutes_parallel_build():
    cmd = [{"lines": ["make -j@DPP_PARALLEL_BUILD@ check"]}]
    out = _render_test_command_template(cmd, 1)
    check("render: @DPP_PARALLEL_BUILD@ replaced",
          "@DPP_PARALLEL_BUILD@" not in out and "-j1" in out, out)


def test_render_substitutes_relative_index():
    cmd = [{"lines": ["bash -c 'cd tests; index=$(cat ../DPP_TEST_INDEX); echo $index'"]}]
    out = _render_test_command_template(cmd, 12)
    check("render: ../DPP_TEST_INDEX substituted",
          "12" in out and "../DPP_TEST_INDEX" not in out, out)


def test_render_joins_multiple_lines():
    cmd = [{"lines": [
        "bash -c '[ -f X ] || echo y > X'",
        "bash -c 'cat X'",
    ]}]
    out = _render_test_command_template(cmd, 1)
    check("render: joins lines with &&", " && " in out, out)


def test_render_returns_none_on_empty():
    check("render: empty list -> None", _render_test_command_template([], 1) is None)
    check("render: None -> None", _render_test_command_template(None, 1) is None)
    check("render: blank lines -> None",
          _render_test_command_template([{"lines": ["", "  "]}], 1) is None)


# ── Tier-1 ctest json parser ────────────────────────────────────────────────

def test_ctest_json_extracts_argv():
    raw = """
    Internal cmake build directory: /work/build
    {
      "tests": [
        {"name": "test_one", "command": ["/work/build/bin/runner", "--mode", "fast"]},
        {"name": "test_two", "command": ["/work/build/bin/runner", "--mode", "slow"]}
      ]
    }
    """
    argv = _extract_ctest_command_from_json(raw, 2)
    check("ctest_json: picks 1-based case index",
          argv == ["/work/build/bin/runner", "--mode", "slow"], argv)


def test_ctest_json_out_of_range():
    raw = '{"tests":[{"name":"a","command":["/x"]}]}'
    check("ctest_json: out-of-range -> None",
          _extract_ctest_command_from_json(raw, 5) is None)


def test_ctest_json_unparseable():
    check("ctest_json: invalid -> None",
          _extract_ctest_command_from_json("no json here", 1) is None)


# ── Public dispatch ─────────────────────────────────────────────────────────

def test_dispatch_unknown_test_type_uses_template():
    res = resolve_case_trigger(
        project="madeup",
        bug_index=1,
        case_index=3,
        test_type="brand-new-harness",
        common_test_commands=[{"lines": ["bash -c 'echo hello $(cat DPP_TEST_INDEX)'"]}],
        workspace_dir=None,
        docker_image=None,
    )
    check("dispatch: unknown harness falls back to templated",
          res.harness == "templated" and res.status == "wrapped"
          and "3" in res.trigger_command, repr(res))


def test_dispatch_no_workspace_no_template_unsupported():
    res = resolve_case_trigger(
        project="madeup",
        bug_index=1,
        case_index=3,
        test_type="ctest",
        common_test_commands=None,
        workspace_dir=None,
        docker_image=None,
    )
    check("dispatch: no template + no workspace -> unsupported",
          res.harness == "unsupported"
          and res.status == "unsupported"
          and res.trigger_command is None, repr(res))


def test_dispatch_invalid_case_index():
    res = resolve_case_trigger(
        project="x", bug_index=1, case_index=0,
        test_type="ctest",
        common_test_commands=[{"lines": ["echo $(cat DPP_TEST_INDEX)"]}],
    )
    check("dispatch: case_index < 1 -> error", res.status == "error", repr(res))


# ── End-to-end: every case-format defect in the real taxonomy gets a trigger ─

def test_taxonomy_full_coverage():
    if not BUGSCPP_TAXONOMY_DIR.exists():
        print(f"  SKIP  taxonomy coverage: {BUGSCPP_TAXONOMY_DIR} not present")
        return

    # Resolve each defect with a clean workspace path so leftover state from
    # prior pipeline runs doesn't tilt the harness mix.
    empty_ws = Path("/__nonexistent_resolver_smoke_ws__")
    total = 0
    no_resolution_rows = 0
    by_harness: dict[str, int] = {}
    by_status: dict[str, int] = {}
    unresolved_examples: list[tuple[str, int, str]] = []

    for proj_dir in sorted(BUGSCPP_TAXONOMY_DIR.iterdir()):
        if not proj_dir.is_dir() or proj_dir.name in SKIP_PROJECTS:
            continue
        meta_file = proj_dir / "meta.json"
        if not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text())
        common = meta.get("common", {})
        test_type = common.get("test-type")
        cmds = (common.get("test") or {}).get("commands")

        for defect in meta.get("defects", []):
            total += 1
            res = _extract_trigger_resolution(
                defect,
                project=proj_dir.name,
                test_type=test_type,
                common_test_commands=cmds,
                resolve_case_triggers=True,
                workspace_dir=empty_ws,
            )
            if res is None:
                no_resolution_rows += 1
                continue
            by_harness[res.harness] = by_harness.get(res.harness, 0) + 1
            by_status[res.status] = by_status.get(res.status, 0) + 1
            if res.trigger_command is None:
                unresolved_examples.append(
                    (proj_dir.name, defect.get("id"), res.reason or "")
                )

    print(f"\n  Total defects: {total}")
    print(f"  Harness breakdown: {by_harness}")
    print(f"  Status  breakdown: {by_status}")
    print(f"  No-resolution rows (defects with neither extra_tests nor case): "
          f"{no_resolution_rows}")
    if unresolved_examples:
        print(f"  Unresolved (first 10): {unresolved_examples[:10]}")

    unresolved = sum(1 for _, _, _ in unresolved_examples)
    accounted = sum(by_status.values()) + no_resolution_rows

    # F5 exit criterion (a): ≤20 unresolved triggers across the whole corpus.
    check("coverage: <=20 bugs unresolved",
          unresolved <= 20, f"unresolved={unresolved}")
    # Every defect must be accounted for: either a resolution row or
    # documented as having no resolvable signal.
    check("coverage: every defect accounted for",
          accounted == total,
          f"accounted={accounted} total={total}")
    # All extra_tests rows + all case-format rows that produced a templated
    # render must be reachable via Tier 2 alone (no docker).
    check("coverage: templated handler reaches case-format defects",
          by_harness.get("templated", 0) >= 175,
          f"templated={by_harness.get('templated', 0)} (expected ~182)")


def main():
    tests = [
        test_render_substitutes_dpp_test_index,
        test_render_substitutes_parallel_build,
        test_render_substitutes_relative_index,
        test_render_joins_multiple_lines,
        test_render_returns_none_on_empty,
        test_ctest_json_extracts_argv,
        test_ctest_json_out_of_range,
        test_ctest_json_unparseable,
        test_dispatch_unknown_test_type_uses_template,
        test_dispatch_no_workspace_no_template_unsupported,
        test_dispatch_invalid_case_index,
        test_taxonomy_full_coverage,
    ]
    for t in tests:
        print(f"\n{t.__name__}")
        try:
            t()
        except Exception:
            global _FAILED
            _FAILED += 1
            print(f"  ERROR: {t.__name__} raised")
            traceback.print_exc()
    print(f"\n{'='*60}")
    print(f"PASS={_PASSED}  FAIL={_FAILED}")
    sys.exit(0 if _FAILED == 0 else 1)


if __name__ == "__main__":
    main()
