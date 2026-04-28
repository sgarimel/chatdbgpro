# Judge Pipeline for DockerDriver (BugsCPP) Runs

## What's new

The judge pipeline (`judge.py`) now works on DockerDriver runs out of the box.

**New runs**: `DockerDriver.run()` automatically writes `case.yaml` + a sliced
source file into each run directory. No action needed.

**Existing runs**: Use the backfill script (see below).

## Scoring axes

For BugsCPP bugs, the three scoring axes are:

| Axis | What it measures |
|------|-----------------|
| `root_cause` | Did the model identify the correct defect location (file, line, function)? |
| `local_fix` | Does the model's suggested code change match the developer patch (correct file, correct site, equivalent fix)? |
| `global_fix` | Does the model's reasoning explain *why* the bug exists — the underlying cause (e.g. missing bounds check, use-after-free, integer overflow), not just "change line X"? |

These are auto-generated from corpus.db ground truth (`patch_first_file`,
`patch_first_line`, `patch_diff`, `user_frame_function`, `bug_type`).

The synthetic (local) cases are unchanged — they keep their hand-written criteria.

## Backfill existing results

```bash
git pull origin main

# Backfill case.yaml + source into every run dir
python -m bench.backfill_case_yamls bench/results/<your_run_name>/

# Then score as usual
python -m bench.judge bench/results/<your_run_name>/
```

Options:
- `--overwrite` — re-generate case.yaml files that already exist
- `--db <path>` — use a different corpus.db (default: `data/corpus.db`)

## What the backfill writes into each run directory

```
bench/results/<run_name>/<run_id>/
├── result.json        # already exists (from DockerDriver)
├── collect.json       # already exists (from ChatDBG)
├── case.yaml          # NEW — criteria + metadata for judge
├── <source>.c         # NEW — ±50 lines of buggy source around patch site
├── stdout.log
└── stderr.log
```

## Known limitations

1. `local_fix` vs `global_fix` use different definitions than the synthetic
   cases (patch-match vs reasoning-quality). They're semantically compatible
   but not identical — flag this if comparing across bug sets in plots.

2. Multi-file patches: only `patch_first_file` is copied as the source slice.
   The full `patch_diff` is inlined in the criteria so the judge sees all
   touched files.

3. ~20-30% of `patch_first_line` values from `parse_patch.py` point at a
   context line, not the exact buggy line. The judge tolerates this since the
   full diff is in the criteria.

## Files changed

- `bench/common.py` — added `write_docker_case_yaml()`, new fields on `DockerCase`
- `bench/drivers/docker_gdb.py` — calls `write_docker_case_yaml()` after each run
- `bench/backfill_case_yamls.py` — standalone backfill script for existing results
