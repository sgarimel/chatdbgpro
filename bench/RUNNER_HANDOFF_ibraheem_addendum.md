# Ibraheem — addendum to RUNNER_HANDOFF_ibraheem.md  (2026-05-10)

Anika's slice (synthetic panel, 320/320 cells) is now complete on
`push/local-runs-anika`. While running it her session discovered and fixed
five issues in the bench infrastructure that will affect your realworld
runs too — **read this file before you sbatch anything**. The original
handoff (`bench/RUNNER_HANDOFF_ibraheem.md`) is otherwise still correct.

The TL;DR: pull her branch, follow the original handoff, but apply the
small Adroit-specific deltas in §6 below.

## §1. New permanent fixes (already in main code paths — no action from you)

These five changes are in the codebase you'll be pulling. They activate
automatically for every sweep, so you don't need to do anything to enable
them. They're listed here so you understand what improved.

### §1.1 Tier-1 prompt iter-5: "content has no audience" framing

`bench/drivers/tier1_runner.py::DEBUG_INSTANCE_TEMPLATE` now opens with a
`<critical_submission_protocol>` block that tells the model the only
delivery channel is bash tool calls, and the diagnosis must go inside a
`cat <<EOF` heredoc tool call. Without this, gpt-4o-class models emit
their diagnosis as plain text (which mini-swe-agent silently rejects) and
look "empty" in the output.

Effect on Anika's gpt-4o T1: 7/20 → 17/20 full RC/LF/GF, 4 timeouts → 0,
wall time 1062s → 121s. Applies to every T1 cell, realworld included.

### §1.2 Tier-3 gdb path for `injected_repo` cases

`bench/drivers/tier3_gdb.py::_run_injected` previously raised
`ValueError("injected_repo only supports lldb for now, got gdb")`. Now it
has a gdb branch (mirrors the lldb script via `build_gdb_script`'s
pattern). injected_repo cases include cjson, lua-string-use-after-free,
mongoose-http-uninit, sqlite-shell-null-deref, zlib-inflate-dict-oob,
uaf-linked-list — all of which appear in your realworld runset too.

### §1.3 ASAN_OPTIONS=abort_on_error=1 so debugger catches the crash

The biggest harness fix. Under gdb (and lldb), ASan/UBSan/MSan/LSan
default to calling `_exit()` on detected error — debugger sees a normal
exit and chatdbg's stop_handler records no signal, so the prompt becomes
"stopped (no-signal)" with no crash backtrace. The model has nothing
concrete to investigate.

`_chatdbg_env` now sets `setdefault("ASAN_OPTIONS", "abort_on_error=1:...")`
for ASAN/UBSAN/MSAN/LSAN. Now ASan raises SIGABRT, gdb catches it, the
prompt gets a real signal + backtrace.

Smoke-test on cjson/T3/gpt-4o went from 67-token partial narration to
1906-char full RC/LF/GF diagnosis. Likely matters for your realworld T3
too — BugsCPP cases are usually ASan-instrumented.

### §1.4 outer subprocess timeout (parallel_run safety net)

`bench/parallel_run.py::run_one` wraps `subprocess.run` with
`timeout=timeout+120`. Catches the rare case where the inner
`proc.communicate(timeout=600)` doesn't fire (one synthetic-T1 cell ran
3733 s instead of 600 s). On overrun, kills the worker and reports
`rc=-9 outer-timeout-kill`. Re-runnable next sweep via `--skip-existing`.

### §1.5 `--no-docker` shim for synthetic case discovery

`bench/parallel_run.py` got a `--no-docker` flag that routes through
`orchestrator --cases <id>` (on-disk discovery) instead of
`--docker --bug-ids <id>` (corpus.db). `bench/run_runset_shard.py`
auto-passes it for `--panel synthetic`.

You're running `--panel realworld`, so this doesn't change anything for
you — realworld cases live in corpus.db and continue to use the docker
path. Just FYI in case you ever need to run synthetic.

## §2. New tooling — things you may want to run

### §2.1 `bench/recover_responses.py` — run before judging

Some smaller / quirkier models (gemini-flash-lite, and historically
qwen30) echo their diagnosis through bash instead of writing it to the
assistant content. Their `collect.json.queries[0].response` ends up empty
and the judge would score them 0/0/0 even when they solved the case.

`recover_responses.py` walks every cell under a target dir, checks
trajectory.json for a tool message that contains ROOT CAUSE + LOCAL FIX +
GLOBAL FIX, and lifts that text into the response field (preserving the
original under `response_pre_recovery`).

Run it on `final_paper_bench/realworld/` after your sweeps merge in, and
before the judge pass:
```bash
python -m bench.recover_responses bench/results/final_paper_bench/realworld
```
Idempotent. Anika's sweep recovered 13/160 T1 cells. Adroit realworld
will probably recover fewer because the worst offenders (gemini-flash-
lite) were T1-only on her runset.

### §2.2 `bench/analyze_synthetic_panel.py` — diagnostics

Generates coverage / format-compliance / latency / per-case heatmap
figures from final_paper_bench/synthetic. There's no realworld
equivalent yet; if you want the same diagnostics for your panel, easiest
is to copy the script to `bench/analyze_realworld_panel.py` and change
the panel path constant. Or skip it and rely on `judge.py`'s output for
the final figure.

### §2.3 `CHATDBG_LOG_REJECTED=1` — env var for debugging silent rejections

Tier1 runner now has an env-var-gated hook that saves every raw model
response (accepted or rejected) to
`<run_dir>/rejected_responses.jsonl`. Only useful when investigating
specific cells where the model "looks empty" but probably wrote real
prose. Don't enable for normal sweeps — disk overhead and not needed
unless triaging.

## §3. Things to look for in your realworld results

If you see any of these patterns, they're known and you don't need to
debug from scratch:

1. **"stopped (no-signal)" in collect.json prompts.** Means the
   ASAN_OPTIONS fix didn't take effect — check that `_chatdbg_env`
   actually ran for that cell. Should now be impossible.
2. **gpt-4o cells with `response = ''` but rc=0 and a large num_tool_calls.**
   Was the dominant T1 failure mode before iter-5. If you see it now,
   the prompt template patch didn't make it into your tier1_runner.py.
3. **Many "no_collect" status from BugsCPP cases.** Could be the
   `injected_repo only supports lldb` ValueError if your realworld
   driver dispatches that path. Should be fixed by §1.2. If it still
   happens, check that gdb is actually being picked by `pick_debugger()`
   on Adroit.
4. **gpt-4o T3 with very short responses on injected_repo cases.** Same
   as the synthetic "stopped (no-signal)" issue — the model gets little
   to work with. The ASAN_OPTIONS fix should resolve it.

## §4. Branch coordination

Anika has been pushing to `push/local-runs-anika`. Her latest tip is
`a91f4dcb` (ASAN_OPTIONS harness fix). Before you start the realworld
sweep:

```bash
cd ~/chatdbgpro
git fetch origin
git merge origin/push/local-runs-anika --no-edit
```

This brings in the five fixes in §1, all the analysis tooling, and the
160 synthetic cells. Your sbatch jobs will use the fixed code automatically.

Conflicts: very unlikely — Anika only touched bench/drivers,
bench/parallel_run.py, bench/run_runset_shard.py, bench/run_synthetic_with_venv.sh,
bench/recover_responses.py, bench/analyze_synthetic_panel.py,
the analysis_artifacts/, and the synthetic cells under final_paper_bench.
None of her edits should conflict with realworld panel work.

## §5. The shared judge pass (post-merge)

Once realworld is in final_paper_bench, run **on whichever owner's
machine has bandwidth**:

```bash
# 1. Recover any echo'd-via-bash responses (mostly small models)
python -m bench.recover_responses bench/results/final_paper_bench/synthetic
python -m bench.recover_responses bench/results/final_paper_bench/realworld

# 2. Judge
python bench/judge.py bench/results/final_paper_bench/synthetic --overwrite
python bench/judge.py bench/results/final_paper_bench/realworld  --overwrite

# 3. Figure: patch TIER_LABELS in bench/charts.py:27 (T1=bash, T2=gdb-only;
#    note paper T2 maps to codebase tier3 — don't rename anything on disk)
python -m bench.charts
```

## §6. Adroit-specific deltas (small)

The original handoff (`bench/RUNNER_HANDOFF_ibraheem.md`) is otherwise
unchanged. Adroit-only items to confirm:

1. **gdb's embedded Python needs chatdbg + deps importable.** On Adroit
   you presumably have a `.venv-bench` at the repo root with `pip install -e .`
   — `_repo_venv_site_packages()` will find it automatically. If you put
   your venv elsewhere (e.g. `/scratch/<netid>/.venvs/`), export
   `CHATDBG_VENV=<path>` so the resolver can find it. Anika exports this
   in `bench/run_synthetic_with_venv.sh`; you can do the same in your
   sbatch wrapper.

2. **Apptainer instead of docker.** All Anika's fixes are runtime-
   agnostic — the ASAN_OPTIONS env propagates through subprocess.run
   regardless of which container backend you use. Should Just Work.

3. **No need for `.venv-bench` symlink trickery.** Anika's setup symlinked
   `.venv-bench → /root/.venvs/chatdbg-bench` because OneDrive on WSL2
   made it slow to keep the venv inside /mnt/c. On Adroit you can just
   put `.venv-bench` directly at the repo root — no symlink, no
   `CHATDBG_VENV` env var needed.

## §7. What's still mine vs yours

- ✅ **synthetic panel (320 cells)** — done, on `push/local-runs-anika`.
- ⏳ **realworld panel (160 cells from your runset)** — yours. Same
  process as the original handoff, but the §1 fixes are now in place.
- ⏳ **joint judge pass + figure render** — whoever has bandwidth.

Memory entries that Anika's Claude session updated (relevant to you):
- `project_tier1_response_extraction_blind_spot.md` — the iter-5 prompt
  insight and why it matters.
- `project_synthetic_not_in_corpus_db.md` — synthetic-only, not your
  problem, but explains the `--no-docker` shim.

## §8. Quick sanity check after your first sweep

Pick any one realworld T3 cell and verify:
```bash
python3 -c "
import json
cj = json.load(open('bench/results/<your sweep>/<cell>/collect.json'))
prompt = cj['queries'][0]['prompt']
import re
m = re.search(r'encountered the following error:.*?\`\`\`\n(.+?)\`\`\`', prompt, re.DOTALL)
print('ERROR field:', repr(m.group(1).strip()) if m else 'unparseable')
"
```
Expected: a real signal name like `'SIGABRT'` or `'SIGSEGV'`, not
`'stopped (no-signal)'`. If you see "stopped (no-signal)", §1.3 didn't
take effect — check that you actually pulled origin/push/local-runs-anika.
