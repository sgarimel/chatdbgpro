# pipeline2 — BugsC++ corpus builder

One DB row per BugsC++ bug, plus one `bench/cases/<case_id>/case.yaml` for every
bug that builds, crashes reproducibly, and yields a developer patch.

## Prerequisites

- Docker daemon running.
- `BUGSCPP_REPO` env var → path to the cloned `bugscpp` repo.
- Python 3.9+.

## Run end-to-end

```bash
BUGSCPP_REPO=/path/to/bugscpp python pipeline2/run_all.py --workers 4
```

Equivalent step-by-step (each script is independently runnable):

```bash
python -c "import sqlite3; sqlite3.connect('data/corpus.db').executescript(open('pipeline2/schema.sql').read())"
BUGSCPP_REPO=/path/to/bugscpp python pipeline2/seed.py
BUGSCPP_REPO=/path/to/bugscpp python pipeline2/build_and_probe.py --workers 4 [--project <name>] [--resume]
```

## Outputs (global)

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

---

## Per-file reference

### `schema.sql`

**Run:**
```bash
python -c "import sqlite3; sqlite3.connect('data/corpus.db').executescript(open('pipeline2/schema.sql').read())"
```

**Expected output:** none. Creates the `bugs` table in `data/corpus.db`. Idempotent if the table already matches; will error on conflicting prior schema.

**Runtime:** < 1 s.

---

### `docker/gdb-base.Dockerfile`

**Run (manually, normally invoked by `ensure_image.py`):**
```bash
docker build -t chatdbgpro/gdb-libtiff:latest \
    --build-arg PROJECT=libtiff \
    -f pipeline2/docker/gdb-base.Dockerfile .
```

**Expected output:** Docker build log ending with `Successfully tagged chatdbgpro/gdb-<project>:latest`. Adds `gdb`, `libtool-bin`, `patch` on top of `hschoe/defects4cpp-ubuntu:<project>`.

**Runtime:** 30–90 s per project on first build (cold image pull dominates); ~2 s if base image is cached. Disk: ~1.5 GB per image.

---

### `ensure_image.py`

**Run (idempotent — only builds if missing):**
```bash
python pipeline2/ensure_image.py libtiff cppcheck exiv2
```

**Expected output:** one line per project, `[ensure_image] <project> -> chatdbgpro/gdb-<project>:latest`. Skips the docker build if `docker image inspect` finds the tag.

**Runtime:** ~1 s per already-built image; same as `gdb-base.Dockerfile` build cost when missing.

---

### `seed.py`

**Run:**
```bash
BUGSCPP_REPO=/path/to/bugscpp python pipeline2/seed.py [--db data/corpus.db]
```

**Expected output:**
```
[seed] 214 inserted, 0 updated; 214 total, 214 with trigger_argv
```
Walks `$BUGSCPP_REPO/bugscpp/taxonomy/<project>/meta.json` for all 23 projects
(skips `example`). Resolves `trigger_argv` per defect — Tier A (extra_tests
literal) preferred, Tier B (templated `bash -c` from `common.test.commands`)
fallback. Idempotent: re-running upserts by `case_id`.

**Runtime:** 2–5 s. Pure metadata pass; no Docker, no network.

---

### `build_and_probe.py`

**Run:**
```bash
BUGSCPP_REPO=/path/to/bugscpp python pipeline2/build_and_probe.py \
    [--db data/corpus.db] \
    [--project <name>] \
    [--workers 4] \
    [--resume]
```

`--workers` schedules across **projects** (serial within a project, because
the bugscpp CLI uses a fixed `<project>-dpp` container name). `--resume`
skips rows where `probed_at IS NOT NULL`.

**Per-bug pipeline (9 steps):** checkout buggy → `bugscpp build` → ensure gdb
image → construct `docker run … gdb …` command → run 3× → parse signal +
`bt full` → checkout fixed → `diff -ruN` (source extensions only) → write
`bench/cases/<case_id>/{case.yaml, bug.patch}` → apply inclusion gate →
single `UPDATE bugs` write.

**Expected output:** one progress line per bug, e.g.
```
[project=libtiff] 5 bugs
[bugscpp-libtiff-1] ✓ SIGSEGV user_frame=libtiff/tools/tiffcrop.c:6648
[bugscpp-libtiff-2] ✗ no-crash user_frame=None:None
…
[probe] done: total=214 built=180 reproducible=140 included=120
```

**Runtime:**
- **Per bug:** 90–240 s (build dominates: 30–120 s; 3 gdb runs: 15–45 s; fixed
  rebuild + diff: 30–60 s).
- **Per project (5–20 bugs):** 10–60 min serial.
- **Full corpus (214 bugs, `--workers 4`):** ~3–5 hours wall clock.

---

### `emit_case_yaml.py`

**Run (library; not invoked directly — `build_and_probe.py` calls
`write_case_yaml(bug_row)`):**
```bash
python -c "from pipeline2.emit_case_yaml import write_case_yaml; ..."
```

**Expected output:** writes
```
bench/cases/<case_id>/
├── case.yaml          # injected_repo case, bench/-framework compatible
└── bug.patch          # unified diff (buggy → fixed), source files only
```

**Runtime:** < 50 ms per bug.

---

### `run_all.py`

**Run:**
```bash
BUGSCPP_REPO=/path/to/bugscpp python pipeline2/run_all.py --workers 4 [--project <name>] [--resume]
```

**Expected output:** sequential headers `[run_all] applying schema` →
`[run_all] seeding bugs table` → `[run_all] build + probe`, followed by
each child script's own output. Exits with the child's exit code.

**Runtime:** schema + seed are negligible; total dominated by
`build_and_probe.py` (~3–5 h on full corpus, `--workers 4`).

---

## Notes

- `bench/common.py::prepare_injected_workspace` needs a one-line short-circuit
  for `repo.prebuilt_workspace`; until it's added, `bench/` won't pick up these
  cases. The `case.yaml` itself already conforms.
- Generated `criteria.*` are templated prose suitable for line-level scoring;
  rewrite by hand before any LLM-judge evaluation that's intended for a paper.
