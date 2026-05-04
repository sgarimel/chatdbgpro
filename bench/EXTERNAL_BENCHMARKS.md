# External C/C++ Benchmarks

This repo now has a low-friction external benchmark path in addition to
BugsC++:

```bash
python scripts/import_external_benchmarks.py
python bench/orchestrator.py \
  --cases crashbench-abo1 juliet-cwe121-char-type-overrun-memcpy-01 \
  --models openrouter/moonshotai/kimi-k2.5 \
  --tool-configs tier3_gdb_only \
  --tiers 3 \
  --trials 1
```

After judging a sweep, generate the three project charts with:

```bash
python bench/judge.py bench/results/<sweep-name> --judge-model openrouter/openai/gpt-5
python bench/analyze.py bench/results/<sweep-name>
python bench/charts.py bench/results/<sweep-name>
```

Chart outputs land in `bench/results/<sweep-name>/analysis/charts/`:

- `score_heatmap_by_model_tier.png` - 12-column heatmap grouped by
  T1/T2/T3/T4 and root_cause/local_fix/global_fix.
- `average_debugging_score_by_model.png`
- `average_tokens_by_model.png`

The imported cases live under `bench/cases/external/` and are ordinary
synthetic cases. They do not need BugsC++ project Docker images or
`data/corpus.db`. Tier 3 runs them through the synthetic gdb runner image
(`chatdbgpro/synthetic-runner:latest`), so the debugger surface is still gdb
with ChatDBG loaded.

## Ready Now

### Crashbench

Source: `https://github.com/ortegaalfredo/crashbench`

Why it fits: small C files with expected vulnerable line metadata in
`config.ini`. The importer copies a gdb-friendly subset into cases prefixed
`crashbench-`.

Imported starter set:

- `crashbench-abo1`
- `crashbench-abo2`
- `crashbench-abo3`
- `crashbench-abo5`
- `crashbench-abo7`
- `crashbench-abo8`

These are argv-triggered buffer-overflow cases built with `-g -O0` and ASan.
Some other Crashbench files require stdin, infinite-loop handling, or are
static-review-only examples, so they are not imported by default.

### Juliet C/C++ 1.3

Source: `https://github.com/arichardson/juliet-test-suite-c`

Why it fits: large public C/C++ weakness corpus, organized by CWE. The mirror
adds a Unix build system, but the importer avoids the full CMake build and
copies selected standalone bad variants into normal case directories.

Imported starter set:

- `juliet-cwe121-char-type-overrun-memcpy-01`
- `juliet-cwe122-char-type-overrun-memcpy-01`
- `juliet-cwe126-char-alloca-loop-01`
- `juliet-cwe415-malloc-free-char-01`
- `juliet-cwe416-malloc-free-char-01`

Each case carries `defines: ["INCLUDEMAIN", "OMITGOOD"]`, `io.c`, and
`std_testcase.h`, so ChatDBG debugs only the vulnerable path. The harness now
supports `build.extra_sources`, `build.include_dirs`, `build.support_files`,
and `build.defines` for exactly this shape.

On Windows, Juliet's upstream paths exceed the default path-length limit. After
cloning, run:

```bash
git -C external/benchmarks/juliet-test-suite-c config core.longpaths true
git -C external/benchmarks/juliet-test-suite-c restore --source=HEAD :/
```

## Cloned / Reference-Only For Now

### Codeflaws

Source: `https://github.com/codeflaws/codeflaws`

Why it is not imported yet: the GitHub repo contains scripts and metadata, but
the actual 3902 C defect folders come from a separate tarball. It is useful for
future wrong-answer debugging, but it needs a small adapter that turns one
failing input into a gdb launch and a behavioral oracle. It should not require
Docker once the tarball is unpacked.

### IntroClass / ManyBugs

Source: `https://repairbenchmarks.cs.umass.edu/`

IntroClass is plausible because it is small C student-program data with tests,
but it is distributed as an archive rather than a git repo and still needs a
test-to-gdb adapter. ManyBugs has real C program defects, but the published
site recommends newer Docker/BugZoo infrastructure for reproducible scenarios,
which overlaps the pain we are trying to avoid with BugsC++.

### DBGBench

Source: `https://dbgbench.github.io/`

DBGBench is conceptually very aligned with ChatDBG because it contains human
debugging diagnoses and crash/functional-bug classifications. The public site
is summary/metadata-first and points to upstream repos, reports, and patches;
there is no simple clone-and-run corpus path comparable to Crashbench or
Juliet.

### Defects4C

Source: `https://defects4c.github.io/`

Potentially valuable, but not ready for this project today: the site says the
entry point will open after the paper is published. Treat it as a future
candidate rather than something the team can run this week.

## Recreating Local Checkouts

The upstream checkouts are intentionally ignored by git:

```bash
git clone --depth 1 https://github.com/ortegaalfredo/crashbench.git external/benchmarks/crashbench
git clone --depth 1 https://github.com/arichardson/juliet-test-suite-c.git external/benchmarks/juliet-test-suite-c
git -C external/benchmarks/juliet-test-suite-c config core.longpaths true
git clone --depth 1 https://github.com/codeflaws/codeflaws.git external/benchmarks/codeflaws
python scripts/import_external_benchmarks.py
```

## GDB Requirements

For local synthetic cases, the easiest path is the repo's synthetic runner:

```bash
docker build -t chatdbgpro/synthetic-runner:latest \
  -f bench/drivers/synthetic_runner.Dockerfile bench/drivers/
```

That image provides clang, ASan runtimes, gdb with Python support, and the
ChatDBG Python dependencies. It is separate from the BugsC++
`chatdbgpro/gdb-<project>:latest` images.
