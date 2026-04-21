# Pipeline Smoke-Test Notes — 2026-04-20

Sandbox dry-run of the BugsC++ test-case pipeline against a single bug
(`libtiff-2`) on Windows + Docker Desktop. Purpose: prove the six-script
pipeline end-to-end before scaling to the full 209-bug corpus.

Authoritative pipeline spec: [test_case_pipeline.md](test_case_pipeline.md).

---

## Result

`libtiff-2` passed every gate. Sandbox DB: [data/corpus_smoke.db](data/corpus_smoke.db).

| Field | Value |
|---|---|
| `crash_signal` | SIGABRT |
| `crash_reproducible` | 1 (3/3 GDB runs) |
| `user_frame` | `readextension @ gif2tiff.c:374` |
| `patch_path` | `patches\libtiff-2.diff` (2914 B) |
| `patch_validated` | 1 (fixed-version test suite passes) |
| `included_in_corpus` | 1 |

Ground-truth check: the extracted patch modifies `tools/gif2tiff.c:370-374`
inside `readextension()` — same function, same line — matching the
`user_frame` exactly. This is the signal we'd score models against.

**Per-bug wall time:** ~3 minutes end-to-end.
- crash filter (3 GDB runs): 26s
- extract_crash_location: 3s
- extract_patches + validate (bugscpp checkout-fixed → build → test): 2m31s

---

## Infrastructure added/changed this session

### New
- [docker/gdb-libtiff.Dockerfile](docker/gdb-libtiff.Dockerfile) — extends
  `hschoe/defects4cpp-ubuntu:libtiff` with `gdb` + `libtool`. Built as
  `chatdbgpro/gdb-libtiff:latest`. Removes the expired kitware apt source
  that otherwise breaks `apt-get update` on the base image.
- [data/corpus_smoke.db](data/corpus_smoke.db) — sandbox SQLite with a
  single libtiff-2 row. Kept separate from `data/corpus.db` so the real
  corpus build starts clean.

### Modified
- [scripts/crash_filter.py](scripts/crash_filter.py)
  - Added `DOCKER_GDB_SCRIPT` + `resolve_libtool_argv()` helper.
  - `run_gdb_in_workspace()` dispatches gdb inside a docker container
    with the workspace bind-mounted at `/work` when `--docker-image` is
    set, otherwise runs host gdb as before.
  - CLI flags: `--bug-id`, `--db`, `--docker-image`.
  - Skips re-checkout when workspace already exists.

- [scripts/extract_crash_location.py](scripts/extract_crash_location.py)
  - Same docker dispatch pattern (`DOCKER_BT_SCRIPT` for `bt full`).
  - CLI flags: `--bug-id`, `--db`, `--docker-image`.

- [scripts/extract_patches.py](scripts/extract_patches.py)
  - `validate_patch()` rewritten to match the actual bugscpp CLI: takes
    a checkout PATH, not `<project> <index>`. Now does
    checkout-fixed → `bugscpp build <path>` → `bugscpp test <path>` and
    returns `(ok, reason)` so the caller can record the specific failure
    mode (`checkout_failed` / `build_failed` / `tests_failed`).
  - `--skip-validation` now correctly leaves `patch_validated = 0`
    (previously falsely set to 1, so finalize would include unvalidated
    bugs).
  - CLI flags: `--bug-id`, `--db`.

- [scripts/finalize_corpus.py](scripts/finalize_corpus.py) — added `--db`.

### Problems solved along the way
- Base `hschoe/defects4cpp-ubuntu:libtiff` has no `gdb` → custom image.
- Dockerfile `apt-get update` failed on expired kitware GPG key → strip
  the kitware line from `/etc/apt/sources.list` (not `.list.d/`).
- GDB rejected libtool wrapper scripts ("not in executable format") →
  rewrite `argv[0]` to the sibling `.libs/<name>` real ELF and set
  `LD_LIBRARY_PATH` to every `.libs/` dir under `/work`.
- `bugscpp test libtiff 2` fails with "directory 'libtiff' is not a
  defect taxonomy project" — `test`/`build` take a checkout PATH, not a
  project+index pair. Fix landed in `validate_patch()`.

---

## Open items before the full 209-bug run

### 1. Windows path separators leaking into the DB
`backtrace_path` and `patch_path` currently store `backtraces\libtiff-2.txt`
(backslash). Readers on Linux/HPC will fail. One-line fix at each call
site — use `PurePosixPath` or `.as_posix()` on the relative path:
- [scripts/extract_crash_location.py:276](scripts/extract_crash_location.py#L276)
- [scripts/extract_patches.py:120](scripts/extract_patches.py#L120)

Do this before seeding the real DB so we don't have to migrate rows.

### 2. Per-project gdb-enabled docker images
Only `chatdbgpro/gdb-libtiff` exists. The other 23 BugsC++ projects each
need their own gdb-enabled image, because the base images are built per
project.

**Decision needed**: one of
- **A. Per-project Dockerfiles** — 23 near-identical `gdb-<project>.Dockerfile`
  files, built lazily on first use. Maximum fidelity to BugsC++ build
  envs. Most disk.
- **B. Single generic `gdb-defects4cpp` base** — pick one Ubuntu version
  that matches most BugsC++ images, install gdb, bind-mount workspace
  only. Risk: projects whose source assumes specific compiler/lib
  versions from their own base image will fail to debug correctly.
- **C. Build-on-demand script** — one parameterized Dockerfile + a
  wrapper that `docker build --build-arg BASE=hschoe/...:X`. Middle
  ground. Recommend this.

Also need to decide: check the `gdb-*` images into the registry vs.
build on each machine. For Tinker, building on-node is probably fine
(disk is cheap, bandwidth isn't).

### 3. Scaling projection and parallelism
209 bugs × ~3 min = ~10 hours serial. Two natural axes of parallelism:
- **Across projects** — workspaces are isolated under
  `data/workspaces/<project>-<index>/`. Spawning N workers keyed by
  `(project, index)` is safe. SQLite WAL mode + per-bug commits already
  in place.
- **Within a project** — build cache is per-image, so sequential is
  fine; parallel is ok too.

Target: 4–8 workers → ~1.5–2.5 hours. Decide before starting the real run.

### 4. `extract_patches` resume logic
Currently `--resume` skips rows with `patch_path` already set. That
double-counts bugs where extraction succeeded but validation failed —
they'd be skipped and never retried. Consider keying resume on
`patch_validated = 1` instead, so failed validations re-run
automatically on the next pass.

### 5. Pipeline docs
`test_case_pipeline.md` is written assuming Linux. Add a short Windows +
Docker Desktop appendix (or move the project to a Linux VM/HPC for the
full run and skip this). Leaning toward: do the sandbox exploration on
Windows, run the real corpus build on Tinker.

---

## What NOT to do next

- Don't seed the full `data/corpus.db` yet. Path-separator fix and
  docker-image strategy both need to land first, or we'll rewrite
  rows immediately.
- Don't commit `data/corpus_smoke.db` or the `data/workspaces/` tree.
  Both are reproducible from scratch and `workspaces/` is large.
