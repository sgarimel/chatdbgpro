# pipeline2 — BugsC++ corpus builder

One DB row per BugsC++ bug, plus one `bench/cases/<case_id>/case.yaml` for every
bug that builds, crashes reproducibly, and yields a developer patch.

## Prerequisites

- Docker daemon running.
- `BUGSCPP_REPO` env var → path to the cloned `bugscpp` repo.
- Python 3.9+.

## Run

```bash
python pipeline2/run_all.py --workers 4
```

Equivalent step-by-step:

```bash
sqlite3 data/corpus.db < pipeline2/schema.sql
python pipeline2/seed.py
python pipeline2/build_and_probe.py --workers 4 [--project <name>] [--resume]
```

## Outputs

- `data/corpus.db` — `bugs` table, one row per defect.
- `data/workspaces/<case_id>/<project>/buggy-<idx>/` — built buggy tree
  (kept; bind-mounted by the eval driver).
- `data/backtraces/<case_id>.txt` — raw `gdb bt full` from the last probe run.
- `bench/cases/<case_id>/case.yaml` + `bug.patch` — bench-framework input.
- Per-project gdb image: `chatdbgpro/gdb-<project>:latest`.

## Inclusion gate

`bugs.included_in_corpus = 1` iff:

- `build_ok = 1`
- `crash_reproducible = 1` (same signal across all 3 runs)
- `user_frame_file IS NOT NULL`
- `patch_diff IS NOT NULL`
- `case_yaml_path IS NOT NULL`

## Notes

- `bench/common.py::prepare_injected_workspace` needs a one-line short-circuit
  for `repo.prebuilt_workspace`; until it's added, `bench/` won't pick up these
  cases. The `case.yaml` itself already conforms.
- Generated `criteria.*` are templated prose suitable for line-level scoring;
  rewrite by hand before any LLM-judge evaluation that's intended for a paper.
