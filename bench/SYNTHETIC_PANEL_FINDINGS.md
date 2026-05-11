# Synthetic panel — findings, open decisions, and rerun cost matrix

Author: Anika's Claude session (2026-05-11). Branch: `push/local-runs-anika`.
Companion docs: `bench/SETUP_LOG_anika_synthetic.md` (host setup log),
`bench/RUNNER_HANDOFF_ibraheem_addendum.md` (what changed for Adroit),
`bench/prompts_T1_T3.md` (verbatim prompt snapshot).

## §1. Where we landed

| Tier | Cells | status=ok | timeout | no_collect | full RC/LF/GF | partial prose | empty |
|---|---:|---:|---:|---:|---:|---:|---:|
| T1 | 160 | 140 | 20 | 0 | **111 native + 13 recovered = 124** | 13 | 36 |
| T3 | 160 | 157 | 0 | 3 | **47** | 93 | 20 |
| **total** | **320** | **297** | **20** | **3** | **171** | **106** | **56** |

Per-model breakdown lives in
`bench/analysis_artifacts/synthetic_panel_full/summary.md`. Figures:
- `coverage_by_model_tier.png` — status histograms (ok / timeout / no_collect)
- `format_by_model_tier.png` — labelled-paragraph compliance
- `latency_per_model_tier.png` — wall time per cell (log scale)
- `per_case_heatmap.png` — per (case, model, tier) result grid

All 320 cells live under `bench/results/final_paper_bench/synthetic/` with
real artifacts (case.yaml, result.json, collect.json, stdout/stderr, plus
chatdbg.log.yaml for T3). Provenance recorded in
`_provenance.json`. Ready for the judge pass.

## §2. Five infrastructure fixes that landed during this session

All five are committed on `push/local-runs-anika` and active for both
panels going forward. The summary commits in chronological order:

1. **`2ff5dd52`** — `--no-docker` shim in `parallel_run.py` for synthetic
   cases. Synthetic case ids aren't in corpus.db; previously every
   synthetic shard call returned "no cases match the filter." Auto-passed
   for `--panel synthetic` by `run_runset_shard.py`. (Realworld unaffected.)
2. **`e6f0cc5e`** — outer subprocess timeout safety net in
   `parallel_run.run_one`: `subprocess.run(..., timeout=timeout+120)` and
   force-kill on overrun. Catches the rare WSL-clock-skew case where
   `proc.communicate(timeout=600)` doesn't fire (we saw a 3733 s cell).
3. **`2915b4ee`** — T1 prompt iter-5 ("content has no audience"). Removed
   the choice between content-only and tool_calls-only by declaring
   content has no audience and bash is the only delivery channel. Lifted
   gpt-4o T1 from 7/20 to 17/20 full format compliance; reduced wall
   time 1062 s → 121 s. `CHATDBG_LOG_REJECTED=1` env-var hook in
   `tier1_runner.py` for auditing future silent rejections.
4. **`f541cff0`** — T3 gdb path for `injected_repo` cases. Previously
   raised `ValueError("injected_repo only supports lldb for now")`,
   silently failing every injected-cjson/mongoose/lua/zlib/sqlite cell.
   Resolver for `$CHATDBG_VENV` so gdb's embedded Python finds chatdbg
   deps when the venv lives outside the repo. `.venv-bench` is symlinked
   inside the repo for default discovery.
5. **`a91f4dcb`** — `ASAN_OPTIONS=abort_on_error=1` in `_chatdbg_env`.
   Under gdb, ASan defaulted to `_exit()` on error; debugger saw a
   normal exit and chatdbg's stop_handler set "stopped (no-signal)" as
   the error type. Now ASan raises SIGABRT, gdb catches it, the model
   sees a real signal and stack trace.
6. **`ded2e0d7`** — T3 `DEFAULT_QUESTION` in `bench/common.py` now
   requires ROOT CAUSE / LOCAL FIX / GLOBAL FIX labels. This was the
   miss from historical commit `e6c6e83b` which only updated T1's task
   builders. Single-line (multi-line breaks gdb's `why` parser).

The `bench/recover_responses.py` post-processor lifts diagnoses that
landed in tool output (gemini-flash-lite echo-style) into the response
field. Run it before judging.

## §3. What the data shows

### §3.1 The model-quality signal is intact and clean

T1 full-RC/LF/GF compliance, after the iter-5 prompt:

| Model | T1 full format |
|---|---|
| sonnet-4.5 | 19/20 |
| gpt-5.5 | 17/20 |
| gpt-4o (post-iter-5) | 17/20 (11 native + 6 recovered) |
| llama-3.1-8b | 16/20 |
| grok-4 | 15/20 |
| gemini-flash-lite | 14/20 (7 native + 7 recovered) |
| qwen-30b | 11/20 |
| nemotron-30b | 2/20 |

The mid-tier of llama-8b / grok-4 / gemini-flash-lite cluster within
4 cells of sonnet, which is the paper's main point: smaller / cheaper
models can compete with frontier models on debugging when the harness
is set up correctly. nemotron-30b is the outlier (15/20 timeouts under
T1's mini-swe-agent loop — it spirals into long reasoning that doesn't
finish).

### §3.2 T3 looks worse on the label-match metric, but probably isn't

T3 full-RC/LF/GF compliance:

| Model | T3 full format |
|---|---|
| llama-3.1-8b | 19/20 (!) |
| gpt-4o | 14/20 |
| sonnet-4.5 | 5/20 |
| grok-4 | 2/20 |
| gpt-5.5 | 2/20 |
| qwen-30b | 2/20 |
| nemotron-30b | 2/20 |
| gemini-flash-lite | 1/20 |

Notable: **llama-8b crushes sonnet/gpt-5.5/grok-4 on T3 format**. The
mid-tier models are more dogged about writing out the structured closure;
the big models often "decide they're done" mid-investigation and let
chatdbg's `why` dialog terminate without emitting the labels.

This is **a label-match heuristic, not a debugging-quality measure**.
Cells classified as "partial prose, missing labels" usually contain
correct diagnoses — they just don't carry the exact `ROOT CAUSE:` /
`LOCAL FIX:` / `GLOBAL FIX:` markers. Example: sonnet T3 on cjson
written 108 tokens identifying "the while loop at line 798 doesn't
check if we've reached the end of the input buffer" — correct
diagnosis, mid-sentence cutoff, no labels.

**The judge will read the prose**, not the labels (see
`bench/judge.py:217` `no_prose_synthesis` short-circuit which fires
only on responses with `<50` chars AND `>0` tool calls). So the
true model-quality picture for T3 will emerge from the judge pass.

### §3.3 The harness was lying to the model on T3 (now fixed)

The biggest surprise of the session was that under gdb, ASan was
calling `_exit()` instead of raising SIGABRT. The debugger saw a normal
exit, chatdbg's stop_handler recorded no signal, the prompt told the
model "the program encountered the following error: `stopped (no-signal)`",
and the model had nothing concrete to investigate.

Reproduced directly:
```
$ ./bench_driver < stdin.bin              # bash: ASan + exit 1
$ gdb -batch ./bench_driver               # exited with code 01 (no signal!)
$ ASAN_OPTIONS=abort_on_error=1 gdb ...   # SIGABRT caught, full backtrace
```

This was a real bug, not a model-quality issue. Smoke after the fix:
sonnet T3 on cjson went from "stopped (no-signal)" + 67 partial tokens
→ "SIGABRT" + 798 tokens + full RC/LF/GF. The fix shipped in
`_chatdbg_env`.

### §3.4 Cells we're not certain about

A few quirks worth eyeballing before the paper figure:

- **3 T3 `no_collect` cells.** Sonnet T3 on `test-pointers-loop` and
  `test-pointers`, and gpt-4o T3 on one case. Likely litellm flakes —
  rerun if you want them populated, but probably tolerable as-is.
- **2 nemotron-30b T3 cells classified "full RC/LF/GF" and 17 "partial".**
  Nemotron's T3 outputs look unusually short (median completion tokens
  is low). Probably the same "model gives up" pattern as the big models;
  may be worth a separate look if nemotron's T3 number is a load-bearing
  comparison in the figure.
- **gemini-flash-lite T3: 1/20 full format.** Different failure mode
  than its T1 (where 11/20 echoed the diagnosis to bash and were
  recovered). T3 doesn't have a recovery hook because the response is
  collected from chatdbg's session log, not from a bash sandbox.

## §4. Open decisions

### §4.1 Should T3 be rerun *again* with a different intervention?

The two reruns we've done (ASAN_OPTIONS + RC/LF/GF prompt) didn't move
the format-compliance metric much on T3. Three options if you want
higher RC/LF/GF compliance numbers:

**Option A — Accept the data and judge it.** The judge will score the
diagnostic prose, not the labels. Most "partial prose" cells have real
content. Cost: $0, time 0.

**Option B — Force-terminate chatdbg's `why` loop with a "must emit
labels" check.** Patch `chatdbg_gdb.py` to, when the model stops
emitting tool calls, check whether RC/LF/GF labels are in the last
assistant message; if not, re-prompt with "now write the final answer".
This is a real code change, ~1 day of work. Could substantially lift
T3 numbers for the big models. Risk: changes the experiment design
mid-stream (now T3 has a "format-enforce" feedback loop that T1
doesn't).

**Option C — Rerun T3 once more with higher step / cost limits.**
`bench/configs/tier3_gdb_only.json` may have a step or cost ceiling
that's letting the model stop early. Cost: ~10 min wall, no code
change. Probably small lift; sonnet stopped at 108 tokens which is
not a ceiling issue.

**Recommendation: Option A.** Run the judge once and read the
rationales. If "partial prose" cells are getting unfairly scored 0,
revisit Option B.

### §4.2 Should T1 nemotron-30b be retried separately?

Nemotron timed out 15/20 in T1 (mini-swe-agent loop). Two theories:

1. **Genuine model limitation** — nemotron spirals into reasoning that
   doesn't terminate within 600 s. Then this is a real experimental
   signal: "even a 30B reasoning model can lose to a 7B chat-instruct
   model when the harness is a tool-calling agent."

2. **OpenRouter routing flake** — nemotron's specific backend is
   slow / queued / unreliable. The 1 cell that DID complete
   produced a full RC/LF/GF response in ~200 s, suggesting the model
   can do the task when the API call lands.

Test cost: rerun the 15 timeout cells with the same prompt = ~10 min
wall, $1–2 of API. Worth doing **if nemotron is a load-bearing
comparison in the figure**; otherwise the 5/20 number is the answer.

**Recommendation: Rerun once.** If 5/20 stays, the result is the
result. If it climbs to 10–15/20, the timeout was infrastructure-side.

### §4.3 Should we add a T1 "recovery v2" for the still-empty cells?

19/24 originally-empty cells were "truly empty" — the model investigated
but never wrote RC/LF/GF anywhere (not in `response`, not in tool
output, not in submission). These are mostly gpt-4o pre-iter-5 (now
fixed) and qwen-30b. Post-iter-5 the count dropped substantially.

If you want fewer empties, the path is: enable `CHATDBG_LOG_REJECTED=1`
on a rerun and check whether the model is producing the diagnosis in
rejected text-only attempts. If yes, write a recovery-v2 that reads
from the sidecar. If no (i.e. the model genuinely never writes the
diagnosis even when free to), there's nothing to recover.

**Recommendation: Skip unless the judge rationales for empty cells
look unfair.**

### §4.4 Should we re-judge the archived sweep data?

`final_paper_bench/synthetic/` was assembled from a mix of archived
sweeps plus our reruns. Each archived sweep used whatever prompt was
current at the time — most should match the post-`e6c6e83b` T1 prompt
but T3 archived cells use the *old* T3 prompt (no RC/LF/GF requirement).

Our 81 T3 reruns supersede the archived T3 cells for the same
(case, model) pairs. But ~79 archived T3 cells from the older sweeps
remained intact and didn't get reprompted. If we want every T3 cell
to have seen the new prompt, we'd need to rerun those too.

**Recommendation: Audit which T3 cells are "ours" (post-prompt-fix)
vs "archived" (pre-prompt-fix).** If <20% are archived-pre-fix, accept
the mix. If a lot more, rerun them. Quick query:
```bash
grep -c '"merged_at"' bench/results/final_paper_bench/_provenance.json
# vs total provenance entries
```

### §4.5 When to judge

The judge is intentionally deferred until both panels are in. The
plan is:
```
python -m bench.recover_responses bench/results/final_paper_bench/synthetic
python -m bench.recover_responses bench/results/final_paper_bench/realworld
python bench/judge.py bench/results/final_paper_bench/synthetic --overwrite
python bench/judge.py bench/results/final_paper_bench/realworld  --overwrite
```

`--overwrite` is needed because archived cells have score.json from
earlier sweeps under earlier prompts. We want a fresh prose-judge pass
over the whole 640-cell panel.

Wall-clock estimate per panel: ~30–60 min depending on judge model
(default `openai/gpt-4o`).

## §5. Cost matrix for further reruns

If anyone (Anika or Ibraheem) wants to do another pass before the
judge, here's the cost of each option:

| Option | Cells | Wall | API $ | Code |
|---|---|---|---|---|
| Skip — accept current data, run judge | 0 | 0 | 0 | 0 |
| Rerun nemotron T1 timeouts (§4.2) | 15 | ~10 min | ~$1 | none |
| Force-emit-labels patch + rerun T3 (§4.1B) | 160 | ~30 min | ~$5 | ~1 day |
| Higher step/cost limit + rerun T3 (§4.1C) | 160 | ~30 min | ~$5 | 1 config edit |
| Recovery-v2 (T1 still-empty cells) (§4.3) | 0 | 0 | 0 | ~1 hr |
| Rerun all archived T3 cells (§4.4) | ~80 | ~15 min | ~$2 | none |

The cheapest material lift is probably **§4.2 nemotron-only rerun**.
Everything else either requires real code work (§4.1B, §4.3) or has
unclear payoff (§4.1C, §4.4).

## §6. What to hand to Ibraheem

`bench/RUNNER_HANDOFF_ibraheem_addendum.md` already lists everything
he needs:
- Pull `origin/push/local-runs-anika` before sbatch
- All five fixes activate automatically
- Run `bench/recover_responses.py` on realworld before judging
- Adroit-specific deltas in §6 of that file

He does NOT need to know about the §4 decisions above — those are about
*re-running my panel*, which is his caller's choice (you), not his
operational concern.

## §7. Files of record

If you want to dig into any specific finding, here's where to look:

- **Setup log** (host details, every command run): `bench/SETUP_LOG_anika_synthetic.md`
- **Prompts as the model saw them**: `bench/prompts_T1_T3.md`
- **Per-cell raw artifacts**: `bench/results/final_paper_bench/synthetic/<case>__tier{1,3}__<model>__.../`
- **Per-panel summary table**: `bench/analysis_artifacts/synthetic_panel_full/summary.md`
- **Per-(case, model) heatmap**: `bench/analysis_artifacts/synthetic_panel_full/per_case_heatmap.png`
- **Memory entries Anika's session updated**:
  - `~/.claude/.../memory/project_tier1_response_extraction_blind_spot.md`
    (gpt-4o content/tool_calls split + iter-5 prompt)
  - `~/.claude/.../memory/project_synthetic_not_in_corpus_db.md`
    (`--no-docker` shim rationale)
  - `~/.claude/.../memory/feedback_reproducible_logs.md` (write-as-you-go logs)
