# pipeline2 — BugsC++ corpus builder

Produces the inputs the DockerDriver (downstream eval harness) consumes per
bug: a built buggy workspace on disk, a developer-fix patch for the judge,
and a row in `data/corpus.db` with trigger argv + ground-truth location.

## Contract (what this pipeline produces per bug)

Per bug, keyed by `bug_id = "<project>-<index>"` (e.g. `libtiff-1`):

1. **Built buggy workspace** at
   `data/workspaces/<bug_id>/<project>/buggy-<index>/` — source tree with the
   compiled buggy executable inside. DockerDriver bind-mounts this at `/work`
   in the eval container.
2. **Developer fix patch** at `data/patches/<bug_id>.diff` — reversed from
   BugsC++'s `taxonomy/<project>/patch/<NNNN>-buggy.patch`. Applies cleanly
   to the buggy tree to produce the fixed tree. Judge reads this to score
   the model's response.
3. **Row in `data/corpus.db` table `bugs`** with (at least):
   - `bug_id`, `project`, `bug_index`, `language`, `bug_type`, `cve_id`
   - `trigger_argv_json` — argv to launch the bug (post-`bash -c` unwrap)
   - `gdb_image` — per-project `chatdbgpro/gdb-<project>:latest`
   - `workspace_path`, `patch_path` — filesystem pointers for DockerDriver
   - `patch_first_file`, `patch_first_line`, `patch_line_ranges_json` —
     patch-derived ground-truth location (the bug is where the developer
     patched)
   - `user_frame_file/line/function`, `frame0_*`, `crash_signal` — optional
     gdb observations when the bug crashes; informational for the judge's
     structured-field rubric
   - `bug_observed` — `"crash:<SIG>"` / `"exit_code:<N>"` / `"no_observation"`
   - `included_in_corpus` — gate flag; 1 iff build_ok AND patch_first_file
     AND patch_path

## Prerequisites

- Docker daemon running.
- `BUGSCPP_REPO` env var → path to the cloned `bugscpp` repo (contains
  `bugscpp/taxonomy/` and `bugscpp/bugscpp.py`). If unset, defaults to
  `../bugscpp` relative to this repo.
- Python 3.9+.

## Run end-to-end

```bash
BUGSCPP_REPO=/path/to/bugscpp python pipeline2/run_all.py --workers 4
```

Equivalent step-by-step:

```bash
python -c "import sqlite3; sqlite3.connect('data/corpus.db').executescript(open('pipeline2/schema.sql').read())"
BUGSCPP_REPO=/path/to/bugscpp python pipeline2/seed.py
BUGSCPP_REPO=/path/to/bugscpp python pipeline2/build.py --workers 4 [--project <name>] [--resume]
```

## Inclusion gate

`bugs.included_in_corpus = 1` iff:

- `build_ok = 1`
- `patch_first_file IS NOT NULL` (taxonomy patch parsed to at least one source-file hunk)
- `patch_path IS NOT NULL` (fix patch written to `data/patches/`)

Crash reproducibility is **not** required. Logical-error bugs that build but
don't crash (assertion failures, wrong output, non-zero exits) are still
valid debugging targets — ChatDBG can inspect state with gdb to diagnose.

---

## Per-file reference

### `schema.sql`

**Run:**
```bash
python -c "import sqlite3; sqlite3.connect('data/corpus.db').executescript(open('pipeline2/schema.sql').read())"
```

**Expected output:** none. Creates the `bugs` table in `data/corpus.db`.
Idempotent when schema already matches.

**Runtime:** < 1 s.

---

### `parse_patch.py` (library)

Two pure functions:

- `parse_unified_diff(text) -> [{file, start, end}, ...]` — one entry per
  hunk; line numbers are on the POST-IMAGE side of the hunk.
- `reverse_patch(text) -> str` — swap FIXED↔BUGGY direction. Used to turn
  BugsC++'s `<NNNN>-buggy.patch` into the developer fix patch shipped as
  `data/patches/<bug_id>.diff`.

No CLI; invoked from `seed.py` and `reconcile.py`.

---

### `docker/gdb-base.Dockerfile`

**Run (manually, normally invoked by `ensure_image.py`):**
```bash
docker build -t chatdbgpro/gdb-libtiff:latest \
    --build-arg PROJECT=libtiff \
    -f pipeline2/docker/gdb-base.Dockerfile .
```

**Expected output:** Docker build log ending with
`Successfully tagged chatdbgpro/gdb-<project>:latest`. Adds `gdb`,
`libtool-bin`, `patch` on top of `hschoe/defects4cpp-ubuntu:<project>`.

**Runtime:** 30–90 s per project on first build; ~2 s if base is cached.
Disk: ~1.5 GB per image.

---

### `ensure_image.py`

**Run (idempotent — only builds if missing):**
```bash
python pipeline2/ensure_image.py libtiff cppcheck exiv2
```

**Expected output:** one line per project,
`[ensure_image] <project> -> chatdbgpro/gdb-<project>:latest`. Skips the
docker build if `docker image inspect` finds the tag.

**Runtime:** ~1 s per already-built image; same as gdb-base.Dockerfile build
cost when missing.

---

### `seed.py`

**Run:**
```bash
BUGSCPP_REPO=/path/to/bugscpp python pipeline2/seed.py [--db data/corpus.db]
```

**Expected output:**
```
[seed] 214 inserted, 0 updated; 214 total, 214 with trigger_argv, 214 with parsed patch
```

Walks `$BUGSCPP_REPO/bugscpp/taxonomy/<project>/meta.json` for all 23
projects (skips `example`). Per bug: resolves `trigger_argv` (Tier A:
`extra_tests` literal; Tier B: rendered `common.test.commands`), reads and
reverses the taxonomy buggy.patch into `data/patches/<bug_id>.diff`, and
populates `patch_first_file / patch_first_line / patch_line_ranges_json`.
All ground truth is populated **before** any docker/build work. Idempotent:
re-running upserts by `bug_id`.

**Runtime:** 2–5 s. Pure metadata + patch I/O; no Docker, no network.

---

### `build.py`

**Run:**
```bash
BUGSCPP_REPO=/path/to/bugscpp python pipeline2/build.py \
    [--db data/corpus.db] \
    [--project <name>] \
    [--workers 4] \
    [--resume]
```

`--workers` schedules across **projects** (serial within a project, because
the bugscpp CLI uses a fixed `<project>-dpp` container name). `--resume`
skips rows where `built_at IS NOT NULL`.

**Per-bug pipeline (4 steps):** checkout buggy → `bugscpp build` → optional
single gdb probe (fills `crash_signal`, `user_frame_*`, `bug_observed`; if
no crash, runs trigger once outside gdb for `exit_code`) → apply inclusion
gate → single `UPDATE bugs`.

**Expected output:** one line per bug, e.g.
```
[project=libtiff] 5 bugs
[libtiff-1] OK build_ok=1 crash:SIGSEGV
[libtiff-2] -- build_ok=1 exit_code:1
…
[build] done: total=214 built=180 crashed=40 included=180
```

**Runtime:**
- **Per bug:** 30–240 s (build dominates; single gdb probe is 5–30 s).
- **Per project (5–20 bugs):** 5–40 min serial.
- **Full corpus (214 bugs, `--workers 4`):** ~2–4 hours wall clock.

---

### `reconcile.py`

**Run (one-shot migration after updating schema):**
```bash
python pipeline2/reconcile.py [--db data/corpus.db]
```

**Expected output:**
```
[reconcile] migrating schema in data/corpus.db
[reconcile] 214 rows to process
[reconcile] removed N stale bench/cases/bugscpp-* dirs
[reconcile] done. patches re-extracted: 214/214, bug_observed set: 28, included_in_corpus after gate: ~22
```

Per row: adds the new columns (`bug_id`, `patch_path`,
`patch_first_file/line/ranges_json`, `bug_observed`, `built_at`);
backfills `bug_id` from `case_id`; re-extracts the fix patch from the
taxonomy (overwriting any contaminated `patch_diff` from the old pipeline);
computes `bug_observed` from existing `crash_signal`; sets the canonical
`workspace_path`; re-applies the new inclusion gate. Pure metadata +
filesystem write — no docker, no checkouts.

**Runtime:** < 30 s on a 214-row DB.

---

### `run_all.py`

**Run:**
```bash
BUGSCPP_REPO=/path/to/bugscpp python pipeline2/run_all.py --workers 4 [--project <name>] [--resume]
```

**Expected output:** sequential headers `[run_all] applying schema` →
`[run_all] seeding bugs table (reads taxonomy patches)` →
`[run_all] building buggy workspaces`, followed by each child script's own
output. Exits with the child's exit code.

**Runtime:** schema + seed are negligible; total dominated by `build.py`
(~2–4 h on full corpus, `--workers 4`).

---

## Notes

- DockerDriver is the eval driver (separate, downstream). It reads the
  corpus.db row for a given `bug_id`, bind-mounts `workspace_path` at
  `/work` inside the per-project gdb image, bind-mounts ChatDBG source,
  runs ChatDBG, and writes `collect.json`. Pipeline2 does **not** produce
  `bench/cases/<case_id>/case.yaml` — that tree is reserved for the
  synthetic test suite, not this corpus.
- The developer fix patch lands in `data/patches/<bug_id>.diff`, not under
  `bench/cases/`. The judge reads from there.

## Sharing built Docker images

The built workspaces and generated Docker image layers are not portable
through git. Share the `chatdbgpro/gdb-<project>:latest` images separately,
then teammates can run ChatDBG inside each image while keeping collection and
evaluation artifacts on the host.

Preferred team handoff: push the images to a registry you all can read
(Docker Hub, GHCR, or a private course registry).

```bash
docker images 'chatdbgpro/gdb-*' --format '{{.Repository}}:{{.Tag}}'

REGISTRY=ghcr.io/<org-or-user>/chatdbgpro
for image in $(docker images 'chatdbgpro/gdb-*' --format '{{.Repository}}:{{.Tag}}'); do
  project=${image#chatdbgpro/gdb-}
  project=${project%:latest}
  docker tag "$image" "$REGISTRY/gdb-$project:latest"
  docker push "$REGISTRY/gdb-$project:latest"
done
```

Teammates pull and, if needed, retag back to the names stored in
`data/corpus.db`:

```bash
REGISTRY=ghcr.io/<org-or-user>/chatdbgpro
for project in libtiff cppcheck exiv2 yaml_cpp; do
  docker pull "$REGISTRY/gdb-$project:latest"
  docker tag "$REGISTRY/gdb-$project:latest" "chatdbgpro/gdb-$project:latest"
done
```

No-registry fallback:

```bash
docker save $(docker images 'chatdbgpro/gdb-*' --format '{{.Repository}}:{{.Tag}}') \
  | gzip > chatdbgpro-gdb-images.tar.gz

# On another machine:
gunzip -c chatdbgpro-gdb-images.tar.gz | docker load
```

After importing, verify the tags match the DB values:

```bash
python - <<'PY'
import sqlite3
for (image,) in sqlite3.connect("data/corpus.db").execute(
    "select distinct gdb_image from bugs where gdb_image is not null order by 1"
):
    print(image)
PY
docker images 'chatdbgpro/gdb-*'
```
