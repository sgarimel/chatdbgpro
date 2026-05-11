"""Patch collect.json.queries[0].response when the model wrote its diagnosis
to bash via echo instead of via mini-swe-agent's submission protocol.

Background (see memory: project_tier1_response_extraction_blind_spot.md):
`bench/drivers/tier1_runner.py::_extract_response` only concatenates
assistant `content` and the exit-message `submission`. Smaller and
quirkier models often emit their ROOT CAUSE / LOCAL FIX / GLOBAL FIX
by `echo`-ing it to bash (so the diagnosis becomes tool *output*),
then sending a separate `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`. That
leaves `response` empty and the judge marks the cell
`no_prose_synthesis` 0/0/0 even though the model solved the problem.

This script:
- walks every cell under the target dir
- if `collect.json.queries[0].response` is < 50 chars AND `trajectory.json`
  contains a tool message whose `raw_output` (or `content`) holds all
  three labelled paragraphs (ROOT CAUSE, LOCAL FIX, GLOBAL FIX),
  copy that tool output into `response` and stash the original
  empty/short value in `response_pre_recovery`
- idempotent: skips cells where `response_pre_recovery` already exists
- prints a per-cell change log

Run before judging the panel.

Usage:
    python -m bench.recover_responses bench/results/final_paper_bench/synthetic
    python -m bench.recover_responses bench/results/anika-paper-final-synthetic-20260510-T1-*
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REQUIRED_LABELS = ("ROOT CAUSE", "LOCAL FIX", "GLOBAL FIX")
EMPTY_THRESHOLD = 50


def find_tool_output_with_diagnosis(traj: dict) -> str | None:
    """Return the latest tool message text containing all three labelled
    paragraphs, or None if no such message exists. Prefer raw_output over
    content because mini-swe-agent's tool message `content` is sometimes
    truncated while `raw_output` is the full echoed payload.
    """
    msgs = traj.get("messages") or []
    best: str | None = None
    for m in msgs:
        if m.get("role") != "tool":
            continue
        extra = m.get("extra") or {}
        raw = str(extra.get("raw_output") or "")
        content = str(m.get("content") or "")
        for candidate in (raw, content):
            if not candidate:
                continue
            if all(label in candidate for label in REQUIRED_LABELS):
                best = candidate  # keep walking — we want the LAST occurrence
    return best


def process_cell(cell_dir: Path) -> tuple[str, str]:
    """Return (status, note). status is one of:
      'recovered'     — patched response
      'already_set'   — recovered on a previous run
      'no_change'     — response already populated normally
      'unrecoverable' — empty response AND no diagnosis in tool output
      'skipped'       — collect.json or trajectory.json missing / malformed
    """
    cj_path = cell_dir / "collect.json"
    tj_path = cell_dir / "trajectory.json"
    if not cj_path.exists():
        return "skipped", "no collect.json"
    try:
        cj = json.loads(cj_path.read_text(encoding="utf-8"))
    except Exception as e:
        return "skipped", f"collect.json parse: {e}"

    q = (cj.get("queries") or [{}])[0]
    if q.get("response_pre_recovery") is not None:
        return "already_set", ""
    resp = q.get("response") or ""
    if len(resp) >= EMPTY_THRESHOLD:
        return "no_change", ""

    if not tj_path.exists():
        return "unrecoverable", "no trajectory.json"
    try:
        traj = json.loads(tj_path.read_text(encoding="utf-8"))
    except Exception as e:
        return "unrecoverable", f"trajectory parse: {e}"

    diag = find_tool_output_with_diagnosis(traj)
    if diag is None:
        return "unrecoverable", "no RC/LF/GF in any tool output"

    # Patch in place: keep the original, prepend a marker so anyone
    # reading later can tell this came from tool output rather than the
    # assistant's content.
    q["response_pre_recovery"] = resp
    q["response_source"] = "recovered_from_tool_output"
    q["response"] = (
        "[recovered from tool output by bench.recover_responses; "
        "model echo'd diagnosis instead of using mini-swe-agent submission]\n\n"
        + diag.strip()
    )
    cj["queries"][0] = q
    cj_path.write_text(json.dumps(cj, indent=2), encoding="utf-8")
    return "recovered", f"{len(diag)} chars from tool output"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("targets", nargs="+", type=Path,
                   help="One or more directories. Each is treated as either "
                        "(a) a panel dir containing cell subdirs directly, or "
                        "(b) a sweep dir containing cell subdirs. Both shapes work — "
                        "we walk every direct subdir that contains a result.json.")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    totals = dict(recovered=0, already_set=0, no_change=0,
                  unrecoverable=0, skipped=0)
    examples: dict[str, list[str]] = {k: [] for k in totals}
    for target in args.targets:
        if not target.exists():
            print(f"[warn] skipping missing dir: {target}", file=sys.stderr)
            continue
        for cell in sorted(target.iterdir()):
            if not cell.is_dir():
                continue
            if not (cell / "result.json").exists():
                continue
            status, note = process_cell(cell)
            totals[status] += 1
            if len(examples[status]) < 3:
                examples[status].append(f"{cell.name}{(': ' + note) if note else ''}")
            if not args.quiet and status == "recovered":
                print(f"[recover] {cell.relative_to(target.parent)}  ({note})")

    print()
    print("[recover] summary")
    for k in ("recovered", "already_set", "no_change", "unrecoverable", "skipped"):
        print(f"  {k:>14}: {totals[k]}")
        if examples[k] and k in ("unrecoverable", "skipped"):
            for ex in examples[k][:3]:
                print(f"                  e.g. {ex}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
