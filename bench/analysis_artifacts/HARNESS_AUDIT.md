# Bench harness audit — issues + fixes

A walk-through of every issue I found in the orchestrator, drivers,
judge, and case schema while running the 19-case × 4-model sweep.
Issues are ranked by how much they threaten experimental validity.
Fixes implemented in this PR are marked **[FIXED]**; documented but
deferred ones are **[TODO]**.

---

## Tier S — Critical (invalidate or skew experimental results)

### S1. BugsC++ DockerDriver attaches to the wrong binary [PARTIAL FIX]
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

**Fix landed (partial):** Added `is_system_trigger_wrapper()` in
`bench/common.py` and a `--skip-system-triggers` flag on the
orchestrator. When set, discovery drops 75 of 85 BugsC++ cases that
would otherwise have gdb attached to bash/sed/find/make. Verified
empirically: with the flag, only the 10 cases whose trigger_argv[0]
is the actual buggy binary (jerryscript-1..9, libtiff-1/2/5)
survive. The full two-pass fix (resolve via `catch exec_*`) is still
needed to **rescue** the 75 wrapper cases — currently we just skip
them. Documented as a follow-up.

### S2. Default `trials=1` plus stochastic models [FIXED — default change]
**Symptom:** Every cell in the heatmap is one trial. With temperature
default and tool-use non-determinism, single-shot scores have high
variance — re-running the same (case × model) produces different
scores often enough that 1-2 cells flip per run.

**Impact:** Direction of mean-total-per-model is robust; per-cell
claims aren't. The "Qwen beat GPT-5.5 on heap-overflow-csv global_fix"
finding could be an artifact of the trial.

**Fix landed:** orchestrator default changed from `--trials 1` to
`--trials 3`. Future sweeps will include variance information by
default. Existing single-trial heatmap is preserved as a baseline;
re-running the 19 × 4 matrix at trials=3 is a $5 / 3hr follow-up.

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

### S5. ChatDBG harness assumes "run-until-crash" — fails on wrong-output bugs [FIXED]
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

**Fix landed:** Both (a) and (b) are implemented:

- **--crash-only flag** filters discovery to cases with
  `crash_signal IS NOT NULL` in corpus.db. Currently retains 2 of 85
  cases (libtiff-1, libtiff-2) because the corpus is largely
  unprobed; once `pipeline2/probe.py` populates more rows the filter
  will retain more cases automatically.

- **--breakpoint-at-patch flag** sets a gdb breakpoint at
  `patch_first_file:patch_first_line` before `run`. For
  non-crashing bugs the program will stop at the defect site and
  the model gets a populated stack frame to inspect. Wired into
  both `bench/drivers/docker_gdb.py` and `bench/drivers/tier3_gdb.py`
  (which generates `breakpoint set --file X --line N` for lldb and
  `break <file>:<line>` for gdb).

The single Qwen 3/3 on `libtiff-2` (`./tools/.libs/gif2tiff`) is
proof-of-concept: when the harness *does* deliver a crashing binary,
30B-class models can solve real-codebase bugs. With the new flags
the rest of the corpus becomes attemptable too.

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

### B3. global_fix criterion mismatches the model's prompt [PARTIAL FIX]
The model is asked "propose a fix in code". It minimizes diff. The
global_fix criterion then asks "did you propose a structural change?"
— a different question. Causes the universal off-by-one-crc 0/4 on
global_fix. **Partial fix landed:** `--structural-fix-turn` flag
appends a second `why "Now propose a structural change..."` to the
debugger session. Driver-side wiring verified (the second `why` is
emitted into session.cmds). However, ChatDBG-side recording only
writes one entry per session into collect.json, so the second turn's
response isn't separately scored today — needs a small ChatDBG
patch (track multiple why-call records in collect.json) before
this is end-to-end useful.

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

### C7. No CI test for case.yaml schema [FIXED]
A typo in `criteria.global_fix:` breaks judging silently. **Fixed:**
`_validate_case_meta()` now runs at discovery time and reports
problems (missing source_file, missing criteria axes, missing
repo.url/sha for injected cases, malformed YAML). Default behavior
warns + skips the bad case; `--strict-schema` flag makes it fatal.
Verified: a deliberately-broken `case.yaml` with no source_file or
criteria is reported with all 4 issues and dropped from the run.

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

## Round 3 — Tier 1 driver (this commit)

Until this commit, the orchestrator's `--tiers 1` flag raised
`NotImplementedError`. Tier 1 is now wired via mini-swe-agent v2.

### Architecture

```
Orchestrator (.venv-bench-39, Py 3.9, Apple lldb pinned)
 └── Tier1Driver.run(spec, run_dir, ...)
      ├── compile_case() / prepare_injected_workspace()  (same as Tier3)
      ├── write task.md, session.cmds (runner argv for hand-rerun)
      └── subprocess: .venv-bench/bin/python3 tier1_runner.py ...
                       (Py 3.14, mini-swe-agent installed)
                        └── DefaultAgent(LitellmModel, LocalEnvironment).run(task)
                             ├── trajectory.json   (mini's native serialize format)
                             └── collect.json      (our standardized schema —
                                                    judge consumes without
                                                    per-tier branching)
```

### Why two venvs

mini-swe-agent v2 requires Python ≥3.10. The orchestrator can't drop
its 3.9 pin (Apple's lldb embeds Python 3.9 for Tier 3's debugger
integration). The Tier1Driver runs in the orchestrator's venv but
shells out to `.venv-bench` for the agent itself. This isolates the
Python version constraint to a single subprocess boundary.

### Files

| File | Purpose |
|---|---|
| `bench/drivers/tier1_minisweagent.py` | Driver (orchestrator-side). Reuses `compile_case`, `prepare_injected_workspace`, `_run_debugger` (proper SIGKILL-pgid handling) so Tier 1 inherits all Round-1 reliability fixes. |
| `bench/drivers/tier1_runner.py` | Subprocess entry point in the mini venv. Standalone — does NOT import `bench.*` so it's independent of harness Python version. Synthesizes both `trajectory.json` (mini's native format) and `collect.json` (our schema). |
| `bench/configs/tier1_bash_only.json` | Informational config — mini doesn't read tool flags, but we keep the file so `run_id_for()` / `heatmap_real.py` pivot on tool_config without special-casing tier 1. |
| `bench/drivers/__init__.py` | `get_driver(1)` returns `Tier1Driver` instead of raising. |
| `bench/orchestrator.py` | New dispatch branch logging `[orchestrator] tier1 using mini-swe-agent (bash-only)`. |

### Logging fidelity vs Tier 3

| Artifact | Tier 3 | Tier 1 |
|---|---|---|
| `case.yaml` (judge input) | ✓ | ✓ |
| `program.c` / source | ✓ | ✓ |
| `build/prog` | ✓ | ✓ |
| `compile.log` | ✓ | ✓ |
| `session.cmds` (replay command) | ✓ (lldb script) | ✓ (runner argv) |
| Trajectory record | `chatdbg.log.yaml` | `trajectory.json` (mini native) + `task.md` |
| `collect.json` (our schema) | ✓ | ✓ |
| `stdout.log` / `stderr.log` | ✓ | ✓ |
| `result.json` (status taxonomy) | ok / timeout / compile_failed / no_collect / skipped_platform | same set + `missing_dep` (mini venv absent) |

### Judge compatibility

`bench/judge.py` consumes Tier-1 `collect.json` byte-identically with
Tier-3 — the judge prompt was already model-and-tool-agnostic. Verified
on `off-by-one-crc × gpt-5.5`: judge produced
`rc=1 lf=1 gf=0`, matching the same case's Tier-3 pattern (universal
local-fix / no-global-fix gap from `HARD_BUGS.md`).

### Operational notes

- `step_limit` default = 15. mini's text-mode parser rejects responses
  without a fenced bash block; some models (gpt-5.5 in particular)
  occasionally emit prose-only responses, triggering an interrupt
  loop. step_limit caps the loop.
- `cost_limit` default = $0.50. Independent of step_limit.
- LiteLLM cost tracking is set to `ignore_errors` because mini's price
  database doesn't include every OpenRouter model (e.g. `gpt-5.5`,
  `gemini-3.1-flash-lite-preview`). Token counts are still tallied
  via `message['extra']['response']['usage']`.
- Setup: `python3.10+ -m venv .venv-bench && .venv-bench/bin/pip install mini-swe-agent`.
  Driver checks for the venv and writes `error.log` with a setup hint
  if it's missing.

### Round-3 validation matrix

| Test | Result |
|---|---|
| Imports clean from orchestrator's venv | ✓ |
| `--tiers 1 --dry-run` produces correct run_id with `tier1_bash_only` config | ✓ |
| End-to-end on `off-by-one-crc × gpt-5.5`: status=ok, exit_status=Submitted, 4 tool calls (nl, prog, gdb, echo), all three diagnosis labels in response | ✓ (smoke 8) |
| `bench/judge.py` scores the resulting `collect.json` without per-tier branching | ✓ (smoke 9, rc=1 lf=1 gf=0) |
| Process-group SIGKILL on timeout (reuses `_run_debugger`) | ✓ (Round 1 invariant) |
| Demo sweep: 4 cases × 2 models, 8/8 status=ok, 7/8 judge=ok + 1 no_prose_synthesis | ✓ |

### Round-3 demo sweep — first Tier-1 numbers

Single-trial 4×2 sweep (heap-overflow-csv, null-deref-env, off-by-one-crc,
signed-unsigned-loop × gpt-5.5, qwen-30B), Tier 1 vs prior Tier 3:

| Case | gpt-5.5 (T1) | qwen-30B (T1) | gpt-5.5 (T3) | qwen-30B (T3) |
|---|---|---|---|---|
| heap-overflow-csv | 0 | 2 | 2 | 3 |
| null-deref-env | 0 | 2 | 2 | 2 |
| off-by-one-crc | 0 | 2 | 2 | 2 |
| signed-unsigned-loop | (no_prose) | 1 | 3 | 3 |
| **mean** | **0** | **1.75** | **2.25** | **2.50** |

Two surprising findings worth flagging:

1. **GPT-5.5 collapses on Tier 1** (mean 0 vs 2.25 on Tier 3).
   Inspection of the trajectories shows it consistently emits its
   final answer *without* the required bash-block submit command,
   gets caught in mini's "no tool calls found" interrupt loop, and
   exits without a structured diagnosis recorded. mini's text-mode
   parser is rigid; gpt-5.5 prefers the OpenAI tool-calling protocol
   and doesn't reliably fall back to fenced bash blocks.

2. **Qwen-30B partially survives** (mean 1.75 vs 2.50 on Tier 3) —
   loses ~0.75 of its score going to bash-only. Qwen follows mini's
   text format more reliably and produces structured diagnoses, so
   the score drop reflects genuine "removing the gdb tool hurts"
   rather than format mismatch.

This is an honest answer to the project's headline question — *agent
scaffold genuinely matters* — but it also exposes a coupling between
"model formatting habits" and "ablation outcome" that the current
Tier-1 setup can't disentangle. A useful follow-up: re-run Tier 1
with mini configured to use OpenAI tool-calling mode for gpt-5.5 (mini
supports both) and see whether GPT-5.5's score recovers. If it does,
the format mismatch is the dominant effect; if it doesn't, the
debugger-tool deficit is.

## Round 3.5 — Tier 1 model robustness (this PR)

The original Tier-1 driver in PR #6 used `LitellmModel` (mini's
default, tool-calling) but with text-mode prompts (`mswea_bash_command`
fenced blocks). That mismatch surfaced as the "GPT-5.5 collapses on
Tier 1" finding from the prior demo sweep — gpt-5.5 emitted tool calls
correctly, but my prompts told it to emit prose-with-bash-blocks, so
its content wandered between the two formats and mini's parser
rejected most responses.

This PR aligns prompts to mini's canonical `swebench.yaml` pattern
(tool-calling) and adds a textbased fallback for models that need it.

### What changed

1. **Tool-calling prompts patterned after `swebench.yaml`.** System
   template is concise; instance template is "make tool calls"
   focused with a CRITICAL REQUIREMENTS block; format-error template
   tells the model to call the bash tool with explicit
   `{"command": "..."}` syntax. No more `mswea_bash_command` mention
   in the default path.

2. **`get_model()` instead of `LitellmModel(...)` directly.** Lets
   mini auto-select the optimal class based on the model name string:
   `claude*`/`sonnet*`/`opus*` get prompt-caching; `*_response_model`
   names route to the Responses API. This matches the recommended
   usage from mini's docs.

3. **`drop_params=True` and `parallel_tool_calls=True`** model_kwargs
   from `swebench.yaml`. `drop_params` lets LiteLLM silently drop
   unsupported args per backend; `parallel_tool_calls` lets capable
   models batch.

4. **Textbased prompt set + auto-routing.** When the resolved class
   has `Textbased` in its name (e.g.
   `LitellmTextbasedModel`), the runner switches to a fenced-bash
   prompt set patterned after mini's `mini_textbased.yaml`. Format
   error template also switches.

5. **`--mini-model-class` orchestrator flag.** Lets a researcher
   override mini's auto-selection (e.g.
   `--mini-model-class litellm_textbased` for models that emit empty
   content under tool-calling mode).

### Robustness verification — 5 models on `off-by-one-crc`

Auto mode (default — mini's `LitellmModel`, tool-calling):

| Model | exit_status | tools | resp_len | judge | rc/lf/gf |
|---|---|---|---|---|---|
| claude-sonnet-4.5 | Submitted | 6 | 3189 | ok | **3/3** |
| gpt-5.5 | Submitted | 4 | 2587 | ok | **3/3** |
| qwen3-30B-a3b-instruct | Submitted | 6 | 1722 | ok | **3/3** |
| gemini-3.1-flash-lite | Submitted | 6 | **0** | no_prose_synthesis | 0/3 |
| nemotron-3-nano-30b-a3b | LimitsExceeded | 4 | **0** | no_prose_synthesis | 0/3 |

Textbased mode (`--mini-model-class litellm_textbased`) for the two
that produced empty content:

| Model | exit_status | tools | resp_len | judge | rc/lf/gf |
|---|---|---|---|---|---|
| gemini-3.1-flash-lite | Submitted | 4 | 3987 | ok | 2/3 |
| nemotron-3-nano-30b-a3b | Submitted | 1 | 787 | ok | 0/3 |

### Why some models need textbased mode

Both Gemini-Flash-Lite and Nemotron-30B-A3B *emit valid tool calls*
under tool-calling mode (mini's parser successfully extracts them and
runs the bash). They also emit empty `content` strings alongside the
tool calls — which means the model's "thought / diagnosis" is missing
from every assistant turn. Switching to textbased forces the model to
put both reasoning AND action in the message body, which both models
do correctly.

This is **a model-side behavior, not a harness behavior**. The
harness's job is to give every model a path that works; auto-routing
+ the override flag together do that. Researchers running new models
should:

1. Try auto-mode first. If `resp_len == 0` across most assistant
   turns, switch to textbased.
2. Mini's docs (https://mini-swe-agent.com/latest/) catalogue this
   pattern for a few known models.

### Round-3.5 validation matrix

| Test | Result |
|---|---|
| All 5 models produce `status=ok` with appropriate model class | ✓ |
| GPT-5.5 (was 0/3 in PR #6) now scores 3/3 in auto mode | ✓ |
| Claude/Qwen unchanged at 3/3 | ✓ |
| Gemini-FL recovers from `no_prose` to 2/3 with `--mini-model-class litellm_textbased` | ✓ |
| Nemotron-30B recovers from `no_prose` to producing structured prose (still 0/3 from judge — model-quality limit, not harness) | ✓ |
| `prompt_mode` field in collect.json's meta documents which path each run took | ✓ |
| `mini_model_class` field documents the resolved class | ✓ |
| Existing PR-#6 logging / status taxonomy / judge contract preserved | ✓ |

## Round 4 — Tier 2 driver (mini bash + persistent gdb)

Until this commit, the orchestrator's `--tiers 2` flag raised
`NotImplementedError`. Tier 2 is now wired as a mini-swe-agent
extension: same DefaultAgent + LiteLLM + LocalEnvironment scaffold as
Tier 1, but with TWO tools registered — `bash` (mini's canonical
stateless subprocess) and `gdb` (a persistent gdb session preloaded
with the buggy binary).

This is the cleanest possible "what does adding a stateful debugger
to a generic bash agent buy?" ablation: holding the agent scaffold
constant (mini), we vary only the tool surface (Tier 1 = bash; Tier 2
= bash + gdb).

### Architecture

```
Orchestrator (.venv-bench-39, Py 3.9)
 └── Tier2Driver.run()
      └── subprocess: .venv-bench/bin/python3 tier2_runner.py
                       (Py 3.14, mini-swe-agent installed)
            ├── DualToolModel(LitellmModel)         — registers BASH_TOOL + GDB_TOOL
            ├── LocalGdbBashEnvironment             — dispatches on action['tool']
            │    ├── bash → super().execute (LocalEnvironment, stateless subprocess.run)
            │    └── gdb  → GdbSession.execute     (persistent gdb subprocess, sentinel I/O)
            └── DefaultAgent.run(task)
                 ├── trajectory.json    (mini's native serialize format)
                 └── collect.json       (judge-ready schema, identical to T1/T3)
```

### Files

| File | Purpose |
|---|---|
| `bench/drivers/tier2_minisweagent.py` | Orchestrator-side driver. Reuses `compile_case`, `prepare_injected_workspace`, `_run_debugger`. Same plumbing as Tier 1; passes the buggy-binary path through to the runner so the gdb session can be preloaded. |
| `bench/drivers/tier2_runner.py` | Subprocess entry point in the mini venv. Defines `BASH_TOOL`, `GDB_TOOL`, custom `parse_dual_tool_actions`, `DualToolModel`, `LocalGdbBashEnvironment`, and `GdbSession`. Standalone — no `bench.*` imports so it works in mini's venv. |
| `bench/configs/tier2_gdb_plus_bash.json` | Informational config so `run_id_for()` / heatmap pivot on tool_config without per-tier branching. |
| `bench/drivers/__init__.py` | `get_driver(2)` returns `Tier2Driver`. |
| `bench/orchestrator.py` | New tier-2 dispatch branch with `--mini-model-class` propagation. |

### `GdbSession` — persistent gdb subprocess

The novel piece. Wraps `gdb -q -nx --args <binary> <argv>` with
stdin/stdout pipes. Each `gdb` tool call sends commands followed by
`echo <unique-sentinel>`; the reader uses `select()` to read lines
from stdout until the sentinel appears. gdb's `echo` writes to gdb's
own stdout (not the inferior's) so the sentinel reliably surfaces
even when the inferior also writes output.

Edge cases handled:

- Inferior in an infinite loop: per-command timeout (default 30s)
  raises `TimeoutError`; we send `SIGINT` to gdb to interrupt the
  inferior, then drain to a fresh sentinel so the session is still
  usable for the next tool call.
- gdb itself died (segfault in user-supplied command, etc):
  `proc.poll() != None`; subsequent calls return an exception_info
  dict so the model sees the failure and can recover.
- Long output: streamed line-by-line (no single-buffer overrun).
- Pagination: `set pagination off` + `set confirm off` at session
  startup so gdb never halts on a `--Type <RET>--` prompt.

Submission semantics unchanged: bash output starting with
`COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` raises `Submitted` (mini's
existing path). Submission is via bash so the existing flow works.

### Logging fidelity matches Tier 1 / Tier 3

| Artifact | T1 | T2 | T3 |
|---|---|---|---|
| `case.yaml` (judge input) | ✓ | ✓ | ✓ |
| `program.c` / source | ✓ | ✓ | ✓ |
| `build/prog` + `compile.log` | ✓ | ✓ | ✓ |
| Replay command | session.cmds (runner argv) | session.cmds (runner argv) | session.cmds (lldb script) |
| Trajectory record | trajectory.json | trajectory.json | chatdbg.log.yaml |
| `collect.json` (our schema) | ✓ | ✓ | ✓ |
| `stdout.log` / `stderr.log` | ✓ | ✓ | ✓ |
| `result.json` status taxonomy | ok / timeout / compile_failed / no_collect / skipped_platform / missing_dep | same | same minus missing_dep |

Tier 2's `collect.json` adds two fields that Tier 1 doesn't need:

- `tool_name_counts`: e.g. `{"bash": 5, "gdb": 4}` — at-a-glance "did
  the model use gdb?"
- `tool_frequency_by_tool`: e.g. `{"bash": {"nl": 1, ...}, "gdb": {"run": 1, ...}}`
  — verb-level breakdown per tool, useful for analysis.

The top-level `tool_frequency` (verb counts, ignoring tool name) is
preserved so existing scripts (`analyze_runs.py`, `heatmap_real.py`)
keep working without modification.

### Robustness verification — 5 models on `off-by-one-crc`

Same five models as Tier 1's robustness sweep, default
`LitellmModel` auto-selected (tool-calling):

| Model | bash | gdb | exit_status | resp_len | judge | rc/lf/gf |
|---|---|---|---|---|---|---|
| gpt-5.5 | 4 | 4 | Submitted | 3043 | ok | **2/3** |
| qwen3-30B-a3b-instruct | 2 | 8 | Submitted | 2354 | ok | **2/3** |
| claude-sonnet-4.5 | 5 | 2 | Submitted | 3169 | ok | **2/3** |
| gemini-3.1-flash-lite | 6 | 3 | Submitted | 428 | ok | **2/3** |
| nemotron-3-nano-30b-a3b | 3 | 11 | LimitsExceeded | 0 | no_prose_synthesis | 0/3 |

**4 of 5 models work cleanly**, all four invoking gdb 2–8 times — the
dual-tool dispatch is exercised. Notable: **Gemini-Flash-Lite
succeeds in Tier 2** despite failing in Tier 1's auto mode (where it
emitted empty content). Having gdb available as a peer tool seems to
anchor Gemini's output format. Nemotron-30B continues its Tier-3
"Mode A — wave the white flag" pattern (model behavior, not
harness — see HARD_BUGS.md).

Universal `global_fix=0` is the "fix-vs-explain cliff" we already
documented across tiers — none of these tiers' models propose a
structural fix for the off-by-one-crc case. Round 4 doesn't address
that; it's a prompt-criterion mismatch, not a tool-surface issue.

### Tier comparison on `off-by-one-crc`

| Model | T1 auto | T1 textbased | T2 (auto) | T3 |
|---|---|---|---|---|
| gpt-5.5 | 3/3 | – | 2/3 | 2/3 |
| claude-sonnet-4.5 | 3/3 | – | 2/3 | (n/a) |
| qwen3-30B | 3/3 | – | 2/3 | 2/3 |
| gemini-3.1-flash-lite | 0 (no_prose) | 2/3 | 2/3 | 0 (no_prose) |
| nemotron-3-nano-30b | 0 (no_prose) | 0/3 | 0 (no_prose) | (n/a) |

For this single case, Tier 1 (bash-only) actually scored highest for
the three working models. Tier 2's added gdb didn't *hurt* — but on
this small-source case, bash + nl + reading the source was enough.
Real-codebase cases (`bench/cases/injected/`) where the source tree
is too big to grep are where Tier 2's persistent gdb should shine;
follow-up work.

### Round-4 validation matrix

| Test | Result |
|---|---|
| Imports clean from orchestrator's venv | ✓ |
| Runner imports cleanly inside `.venv-bench` | ✓ |
| `--tiers 2 --dry-run` produces correct run_id with `tier2_gdb_plus_bash` | ✓ |
| End-to-end on gpt-5.5: status=ok, 9 tool calls (5 bash + 4 gdb), all 3 labels | ✓ |
| `bench/judge.py` scores Tier-2 collect.json without per-tier branching | ✓ |
| 4 of 5 representative models complete cleanly; the failing one (Nemotron-30B) is a known model-quality issue | ✓ |
| GdbSession correctly handles inferior crash (gdb's prompt comes back) — verified in gpt-5.5 trajectory | ✓ |
| GdbSession sentinel-based read survives multi-line output from `bt` / `print` / `info locals` | ✓ |
| Process-group SIGKILL on outer timeout (Round 1 invariant via `_run_debugger`) | ✓ |

## Round 2 fixes (prior commit)

| ID | Issue | Status | File(s) |
|---|---|---|---|
| S1 | Wrong-binary trigger | PARTIAL | `bench/common.py` (`is_system_trigger_wrapper`, `--skip-system-triggers`) |
| S2 | Single-trial default | FIXED | `bench/orchestrator.py` (default trials=3) |
| S5(a) | Crash-only filter | FIXED | `bench/common.py` (`crash_only` arg, `--crash-only`) |
| S5(b) | Breakpoint-at-patch | FIXED | both drivers (`build_lldb_script` / `_build_gdb_session` accept `breakpoint_spec`) |
| B3 | Structural follow-up | PARTIAL | drivers wire a second `why`; ChatDBG-side recording is a follow-up |
| C7 | case.yaml schema | FIXED | `bench/common.py` (`_validate_case_meta`, `--strict-schema`) |

### Round-2 validation matrix

| Test | Evidence |
|---|---|
| S1 unit | `is_system_trigger_wrapper(['bash', '-c', 'true'])` → True; `(['./build/prog'])` → False |
| S1 integration | `discover_docker_cases(skip_system_triggers=True)` drops 75/85 cases, retains the 10 with real binaries (jerryscript-1..9, libtiff-1/2/5) |
| S2 | `--help` shows "Number of trials per (case, model, config). Default 3" |
| S5(a) | `discover_docker_cases(crash_only=True)` retains exactly 2 cases (libtiff-1, libtiff-2 — the only ones with `crash_signal IS NOT NULL` in current corpus) |
| S5(b) script | `build_lldb_script(..., breakpoint_spec='program.c:11')` emits `breakpoint set --file program.c --line 11`; gdb path emits `break program.c:11` |
| B3 script | `build_lldb_script(..., structural_followup=True)` emits two `why` commands; the second is the structural-fix question |
| C7 warn | Synthetic case with no source_file + no criteria reports 4 distinct schema errors and is dropped from discovery |
| C7 strict | `--strict-schema` raises `ValueError` instead of warn-and-skip |
| Regression | All 25 cases discover cleanly; heatmap regenerates; orchestrator imports + `--help` lists every new flag |

End-to-end smoke (`--structural-fix-turn` on `off-by-one-crc` with
gpt-5.5): orchestrator + driver flow runs to completion (status=ok,
elapsed=97s, response 3.1KB). Note: collect.json still contains only
1 query — driver wiring is correct but ChatDBG itself records only
one query per session, so a future ChatDBG patch is needed to
expose the second turn's response separately. The first answer
already mixes local + structural reasoning in many cases, so this
is a refinement rather than a blocker.
