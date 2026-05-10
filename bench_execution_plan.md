# Benchmark Audit + Prioritized Execution Plan

## Context

We are finalizing data for the ChatDBG-Pro paper. The Figure 3 panels target **cases × models × tiers**, scored by a forthcoming **apply-and-verify judge** (recompile + run the trigger) — though the existing prose judge remains a fallback. A snapshot already exists at `bench/results/final_paper_bench/`; its `README.md` is the canonical inventory.

**Three problems to resolve:**
1. **Coverage gap** — 365 / 640 paper cells (57%) have no model trace yet.
2. **Timeout drift** — 228 of the 275 reusable cells were run at 240s or 300s, not the agreed 600s.
3. **Judge swap** — no apply-and-verify judge has been committed yet (PR #25 archived data "ahead of patch-applicator rerun" but the implementation never landed). Need to design and build it.

---

## Decisions locked in (from this session)

- **Rerun scope:** missing cells + only the non-600s cells where the wall actually bound.
- **Judge:** plan and design the apply-and-verify pipeline; keep the prose judge as a fallback. Final pick made when the new judge is ready and validated.
- **Tiers in figures:** keep **T1 (bash only)**, **T2 (gdb only)**, **T4 (Claude Code)**. **Open question** — keep or drop **T3 (bash + gdb)**. See §C.

---

## Critical clarification: tier label scheme

Two schemes coexist on disk and they swap T2 and T3:

| Paper label (target) | What it means        | Codebase config file                  |
|----------------------|----------------------|---------------------------------------|
| T1                   | bash only            | `tier1_bash_only.json`                |
| T2                   | gdb only             | `tier3_gdb_only.json`                 |
| T3 (open question)   | bash + gdb           | `tier2_gdb_plus_bash.json`            |
| T4                   | Claude Code agent    | `tier4_claude_code.json`              |

`bench/results/archive/DATA_MAP.md` documents data under the **old** scheme (T2=bash+gdb, T3=gdb-only). `bench/results/final_paper_bench/README.md` already uses the **new/paper** scheme. **Do not rename folders or configs** — only relabel at figure/judge time.

---

## Step 1 — Audit findings

### `bench/results/` (active, top level)

| Directory                                               | Tiers (paper labels) | Models                                                       | Timeout  | Status                                                                 |
|---------------------------------------------------------|----------------------|--------------------------------------------------------------|----------|------------------------------------------------------------------------|
| `final_paper_bench/`                                    | T1, T3               | 8 paper models                                               | mixed    | Authoritative input set; 275/640 cells reusable                         |
| `external-native-ablation-20260504-merged`              | T1,T2,T3,T4          | GPT-5.5, Sonnet-4.5, Gemini-3.1-FL-Lite, Nemotron-30B, Qwen-30B | 300s    | Subset already pulled into final_paper_bench                            |
| `external-native-ablation-20260504-merged-t3rerun`      | T3                   | same 5                                                       | 300s     | Partial reuse                                                           |
| `overnight-tier1-20260501_011643`                       | T1                   | Llama-8B, Nemotron-30B, GPT-4o, Qwen-30B                     | 600s ✓   | Only 2 cells made it into curated set (BugsCPP cases, mostly off-paper) |
| `nemotron-full`, `nemotron-md4c9`                       | T2                   | nemotron-nano-9b-v2                                          | 600s     | Wrong model variant — not paper-relevant                                |
| `merged-yara-pilot`                                     | T1,T2,T3             | mixed                                                        | 600s     | Out of Figure 3 scope                                                   |
| `adroit-yara-after-fix-…`, `adroit-yara-gemini-gpt5-…`  | T1,T2,T3             | Sonnet-4.6, Grok-4.3, Gemini-2.5-Flash, GPT-5.1              | (intent 600s) | **Empty dirs — no `collect.json`.** Either rerun deliberately or delete |

### `bench/results/archive/` (frozen by PR #25)

`archive/DATA_MAP.md` is the source of truth there. Don't pull new data unless `final_paper_bench/_provenance.json` already cites it. Sweeps it cites: `berry_consolidated`, `bugbench-t[13]`, `xtier-t[13]`, `paper-cases*`, `new-cases`, `external-native-*`.

### `bench/cases/` corpus

~30 YAML cases on disk; the rest live in `data/corpus.db`. The 20+20 paper cases are referenced from `final_paper_bench/realworld/` and `…/synthetic/`. **Don't re-derive** — read from `_missing_synthetic.txt` / `_missing_realworld.txt`.

### Coverage table (from `final_paper_bench/README.md`)

| Panel       | 600s-confirmed | non-600s reusable | missing | total |
|-------------|---------------:|------------------:|--------:|------:|
| Synthetic   |              0 |               111 |     209 |   320 |
| Real-world  |             47 |               117 |     156 |   320 |
| **Total**   |         **47** |           **228** | **365** | **640** |

These 640 cells are **T1+T3 only** (per the curated snapshot). T2 and T4 cells aren't yet in `final_paper_bench/`; if we keep them in the paper they need their own runs.

---

## Step 2 — Judge audit

### Current judge (`bench/judge.py`)
- LLM-as-judge via `litellm` against `openai/gpt-4o` (override via `--judge-model` / `$CHATDBG_JUDGE_MODEL`).
- Inputs per cell: `collect.json`, `case.yaml`, `result.json`, source file (truncated 20k chars). Prompt at `bench/prompts/judge_user.txt`.
- Outputs `score.json` with `{root_cause, local_fix, global_fix} ∈ {0,1}` + rationales + tool-use stats.
- **Never compiles or applies a patch.** Short-circuits with 0/0/0 if the agent emitted ≤50 chars of prose.
- Re-judging: `python bench/judge.py <run_dir> --overwrite` — no separate "judge-only" script needed.

### Reusability of existing traces
- Agent and judge outputs are decoupled (`collect.json` vs `score.json`). **All 275 reusable cells can be re-judged without re-running the agent.**
- Apply-and-verify judge can also work entirely from `collect.json` + the case workspace; no agent rerun needed.

### Apply-and-verify judge — detailed pipeline plan

**Goal:** verdict = (buggy binary crashes on trigger) ∧ (patched binary does NOT crash on trigger). Replaces the LLM rubric for `local_fix`/`global_fix`; keeps prose judge for `root_cause` (or treat root_cause as "patch landed in the right file/function").

**New file:** `bench/judge_apply.py` (sibling of `judge.py`, doesn't touch it).

**Per-cell flow:**

1. **Load trace.** Open `collect.json`; extract the agent's final response (prose). Open `case.yaml` for invocation, expected crash signature, and the case `kind` (`synthetic_single_file` vs `injected_repo`).
2. **Extract structured patch from prose.** Call an LLM (default `openrouter/openai/gpt-4o`) with a system prompt that demands **one of three machine-readable shapes**:
   - **Unified diff** against the buggy source (preferred when the agent already wrote one).
   - **(file, before_snippet, after_snippet)** triples for textual replace.
   - **`NO_CONCRETE_FIX`** sentinel if no actionable patch exists.
   Prompt lives at `bench/prompts/judge_apply_extract.txt`. Cache extraction output in `score.v2.json` so we don't re-pay on retries.
3. **Materialize a workspace.**
   - Synthetic: copy `case-source.c` (or per-case sources from `case.yaml.sources`) into a temp dir. Use `bench/common.py:compile_case` to build the *unmodified* binary first as a sanity check.
   - Injected: call `bench/common.py:prepare_injected_workspace` to clone+patch base repo, then revert just the bug fix (so we have the buggy state). Reuse the workspace cache.
4. **Apply.** For unified diff: `git apply --3way` inside the workspace. For triples: textual replacement, fail loudly if `before_snippet` not found exactly once. For `NO_CONCRETE_FIX`: skip step 5–6, write verdict `no_patch`.
5. **Recompile.** Reuse `compile_case` with the same flags from `case.yaml`. Compile failure = verdict `compile_failed`.
6. **Re-run trigger.** Invoke the case's `run.args` against the new binary, with the same env. Capture exit code + stderr.
7. **Verdict.**
   - Buggy binary crashes (ASan / SEGV / non-zero from undefined behavior).
   - Patched binary returns clean (exit 0 OR expected non-crash exit) with no sanitizer output.
   - Both true → `fixed`. Else → `not_fixed` with a reason field.
8. **Write `score.v2.json`** next to existing `score.json`. Schema:
   ```json
   {
     "judge": "apply_and_verify",
     "judge_extract_model": "openrouter/openai/gpt-4o",
     "patch_shape": "unified_diff" | "triples" | "no_patch",
     "patch_applied": true|false,
     "compile_ok": true|false,
     "buggy_crash_signature": "...",
     "patched_exit": {...},
     "verdict": "fixed" | "not_fixed" | "compile_failed" | "no_patch" | "extract_failed",
     "score": {"local_fix": 0|1, "global_fix": 0|1},
     "rationale": "..."
   }
   ```
   `root_cause` either keeps the prose-judge value (if available) or is re-judged with a small LLM call against `case.yaml.bug.root_cause_file`.

**Validation gate before running over all cells:** run on the 47 berry cells where we already have ground truth and high-confidence `score.json`. Agreement target: ≥80% on `local_fix`/`global_fix`. Investigate every disagreement.

**Compute cost:** ~5–10× current judge per cell (full recompile dominates). At 640 cells: a few hours on one machine.

**Fallback path:** if apply-and-verify proves brittle (extract LLM hallucinates patches, injected workspaces don't recompile cleanly under our automation), fall back to the prose judge — `bench/judge.py --overwrite` over the same `collect.json` set produces `score.json` in ~30–60 min.

---

## Step 3 — Prioritized execution plan

### A. Complete and usable as-is

| Asset                                                  | Use for                                                |
|--------------------------------------------------------|--------------------------------------------------------|
| `final_paper_bench/` 47 berry cells (600s ✓)           | Real-world panel — judge directly                      |
| `final_paper_bench/` 228 non-600s reusable cells       | Judge directly **except** the subset that hit the wall (see B) |
| `bench/judge.py` infra                                 | Reuse for trace plumbing + as fallback judge           |

### B. What needs to be (re)run

| Bucket                              | Count       | Reason                  | Action                                       |
|-------------------------------------|------------:|-------------------------|----------------------------------------------|
| Missing T1+T3 cells                 | 365         | No `collect.json`       | Fresh agent runs at 600s                     |
| Non-600s cells that **bound the wall** | TBD (small) | `elapsed_s ≥ timeout * 0.95` | Fresh agent runs at 600s                |
| Non-600s cells that finished freely | ≈228 minus above | Wall didn't bind   | **Keep as-is**, footnote in paper            |
| All cells under apply-and-verify    | 640         | New judge               | Re-judge after agent runs settle             |
| T2 cells (if kept in paper)         | up to 320 (20×8×T2 paper panel) + same for synthetic | Decision per Q in §C   | Fresh agent runs at 600s                     |
| T4 cells                            | small (Claude only) | Cheap to run    | Fresh agent runs at 600s                     |

**Action item (1-shot script, do this first):** scan every `result.json` cited in `final_paper_bench/_provenance.json` and emit a CSV of `(cell, sweep, timeout, elapsed_s, bound)` where `bound = elapsed_s >= 0.95 * timeout`. The set of `bound=True` rows is the "parity rerun" list. Expected size: dozens, not hundreds.

### C. Open question — keep or drop the bash + gdb tier (paper T3)?

| Option         | Pro                                                          | Con                                                          |
|----------------|--------------------------------------------------------------|--------------------------------------------------------------|
| Keep T3        | Most "powerful" tier; upper bound for tool-augmented agents; matches original ChatDBG paper's setup most closely | Most cells already collected at T3 — sunk cost says keep; ~365 missing cells dominated by T3; doubles the figure-3 cell count vs. T1+T2-only |
| Drop T3        | Cleaner story: T1 (bash) vs T2 (gdb) is a *true* ablation; halves remaining work; figure becomes a 2-bar comparison per model | Loses the upper-bound; reviewers may ask "what if both?"; abandons most of the data we already have |

**Recommendation: keep T3.** The data is mostly there, dropping it loses the strongest comparison point, and the curated `final_paper_bench/` is already organized around T1+T3. Marked as a decision the user should sign off on.

If we keep T3 + add T2, the **paper-final cell budget** becomes:
- T1+T3: 640 cells (existing target)
- T2: ~320 cells if we mirror T1 cases × 8 models × synthetic+real-world panels (currently 0 T2 cells in `final_paper_bench/`; some T2 data exists at 300s in `external-native-ablation-…-merged` for 5/8 models)
- T4: ~40 cells (single model × 40 cases)
- **Total: ~1000 cells.**

If we drop T3:
- T1+T2: ~640 cells, but T2 needs to be built from scratch (~320 cells of fresh runs) since `final_paper_bench/` has none
- T4: ~40 cells
- **Total: ~680 cells, with ~360 fresh runs needed.**

### D. Three-machine split (3 people running in parallel)

Order cells deterministically by `(panel, case_id, model, tier)` and shard by `index % 3`. Even distribution of slow real-world multi-file builds; trivially resumable.

| Shard | "Keep T3" cells | "Drop T3" cells |
|------:|----------------:|----------------:|
| 0     | ~340            | ~120            |
| 1     | ~340            | ~120            |
| 2     | ~340            | ~120            |

Per-machine workflow:
```
.venv-bench/bin/python bench/parallel_run.py \
    --shard-index <0|1|2> --shard-count 3 \
    --target final_paper_bench \
    --timeout 600 \
    --out bench/results/paper-final-<shard>-<date>
```
(`bench/parallel_run.py` exists; verify it accepts a sharded final-bench target — may need a thin wrapper that reads `_runset_locked_<date>.txt`.)

### E. Wall-clock estimates (600s timeout)

Worst case per cell ≈ 600s + ~30s docker setup ≈ 10.5 min. Realistic mean from existing logs: ~60s; cap most cells at 2–4 min.

| Scenario                                  | Per-shard cells | Worst case  | Realistic mean |
|-------------------------------------------|----------------:|-------------|----------------|
| Keep T3, missing + bound parity           | ~340            | ~60 hrs     | ~12–22 hrs     |
| Drop T3, T2 fresh, missing only           | ~120            | ~21 hrs     | ~4–8 hrs       |

Judge stage adds ~30–60 min (prose judge) or ~3–5 hrs (apply-and-verify) once for all cells, run on whichever machine finishes first.

### F. Pre-flight checklist (do before any rerun starts)

1. **Push every local sweep to the repo.** Confirm with each teammate. Especially anything under `bench/results/` not in `git status`. Prevents double-running cells.
2. **Lock the case list.** Snapshot `_missing_synthetic.txt` + `_missing_realworld.txt` (and the bound-parity CSV from §B) to `final_paper_bench/_runset_locked_<date>.txt`.
3. **Confirm 600s default** in `bench/orchestrator.py` and `bench/parallel_run.py`. Patch any defaults still emitting 240/300s.
4. **Smoke-test one cell per shard** before going wide.
5. **Decide T3 keep/drop** (§C) — this changes the cell count by 50%.

### G. Apply-and-verify judge — implementation track (parallel)

While agent runs execute, build `bench/judge_apply.py` per §Step 2 plan. Suggested order:

1. Implement patch extraction (`bench/prompts/judge_apply_extract.txt` + an `extract_patch(prose, source) -> Patch` function). Unit test against ~10 hand-picked traces.
2. Implement workspace materialization for `synthetic_single_file` cases (simpler). Reuse `compile_case`.
3. Add `injected_repo` support via `prepare_injected_workspace`.
4. Run on the 47 berry cells. Compare `score.v2.json` to `score.json`. Tune until ≥80% agreement on `local_fix`/`global_fix`.
5. Run on remaining `collect.json` cells.
6. If it fails the agreement gate, fall back to `bench/judge.py --overwrite` over the same set.

### H. Figure-time relabeling (do at chart layer, not in code/folders)

In `bench/charts.py` / `bench/visualize.py`, add a label remap when reading on-disk tier names:

```
codebase tier1 → paper T1
codebase tier3 → paper T2
codebase tier2 → paper T3
codebase tier4 → paper T4
```

Generate **two variants** of each figure:
- Timeouts-as-zero (canonical).
- Timeouts-excluded (sensitivity check for the appendix).

---

## Critical files

- `bench/results/final_paper_bench/README.md` — coverage source of truth
- `bench/results/final_paper_bench/_missing_{synthetic,realworld}.txt` — work list
- `bench/results/final_paper_bench/_provenance.json` — what came from where
- `bench/judge.py`, `bench/JUDGE_README.md`, `bench/prompts/judge_user.txt` — current judge
- `bench/common.py` (`compile_case`, `prepare_injected_workspace`) — patch-applicator building blocks
- `bench/parallel_run.py`, `bench/orchestrator.py`, `bench/external_runner.py` — run launchers (verify 600s defaults)
- `bench/configs/tier{1,2,3,4}_*.json` — codebase tier configs (do NOT rename)
- `bench/charts.py`, `bench/visualize.py` — figure generation (add tier remap)
- `bench/results/archive/DATA_MAP.md` — old-scheme doc; useful for cross-referencing
- **New:** `bench/judge_apply.py`, `bench/prompts/judge_apply_extract.txt`

---

## Verification

- After agent runs: `find bench/results/paper-final-*-<date> -name collect.json | wc -l` matches the locked runset count per shard.
- After judge: every cell in `final_paper_bench/` has a `score.v2.json` (or `score.json` if we fell back to prose).
- Render Figure 3 (both timeout variants) and inspect heatmap blanks; any blank should map back to a known cut (T2-only-if-dropped, T3-if-dropped) or known-impossible model.
- Spot-check 10 apply-and-verify verdicts against the prose judge for face validity.
- Sanity check: `nemotron-full`, `nemotron-md4c9`, `adroit-yara-*` (empty), and any pre-PR-#25 sweeps stay out of the judge's input set.
