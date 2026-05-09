# Archived bench results (pre-rerun)

Everything in this directory is **old data**. It comes from the
sweeps run before we decided to redesign two pieces of the bench
pipeline:

1. **Patch applicator.** The current LLM-as-judge scores `local_fix`
   and `global_fix` purely from prose — the model's natural-language
   description is compared, by a judge LLM, to the developer patch
   embedded in `case.yaml`. Nothing is recompiled, no patch is
   actually applied. We are planning to switch to an
   *apply-and-verify* axis: take the model's prose fix, materialise
   it as a diff, apply it to the buggy source, recompile, and run
   the trigger. That changes the scoring contract for every cell,
   so we will rerun the bench from scratch once the new applicator
   lands.

2. **Tier-naming + tier-set decisions** still in flight (e.g.
   whether T2 is dropped or kept, how T4 is bounded). Doing the
   rename + drop *before* the rerun keeps the new dataset clean.

This archive is preserved so:

- Figures we already shipped (poster v1, the per-axis heatmaps in
  `bench/analysis_artifacts/figs/poster/`) keep working — they read
  from these paths.
- We can A/B compare a representative slice of the new dataset
  against the old judge to quantify how much the prose-judge differed
  from the apply-and-verify judge.
- The exact judging rationale text is still recoverable for any
  poster claim that cited a specific cell.

## What's in here

```
archive/
├── DATA_MAP.md                                 prose inventory of every sweep below
├── adroit-yara-after-fix-20260503-223021/      yara T1+T2+T3 (post-trigger fix)
├── adroit-yara-gemini-gpt5-20260503-235331/    yara T1+T2+T3 (gemini, gpt-5.5)
├── berry_consolidated/                          5 berry bugs × 6 models × T1-T4 (PR #23)
├── bugbench-t1/, bugbench-t2/, bugbench-t3/    4 BugBench cases × 4 models × T{1,2,3}
├── external-native-ablation-20260504*/          Crashbench + Juliet T1-T4 partials
├── external-native-ablation-20260504-merged-t3rerun/  canonical synthetic merge
├── external-native-t3-rerun-20260504-*/        per-model T3 reruns
├── merged-yara-pilot/                           early yara pilot
├── nemotron-full/, nemotron-md4c9/              nemotron sweep partials
├── overnight-tier1-20260501_011643/             T1 overnight on bugscpp
├── preflight-{native,tier4}-dryrun/             auth + image preflight
├── t3-native-smoke-gpt55*/, native-smoke-t123-gpt55/  T3 smokes
└── tier4-auth-smoke/                            T4 auth smoke
```

Untracked sweeps that lived alongside these (`pilot-yara-*`,
`smoke-*`, `verify-*`, `xtier-*`, `step4-pilot-*`, `t1-auto`,
`t1-validation`, `t2-validation`, `paper-cases*`, `new-cases*`,
`full-synthetic-v1-stripped`, etc.) were never committed and are
not in this archive — see the figure-data audit for which sweeps
contributed to which past figures.

## What this archive does NOT contain

- **The new rerun.** Once the patch applicator + tier-set decisions
  are merged, results will land in `bench/results/<sweep-name>/`
  again, and figures will source from there.
- **Build artefacts.** Per-run `build/` subdirs (~1.6 MB ASan
  binaries each) are still gitignored under `archive/.../*/build/`;
  regenerable from `pipeline2/ensure_image.py` + the test runner if
  needed.

## Touching this archive

Don't. New sweeps go in `bench/results/<sweep-name>/`, not under
`archive/`. The whitelist in `.gitignore` only reaches into this
subtree, so anything you drop above it stays untracked by default.
If we *delete* the archive after the rerun is validated, do it as
a single `git rm -r` PR so history is clean.
