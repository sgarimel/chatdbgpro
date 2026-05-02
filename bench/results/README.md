# bench/results/ — what's in each run dir

Every ablation run produces a tree under `bench/results/<run_name>/`. This
file explains what each artifact contains, how to use it, and how to
re-run individual stages without re-running the model.

If you're new to the project, start with [bench/README.md](../README.md)
for the harness as a whole and [bench/JUDGE_README.md](../JUDGE_README.md)
for the LLM-as-judge details.

## Layout

```
bench/results/<run_name>/
├── index.json                         # one entry per run (model x case)
├── <bug_id>__tier3__<model>__<config>__ctx10__t1/
│   ├── result.json
│   ├── collect.json
│   ├── case.yaml
│   ├── <source>.c                     # sliced source for the judge
│   ├── tool_config.json
│   ├── score.json                     # added by `bench.judge`
│   ├── stdout.log                     # gitignored
│   ├── stderr.log                     # gitignored
│   └── chatdbg.log.yaml               # gitignored
└── <bug_id>__tier3__<model2>__...     # one dir per (case, model) cell
```

The `<run_id>` directory name encodes:
- `<bug_id>` — e.g. `berry-1`, matches `bugs.bug_id` in `data/corpus.db`
- `tier3` — execution tier (3 = ChatDBG with debugger). The other two
  tiers from the design doc aren't implemented yet.
- `<model>` — slashes replaced with underscores
  (e.g. `openrouter_qwen_qwen3-30b-a3b-instruct-2507`)
- `<config>` — tool-config name from `bench/configs/`
  (e.g. `tier3_gdb_only`, `tier2_bash_plus_gdb`)
- `ctx10` — `--context-lines` (source-context size around stack frames)
- `t1` — trial number (when `--trials > 1`)

## Files in each run dir

### `result.json` (~700 bytes)

Run-level metadata, not the model's output. Useful for sorting/grouping
runs and getting overall corpus statistics.

```json
{
  "run_id":       "berry-1__tier3__openrouter_qwen_...",
  "status":       "ok",                  // ok | timeout | no_collect | docker_build_failed | ...
  "exit_code":    0,
  "elapsed_s":    14.3,                   // wall time inside the docker run
  "model":        "openrouter/qwen/...",
  "tool_config":  "tier3_gdb_only.json",
  "context_lines": 10,
  "tier":         3,
  "trial":        1,
  "case_id":      "berry-1",
  "language":     "c",
  "timestamp":    "2026-05-01T05:14:22",
  "collect_path": "collect.json"          // null when status != ok
}
```

Use it for: filtering by status (e.g. only ok runs), counting per-model
timeouts, computing wall-time distributions.

### `collect.json` (varies, often 5–50 KB)

The full model session ChatDBG captured. **This is the model's output.**

Top-level keys:
- `meta` — model name, timestamp, tools enabled
- `instructions` — the system message ChatDBG sent (loaded from
  `src/chatdbg/util/instructions/<model>.txt` or `default.txt`)
- `queries` — list of one element per `why <question>` invocation. Our
  harness only invokes `why` once, so `queries[0]` is what you want.

Inside `queries[0]`:
- `user_text` — the question we asked (built from `spec.question`)
- `prompt` — the full first-turn user message (stack trace, error
  string, command line, project info, the question). This is what the
  model literally sees.
- `thinking` — model's CoT trace if it streamed one
- `response` — the model's final text answer (may be empty for timeouts)
- `tool_calls` — list of `{tool_name, call, result, result_length}`
  dicts, one per tool invocation in order. Use this to see what the
  model actually did.
- `num_tool_calls`, `tool_frequency` — quick counts
- `code_blocks`, `total_code_length` — extracted code snippets in the
  response
- `stats` — token counts, cost (when available)

Use it for:
- Reading what the model said: `q['response']`
- Reading what the model did: `q['tool_calls']`
- Understanding *why* a model failed (look at the prompt + the trace)

### `case.yaml` (~1.5 KB)

Per-case metadata + judge rubric. Auto-generated from `data/corpus.db`
by `write_docker_case_yaml()` ([bench/common.py](../common.py)) at run
time. The judge reads this to score the run.

Important fields:
- `id`, `language`, `source_file`
- `criteria`:
  - `root_cause` — "Diagnosis must identify the defect at
    `<patch_first_file>:<patch_first_line>` in function
    `<user_frame_function>`"
  - `local_fix` — the developer's `patch_diff`
  - `global_fix` — generic language about explaining the underlying cause

The criteria are derived from corpus.db ground truth and are
**pre-registered** — they don't change based on what the model said.

### `<source>.c` (varies, ~3–10 KB)

A ±50-line slice of the source file the developer patched, taken from
the buggy workspace at `data/workspaces/<bug_id>/`. The judge sees this
when scoring; the model under test does not (the model has to find the
source itself via tools).

The filename matches `case.source_file` (e.g. `be_vm.c`, `split.c`).

### `tool_config.json` (~160 bytes)

Copy of `bench/configs/<tool_config>.json` for the run. Tells you which
tools the model could call:

```json
{
  "enable_native_debug": true,        // gdb commands via `debug`
  "enable_get_code_surrounding": true, // read N lines around file:line
  "enable_find_definition": true,      // LSP go-to-definition
  "enable_oracle": false,              // GPT-5 sub-tool (off in our runs)
  "enable_bash": true                  // shell commands (tier2 only)
}
```

### `score.json` (added by `bench.judge`, ~2 KB)

Judge's verdict on this run. Written by
[bench/judge.py](../judge.py) from `collect.json` + `case.yaml` +
`<source>.c`.

```json
{
  "judge_model": "openrouter/openai/gpt-4o",
  "scores":    {"root_cause": 1, "local_fix": 1, "global_fix": 1},
  "rationale": {
    "root_cause": "Identified src/be_vm.c:743 in FLIP opcode handling.",
    "local_fix":  "Proposed replacing -a->v.i with ~a->v.i, matches patch.",
    "global_fix": "Explains arithmetic-negate vs bitwise-NOT semantics."
  },
  "judge_input_tokens":  3273,
  "judge_output_tokens": 499,
  "status": "ok"
}
```

Each axis is binary (0 or 1):
- `root_cause`: did the model name the right file/line/function?
- `local_fix`: does the proposed change match the developer patch?
- `global_fix`: does the explanation describe the underlying cause?

A run can score `1/0/1` (correct location and reasoning, but the
suggested fix is somewhere other than the developer's patch site).
Score `0/0/0` is the failure floor — model didn't engage productively
or hit the wrong code path entirely.

### `stdout.log`, `stderr.log` (gitignored — large, noisy)

GDB's full stdout/stderr from the docker run. Useful for debugging
ChatDBG itself or weird cases where the harness misbehaves. **Not
included in commits** — see the per-tier commits for the convention.

### `chatdbg.log.yaml` (gitignored)

ChatDBG's own session log. Redundant with `collect.json` for our
purposes. Skipped from commits.

## Files at the run-tree level

### `index.json`

One JSON-array entry per run, written by `bench/orchestrator.py` after
each run completes. Mirrors `result.json` but flattened into a single
file you can grep without walking the tree.

```python
import json, pathlib
idx = json.loads(pathlib.Path("bench/results/<name>/index.json").read_text())
print(len(idx))                                # total runs
ok = [r for r in idx if r["status"] == "ok"]   # filter by status
```

## Common workflows

### Read what one model did on one bug

```python
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
d = next(Path("bench/results/<run_name>").glob("berry-1__*qwen*"))
c = json.loads((d / "collect.json").read_text(encoding="utf-8"))
q = c["queries"][0]
print("==prompt==");   print(q["prompt"])
print("==tools==");    print(q.get("tool_frequency"))
print("==response=="); print(q["response"])
```

### See the judge's verdict

```python
import json
from pathlib import Path
d = next(Path("bench/results/<run_name>").glob("berry-1__*qwen*"))
s = json.loads((d / "score.json").read_text(encoding="utf-8"))
print(s["scores"])
print(s["rationale"]["root_cause"])
```

### Aggregate scores by model

```bash
# Quick CLI summary (also wired into check_progress.sh):
python -c "
import json, collections
from pathlib import Path
rd = Path('bench/results/<run_name>')
idx = json.loads((rd / 'index.json').read_text(encoding='utf-8'))
by = collections.defaultdict(lambda: {'n':0,'rc':0,'lf':0,'gf':0,'any':0})
for r in idx:
    sp = rd / r['run_id'] / 'score.json'
    if not sp.exists(): continue
    s = json.loads(sp.read_text(encoding='utf-8')).get('scores', {})
    m = r['model'].split('/')[-1]
    rc, lf, gf = int(s.get('root_cause', 0)), int(s.get('local_fix', 0)), int(s.get('global_fix', 0))
    by[m]['n'] += 1
    by[m]['rc'] += rc; by[m]['lf'] += lf; by[m]['gf'] += gf
    if rc or lf or gf: by[m]['any'] += 1
print(f\"{'model':40} {'n':>4} {'rc':>4} {'lf':>4} {'gf':>4} {'any':>4}\")
for m, c in sorted(by.items()):
    print(f'  {m:38} {c[\"n\"]:>4} {c[\"rc\"]:>4} {c[\"lf\"]:>4} {c[\"gf\"]:>4} {c[\"any\"]:>4}')
"
```

Or use [`bench/show_runs.py`](../show_runs.py) (general status table) or
[`bench/analyze.py`](../analyze.py) (CSV + per-axis report).

### Re-judge an existing run tree (don't re-run the model)

`collect.json` + `case.yaml` + `<source>.c` are everything the judge
needs. To re-score with a different judge model or rubric:

```bash
export OPENROUTER_API_KEY=...
python -m bench.judge bench/results/<run_name>/ \
    --judge-model openrouter/openai/gpt-4o \
    --temperature 0 \
    --overwrite                               # rescore even if score.json exists
```

You can also pass `--limit N` to score only the first N runs.

### Backfill `case.yaml` for an old run tree

Pre-`write_docker_case_yaml` runs don't have `case.yaml`. Use:

```bash
python -m bench.backfill_case_yamls bench/results/<run_name>/ --overwrite
```

It re-derives criteria from `data/corpus.db`. Required if you're trying
to judge runs from before the backfill landed.

### Inspect what the model was given

`collect.json[queries][0][prompt]` is the literal first-turn user
message. The system message is in `collect.json[instructions]`.

For tier3_gdb_only (no bash) the prompt looks like:

```
The program has this stack trace:
```
0: exit()
1: __libc_start_main()
2: _start()
```

The program encountered the following error:
```
The bugscpp test for this bug failed: the program exited with code 0
but the test oracle expected a passing run...
```
project=berry, language=c, workspace=/work, bug_type=other

This was the command line:
```
/work/berry tests/bitwise.be
```

What is the root cause of this crash? Walk through the program state...
```

The `command line` and `error` strings are populated from
`buggy_binary_argv_json` and `bug_observed` in `data/corpus.db` (see
[pipeline2/README.md](../../pipeline2/README.md) for how those are
captured).

## What's gitignored vs. committed

`bench/results/` is in `.gitignore`. Specific runs we want to share
across the team are force-added past the ignore rule, following the
pattern from commit `448eaf41`. Each "publish" commit force-adds:

- `result.json`, `collect.json` — model output + metadata
- `case.yaml`, `<source>.c`, `tool_config.json` — judge inputs
- `index.json` — run-tree index
- `score.json` — judge verdicts (added in a follow-up commit once the
  judge step finishes)

We **exclude** `stdout.log`, `stderr.log`, `chatdbg.log.yaml` because
they're large, noisy, and contain absolute container paths.

## Run-naming conventions in this project

Recent run trees:
- `nemotron-full/` — initial nemotron-nano-9b-v2 sweep (commit 448eaf41)
- `overnight-tier1-<TS>/` — 4-model × 158-bug sweep with
  `tier3_gdb_only` (no bash); see commit 31d09b59 + bb64cd99
- `overnight-tier2-<TS>-3models/` — 3-model × 158-bug sweep with
  `tier2_bash_plus_gdb` (Llama, Qwen, GPT-4o)
- `overnight-tier2-<TS>-nemotron/` — Nemotron-30B × 158-bug sweep with
  `tier2_bash_plus_gdb`, separated because Nemotron's median wall time
  is ~10x the others

Helper: `bash check_progress.sh` from the repo root prints a live
summary of any in-progress overnight runs.
