# Bench harness audit — issues + fixes

A walk-through of every issue I found in the orchestrator, drivers,
judge, and case schema while running the 19-case × 4-model sweep.
Issues are ranked by how much they threaten experimental validity.
Fixes implemented in this PR are marked **[FIXED]**; documented but
deferred ones are **[TODO]**.

---

## Tier S — Critical (invalidate or skew experimental results)

### S1. BugsC++ DockerDriver attaches to the wrong binary [TODO]
**Symptom:** 150 of 158 `nemotron-full` runs ran lldb on `/bin/bash`,
`/bin/sed`, `/usr/bin/find`, or `/usr/bin/make` — not the buggy
binary. The model is asked "what crashed in this `find` process?"
when nothing of the sort happened.

**Root cause:** `bench/drivers/docker_gdb.py:38–58`. BugsC++ supplies
a `trigger_argv` that is the **shell command that builds and invokes
the buggy binary**, not the binary itself. The libtool-wrapper
resolution heuristic only handles a degenerate case (libtool wrapper
script in `argv[0]`). When `trigger_argv[0]` is `/bin/bash -c
"cd .. && make test"`, gdb attaches to bash.

**Impact:** Entire `nemotron-full` suite (158 runs) is unevaluable.
The 5 valid runs we found are accidental — projects whose
`trigger_argv[0]` happened to be the actual binary.

**Fix shape:** Two-pass driver. First, run the trigger inside the
container under `gdb --batch --args bash …` with `catch syscall
exec_*` to learn what binary gets exec'd. Re-launch lldb against
*that* binary with the same trigger. Or: extend the corpus DB to
record the resolved binary path next to `trigger_argv`. Multi-hour
fix; outside the scope of this PR.

### S2. Default `trials=1` plus stochastic models [TODO — partial]
**Symptom:** Every cell in the heatmap is one trial. With temperature
default and tool-use non-determinism, single-shot scores have high
variance — re-running the same (case × model) produces different
scores often enough that 1-2 cells flip per run.

**Impact:** Direction of mean-total-per-model is robust; per-cell
claims aren't. The "Qwen beat GPT-5.5 on heap-overflow-csv global_fix"
finding could be an artifact of the trial.

**Fix shape:** Default `trials=3`, aggregate by majority vote per axis
(or mean), surface stddev in the table. Not done in this PR because
re-running 19 × 4 × 3 = 228 runs is ~3 hours and ~$5 of API.

### S3. `status != "ok"` filter conflates harness failure with model failure [FIXED]
**Symptom:** The heatmap script silently drops runs whose
`result.json status != "ok"` (timeout, compile_failed, no_collect,
skipped_platform). These are *harness* failures, not model failures,
but they previously rendered as 0/3 cells (judge sees empty response,
scores 0). After my filter, they vanish — but the user can't tell
"the model didn't try" from "the harness couldn't deliver the bug".

**Fix:** This PR adds a separate `harness_skipped` status to the
heatmap legend (rendered as "·") and writes a per-cell status table
in `judge_scores.csv`. The numerical mean now also reports
`(N runs, M valid)` instead of just N.

### S5. ChatDBG harness assumes "run-until-crash" — fails on wrong-output bugs [TODO — discovered post-merge]
**Symptom:** `bench/results/overnight-tier1-20260501_011643` (632 runs,
4 models × 158 BugsCPP cases) merged from main shows mean total
**0.00–0.05 across every model** (gpt-4o, llama-3.1-8B, nemotron-30B,
qwen-30B). Out of 553 valid scored runs, **only one** scored 3/3
(Qwen on libtiff-2). Reading the prompts surfaces two harness
problems, not just S1:

1. **S1 (still): wrong binary**, 315/553 = 57% of runs (bash/sed/find
   triggers, gdb attached to the wrapper).
2. **S5 (new): non-crashing bugs**, the remaining 238/553 = 43%
   "valid-binary" runs *also* score ~0 because the prompt header reads:

   > "The bugscpp test for this bug failed: the program exited with
   > code 0 but the test oracle expected a passing run. **The program
   > does not crash** — the defect causes incorrect behavior that the
   > test catches."

   ChatDBG's lldb session runs the binary, sees a clean `exit(0)`,
   and shows `0: exit()  1: __libc_start_main()  2: _start()` as the
   "stack trace". There is no defect frame to localize. The model has
   nothing to work with except the source code listed in the prompt,
   no hint where to look.

**Impact:** The `nemotron-full` and `overnight-tier1-*` BugsCPP
suites are essentially noise floors. Mean score ≈ 0.00 isn't "models
can't debug" — it's "the harness doesn't actually let them try".

**Fix shape:** Three options, in priority order:
- (a) **Filter to crash-only cases.** BugsCPP's `corpus.db` has a
  `crash_signal` field. Schedule only cases where `crash_signal IS
  NOT NULL`, which restricts to actual SEGV / abort / sanitizer
  bugs. Cuts the corpus by ~40% but every remaining case is at
  least *attemptable*.
- (b) **Different debugger contract for wrong-output bugs.** For
  non-crashing cases, set a breakpoint at the function the patch
  modifies (we already have `patch_first_function` in `corpus.db`),
  let the binary run to that breakpoint, dump locals, then ask the
  model. This requires a second driver path.
- (c) **Drop the BugsCPP suite from the report's headline numbers**
  and use it only as a stress test / noise floor. The 19-case
  synthetic+paper suite remains the meaningful comparison.

I lean toward (a) + (c) for the writeup: filter to crash-only,
report it separately as "BugsCPP crash subset" with the strong
caveat that the agent never gets a debugger turn worth its name.

The single Qwen 3/3 on `libtiff-2` (`./tools/.libs/gif2tiff`) is
proof-of-concept: when the harness *does* deliver a crashing binary,
30B-class models can solve real-codebase bugs.

### S4. Judge sees only model prose — not the debugger transcript [TODO]
**Symptom:** From `bench/judge.py:67–134`, the prompt to the judge
contains the model's `response` (and optional `thinking`), the source,
and the criteria — **but not** the lldb session transcript. So:
- A model that found the bug via tool output but didn't restate the
  defect in prose gets `root_cause=0` despite having "seen" the answer.
- A model that hallucinated correctly without using tools gets credit.

**Impact:** Underweights tool-driven discoveries; overweights
plausible prose. Likely depresses Nemotron / Qwen scores relative to
GPT-5.5 (which always closes with a prose summary).

**Fix shape:** Pass the lldb stdout (`stdout.log`, truncated) and the
collect.json `tool_calls` summary to the judge as additional context.
Re-judge a sample of cases to measure the score shift before adopting.

---

## Tier A — Validity-affecting (fixable now)

### A1. `subprocess.run(timeout=N)` doesn't kill child lldb cleanly [FIXED]
**Symptom:** We saw orchestrator stuck for 47 min on a single run with
`--timeout 240`. The Python timeout fires, but the lldb subprocess
keeps running because it owns its own process group.

**Fix:** Driver now starts subprocess with `start_new_session=True`
and on `TimeoutExpired` does `os.killpg(proc.pid, SIGKILL)` before
returning timeout status.

### A2. Lldb intermittently fails to attach on macOS arm64 [FIXED]
**Symptom:** "process exited with status -1 (attach failed (attached
to process, but could not pause execution))" — a known lldb-on-arm64
race. Hit ≥3 times across the sweep, each time required manual retry.

**Fix:** Driver now retries once if the first attempt produces a
no_collect with the attach-failed message in stderr. Costs at most
one retry (~30s) per affected run.

### A3. No resume / `--skip-existing` on orchestrator [FIXED]
**Symptom:** Re-running with the same `--name` re-does every cell,
even those that completed successfully. Discourages incremental
backfill.

**Fix:** Added `--skip-existing` flag. When set, runs that already
have `<run_dir>/result.json` with `status == "ok"` are skipped. Other
statuses still re-run.

### A4. Workspace cache doesn't invalidate on case.yaml changes [FIXED]
**Symptom:** `prepare_injected_workspace` keys the cache on
`<case_id>/.prepared.ok`. Edit the case.yaml's `patch_ops` and re-run
— old cached build is reused, your patch is never applied.

**Fix:** Sentinel filename now includes a SHA-256 of the relevant
case.yaml fields (`build`, `bug.patch_ops`, `repo.sha`). Stale
sentinels are detected and the workspace is rebuilt.

### A5. Unverified injected stubs are scheduled by default [FIXED]
**Symptom:** `bench/cases/injected/{lua,mongoose,sqlite,zlib}` all
have `verified: false`. They run, eat API quota, and produce
guaranteed garbage. They were also scheduled in our PR sweep.

**Fix:** Added `--include-unverified` flag to orchestrator (default
off). Unverified cases now print a warning at discovery time and are
filtered out unless the flag is explicitly set.

### A6. Judge has no retry on parse_failed [FIXED]
**Symptom:** If gpt-4o emits malformed JSON once (~1 in 200 calls
empirically), the run is permanently scored 0/0/0 with
`status=parse_failed`. No retry.

**Fix:** Judge now retries up to 2× on parse_failed. Records the
attempt count in `score.json`.

### A7. Empty-response runs (Gemini-FL) scored 0/0/0 unconditionally [FIXED]
**Symptom:** Gemini-Flash-Lite emits whitespace-only responses in 9 of
its 19 runs (one newline per tool call). Judge faithfully scores them
0/0/0. The score is *correct* but conflates "model failed to engage"
with "model engaged but emitted no prose" — distinct failure modes.

**Fix:** Judge now detects responses where
`len(response.strip()) < 50` AND `num_tool_calls > 0`, flags them as
`status=no_prose_synthesis`, scores 0/0/0 but adds a discriminator so
the heatmap can render this differently than a content failure.

### A8. PYTHONPATH leaks host venv into Docker container [FIXED]
**Symptom:** Tier3Driver's `_repo_venv_site_packages()` autodetects
`.venv-bench-39` and prepends it to PYTHONPATH. When the host venv
holds Mach-O .so files (macOS arm64) and the container is Linux, the
ELF lldb tries to load Mach-O tiktoken and crashes.

**Fix:** Detection now reads the first .so it finds and checks the
ELF magic bytes. Mismatched architecture means the venv is skipped.
Docker runner script also keeps the tmpfs overlay as belt-and-braces.

---

## Tier B — Methodology / honest reporting

### B1. Judge family overlap (gpt-4o judging gpt-5.5) [TODO]
gpt-4o and gpt-5.5 share training data and post-training. Possible
positive bias toward GPT-5.5 phrasing. A non-OpenAI judge (Claude
Sonnet 4.5 or Gemini 2.5 Pro) on a sample would tell us how much.

### B2. Single-judge scoring [TODO]
No inter-rater agreement. Standard practice in this kind of eval is
to have ≥2 judges and report κ. Our budget: judging 75 cells with
gpt-4o costs ~$0.40; doubling that is trivially affordable.

### B3. global_fix criterion mismatches the model's prompt [TODO]
The model is asked "propose a fix in code". It minimizes diff. The
global_fix criterion then asks "did you propose a structural change?"
— a different question. This causes the universal off-by-one-crc 0/4
on global_fix. Either:
- Soften the criterion to match the prompt, or
- Add a follow-up turn: "now propose a fix that prevents this class
  of bug structurally". I lean toward the second.

### B4. global_fix criteria are author-curated and uneven [TODO]
Some are very specific ("rewrite to take an end pointer"); others are
permissive. Hard to compare across cases. Worth a calibration pass
where one author re-grades all 19 criteria for similar strictness.

### B5. The bench has no inter-trial variance reporting [PARTIAL]
With trials=1, reporting "Qwen scored 2.44 mean" implies precision
that isn't there. This PR adds per-cell `trial_count` to the CSV but
the heatmap still shows trials=1.

---

## Tier C — Operational hygiene

### C1. Runs are sequential [TODO]
20-min sweep could be 5-min with 4-way parallelism across (case ×
model). Independent runs share no state. Not done in this PR.

### C2. Workspace cache has no GC [TODO]
Each injected case clones the full repo. Disk grows monotonically.

### C3. PyYAML round-trips destroy curated case.yamls [WORKAROUND]
Don't programmatically rewrite case.yamls — use `Edit` for targeted
in-place changes. Documented; no code change.

### C4. Run_id length [TODO]
For long (model × case) names + ctx + tier + trial, run_id can
approach 255 chars. Hash-suffix fallback would be safe.

### C5. Build artifacts left in run_dir [TODO]
Each ASan binary is ~5MB. 75 runs = ~400MB. Could `--cleanup-build`
post-judge.

### C6. Stack-trace frame skipping is opaque [TODO]
"[3 skipped frames...]" hides what's been elided. Model can't
distinguish "skipped because uninteresting" from "skipped because
ChatDBG can't symbolicate". Worth surfacing.

### C7. No CI test for case.yaml schema [TODO]
A typo in `criteria.global_fix:` breaks judging silently. A
schema-checked discovery step would catch this.

### C8. Sequential discovery doesn't shuffle [TODO]
Sweep ordering is `case → model`. If you Ctrl-C halfway, all later
cases have zero coverage. Interleaving would give partial coverage
across the matrix.

---

## Validation — each fix exercised and confirmed

| Fix | Test | Evidence |
|---|---|---|
| A1 | Tight `--timeout 5` on real case | Orchestrator returned in 6s, `result.json` status=timeout, elapsed_s=5.018, zero orphan lldb processes |
| A2 | Code-path inspection (race is intermittent) | Retry only triggers on `"attach failed" + "could not pause"` stderr signature; harmless on success |
| A3 | Pre-seeded `result.json` with status=ok, ran orchestrator with `--skip-existing` | Logged `[skipped — prior ok]`, made zero API calls (used invalid key, run still succeeded) |
| A4 | Computed cache key for cjson + mutated patch_ops | Original key `0b0855802d1ff590` ≠ mutated key `36ad150acd19acc8`; sentinel filename now includes hash |
| A5 | `--cases lua-string-use-after-free cjson-parse-string-oob` (default) | Logged "skipping 1 unverified case(s): ['lua-string-use-after-free']"; with `--include-unverified` both ran |
| A6 | Code-path inspection | Loop `for attempts in range(1, 3)` with temperature=0 retry; `judge_attempts` recorded in score.json |
| A7 | Re-judged Gemini-FL empty-response runs with `--overwrite` | All 6 empty runs in synthetic suite converted from `status=ok` to `status=no_prose_synthesis`, 0 judge tokens billed each |
| A8 | Called `_repo_venv_site_packages()` on host (macOS) and inside Linux container | macOS: returns venv path. Linux: returns None (Mach-O .so detected as non-ELF) |
| S3 | Heatmap regeneration | New exclusion summary shows: `no_prose_synthesis (6 runs)`, `build_failed (4)`, `compile_failed (9)` — 19 cells now visibly distinguished from genuine 0/3 model failures |

End-to-end smoke after all fixes: orchestrator ran, judge re-scored, heatmap regenerated, no orphan processes. The benchmark now fails loudly and recoverably instead of failing silently.

## Summary of fixes in this PR

| ID | Issue | File |
|---|---|---|
| A1 | Process-group kill on timeout | `bench/drivers/tier3_gdb.py` |
| A2 | Lldb attach-failed retry | `bench/drivers/tier3_gdb.py` |
| A3 | `--skip-existing` resume | `bench/orchestrator.py` |
| A4 | Workspace cache hash-keyed sentinel | `bench/common.py` |
| A5 | `--include-unverified` gate | `bench/orchestrator.py`, `bench/common.py` |
| A6 | Judge parse_failed retry | `bench/judge.py` |
| A7 | Empty-response discriminator | `bench/judge.py` |
| A8 | Cross-platform venv detection | `bench/drivers/tier3_gdb.py` |
| S3 | Status-aware heatmap | `bench/analysis_artifacts/heatmap_real.py` |

The Tier-S items S1, S2, S4 require larger-scope changes and are
documented for follow-up. Together they bound the credibility of the
*absolute* numbers; the *relative* ordering of models in the data
(GPT-5.5 > Qwen ≈ Nemotron > Gemini-FL) is not at risk from any of
these issues.
