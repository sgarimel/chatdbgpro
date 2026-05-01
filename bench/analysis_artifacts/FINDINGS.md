# ChatDBG-Pro bench analysis — findings & next moves

**Scope of the data on disk (200 runs total, all unjudged):**

| Suite | Runs | Models | Notes |
|---|---|---|---|
| `nemotron-full` | 158 | nemotron-nano-9B | BugsC++, tier3 (gdb + source + LSP), ctx=10 |
| `full-synthetic-v1-stripped` | 16 | nemotron-30B, qwen-30B | 8 hand-written cases × 2 models, t=1 |
| `smoke-v3-nemotron-qwen` / `step4-pilot-v2` | 6 | same | smoke runs on a subset |
| pilots / archived smokes | ~20 | mixed | low signal |

**No `score.json` files exist.** Nothing has been run through the LLM-judge,
so all "correctness" numbers below are from heuristics on the response text
(line ±3 mention, file basename, function name, per-case fix anchors).
The judge pipeline is wired up (`bench/judge.py`, `bench/prompts/`) — it just
hasn't been executed against any of these runs.

---

## Capital-H Hard Problem #1 — *the harness is debugging the wrong binary in 95% of BugsC++ runs*

```
debugged binary across nemotron-full (158 runs):
   /usr/bin/bash         54
   /bin/sed              42
   /bin/bash             40
   /usr/bin/find         14
   /usr/bin/make          2
   ./install/bin/dlt-receive 1
   ./build/bin/exiv2      1
   ./tools/.libs/tiffcrop 1
   ./tools/.libs/gif2tiff 1
   ./tools/.libs/tiffsplit 1
```

Only **5 of 158 runs (3%)** have gdb attached to the actual buggy program.
The rest have gdb attached to BugsC++'s *trigger wrapper* (the make/sed/find
script that builds and invokes the buggy binary).  ChatDBG's stack trace in
those cases is an `exit()` / `__libc_start_main` / `??()` from a normally
exiting shell utility.

Concrete consequences in the data:
- `berry-1` (defect at `src/be_vm.c:743`) → gdb is debugging `/usr/bin/find`.
  Model's response is a wholly fabricated lecture about the GNU `find`
  command. **Zero connection to the actual bug.**
- `cppcheck-1` → `/bin/bash`. Model invents a story about bash's exit code.
- `coreutils-1` → `/usr/bin/make`. Model speculates about Makefile syntax.

Root cause is in the driver's trigger handling
(`bench/drivers/docker_gdb.py:38–58`): the libtool-wrapper resolution only
fires for the first `argv` element. When the BugsC++ trigger is "run *this
shell command* which eventually invokes the buggy binary", gdb attaches to
the shell, not the binary. **Until this is fixed, the entire `nemotron-full`
suite is unevaluable** — and any improvement we measure on it is noise.

→ See `figs/01_harness_validity.png`, `figs/02_bugscpp_binaries.png`.

## Capital-H Hard Problem #2 — *even on the 5 "valid" BugsC++ runs, the 9B model collapses to "please run gdb on this"*

I read all 5 transcripts where gdb did attach to the right binary
(dlt_daemon-1, exiv2-8, libtiff-1, libtiff-2, libtiff-5). The pattern is
uniform and damning:

| Case | Tool calls | Model behavior |
|---|---|---|
| dlt_daemon-1 | 1 (`backtrace`) | Asks user to "provide the filename and line number" |
| exiv2-8 | 2 (`backtrace`, `info`) | Suggests user "run program again with GDB attached" |
| libtiff-1 | 1 (`backtrace`) | Tells user to `gdb ./tools/.libs/tiffcrop` |
| libtiff-2 | 0 | Hallucinates about `__fread_chk_warn` glibc internals |
| libtiff-5 | 1 (`bt`) | Generic advice: "Add error handling around file operations" |

**Across 5 valid BugsC++ runs nobody mentions the truth file.** Mean tool
calls = 1.0 with `tier3_gdb_only` (which allows `debug`, `code`, `definition`).
The model does not appear to understand that *it is already inside gdb* — it
keeps suggesting the user run gdb.

This is independent of the harness bug. Even with a perfect harness, the 9B
model wouldn't have solved these. This is the strongest evidence so far for
the project motivation: **current (small) models + ChatDBG's question/answer
shape are insufficient for real-world C/C++ bugs.**

→ See `figs/06_bugscpp_overconfidence.png`.

## Capital-H Hard Problem #3 — *Nemotron-30B almost never uses tools; Qwen-30B does*

Synthetic suite, valid runs (n=14):

| Model | Mean tool calls / run | Mean elapsed (s) |
|---|---|---|
| nemotron-3-nano-30B-a3b | **0.4** | 44.8 |
| qwen3-30B-a3b-instruct | **10.1** | 38.9 |

Nemotron-30B answered 4 of 7 synthetic cases with **zero** tool calls —
purely from the static stack trace + the inline source the harness provides.
Qwen explores frame-by-frame (4–9 `frame` calls per run, plus `code` and
`definition` lookups).

In our heuristic-scoring fog of war these come out roughly equivalent on
the 8 small synthetic cases, but the underlying behavior is wildly
different. **For BugsC++ where the source isn't trivially in-prompt, the
"don't tool" strategy fails entirely** (see Hard Problem #2).

→ See `figs/03_tool_calls.png`, `figs/05_engagement_vs_hit.png`,
`figs/07_tokens.png`.

## Capital-H Hard Problem #4 — *we don't have a real metric*

This whole exercise is held together by string matching. Three axes need
to land:

1. **Run the existing judge.** `bench/judge.py` is implemented and wired to
   `bench/prompts/judge_*.txt`. It's never been executed against these
   runs (no `score.json` anywhere). Cost is small — 200 runs × ~one
   gpt-5/sonnet call.
2. **Don't trust BugsC++ results until #1 is fixed.** The `nemotron-full`
   suite is dominated by harness errors; running the judge over it will
   mostly score "did the model give up correctly". Useful only as a
   negative-control corpus for the new methodology.
3. **Add a structural signal alongside the judge.** "Did the response
   reference the truth file basename and a line within ±5?" is cheap and
   monotone — a useful sanity check on judge variance.

→ See `hard_cases_synthetic.csv`, `all_runs_scored.csv`.

---

## Concrete recommendations (mapped to your 4/24 plan)

### "Have a clearer metric"
1. **Run `bench/judge.py` on the synthetic suite first** (16 runs, ~$1).
   Three axes (root_cause / local_fix / global_fix) plus rationales gives
   you the grounded ChatDBG-paper-style numbers.
2. Add a structural pre-filter (file+line mention) so judge calls on
   obviously-broken runs are skipped. This is also your hard-problem
   detector for free.

### "Try on ½ SOTA model (only on the promising bugs)"
"Promising" = a case with at least one positive heuristic hit on a
small model. From the synthetic set with the strong-anchor heuristic, all
8 cases qualify but the *informative* ones (ones where models actually
diverge in tool use) are:

| Case | Why it discriminates |
|---|---|
| `heap-overflow-csv` | nemotron-30B: 1 tool call. qwen-30B: 14. Both reach the fix but via very different paths — good for the "structure of the interaction matters" claim. |
| `intoverflow-alloc` | Largest mean response (12K chars). Stress-tests verbosity-vs-correctness. |
| `uaf-linked-list` | qwen used 10 tools; nemotron 0. UAF requires temporal reasoning — tests whether tool-driven exploration helps. |
| `double-free-errpath` | Same shape; error-path bug the model has to *reach*. |

Run **Nemotron-Super 120B** on those 4, with both `tier3_gdb_only` and
`debug_with_oracle`. That's 16 runs. Budget < $2.

### "Analyze why model + ChatDBG method did not solve it"
The 5 valid BugsC++ transcripts already tell a clean story:

- **No multi-step reasoning.** The 9B model treats the question as
  zero-shot QA. Tool-call frequency rarely exceeds 1.
- **No spatial localization.** It never asks for source around the
  crashing frame, even though `enable_get_code_surrounding=true`.
- **No self-correction.** It produces a confident "Recommendation"
  section even when the input is `exit()` from /bin/bash.
- **No awareness of the harness.** It instructs the *user* to run gdb.

These are exactly the failure modes that motivate "agent-driven
debugging" as a separate discipline from "frontier LLM with tools".
The bench is, perhaps unintentionally, already a strong case study —
the data is just buried under the harness bug.

---

## Update 2026-05-01: real judge scores across 4 models × 15 cases

Real LLM-judge has now run (judge=`openrouter/openai/gpt-4o`) on the full
synthetic suite (8 cases) plus 7 paper cases that compiled and ran cleanly
(5 from the `paper/` subdir as-is, 2 — test-deep-recursion and
test-definition-likely — after adding `-std=c++17` to fix nullptr compile).
test-pointers and test-pointers-loop hung lldb on macOS for some models;
their dirs are present but excluded from the heatmap (status=compile_failed
or no_collect). uninit-stack-accumulator was run inside a linux/amd64
container (clang-18 + libclang-rt-18-dev for MSan) so the row is real.

Mean total score (root_cause + local_fix + global_fix, 0-3) over 15 cases:

| Model | Mean | 3/3 wins | 0/3 losses |
|---|---|---|---|
| GPT-5.5 | **2.80** | 12 | 0 |
| Nemotron-30B | **2.33** | 9 | 2 |
| Qwen-30B | 2.29 (n=14) | 8 | 2 |
| Gemini-3.1-Flash-Lite | 1.00 | 3 | 9 |

Hardest cases (cells averaged across all models):

| Case | Mean total | Notes |
|---|---|---|
| test-overflow | 0.75 | global-buffer-overflow with multiplier index — only Qwen got 3 |
| uninit-stack-accumulator | 0.75 | only GPT-5.5 solved (3); 9B and both 30Bs scored 0 |
| off-by-one-crc | 1.50 | none got global_fix |
| double-free-errpath | 1.75 | only GPT-5.5 got local_fix |
| heap-overflow-csv | 1.75 | none reasoned about why bounds matter |

Saturated (every model 3/3):
- signed-unsigned-loop, uaf-linked-list, test-stack-overflow

### + 1 real-repo (injected) case: cjson-parse-string-oob
Cloned cJSON v1.7.18, removed the bounds check before the parse-string
quote-scan loop, ASan flagged a heap-buffer-overflow on `"abc` input.
GPT-5.5 / Nemotron-30B / Qwen-30B all hit 3/3; Gemini-3.1-Flash-Lite
scored 0/3. **First real-codebase data point** — extends the synthetic
results onto an upstream library.

The other 4 injected cases are stubs with `verified: false` — they have
`bug.patch` files with approximate line numbers but no `patch_ops` (the
text-substitution form the driver actually applies), so the bug is
never injected even when the build succeeds. Mongoose additionally
expects a `test/msan_http_parse.c` harness that doesn't ship with
upstream 7.15. Documented but not fixed in this PR; calibration is
multi-hour per case.

### + 3 new synthetic cases (this PR)

Added to extend bug-class coverage:

| Case | Class | Sanitizer | Why discriminating |
|---|---|---|---|
| `stack-buffer-overflow-strcpy` | stack OOB write | ASan | Tests size-arithmetic reasoning. Gemini-FL: 0/3, others 3/3. |
| `vector-iter-after-pushback` | iterator UAF | ASan | All 4 models: 3/3 — saturated. |
| `shift-int-overflow` | UB shift count | UBSan | Tests type-promotion reasoning. GPT-5.5 / Qwen 3/3, Gemini-FL & Nemotron 2/3. |

Final headline numbers (19 cases × 4 models, judge=gpt-4o):

| Model | Mean total |
|---|---|
| GPT-5.5 | **2.84** |
| Qwen-30B-A3B | 2.44 |
| Nemotron-30B-A3B | 2.42 |
| Gemini-3.1-Flash-Lite | 1.05 |

Key takeaways:
1. **GPT-5.5 is the only model that reliably solves uninit-stack-accumulator**
   — even with MSan deterministically catching it, the others can't compose
   the temporal-reasoning argument from the report. 38 tool calls for
   GPT-5.5 vs 41 for Gemini-FL with completely different outcomes — call
   *volume* doesn't predict success.
2. **30B-class A3B models tie GPT-5.5 on the easy half of the suite, lose
   ~0.5 score on the hard half.** Project hypothesis (small model + better
   structure can match large model) is half-supported: it works on the
   straightforward sanitizer hits, fails on bugs requiring multi-step
   semantic reasoning (double-free error-paths, integer overflow).
3. **Gemini-3.1-Flash-Lite is the canary** for "model too small even with
   full ChatDBG harness". 9/15 zero scores — it tools heavily (avg ~10
   calls/run) but fails to localize.
4. **Saturated cases (all-3/3) are the ones where ASan's report names the
   defect directly in the stack trace** — UAF, stack-overflow, signed
   underflow with abort. These are the cases where any model wins because
   the harness already did the localization.

## Files in this directory

```
all_runs.csv                # one row per run, 200 rows
all_runs_scored.csv         # + strong-anchor heuristic
hard_cases_synthetic.csv    # synthetic cases ranked by line-±3 hit rate
hard_cases_strong.csv       # ranked by anchor-based hit rate
promising_cases_for_half_sota.txt
analyze_runs.py             # aggregator
make_figures.py             # figure generator
strong_score.py             # anchor-based heuristic
figs/01..07_*.png           # see references in body
```

## What's NOT in here that you might want next

- **Actual judge scores.** Highest-leverage missing piece.
- **Per-bug-category rollups.** Need a real corpus.db join + judge
  scores; trivial to add once #1 is done.
- **Latency / cost-per-fix curves.** Half-written; collect.json has
  `stats.cost` but nemotron runs all show `cost: 0` (free tier).
- **Comparison to GPT-4 baseline.** Not in the data on disk.
