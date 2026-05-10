"""Find archived cells where the wall actually bound, so we can rerun them at 600s parity.

Reads bench/results/final_paper_bench/_provenance.json, looks up each source
result.json under bench/results/archive/, and emits a CSV listing cells whose
elapsed_s came within 5% of their original wall budget.

Usage:
    python -m bench.audit_bound_cells \
        --provenance bench/results/final_paper_bench/_provenance.json \
        --archive    bench/results/archive \
        --out        bench/results/final_paper_bench/_bound_cells.csv

Why this exists: most provenance entries ran at 240s or 300s instead of the
canonical 600s. Most never approached the wall (median elapsed << timeout) and
are valid as-is. We only need to rerun the subset where the wall bound the run.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

# Original wall budget per source sweep, derived from
# bench/results/final_paper_bench/README.md "Timeout audit" table.
TIMEOUT_BY_SWEEP = {
    "berry_consolidated": 600,
    "bugscpp-berry-t1t3-20260504-234836": 600,
    "t3-clean-gpt55-1777956722": 600,
    "external-native-ablation-20260504-merged-t3rerun": 300,
    "external-native-ablation-20260504": 300,
    "external-native-ablation-20260504-gemini31fl": 300,
    "external-native-ablation-20260504-gpt55": 300,
    "external-native-ablation-20260504-merged": 300,
    "external-native-ablation-20260504-nemotron30": 300,
    "external-native-ablation-20260504-qwen30": 300,
    "external-native-ablation-20260504-sonnet45": 300,
    "external-native-ablation-20260504-tier4": 300,
    "external-native-t3-rerun-20260504-gemini31fl": 300,
    "external-native-t3-rerun-20260504-gpt55": 300,
    "external-native-t3-rerun-20260504-nemotron30": 300,
    "external-native-t3-rerun-20260504-qwen30": 300,
    "external-native-t3-rerun-20260504-sonnet45": 300,
    "bugbench-t1": 240,
    "bugbench-t2": 240,
    "bugbench-t3": 240,
    "xtier-t1": 600,  # README says n/a — no cell hit any wall, max=283s; treat as 600s
    "xtier-t3": 600,
    "paper-cases": 600,
    "paper-cases-fix": 600,
    "new-cases": 600,
    "full-synthetic-v1-stripped": 600,
    "tier1-demo": 600,
    "t1-validation": 600,
    "injected-cases": 600,
    "native-smoke-t123-gpt55": 600,
    "t3-native-smoke-gpt55-v3": 600,
    "overnight-tier1-20260501_011643": 600,
}

# Anything in TIMEOUT_BY_SWEEP with value 600 was either confirmed 600s or had
# no wall-bound cells per the audit; either way, rerunning is unnecessary.
BIND_THRESHOLD = 0.95


def lookup_timeout(sweep: str) -> int:
    if sweep in TIMEOUT_BY_SWEEP:
        return TIMEOUT_BY_SWEEP[sweep]
    # Unknown sweep -> assume 300s and let the caller eyeball the result.
    return 300


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provenance", required=True, type=Path)
    p.add_argument("--archive", required=True, type=Path,
                   help="Path to bench/results/archive (or wherever the source sweeps live)")
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()

    prov = json.loads(args.provenance.read_text(encoding="utf-8"))
    rows = []
    bound_count = 0
    for entry in prov.get("copied", []):
        sweep = entry["source_sweep"]
        cell = entry["source_cell"]
        timeout = lookup_timeout(sweep)
        result_path = args.archive / sweep / cell / "result.json"
        elapsed = None
        if result_path.exists():
            try:
                elapsed = float(json.loads(result_path.read_text(encoding="utf-8")).get("elapsed_s") or 0.0)
            except Exception:
                elapsed = None
        bound = bool(elapsed is not None and elapsed >= BIND_THRESHOLD * timeout)
        if bound:
            bound_count += 1
        rows.append({
            "panel": entry["panel"],
            "case": entry["case"],
            "tier": entry["tier"],
            "model": entry["model"],
            "source_sweep": sweep,
            "source_cell": cell,
            "timeout": timeout,
            "elapsed_s": "" if elapsed is None else f"{elapsed:.2f}",
            "bound": "true" if bound else "false",
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["panel", "case", "tier", "model", "source_sweep",
                            "source_cell", "timeout", "elapsed_s", "bound"])
        w.writeheader()
        w.writerows(rows)

    print(f"[audit_bound_cells] {len(rows)} provenance entries scanned, "
          f"{bound_count} bound (>={BIND_THRESHOLD:.0%} of original wall) -> {args.out}")


if __name__ == "__main__":
    main()
