"""Merge fresh sweep cells into bench/results/final_paper_bench/<panel>/.

Walks one or more source sweep dirs, classifies each cell by panel
(synthetic vs realworld) using the runset TSV, copies the per-cell artifacts
that the judge needs, and appends provenance entries to _provenance.json.

Usage:
    python -m bench.copy_to_final_bench \
        --sweep bench/results/anika-paper-final-synthetic-20260510-T1-openrouter-anthropic-claude-sonnet-4-5 \
        --runset bench/results/final_paper_bench/_runset_locked.tsv \
        --final  bench/results/final_paper_bench

You can pass --sweep multiple times. Cells that already exist in the
target panel dir are skipped (no overwrite). Provenance is appended,
never rewritten.

Files copied per cell (matches the original copy_final_bench.py picker):
    case.yaml, result.json, collect.json, trajectory.json (if present),
    case-source.c (or sources/ if present), stdout.log, stderr.log,
    session.cmds, compile.log
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PER_CELL_FILES = (
    "case.yaml",
    "result.json",
    "collect.json",
    "trajectory.json",
    "case-source.c",
    "stdout.log",
    "stderr.log",
    "session.cmds",
    "compile.log",
)


def _load_panel_index(runset: Path) -> dict[str, str]:
    """Map case_id -> panel from the runset TSV."""
    out: dict[str, str] = {}
    with runset.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            out[row["case"]] = row["panel"]
    return out


def _classify_cell(cell_dir: Path, panel_by_case: dict[str, str]) -> tuple[str | None, str | None, int | None, str | None]:
    """Return (panel, case, tier, model) for a sweep-cell dir, or (None, ...) if unparseable."""
    name = cell_dir.name
    # <case>__tier<N>__<model_slug>__<config_slug>__ctx<C>__t<TR>
    parts = name.split("__")
    if len(parts) < 4:
        return None, None, None, None
    case = parts[0]
    tier_tok = parts[1]
    if not tier_tok.startswith("tier"):
        return None, None, None, None
    try:
        tier = int(tier_tok[len("tier"):])
    except ValueError:
        return None, None, None, None
    model_slug = parts[2]
    panel = panel_by_case.get(case)
    return panel, case, tier, model_slug


def _copy_one_cell(src: Path, dst: Path) -> int:
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for fname in PER_CELL_FILES:
        f = src / fname
        if f.exists():
            shutil.copy2(f, dst / fname)
            n += 1
    # Optional: per-case source files dir
    src_sources = src / "sources"
    if src_sources.is_dir():
        shutil.copytree(src_sources, dst / "sources", dirs_exist_ok=True)
    return n


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sweep", action="append", required=True, type=Path,
                   help="One or more source sweep dirs under bench/results/")
    p.add_argument("--runset", required=True, type=Path,
                   help="Runset TSV (used to classify case -> panel)")
    p.add_argument("--final", required=True, type=Path,
                   help="Path to bench/results/final_paper_bench")
    args = p.parse_args()

    panel_by_case = _load_panel_index(args.runset)
    prov_path = args.final / "_provenance.json"
    prov = {"copied": []}
    if prov_path.exists():
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
    existing_keys = {
        (e["panel"], e["case"], e["tier"], e["model"], e.get("source_cell", ""))
        for e in prov.get("copied", [])
    }

    new_entries = []
    skipped_existing = 0
    skipped_unclassified = 0
    n_cells = 0
    for sweep in args.sweep:
        if not sweep.is_dir():
            print(f"[copy] missing sweep dir: {sweep}", file=sys.stderr)
            continue
        for cell in sorted(sweep.iterdir()):
            if not cell.is_dir():
                continue
            panel, case, tier, model_slug = _classify_cell(cell, panel_by_case)
            if not panel or case is None or tier is None:
                skipped_unclassified += 1
                continue
            result_path = cell / "result.json"
            if not result_path.exists():
                continue
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            model = result.get("model") or model_slug
            elapsed_s = float(result.get("elapsed_s") or 0.0)
            status = result.get("status") or "unknown"
            key = (panel, case, tier, model, cell.name)
            if key in existing_keys:
                skipped_existing += 1
                continue
            dst_dir = args.final / panel / cell.name
            if dst_dir.exists() and (dst_dir / "result.json").exists():
                skipped_existing += 1
                continue
            n_files = _copy_one_cell(cell, dst_dir)
            new_entries.append({
                "panel": panel,
                "case": case,
                "tier": tier,
                "model": model,
                "source_sweep": sweep.name,
                "source_cell": cell.name,
                "status": status,
                "elapsed_s": elapsed_s,
                "timeout_was_600s": True,
                "files_copied": n_files,
                "merged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            n_cells += 1

    if new_entries:
        prov.setdefault("copied", []).extend(new_entries)
        prov_path.write_text(json.dumps(prov, indent=2), encoding="utf-8")

    print(f"[copy] merged {n_cells} new cells; skipped {skipped_existing} already-present, "
          f"{skipped_unclassified} unclassified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
