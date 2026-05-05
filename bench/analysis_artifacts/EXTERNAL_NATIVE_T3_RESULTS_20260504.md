# External-Native Ablation: 11 Real C Bugs × 5 Models × 4 Tiers

Captured 2026-05-04 after the Tier-3 prompt/permission fixes landed
(commits `d1be675d`, `a16c5207`, `5a2a0bae`). This document reports the
outcome of running the updated harness end-to-end on a fresh set of
external, non-BugsC++ native bugs.

## What Was Tested

| Axis | Setting |
|---|---|
| Cases | 11 native external bugs (see "Where the Bugs Came From") |
| Tiers | 1 (bash-only), 2 (bash + gdb), 3 (ChatDBG with `t3_unfenced_cmw`), 4 (Claude Code) |
| Models (T1–T3) | sonnet-4.5, gpt-5.5, gemini-3.1-flash-lite, qwen3-30B, nemotron-3-nano-30B |
| Models (T4) | haiku, sonnet (Claude Code) |
| Trials | 1 per (case, model, tier) |
| Context lines | 10 |
| Per-run timeout | 300s |
| Judge | OpenRouter `openai/gpt-5` (reasoning, temperature 0) |

The Tier-3 config used here, `t3_unfenced_cmw.json`, enables native GDB
debug, code surrounding lookup, definition lookup, and the
"check-my-work" tool while keeping bash disabled — the configuration
that came out of the prompt/permission diagnosis in
`T3_T4_PROMPT_TOOL_DIAGNOSIS.md`. T3 also runs with `CHATDBG_UNSAFE=true`
plus the prompt-augmentation env vars
(`CHATDBG_PROMPT_SOURCE_FILE`, `CHATDBG_PROMPT_BEHAVIOR`,
`CHATDBG_PROMPT_DESCRIPTION`).

## Where the Bugs Came From

11 single-purpose C programs imported by
`scripts/import_external_benchmarks.py` from two upstream corpora.
**None are BugsC++**; **none use Docker**.

### Crashbench (6 cases) — `external/benchmarks/crashbench`
Source: <https://github.com/ortegaalfredo/crashbench> (via
`bench/cases/external/crashbench-abo*`). Each is a small reproducer
that calls `strcpy` on a fixed-size stack buffer with a long argv
string; clang+ASan turns the overflow into a hard fault at the unsafe
copy site.

- `crashbench-abo1` — abo1.c, line 9 unsafe strcpy
- `crashbench-abo2` — abo2.c
- `crashbench-abo3` — abo3.c
- `crashbench-abo5` — abo5.c
- `crashbench-abo7` — abo7.c
- `crashbench-abo8` — abo8.c

### Juliet (5 cases) — `external/benchmarks/juliet-test-suite-c`
Source: NIST Juliet C/C++ 1.3 via
<https://github.com/arichardson/juliet-test-suite-c> (Unix-friendly
mirror). Compiled `bad`-only (`OMITGOOD`, `INCLUDEMAIN`) with clang
+ASan against the upstream `io.c`/`std_testcase.h` support files.

- `juliet-cwe121-char-type-overrun-memcpy-01` — stack buffer overrun via
  wrong-type `memcpy` length
- `juliet-cwe122-char-type-overrun-memcpy-01` — heap buffer overrun via
  same wrong-type `memcpy` pattern
- `juliet-cwe126-char-alloca-loop-01` — alloca-backed buffer over-read
- `juliet-cwe415-malloc-free-char-01` — double-free
- `juliet-cwe416-malloc-free-char-01` — use-after-free

These are **multifile** real-world bug shapes (the upstream
test bodies plus their support files), as opposed to the previous
hand-written single-file synthetic cases under `bench/cases/`.

## How the Run Was Produced

1. **Tier 1, Tier 2, Tier 4** results were carried over from the prior
   merged ablation `external-native-ablation-20260504-merged` (T1=55
   rows, T2=55 rows, T4=22 rows).
2. **Tier 3** was rerun fresh on WSL using
   `bench.external_runner --tier3-config t3_unfenced_cmw.json` against
   each of the 5 T1–T3 models. Five runner processes, one per model;
   each ran the 11 cases serially.
3. The merged T1+T2+(new T3)+T4 suite was assembled at
   `bench/results/external-native-ablation-20260504-merged-t3rerun/`
   (187 rows total, T1=55 / T2=55 / T3=55 / T4=22) and judged with
   `bench/judge.py --judge-model openrouter/openai/gpt-5`.
4. Judging failed mid-run when an OpenRouter credit reservation
   (`max_tokens` × upstream price) exceeded the available balance and 70
   calls bounced with HTTP 402. Credits were topped up; the judge was
   relaunched and natively skipped the 95 already-scored runs, scoring
   the remaining 70 cleanly.
5. Of the 187 rows, **22 are structurally unjudgeable**: the 22 Tier-4
   `claude_code` runs do not produce a `collect.json`/transcript that the
   judge can read, so `bench/judge.py` returns
   `skipped (no source/result)`. They show up in the index but never get
   a `score.json`. **165/165 judgeable rows scored, 0 errors.**

Total judge cost: ~$0.27.

## Headline Results

Per-model average across the 33 attempts each model gets (11 cases × 3
tiers, T1–T3 only — Tier 4 is not part of these averages because only
two models ran T4):

| Model | RC | LF | GF | Tools | Tokens | Time | Cost |
|---|---|---|---|---|---|---|---|
| **gpt-5.5** | **0.85** | **0.82** | **0.91** | 12.3 | 10,558 | 91s | $10.73 |
| claude-sonnet-4.5 | 0.48 | 0.21 | 0.48 | 14.0 | 14,979 | 185s | $1.10 |
| gemini-3.1-flash-lite | 0.48 | 0.33 | 0.48 | 9.5 | 7,798 | 41s | $0.41 |
| qwen3-30B | 0.52 | 0.15 | 0.52 | 4.2 | 7,367 | 99s | $0.00 |
| nemotron-3-nano-30B | 0.15 | 0.15 | 0.30 | 1.9 | 1,840 | 174s | $0.00 |

**RC** = root_cause (judge 0/1), **LF** = local_fix, **GF** = global_fix.
Token/cost columns reflect the *agent* doing the debugging, not the
judge. (`$0.00` reflects free-tier OpenRouter routing for the open-weight
30B models at the time of the run.)

## Tier-3 GDB-Call Distribution

`bench/analysis_artifacts/gdb_call_distribution.py` aggregates the
`tool_frequency` blob from each Tier-3 run's `collect.json`,
normalizes aliases (`bt`/`backtrace`/`where`, `p`/`print`,
`b`/`break`, `c`/`continue`, `s`/`step`, `n`/`next`, `r`/`run`,
`x/...`→`x`), drops non-GDB shell calls, and writes a stacked-bar +
heatmap to the suite's `analysis/`. Total GDB-command invocations
across the 11 Tier-3 runs per model:

| Model | Total GDB calls (T3) |
|---|---|
| sonnet-4.5 | 322 |
| gpt-5.5 | 231 |
| gemini-3.1-FL | 217 |
| qwen-30B | 44 |
| nemotron-30B | 13 |

Top commands (in rank order across the suite): `print`, `run`, `info`,
`backtrace`, `break`, `continue`, `next`, `list`, `step`, `start`. See
`gdb_call_distribution_counts.png`,
`gdb_call_distribution_fraction.png`,
`gdb_call_distribution_heatmap.png`, `gdb_call_distribution.csv`
inside the suite's `analysis/` directory.

## Initial Analysis

- **GPT-5.5 dominates.** It is the only model to clear 0.8 on every
  rubric axis. It also issues the highest-value GDB sequences (`print`
  + `info` + `backtrace`) more often than peers and, despite using
  more tokens than gemini, finishes in less wall-clock time per case
  (91s vs 185s for sonnet) because it makes fewer remediation
  round-trips.
- **Sonnet-4.5 is verbose but mid-table.** It logs the highest tool-call
  count (14.0 mean) and the most tokens (≈15k) but lands at 0.48 RC /
  0.21 LF / 0.48 GF — the LF gap is the most striking: Sonnet describes
  the bug correctly but rarely produces a concrete patch the judge will
  accept. Sonnet was also the long-pole tail of judging: one Tier-3
  Sonnet transcript took ~36 minutes for a single GPT-5 grading call,
  driven by reasoning-token cost on its lengthy tool-use traces. The
  remaining four Sonnet T3 calls completed at normal speed, so the slow
  case was an outlier and not systemic.
- **Open-weight 30B leaderboard inverts.** Qwen-30B (0.52 RC / 0.15 LF
  / 0.52 GF, 4.2 tools, 7.4k tokens) materially outperforms
  Nemotron-3-nano-30B (0.15 / 0.15 / 0.30, 1.9 tools, 1.8k tokens) on
  these cases. Nemotron's near-floor score correlates strongly with
  near-floor tool engagement (1.9 mean tool calls vs Qwen's 4.2 vs
  Sonnet's 14): the model rarely drives the debugger and so misses the
  ASan signal even when it's one `bt` away.
- **gemini-3.1-flash-lite is the cost-efficiency winner.** Same RC/GF
  as Sonnet (0.48), highest LF among non-frontier models (0.33), lowest
  wall-clock (41s/case), and 1/2.7× Sonnet's cost. If RC parity is the
  bar, gemini beats sonnet on every other axis.
- **70/187 first-pass judge calls failed on credits, not capability.**
  The 402 errors all had identical `max_tokens=65536` reservation
  pattern. Setting `max_tokens=8000` in `bench/judge.py` would let small
  OpenRouter balances finish a 187-row pass in one go, at the cost of
  occasionally truncating a long judge rationale. We chose to top up
  instead and re-run; the resume was clean because `judge_one` already
  no-ops when `score.json` exists.

## Artifacts

All under
`bench/results/external-native-ablation-20260504-merged-t3rerun/`:

- `index.json` — 187 rows of run metadata
- `<run-dir>/result.json`, `<run-dir>/collect.json`,
  `<run-dir>/score.json` — per-run inputs and judge outputs
- `analysis/runs.csv` and `analysis/summary_by_*.csv` —
  `bench/analyze.py` output
- `analysis/charts/score_heatmap_by_model_tier.png` — 12-column heatmap
  (4 tiers × 3 rubric dims)
- `analysis/charts/average_debugging_score_by_model.png`,
  `average_tokens_by_model.png`
- `analysis/visualize_existing/` — auxiliary figures from
  `bench/visualize.py` (heatmap_model_case, scores_by_model,
  time_by_model, tokens_vs_score, tool_calls_by_model)
- `analysis/cross_tier_existing.pdf` and `.csv` — cross-tier report
  from `bench/analysis_artifacts/build_cross_tier_pdf.py`
- `analysis/gdb_call_distribution_*.{png,csv}` — Tier-3 GDB-command
  distribution from
  `bench/analysis_artifacts/gdb_call_distribution.py`
- `analysis/report.md` — auto-generated tabular summary

## Reproducing

```bash
# WSL Ubuntu, /root/chatdbgpro on this commit:

# (1) Tier 3 reruns — five separate processes, one per model
for MODEL in \
  openrouter/openai/gpt-5.5 \
  openrouter/anthropic/claude-sonnet-4.5 \
  openrouter/google/gemini-3.1-flash-lite-preview \
  openrouter/qwen/qwen3-30b-a3b-instruct-2507 \
  openrouter/nvidia/nemotron-3-nano-30b-a3b ; do
  TAG=$(echo "$MODEL" | sed 's|.*/||;s|[^a-z0-9]||g')
  .venv/bin/python -m bench.external_runner \
    --cases crashbench-abo1 crashbench-abo2 crashbench-abo3 \
            crashbench-abo5 crashbench-abo7 crashbench-abo8 \
            juliet-cwe121-char-type-overrun-memcpy-01 \
            juliet-cwe122-char-type-overrun-memcpy-01 \
            juliet-cwe126-char-alloca-loop-01 \
            juliet-cwe415-malloc-free-char-01 \
            juliet-cwe416-malloc-free-char-01 \
    --models "$MODEL" --tiers 3 --trials 1 \
    --context-lines 10 --timeout 300 \
    --tier3-config t3_unfenced_cmw.json \
    --name "external-native-t3-rerun-20260504-${TAG}" &
done; wait

# (2) Merge T1/T2/(new T3)/T4
src=bench/results/external-native-ablation-20260504-merged
dst=bench/results/external-native-ablation-20260504-merged-t3rerun
cp -a "$src" "$dst"
find "$dst" -mindepth 1 -maxdepth 1 -type d -name '*tier3*' -exec rm -rf {} +
for r in bench/results/external-native-t3-rerun-20260504-*; do
  find "$r" -mindepth 1 -maxdepth 1 -type d -exec cp -a {} "$dst"/ \;
done
find "$dst" -name score.json -delete
.venv/bin/python -c '
import json, pathlib
d = pathlib.Path("'"$dst"'")
rows = [json.loads((p/"result.json").read_text()) for p in sorted(d.iterdir()) if (p/"result.json").exists()]
(d/"index.json").write_text(json.dumps(rows, indent=2))
'

# (3) Judge
.venv/bin/python bench/judge.py "$dst" --judge-model openrouter/openai/gpt-5

# (4) Analyses + figures
.venv/bin/python bench/analyze.py "$dst"
.venv/bin/python bench/charts.py "$dst"
.venv/bin/python bench/visualize.py --results-dir "$dst" --output "$dst/analysis/visualize_existing"
.venv/bin/python bench/analysis_artifacts/build_cross_tier_pdf.py --suite "$dst" --out "$dst/analysis/cross_tier_existing.pdf"
.venv/bin/python bench/analysis_artifacts/gdb_call_distribution.py "$dst" --tier 3
```
