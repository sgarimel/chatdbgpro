"""Produce the locked runset of (panel, case, tier, model) cells to (re)run.

Combines:
  - The 365 missing cells in final_paper_bench/_missing_{synthetic,realworld}.txt
  - The bound-parity rows from final_paper_bench/_bound_cells.csv
    (produced by bench/audit_bound_cells.py)

Deduplicates and writes a TSV that downstream runners (run_runset_shard.py)
consume directly.

Usage:
    python -m bench.build_runset \
        --missing-synthetic bench/results/final_paper_bench/_missing_synthetic.txt \
        --missing-realworld bench/results/final_paper_bench/_missing_realworld.txt \
        --bound-csv         bench/results/final_paper_bench/_bound_cells.csv \
        --out               bench/results/final_paper_bench/_runset_locked.tsv

Output format (TSV, with header):
    panel<TAB>case<TAB>tier<TAB>model

Tier is the codebase number (1=bash-only, 2=bash+gdb, 3=gdb-only, 4=Claude Code),
not the paper label. parallel_run.py / orchestrator.py consume codebase numbers.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def _parse_missing_file(path: Path, panel: str) -> list[tuple[str, str, int, str]]:
    """Returns list of (panel, case, tier_int, model) tuples."""
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Format: "<case>  | T<tier>  | <model>"
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            continue
        case, tier_tok, model = parts
        if not tier_tok.startswith("T"):
            continue
        try:
            tier = int(tier_tok[1:])
        except ValueError:
            continue
        out.append((panel, case, tier, model))
    return out


def _parse_bound_csv(path: Path) -> list[tuple[str, str, int, str]]:
    out = []
    if not path.exists():
        print(f"[build_runset] bound CSV not found: {path} (skipping bound-parity rows)")
        return out
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("bound", "false").lower() != "true":
                continue
            try:
                tier = int(row["tier"])
            except (KeyError, ValueError):
                continue
            out.append((row["panel"], row["case"], tier, row["model"]))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--missing-synthetic", required=True, type=Path)
    p.add_argument("--missing-realworld", required=True, type=Path)
    p.add_argument("--bound-csv", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()

    rows: list[tuple[str, str, int, str]] = []
    rows += _parse_missing_file(args.missing_synthetic, "synthetic")
    rows += _parse_missing_file(args.missing_realworld, "realworld")
    n_missing = len(rows)
    rows += _parse_bound_csv(args.bound_csv)

    seen = set()
    deduped: list[tuple[str, str, int, str]] = []
    for r in rows:
        if r in seen:
            continue
        seen.add(r)
        deduped.append(r)

    deduped.sort()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["panel", "case", "tier", "model"])
        for r in deduped:
            w.writerow(r)

    n_bound = len(deduped) - n_missing
    by_panel = {"synthetic": 0, "realworld": 0}
    by_panel_tier = {}
    for panel, _, tier, _ in deduped:
        by_panel[panel] = by_panel.get(panel, 0) + 1
        by_panel_tier[(panel, tier)] = by_panel_tier.get((panel, tier), 0) + 1

    print(f"[build_runset] {len(deduped)} cells locked into {args.out}")
    print(f"  missing-only: {n_missing}, bound-parity adds: {n_bound}")
    for panel in ("synthetic", "realworld"):
        print(f"  {panel}: {by_panel.get(panel, 0)} cells")
        for tier in (1, 2, 3, 4):
            n = by_panel_tier.get((panel, tier), 0)
            if n:
                print(f"    T{tier} (codebase): {n}")


if __name__ == "__main__":
    main()
