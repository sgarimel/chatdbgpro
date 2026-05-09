# `final_paper_bench/` — curated input data for the paper figures

This directory holds the per-cell input artifacts (case.yaml, collect.json,
result.json, transcripts) for the two figures the team agreed to ship in
the paper:

- **Figure 3 left** — Synthetic / Single-File Bugs (20 cases × 8 models × T1+T3)
- **Figure 3 right** — Real-World / Multi-File Bugs (20 cases × 8 models × T1+T3)

Total figure cells targeted: 640 = (20 × 8 × 2) × 2 panels.

The judge will be re-run from scratch on these cells under the new
**apply-and-verify** rubric (materialize the model's prose fix, apply,
recompile, run the trigger). For that reason, **no `score.json` files
were copied** — the new judge writes fresh scores. Every other artifact
the new judge needs is here:

```
final_paper_bench/<panel>/<case>__tier{1|3}__<model>__.../
    case.yaml         (judging criteria + developer patch)
    result.json       (status, exit_code, elapsed_s, model)
    collect.json      (model's prose response — the input to the new applicator)
    case-source.c     (or per-case source files for synthetic cases)
    stdout.log, stderr.log, session.cmds, etc.
```

Provenance for every copied cell is recorded in `_provenance.json`
(source sweep, timeout-was-600s flag, files copied).

## Inventory

| panel | 600s-confirmed | non-600s (audit) | missing (rerun) | total |
|---|---:|---:|---:|---:|
| Synthetic   | 0   | 111 | 209 | 320 |
| Real-world  | 47  | 117 | 156 | 320 |
| **Total**   | **47** | **228** | **365** | **640** |

275 of 640 figure cells (43%) have reusable run data. 365 (57%) need a
fresh run before the new judge can score them.

## ⚠ Timeout audit — most archived sweeps did NOT use 600s

| Source sweep | Timeout used | Cells contributed |
|---|---|---:|
| `berry_consolidated/` (in `archive/`) | **600s ✓** | 47 |
| `bugscpp-berry-t1t3-20260504-234836/` | **600s ✓** | 0 (superseded by berry_consolidated) |
| `t3-clean-gpt55-1777956722/` | **600s ✓** | 0 (cells already in berry_consolidated) |
| `external-native-ablation-...-merged-t3rerun/` | 300s | (not picked) |
| `external-native-ablation-20260504-*` (per-model partials) | 300s | 31 |
| `external-native-t3-rerun-...` | 300s | 44 |
| `bugbench-t1/`, `bugbench-t3/` | 240s | 14 |
| `xtier-t1`, `xtier-t3` (untracked sweeps) | "n/a" — no cell hit any wall, max=283s | 48 |
| `paper-cases`, `paper-cases-fix`, `new-cases`, `full-synthetic-v1-stripped` | "n/a" — no timeouts, max=156s | 51 |
| `tier1-demo`, `t1-validation`, others | "n/a" | small contributions |

**Verdict:** the only sweep we can confirm at 600s parity is
`berry_consolidated/`. All non-berry cells in this directory came from
sweeps configured at 240s or 300s. *In most cases this didn't bind*:
the model finished its work voluntarily well under the wall (max
elapsed in those sweeps is < 300s for almost every cell). But it's not
strict 600s parity. The 228 "non-600s" cells in the table above are
candidates for a rerun if you want strict apples-to-apples wall budgets
across every cell.

## Source-sweep contribution

| n | sweep |
|---:|---|
| 47 | berry_consolidated |
| 24 | xtier-t1 |
| 24 | xtier-t3 |
| 21 | external-native-ablation-20260504-merged |
| 20 | paper-cases |
| 13 | external-native-ablation-20260504-sonnet45 |
| 12 | full-synthetic-v1-stripped |
| 12 | new-cases |
| 10 | external-native-t3-rerun-20260504-gemini31fl |
| 9  | external-native-t3-rerun-20260504-qwen30 |
| 9  | external-native-ablation-20260504-nemotron30 |
| 9  | external-native-t3-rerun-20260504-nemotron30 |
| 9  | external-native-t3-rerun-20260504-gpt55 |
| 9  | external-native-ablation-20260504-qwen30 |
| 8  | bugbench-t3 |
| 7  | paper-cases-fix |
| 7  | external-native-t3-rerun-20260504-sonnet45 |
| 6  | tier1-demo |
| 6  | bugbench-t1 |
| 4  | injected-cases |
| 3  | external-native-ablation-20260504 |
| 2  | t1-validation |
| 2  | overnight-tier1-20260501_011643 |
| 1  | native-smoke-t123-gpt55 |
| 1  | t3-native-smoke-gpt55-v3 |

## Missing cells — full list ("gray cells" in Figure 3 that need fresh runs)

All entries below are missing collect.json and need a model run before
the new judge can score them. Read as `<case> | T<tier> | <model>`.

### Synthetic panel (209 missing)

See `_missing_synthetic.txt` for the full list. Top patterns:

- Every cell for **GPT-4o**, **Sonnet-4.5**, **Llama-8B** is missing
  except the `xtier-*` cases (4 cases per tier each). This is because
  the synthetic ablation merged sweep (300s, 11 cases) only ran 5
  models: GPT-5.5, Sonnet-4.5, Gemini-3.1-FL-Lite, Qwen-30B,
  Nemotron-30B — but those cells got 300s not 600s.
- **Grok-4** only has 4 cases per tier (the xtier set: double-free-errpath,
  intoverflow-alloc, off-by-one-crc, uaf-linked-list); 16 cases × 2
  tiers = 32 missing for Grok-4 alone.
- The `test-pointers` and `test-pointers-loop` synthetic cases have
  no judged data anywhere on disk — these need T1 and T3 runs from
  scratch for all 8 models.

### Real-world panel (156 missing)

See `_missing_realworld.txt` for the full list. Top patterns:

- **All 4 BugBench cases** (`bc-heap-overflow`, `man-overflow`,
  `ncompress-overflow`, `polymorph-overflow`) are missing for the
  4 models that *don't* appear in the bugbench-t1/t3 sweeps:
  GPT-5.5, Sonnet-4.5, Gemini-FL, Gemini-FL-Lite. 4 cases × 4 models
  × 2 tiers = 32 cells.
- **Berry**: missing cells are dominated by Sonnet-4.5 and Gemini-FL-Lite
  (they weren't part of the OpenRouter berry sweep). 5 cases × 2 models
  × 2 tiers = 20 cells. Otherwise berry coverage is excellent (47/60).
- **Crashbench (cb-abo*)** and **Juliet (j-*)**: the gaps are
  GPT-4o, Gemini-2.5-FL, and Llama-8B (these models weren't in the
  synthetic ablation sweep). 11 cases × 3 models × 2 tiers = 66 cells.

## What this directory is NOT

- **Not a complete dataset.** It's the curated input set for the two
  figures only. Other tier comparisons (T2, T4) are deliberately
  excluded.
- **Not the final scores.** Score files are intentionally omitted; the
  judge will be rerun under the apply-and-verify rubric and write
  fresh `score.v2.json` (or similar) into each cell.
- **Not source-of-truth for individual transcripts.** The original
  cells remain in `bench/results/archive/` (committed, preserved) and
  in the various untracked sweep directories under `bench/results/`.

## Reproducing this directory

```
.venv-bench/bin/python /tmp/copy_final_bench.py
```

The picker prefers (1) status=ok over timeouts/crashes, (2) cells from
600s-configured sweeps when there's a tie, (3) the most recent run by
mtime as the final tiebreak. Multiple cells per (case, tier, model) are
not currently merged — the best one wins.
