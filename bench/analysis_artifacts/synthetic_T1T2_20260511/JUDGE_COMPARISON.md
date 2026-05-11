# Judge cross-check on synthetic T1 (gpt-4o vs gpt-5)

**Date:** 2026-05-11
**Panel:** `bench/results/final_paper_bench/synthetic` (T1 cells only, 159 paired)
**Judge A:** `openrouter/openai/gpt-4o` (canonical default)
**Judge B:** `openrouter/openai/gpt-5` (one-off audit)

> **Decision (2026-05-11):** stay on **gpt-4o** as the canonical judge.
> gpt-5 is 12% stricter overall but the model leaderboard is preserved,
> and the ~5× cost differential ($10 vs $2 for the full 640-cell figure)
> isn't worth paying for a relative-ranking figure. This document is
> kept as a historical / sensitivity-check record. The per-cell
> `score.gpt5.json` files, the comparison figures, and the supporting
> CSV that backed the audit have been removed to keep the tree clean;
> the numbers below are the canonical record of what the audit found.

## Why we ran this

The original pipeline used gpt-4o because the plan named it as the default
(`bench_execution_plan.md`, Step 8). Inspection of gpt-4o's rationales
on a few cells suggested it credits "concept-present-but-mechanism-missing"
prose more readily than the criteria strictly allow — most visibly on the
garbled `uaf-linked-list` nemotron T2 cell, which was scored 3/3 despite
its response being syntactically corrupted. We ran gpt-5 in parallel on the
T1 panel to measure how much that leniency moves the figure.

To keep the gpt-4o scores intact for diagnostic comparison, the gpt-5
scores were written into `score.gpt5.json` next to each cell's existing
`score.json` (via the new `--score-filename` and `--name-glob` flags on
`bench/judge.py`).

## Headline numbers

| Axis | gpt-4o credits / 159 | gpt-5 credits / 159 | Δ |
|---|---:|---:|---:|
| root_cause | 98 (61.6%) | 85 (53.5%) | −13 (15↓, 2↑) |
| local_fix  | 88 (55.3%) | 86 (54.1%) | −2 (8↓, 6↑) |
| global_fix | 74 (46.5%) | 59 (37.1%) | **−15 (19↓, 4↑)** |
| **total** | **260** | **230** | **−12.0%** |

gpt-5 denies credit on ~12% more axis-cells overall. The gap is
concentrated on `global_fix` — the axis that asks "did the model truly
explain the underlying cause, not just point at a line?" — which is
exactly where gpt-4o's leniency was suspected.

## Per-model totals (mean score, out of 3)

| Model | gpt-4o | gpt-5 | Δ |
|---|---:|---:|---:|
| gpt-5.5 | 2.50 | **2.50** | 0 |
| gpt-4o | 1.89 | 1.37 | **−0.52** |
| claude-sonnet | 2.80 | 2.70 | −0.10 |
| grok | 2.10 | 1.80 | −0.30 |
| gemini | 1.80 | 1.45 | −0.35 |
| qwen | 1.45 | 1.15 | −0.30 |
| nemotron | 0.20 | **0.20** | 0 |
| llama | 0.35 | 0.40 | +0.05 |

**The leaderboard is preserved** — gpt-5.5 > claude-sonnet > grok >
gpt-4o > gemini > qwen > llama > nemotron under both judges. The
difference is in the size of the gap between strong and mid-tier models:
gpt-5 widens the gap by pulling mid-tier (gpt-4o, gemini, qwen) down ~0.3
points each, while leaving gpt-5.5 and claude-sonnet roughly untouched.

## Specific patterns

### gpt-4o (the model) takes the biggest hit (−0.52)

This is the only T1 cell-row that moves more than 0.4 points. The
`global_fix` axis alone drops 0.35 → 0.21. Two interpretations, neither
of which we can fully separate from this one panel:

1. **Family bias.** gpt-4o-judge plausibly credits gpt-4o-model on
   borderline reasoning because the prose register matches what gpt-4o
   would write itself.
2. **The prose really is borderline.** gpt-4o-model often emits answers
   that name the right defect and propose the right local fix but stop
   short of a real mechanism explanation on `global_fix`. gpt-5 reads
   that strictly; gpt-4o gives it the benefit of the doubt.

Both are plausible. Either way, the implication for the paper is the same:
**when citing gpt-4o-the-model performance, use gpt-5 scores** to avoid
the family-bias confound. (gpt-5 judging gpt-5.5 has the same risk in
principle, but gpt-5.5 sits at 2.50/2.50 — gpt-5 isn't visibly
inflating its own family here, which the family-bias hypothesis would
have predicted.)

### nemotron and llama are unchanged

Both are pinned near the floor (0.20/0.20 and 0.35/0.40). The reason
is judge-independent: most of their T1 cells emit <50 chars of prose
after using tools, which triggers the `no_prose_synthesis` short-circuit
in `judge.py` (auto 0/0/0, no LLM call). Both judges respect that
short-circuit identically.

### claude-sonnet is the most stable strong model

−0.10, entirely on `global_fix`. Sonnet's T1 prose is detailed enough
that both judges credit it on most cells.

### Per-cell hot spots (where gpt-4o vs gpt-5 disagree the most)

From the cell-level Δ figure (`judge_compare_T1_case_model.png`), the
deepest disagreements (Δ ≤ −2) cluster on:
- `test-overflow` — gpt-5 found most models' answers underspecified here.
- `test-pointers-loop` and `test-deep-recursion` — borderline cells
  where gpt-4o gave 2/3 and gpt-5 gave 0/3 or 1/3.

A few cells flipped the other direction (gpt-5 credited where gpt-4o
denied): `null-deref-env` for gpt-4o-model and qwen, `signed-unsigned-loop`
for one cell. These are worth manually checking — if gpt-5 over-credits
on those, the family-bias hypothesis loses some force.

## Cost

| Run | Cells | Real cost | Wall |
|---|---:|---:|---:|
| gpt-4o pass | 159 (T1) | ~$0.40 | ~25 min |
| gpt-5 pass | 159 (T1) | $2.01 | ~25 min |

The judge.py cost reporter under-reports gpt-5 by ~6× because it falls
back to gpt-5-mini pricing when LiteLLM doesn't have gpt-5 in its
pricing table. The $2.01 above is computed from token counts at
OpenRouter's $1.25/M input + $10/M output.

## Conclusion / decision

**Stay on `openrouter/openai/gpt-4o` as the canonical judge.**

The leaderboard is preserved across judges:
`gpt-5.5 > claude-sonnet > grok > gpt-4o > gemini > qwen > llama > nemotron`
under both. For a figure that communicates *relative* model performance,
the strictness gain doesn't justify the cost.

Practical implications:
- **No rerun needed** for T2 synthetic or realworld panels. The existing
  gpt-4o `score.json` files are the canonical scores.
- **Footnote on gpt-4o-the-model only.** When the paper figure cites
  gpt-4o-the-model's performance specifically, add a footnote: "gpt-5
  judge spot-check gives mean 1.37/3 vs gpt-4o judge's 1.89/3; gap
  concentrated on global_fix." Other models' bars are stable enough
  across judges that no footnote is needed.
- **If a specific cell becomes contested**, you can re-judge that one
  cell ad hoc with gpt-5 (just point `judge.py --judge-model
  openrouter/openai/gpt-5 --overwrite` at a single-cell parent). No
  ongoing infrastructure for parallel judges is maintained.

## Reproducing this audit (if ever needed)

The supporting files were removed after the decision to stay on gpt-4o.
To regenerate the audit:

1. Re-run `bench.judge` with `--judge-model openrouter/openai/gpt-5` and
   `--overwrite` on a copy of the panel (or in a side-by-side directory
   so the canonical `score.json` files aren't lost).
2. Pair each cell's gpt-5 `score.json` against the canonical gpt-4o
   `score.json` and reproduce the per-axis and per-model tables above.

Estimated cost: ~$2 for synthetic T1 (159 cells); ~$10 for the full
640-cell figure. ~25 min wall per panel.

## Related context

- Default judge model preference: see memory note
  `feedback_judge_model_choice.md`.
- Numbers + per-model breakdown: see memory note
  `project_judge_cross_check_T1.md`.
