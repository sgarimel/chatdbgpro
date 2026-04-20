# ChatDBG Pro — Project Process Log

This document is the running progress log for the ChatDBG-Pro research
fork. It records what has been done, why, and what the artifacts are
for, so a future reader (or a future me) can pick up in the middle
without re-deriving the plan. It is **not** a spec — the spec is in
`CLAUDE.md` (research framing) and the design decisions land in the
code itself. This file is a checkpoint ledger.

---

## Project goal (one paragraph)

Extend ChatDBG (Zheng, Berger et al.) to answer: *how much of a
debugging agent's performance comes from model scale vs. from the
structure of the interaction itself?* We compare three agent tiers on
the same fixed set of bugs, hold the model variable separate, and
score each run against a pre-registered 3-axis rubric. If tier-3
(gdb-only) beats tier-1 (bash-only) by a lot, that's evidence for
"specialised tools matter". If tier-2 (bash + gdb) beats tier-3 on
real-repo bugs, that's evidence for "generality helps even when you
have the specialised tool". Either direction is a publishable finding.

## Tier taxonomy

| Tier | Tools available to the model | Backing implementation |
|-----:|--------------------------------------|-------------------------------------------------------|
| 1    | `bash` only                          | `mini-swe-agent` (Princeton, ~100 LOC, bash-only loop) |
| 2    | `bash` + `gdb`/`lldb` + source helpers | ChatDBG + `enable_bash` = true (our fork's default-new path) |
| 3    | `gdb`/`lldb` + source helpers only   | ChatDBG as in the paper (`enable_bash` = false)         |

All three tiers get the same case, same model, same wall-clock budget;
only the tool surface changes. Runs write a JSON collection that we
score against `criteria.root_cause` / `.local_fix` / `.global_fix` in
each `case.yaml`.

## Cases

Two populations:

1. **Synthetic single-file** (`bench/cases/*.c`). Hand-crafted
   minimal-reproducer cases (double-free, heap-overflow, UAF, etc.).
   Short, deterministic crash under ASan/MSan, one file to read.
   These are the paper's-style test — they reward a short focused
   interaction, so tier-3 is expected to win here.

2. **Injected-bug real repo** (`bench/cases/injected/<id>/`).
   A real upstream project (pinned sha), a unified-diff patch that
   injects one realistic defect (off-by-one, dropped null-check, missing
   memset, missing GC write-barrier), a `bench-repro.sh` that triggers
   it under the right sanitizer, and a rubric that separates
   "re-add the line" from "redesign the invariant". These punish
   `printf`/`grep`-only strategies and reward agents that can actually
   navigate a production codebase. Tier gap is expected to compress
   here; if tier-1 closes it entirely, that's the interesting result.

---

## Step-by-step progress

### Step 1 — tier dispatch refactor ✅ (completed, verified)

**Purpose.** The original `bench/orchestrator.py` hard-coded the
tier-3 control flow (compile → write script → pipe into lldb/gdb →
collect JSON). Before we could add tiers 1 and 2, we had to lift that
logic out of the orchestrator into a `Driver` abstraction so the
orchestrator becomes a thin "which driver, run it, write the index"
loop.

**Artifacts.**

- `bench/__init__.py` — marks `bench/` as a package.
- `bench/common.py` — extracted `Case`, `RunSpec`, `discover_cases`,
  `compile_case`, `finalize_result`, `run_id_for`, `build_matrix`.
  `RunSpec.tier` defaults to 3; `run_id_for` now includes `tier{N}`.
- `bench/drivers/base.py` — `Driver` Protocol (`tier: int` +
  `run(spec, run_dir, *, timeout) -> dict`).
- `bench/drivers/__init__.py` — `get_driver(tier, **kwargs)` factory;
  tier 1 and 2 raise `NotImplementedError` for now.
- `bench/drivers/tier3_gdb.py` — verbatim port of the old tier-3
  pipeline: `pick_debugger`, `build_lldb_script`, `build_gdb_script`,
  `Tier3Driver`.
- `bench/orchestrator.py` — rewritten to a thin CLI: parse args, build
  matrix, for each spec pick a driver, write `index.json`. Accepts a
  `--tiers` flag (default `[3]`) so existing commands still run only
  tier 3.

**Verification.** `bench/tests/test_step1.py` — 28 tests pinning:
- RunSpec defaults, `run_id_for` format, tier discrimination
- `get_driver` dispatch (tier-3 works, tier-1/2 raise, invalid tier
  raises `ValueError`)
- `build_matrix` cardinality with tiers axis
- Script builders match the pre-refactor byte-for-byte output
- `pick_debugger` autodetect (Darwin→lldb, Linux→gdb, neither→raise)
- `Tier3Driver.run` happy path (lldb + gdb) — exact argv, env keys,
  cwd, timeout, input-as-stdin, and result-dict shape
- `Tier3Driver.run` error paths — `dry_run`, `compile_failed`,
  `timeout`, `no_collect`, `clean_env`
- Case discovery covers all 13 cases and recurses one level into
  `cases/injected/`.

All 28 step-1 tests pass. **Behavior change accepted:** run-ID format
now includes `tier{N}`, which lands in fresh results dirs so the index
is still unique — no existing results were invalidated.

### Step 2 — tier-2 tool wiring ✅ (completed, verified)

**Purpose.** Give ChatDBG a `bash` tool so tier 2 actually exists.
Without it, the "tier-2 = bash + gdb" cell in our study is empty.
Done as a pure config flag so tier 3 remains unchanged.

**Artifacts.**

- `src/chatdbg/util/config.py` — added `enable_bash` flag (boolean,
  default `True`) to the `_tool_flags` dict so it's picked up by the
  same config loader that handles `enable_native_debug`,
  `enable_oracle`, etc.
- `src/chatdbg/native_util/dbg_dialog.py`:
  - `import subprocess` at module top (so `unittest.mock.patch`
    against `dbg_dialog.subprocess.run` works in tests).
  - `llm_bash(command: str)` method on `DBGDialog`, carrying an
    OpenAI-function-calling JSON schema in its docstring.
    Implementation: `subprocess.run(command, shell=True,
    timeout=30, capture_output=True, cwd=os.getcwd())`, caps
    stdout+stderr at 8 KB each, prefixes stderr with `[stderr]`,
    appends `[exit=N]` footer. Returns an assistant-visible string.
  - `_supported_functions()` appends `self.llm_bash` to the tool list
    iff `chatdbg_config.enable_bash`.
- `bench/configs/tier2_bash_plus_gdb.json` — explicit tier-2 preset
  (`enable_bash: true` + all the gdb-side flags).
- `bench/configs/tier3_gdb_only.json` — explicit tier-3 preset
  (`enable_bash: false`) so our paper baseline is preserved even now
  that `enable_bash` defaults to true for real users.

**Verification.** `bench/tests/test_step2.py` — 19 tests covering:
- `enable_bash` flag is registered, defaults to True, and the two
  tier presets set it to the right values.
- `llm_bash` happy path (stdout), nonzero exit surfaces `[exit=N]`,
  stderr is labelled, stdout+stderr combined, 8KB truncation applied,
  timeout returns a readable error, unexpected exceptions return a
  readable error, no-output placeholder, pipeline/redirect work, cwd
  inherited, tool schema parses as valid JSON.
- `_supported_functions` includes `llm_bash` iff flag is on.

All 19 step-2 tests pass. Tier-2 is now wired; tier-2 driver itself
still needs to be built (step ≥ 4), but the tool surface is ready.

### Step 3 — injected-repo case specs ✅ (completed, partially verified)

**Purpose.** The synthetic cases reward agents that can solve a bug
in 10 lines of code. The study will be more honest if tier-3's edge
shrinks (or inverts) on realistic code. Five cases, each injecting a
single defect into a real upstream project pinned to a specific sha,
with ASan or MSan catching the crash deterministically.

**Artifacts.**

- `bench/common.py` extended:
  - `Case.kind` property (defaults to `"synthetic_single_file"`,
    injected cases set `kind: injected_repo` in their `case.yaml`).
  - `discover_cases` recurses one level into subdirectories of
    `cases/` so `cases/injected/<id>/case.yaml` is picked up.
- `bench/cases/injected/cjson-parse-string-oob/` — cJSON v1.7.18
  `parse_string()`: drop the length bound from the scan loop, ASan
  catches heap-buffer-overflow READ on an unterminated string.
- `bench/cases/injected/zlib-inflate-dict-oob/` — zlib v1.3.1
  `inftrees.c::inflate_table()`: flip `>=` to `>` on the
  `used`-counter guard, ASan catches one-past-end write on any
  sufficiently-entropic input.
- `bench/cases/injected/sqlite-shell-null-deref/` — SQLite v3.45.2
  `shell.c`: drop the `if (in == 0)` null-check after `fopen` in the
  `.read` handler, ASan catches NULL-deref in `fgets` when reading
  from a missing file.
- `bench/cases/injected/mongoose-http-uninit/` — Mongoose 7.15
  `mg_http_parse()`: drop the entry `memset` of the output
  `struct mg_http_message`, MSan catches use-of-uninitialized-value
  on a subsequent read of an unset optional field.
- `bench/cases/injected/lua-string-use-after-free/` — Lua 5.4.7
  `lvm.c` OP_CONCAT: drop the GC write-barrier after storing the
  new TString into a register, ASan catches heap-use-after-free once
  an incremental GC step sweeps the unreachable-looking result.

Each injected-case directory contains:
- `case.yaml` — the schema (`id`, `repo.{url,sha,subdir}`,
  `build.{prepare,commands,binary}`, `run.{repro,expected_crash,env,
  clean_env}`, `bug.{patch_file,root_cause_file,category,error_type,
  expected_sanitizer,expected_sanitizer_report_contains}`,
  `criteria.{root_cause,local_fix,global_fix}`, `verified`).
- `bug.patch` — the unified diff to be applied after cloning at sha.
  Line numbers are approximate; step 4 re-bases against the actual
  checkout.
- `bench-repro.sh` — the script that trips the crash after build.
- `README.md` — human-readable narrative, "why it's instructive",
  and step-4 calibration items.

**Verification so far.** `bench/tests/test_step1.py` updated:
- `test_all_cases_discovered` now asserts all 13 IDs (8 synthetic +
  5 injected).
- New `test_injected_cases_discovered_nested` asserts the 5 injected
  cases are picked up through one level of recursion and carry
  `kind == "injected_repo"`.
- New `test_synthetic_cases_have_default_kind` asserts the 8
  legacy cases still read as `kind == "synthetic_single_file"`.

All 47 combined step-1+step-2 tests pass.

**Not yet verified.** `verified: false` in every injected `case.yaml`.
Remaining work, **all deferred to step 4**:
1. Clone each repo at the pinned sha and `git apply bug.patch` — this
   will surface approximate-line-number errors in the patch.
2. Run `bench-repro.sh` end-to-end on linux/x86_64 and mac/arm64 and
   confirm the expected ASan/MSan report.
3. Flip `verified: true` and pin exact line numbers in
   `root_cause_lines_approx`.

---

### Step 3.5 — first end-to-end smoke on macOS arm64 ✅ (completed, verified)

**Purpose.** Before investing in tiers 1/2 and the judge, prove the
tier-3 path works at all against real OpenRouter models on the
developer box. The earlier step-1 tests all mocked `subprocess.run`,
so they couldn't catch any lldb/macOS/venv bugs — they only pinned
our own argv-construction logic. This is the first run with a live
model and a live debugger.

**Setup.**

- `.env` at repo root (0600, gitignored) holding
  `OPENROUTER_API_KEY`. `bench/orchestrator.py` doesn't read it
  itself; it's picked up by the `python-dotenv` equivalent in
  `chatdbg` via env inheritance when orchestrator shells out.
- Two study-target models:
  `openrouter/nvidia/nemotron-3-nano-30b-a3b` and
  `openrouter/qwen/qwen3-30b-a3b-instruct-2507`.
- Two synthetic cases: `null-deref-env` and `off-by-one-crc`.
  Matrix = 2×2 = 4 runs. Results under
  `bench/results/smoke-v3-nemotron-qwen/`.

**Four-layer blocker we had to work through.** Each layer was
invisible until the one above it was fixed.

1. **lldb `-b/--batch` silently drops stdin.** The original tier-3
   driver launched `lldb -b -- <binary>` and piped the ChatDBG
   script through stdin. In batch mode lldb ignores the command
   stream, so the `command script import chatdbg.chatdbg_lldb`
   never ran; the target exited normally and the driver reported
   `no_collect` in 0.3 s. The step-1 tests asserted argv shape but
   never actually invoked lldb, so this shipped in the initial port.
   **Fix:** drop `-b` from argv.
2. **Apple's lldb embeds Python 3.9.6, but chatdbg's deps require
   3.11+.** Once the script actually imported, it failed with
   `ModuleNotFoundError: No module named 'llm_utils'`. The deps we
   installed for the orchestrator live under Python 3.13; lldb can't
   see them. **Fix:** build a dedicated `.venv-bench-39` against
   `/Applications/Xcode.app/.../python3` (3.9), pin the
   3.9-compatible versions of ChatDBG's deps (`ipython<9`,
   `rich<15`, `numpy<2.1`, `litellm==1.55.9`, plus
   `ipyflow-0.0.217`). Add a helper `_repo_venv_site_packages()` to
   `bench/drivers/tier3_gdb.py` that prepends that site-packages
   path onto `PYTHONPATH` so the lldb-embedded interpreter finds
   them.
3. **Homebrew llvm lldb looks like a workaround but isn't.** It
   embeds Python 3.14, which would sidestep the dep-pinning problem,
   but it's adhoc-signed. macOS arm64 only honours the
   `com.apple.security.cs.debugger` entitlement when the host binary
   is signed by a real Apple/Developer ID identity. Brew lldb
   therefore *starts* a traced child but never receives stop events —
   `run` fires, the target executes (and crashes), and lldb reports
   nothing. **Fix:** pick Apple's `/usr/bin/lldb` instead, via a new
   `lldb_binary()` helper. The 3.9 dep pin (layer 2) pays for this.
4. **lldb's command stream and the target's stdin must not be the
   same pipe.** Even with the right lldb and the right Python,
   piping the session script through stdin made the launched target
   inherit that same stdin. The target greedily consumed bytes meant
   for lldb, and lldb stayed in async mode where stop events never
   surfaced. **Fix:** write the session script to `run_dir /
   session.cmds` and pass `-s session.cmds` to lldb; send
   `subprocess.DEVNULL` as the child's stdin.

All four fixes land in `bench/drivers/tier3_gdb.py`. The step-1 tests
were updated in `bench/tests/test_step1.py` to re-pin the new argv
shape (`-s session.cmds` instead of `-b`, `stdin=None` since we no
longer pipe) and to patch `lldb_binary` so tests don't depend on
whether `/usr/bin/lldb` exists. 29 step-1 tests pass.

**Smoke results.** All 4 runs `status=ok`, collect.json written:

```
ok  19.0s  null-deref-env  / nemotron-3-nano-30b-a3b
ok  22.8s  null-deref-env  / qwen3-30b-a3b-instruct-2507
ok  31.1s  off-by-one-crc  / nemotron-3-nano-30b-a3b
ok  23.0s  off-by-one-crc  / qwen3-30b-a3b-instruct-2507
```

**What the diagnoses actually say.** Every run correctly identified
the planted defect and proposed the right minimal fix:

| Case | Model | Tool calls | Prompt → completion tokens | Notes |
|---|---|---|---|---|
| null-deref-env | nemotron | 0 | 1625 → 1331 | Correct fix from stack-trace alone; no debugger probe |
| null-deref-env | qwen | 4 (`print u`, `print a`, `code :13`, `definition getenv`) | 1961 → 1183 | Grounded in `u == 0x0` observation; added empty-string guard in "thorough" fix |
| off-by-one-crc | nemotron | 0 | 1712 → 2059 | Correct but quotes the source `/* BUG: ... */` comment verbatim — a known-test-contamination tell |
| off-by-one-crc | qwen | 7 (`definition crc8`, `code :12`, `code :23`, `print buf/len/i`, `frame variable`) | 2423 → 1203 | Explicitly noticed post-overflow stack corruption (`print buf → 0x0`) and reasoned around it |

**Early observations (for later ablations, not conclusions).**

- Nemotron fires **zero** tool calls on both synthetic cases. It
  treats the stack-trace prompt as a pure-text reasoning task. Qwen
  fires 4 and 7 tool calls respectively. Same verdict, very
  different interaction shape. This is exactly the structure vs.
  scale knob the study is meant to separate, so it's encouraging
  that the split shows up even on day-one synthetic cases.
- Synthetic cases leak their answer through the `/* BUG: ... */`
  comment embedded in the source context we hand the model. Fine
  for a smoke, but the real benchmark should either strip these
  comments from `program.c` before passing it to the debugger or
  score "did the model *find* the line vs. *read* the line". Adding
  to step-4 scope.
- Both 30B-A3B models complete a run in ~20 s on OpenRouter for
  under 2K prompt tokens and ~1–2K completion tokens. At the
  $0.05/M-in, $0.20/M-out Nemotron Nano price sheet this is well
  under a penny per run. A full matrix (13 cases × 3 tiers × 4
  models × ≥ 3 trials ≈ 470 runs) is safely under the $1 budget
  ceiling in `CLAUDE.md`.

**Artifacts added in this step.**

- `.env` (repo root, gitignored) — `OPENROUTER_API_KEY`.
- `.venv-bench-39/` (new, gitignored) — Python 3.9 venv with
  pinned chatdbg runtime deps. Needed because Apple lldb embeds
  3.9 and is the only macOS-arm64 lldb with the debugger
  entitlement.
- `.venv-bench/` (present, superseded by `.venv-bench-39`) — a
  Python 3.14 venv from the aborted brew-lldb plan. Kept on disk
  for now; `_repo_venv_site_packages()` prefers the 3.9 one.
- `bench/drivers/tier3_gdb.py` — new helpers `lldb_binary()` and
  `_repo_venv_site_packages()`; argv uses `-s session.cmds` and
  `DEVNULL` stdin; big comment blocks explaining *why* each of
  those choices is non-obvious so we don't regress.
- `bench/tests/test_step1.py` — updated `test_happy_path_lldb` to
  pin the new argv and patch `lldb_binary`. 29 tests pass.
- `bench/results/smoke-v3-nemotron-qwen/` — 4 run dirs + `index.json`.

**Not in scope here.** The smoke only covers 2 of 8 synthetic cases,
no injected cases (step 4 blocks them), tier-3 only (tiers 1/2
driver work is steps 5/6), no judge yet (step 7). None of the
observations above are findings; they're hypotheses for the full
run to test.

### Step 3.6 — full synthetic matrix with stripped bug-comments ✅ (completed, verified)

**Purpose.** Expand from the 2-case × 2-model smoke to the full 8
synthetic cases × 2 models, tier 3 only. First, address the
contamination we flagged in step 3.5: every synthetic `program.c`
carried a `/* BUG: ... */` comment at the defect site that told the
model the answer before it even read the stack trace.

**Comment stripping.** Each of the 8 synthetic programs had its
`/* BUG: ... */` annotation (plus any other "here's how it breaks"
prose comments nearby, e.g. `/* second free of the dangling
pointer */` in `double-free-errpath`) replaced with a plausible
production-style comment of the *same line count*. Line-count
preservation matters because every `case.yaml` pins
`root_cause_lines` / `related_lines` to absolute line numbers and
the rubric prose references those lines by number. A new grep for
`BUG|bug` in `bench/cases/**/program.c*` shows only the literal
word `debug` (in "debug-dump pretty-printer") — clean. All 47
step-1+step-2 tests still pass.

**Matrix.** 13 cases (8 synthetic + 5 injected) × 2 models × 1 tier
× 1 trial = 26 runs. Results under
`bench/results/full-synthetic-v1-stripped/`.

**Outcomes.**

- **14/16 synthetic runs: `ok`, all diagnoses correct.** Both
  models correctly identified the root cause and proposed a valid
  local fix on all 7 cases that compiled.
- **2/16: `compile_failed` on `uninit-stack-accumulator`.** The
  case uses MSan (`-fsanitize=memory -fsanitize-memory-track-origins`)
  to deterministically catch the uninit-`sum` read, but clang on
  macOS arm64 doesn't support MSan. This is a pre-existing
  platform limitation, not a regression from the comment strip.
  Options: (a) mark the case Linux-only and run it on CI / the
  Tinker nodes, (b) swap to ASan + nondeterministic repro, (c)
  rewrite the case so a deterministic crash surfaces without MSan.
  Deferred.
- **10/10 injected runs: `error KeyError('source_file')`.** Tier3Driver
  expects `case.source_file` + `compile_case`, which injected cases
  don't have — they have `repo.{url,sha}` + `build.commands` +
  `bench-repro.sh`. The driver needs a branch on
  `case.kind == 'injected_repo'` that clones the repo at the sha,
  applies `bug.patch`, runs `build.commands`, launches the binary
  under the debugger, and invokes the repro script. That's exactly
  step 4 — no work attempted here.

**Behaviour changes from the comment strip (the interesting part).**

| Case repeat | Nemotron tool calls (pre → post strip) | Qwen tool calls (pre → post strip) |
|---|---|---|
| `null-deref-env` | 0 → 0 | 4 → 9 |
| `off-by-one-crc` | 0 → 0 | 7 → 11 |

- **Nemotron is a zero-tool model.** 6 of 7 synthetic cases use 0
  tool calls; the other two use 1 and 2. It treats the stack-trace
  prompt as a pure-text reasoning task regardless of whether a
  giveaway comment is present. This persisted after the comments
  were stripped, so it isn't an artefact of the earlier leak.
- **Qwen actively debugs and *increased* tool use once the
  giveaway was removed.** Every stripped-run case has 7-14 tool
  calls. Preferred tools are `frame`, `print`, `code`, and
  `definition`; on specific cases Qwen reaches for
  `disassemble` (off-by-one-crc) and `thread` (signed-unsigned-loop).
  The jump from 4→9 and 7→11 tool calls on the repeat cases is
  the cleanest direct evidence we have that the stripping mattered:
  Qwen had to search for information the comment had previously
  handed it.
- Despite making many more tool calls, Qwen finishes *faster* than
  Nemotron on most cases (16-26 s vs 30-42 s). It's chunking
  reasoning across tool calls instead of generating long prose.
  The one exception is `intoverflow-alloc`, where Qwen spent 111 s
  and 8.7 K tokens — the only case where it also made a wrong
  side-observation (questioning whether `sizeof(Record)` is really
  64). The root-cause diagnosis was still correct.

**Full synthetic result table.**

| Case | Nemotron | Qwen |
|---|---|---|
| double-free-errpath | ok 42 s / 0 tools / correct | ok 23 s / 11 tools / correct |
| heap-overflow-csv | ok 31 s / 1 tool / correct | ok 19 s / 14 tools / correct |
| intoverflow-alloc | ok 68 s / 2 tools / correct | ok 111 s / 7 tools / correct (wobbly) |
| null-deref-env | ok 18 s / 0 tools / correct | ok 26 s / 9 tools / correct |
| off-by-one-crc | ok 31 s / 0 tools / correct | ok 16 s / 11 tools / correct |
| signed-unsigned-loop | ok 34 s / 0 tools / correct | ok 22 s / 9 tools / correct |
| uaf-linked-list | ok 25 s / 0 tools / correct | ok 19 s / 10 tools / correct |
| uninit-stack-accumulator | compile_failed (MSan/macOS) | compile_failed (MSan/macOS) |

**What this does and does not tell us.**

- It does tell us the pipeline is solid end-to-end: 14 live
  OpenRouter calls in a row with no infra flakiness, Apple lldb
  under Python 3.9 driving real ChatDBG sessions.
- It does tell us the models we're going to compare have
  *qualitatively* different interaction shapes even on the easiest
  tier of cases, which is exactly what the study is meant to
  isolate. That was not a guaranteed result; same-parameter-count
  models could easily have behaved identically.
- It does **not** tell us anything about tier gap yet — that's
  steps 5/6. The 14 correct diagnoses are all on synthetic
  single-file cases where tier 3's edge is most generous by
  design. The interesting numbers will come from the injected
  cases on tier 1 vs tier 2 vs tier 3.
- It does not tell us whether the diagnoses pass the three-axis
  rubric — that's step 7. Eyeballing them they all meet
  `criteria.root_cause` and `criteria.local_fix`; `criteria.global_fix`
  is mixed (Qwen more often proposes a structural fix like
  `unique_ptr` / `rbegin()`, Nemotron more often sticks to a
  minimal fix).

---

## Step 3.7 — platform gate + injected-repo driver path

Two blockers fell out of the step-3.6 26-run matrix:

1. **MSan on macOS arm64.** `uninit-stack-accumulator` and
   `mongoose-http-uninit` both require `clang -fsanitize=memory`,
   which Apple's clang refuses on arm64. These are semantically
   correct cases — they just can't be *built* here. Treating the
   compile error as a failure would corrupt the study's success
   rates on this host.
2. **Injected-repo cases unwired.** All five `kind: injected_repo`
   cases errored with `KeyError('source_file')` because
   `Tier3Driver` only knew how to compile a single source file.

Both are now fixed:

- `Case.platforms` reads `build.platforms` from `case.yaml`. When
  the host isn't in that list, `Tier3Driver.run` returns status
  `skipped_platform` and never attempts the build. The judge
  treats this as a structural exclusion, not a failure. MSan cases
  carry `platforms: ["linux"]`; on a Linux host they'll run, on
  macOS they're cleanly skipped. This keeps the case files
  portable — no conditional content, just a declarative filter.
- `Tier3Driver.run` now dispatches to `_run_injected` when
  `case.kind == "injected_repo"`. That path calls
  `common.prepare_injected_workspace(case)` — shallow-clone the
  repo, `git checkout <sha>`, apply `bug.patch_ops`, copy
  `build.assets`, run `build.prepare` then `build.commands`, and
  cache the tree at `bench/.workspace-cache/<case_id>/`. A
  `.prepared.ok` sentinel gates the cache so (model × trial) reuse
  the same build. Lldb then runs with `cwd=workdir` so stack
  frames resolve to the checked-out source, and debug args come
  from `case.meta["debug"]` (a separate block from `run` so the
  human-facing `bench-repro.sh` reference stays untouched).

Two design choices worth pinning:

- **`patch_ops`, not `git apply`.** Each op is
  `{file, before, after}` with a hard "`before` must appear
  exactly once in the file" contract. Unified diffs rot when
  upstream shifts lines; the unique-match constraint is robust to
  arbitrary upstream line-number drift and produces clear failure
  messages (`match count != 1`) instead of silent misapplication.
- **`assets`, not heredoc-in-prepare.** `build.assets` copies
  case-dir files into the workspace before the build runs. Needed
  because upstream test harnesses are rarely stdin-driven (cJSON
  v1.7.18's `parse_with_opts.c` is a Unity fixture) — we ship a
  small `driver.c` that reads stdin, calls the library, and is the
  actual ASan target.

### cJSON pilot (verified)

Pilot target: `cjson-parse-string-oob`, a dropped
`(input_end - content) < length` bound in `parse_string`'s
while-loop. Input `"abc` (unterminated) walks past the heap
buffer; ASan reports `heap-buffer-overflow` at
`cJSON.c:798 in parse_string`.

A manual ASan smoke confirmed the patch fires end-to-end before
we involved any model:

```
==75493==ERROR: AddressSanitizer: heap-buffer-overflow ...
SUMMARY: AddressSanitizer: heap-buffer-overflow cJSON.c:798 in parse_string
```

Then a 2-model pilot (`bench/results/step4-pilot-v2/`) —
Qwen-3-30B-A3B and Nemotron-3-Nano-30B-A3B, single trial each:

| Model | Status | Elapsed | Tools | Diagnosis |
|---|---|---|---|---|
| Qwen-3-30B | ok | 27 s | 9 | Correct. Names `parse_string` at cJSON.c:798, explains missing bound, proposes both local (`input_end - base < length`) and structural (`can_access_at_index`) fixes. |
| Nemotron-3-30B | ok | 92 s | 5 | Correct. Names the same site, correct local fix, also sketches a rewrite that allocates after finding the closing quote — close enough to `criteria.global_fix` option (c). |

Both diagnoses clear `criteria.root_cause` and
`criteria.local_fix`; `criteria.global_fix` is met by Qwen and
plausibly by Nemotron. Case is flipped `verified: true`.

The MSan cases on the same pilot returned `skipped_platform` as
expected, with zero elapsed time and no wasted build attempts.

### One transient worth noting

The first pilot run (`step4-pilot-v1/`) produced
`TypeError('data must be str, not bytes')` on the two cJSON runs
while the two MSan cases skipped cleanly. The second pilot
(`step4-pilot-v2/`), with the workspace cache already populated,
produced `ok` on both cJSON runs. The symptom vanished, no code
change in between. Best guess: a subprocess stdout-decoding race
while the first clone/build was still writing into the cache
directory (both models' runs launched within seconds of the
sentinel appearing). Not worth chasing until it reappears — if
it does, add `rebuild=True` on the first run of a new matrix.

---

## Remaining steps

- **Step 4 — per-case calibration (remaining).** Four injected
  cases still need the same treatment as cJSON: rebase their
  `bug.patch` into `patch_ops`, add `debug:` blocks, drop a
  driver.c where the upstream harness isn't stdin-friendly, verify
  on a target host (Linux for MSan cases), flip `verified: true`.
  Lua, sqlite, zlib locally; mongoose on Linux only.
- **Step 5 — tier-1 driver.** Wrap `mini-swe-agent` in a
  `Tier1Driver` that satisfies the same `Driver` protocol. Input:
  the built binary + the crash reproducer + the source tree, via
  bash only. Output: a written diff/analysis that the scorer reads.
- **Step 6 — tier-2 driver.** Run ChatDBG with
  `tier2_bash_plus_gdb.json`. Essentially `Tier3Driver` with a
  different config file; most of the code is shared.
- **Step 7 — scoring harness + rubric evaluator.** Feed each
  `collect.json` and the case's `criteria` block to a judge model
  (or pair: autograder + LLM judge), emit a per-run score sheet,
  aggregate across trials into a 3×2 cell grid (tier × case
  population). Figures and writeup land downstream of this.

---

## Conventions we've settled on

- The `Driver` protocol is the seam between orchestrator and tier.
  Anything tier-specific lives behind the protocol; the orchestrator
  does not import tier modules directly — `get_driver` does.
- Run IDs embed tier so a single results directory can hold mixed
  tiers without collision.
- Every injected case ships with a `verified` boolean; no case is
  allowed into benchmark runs until it flips true in step 4.
- The `criteria.global_fix` rubric bar is deliberately non-trivial:
  "just undo the patch" never qualifies. Otherwise the gap between
  tier-3 and a zero-shot model evaporates and the study measures
  nothing.
- Tests live at `bench/tests/test_stepN.py`, one file per delivered
  step. Tests pin behavior, they don't describe intent — we add a new
  test file per step rather than editing the old one.

Run the full test suite with:

```sh
PYTHONPATH="$(pwd)/src:$(pwd)" python3 -m unittest \
    bench.tests.test_step1 bench.tests.test_step2 bench.tests.test_step4 -v
```
