# Rebuilding and publishing all 19 BugsCPP gdb images

The original images at `ghcr.io/anikamehrotra/chatdbgpro-gdb-<project>:latest`
were built before this repo's harness work. They lack `strace` (which
the strace-based binary probe needs in rootless apptainer), and the
buggy workspaces inside them were compiled without `-g`, so gdb shows
no source-line frames.

This doc walks through the four-step systematic redo:

1. Build all 19 gdb-base images on linux/amd64 with `strace` baked in,
   pushed to your own GHCR namespace.
2. For every bug in `corpus.db`, rebuild the workspace with `-g -O0 …`
   inside the project's container.
3. Re-run the strace probe so `corpus.db.buggy_binary_path` and
   `buggy_binary_argv_json` reflect the actually-buggy ELF.
4. Verify each binary has `.debug_info` ELF sections.

## 1. Build & push all gdb images via GitHub Actions

The repo ships a matrix workflow at
`.github/workflows/build-gdb-images.yml`. It runs on `workflow_dispatch`
(manual button on github.com/actions) or whenever
`pipeline2/docker/gdb-base.Dockerfile` changes on `main`.

```bash
# trigger from CLI
gh workflow run "Build & publish gdb-base images to GHCR"

# or only a subset
gh workflow run "Build & publish gdb-base images to GHCR" \
  -f projects=yara,libtiff,exiv2
```

Output tags (one per project):
```
ghcr.io/<owner>/chatdbgpro-gdb-<project>:latest
ghcr.io/<owner>/chatdbgpro-gdb-<project>:<commit-sha>
```

The matrix is `linux/amd64`-only (BugsCPP base images are amd64-only;
on Apple Silicon the resulting binaries run via Rosetta — but ptrace
is broken under Rosetta, so the probe step must run on a native amd64
host like adroit). Stage 1 (Python 3.11 + gdb 14.2 from source) is
shared across all 19 images via `cache-from: type=gha,scope=gdb-base-stage1`,
so subsequent matrix runs finish in ~5 min per project instead of 30+.

After the workflow succeeds, packages are private by default (GitHub
doesn't expose a visibility flip in their REST API for user-owned
packages). The `link-packages` job in the workflow prints the settings
URLs in the run summary; click "Change visibility → Public" once per
project. Org-owned namespaces can be flipped automatically.

Tell the bench harness to use your namespace:
```bash
export BENCH_APPTAINER_REGISTRY=ghcr.io/<your-namespace>
```

## 2. Rebuild every workspace with debug symbols

`pipeline2/rebuild_with_debug.py` reads each project's bugscpp recipe
from `bugscpp/taxonomy/<project>/meta.json`, substitutes the `@DPP_*@`
placeholders, splices `-g -O0` into any explicit `CFLAGS=` /
`CXXFLAGS=` assignment, exports `CFLAGS` / `CXXFLAGS` for the rest of
the recipe, then runs the recipe inside the project's container.

```bash
# one project
python -m pipeline2.rebuild_with_debug --project yara --runtime apptainer

# every included bug, parallel (run on adroit, NOT under Rosetta)
python -m pipeline2.rebuild_with_debug --all --runtime apptainer --workers 4

# re-probe even bugs that already have buggy_binary_path
python -m pipeline2.rebuild_with_debug --project yara --force
```

Per-bug logs land at `data/rebuild-logs/<bug_id>.log` (the rebuild's
last-80-lines stdout + last-30-lines stderr). The probe phase populates
corpus.db's `buggy_binary_path` and `buggy_binary_argv_json` for each
successfully-rebuilt bug.

For projects whose default recipe can't link cleanly under our flags
(yara needs `LDFLAGS=-llua5.3` for the test binaries to link against
the lua-driven `defects4cpp.h`), add an entry to `_PROJECT_OVERRIDES`
in the script.

## 3. Verify debug symbols

The script's `has_debug_info` check runs `readelf -S` on the resolved
binary and writes the result back into the script's exit summary
(currently logged, not stored — wire it into corpus.db if you need it
for downstream filtering).

Manual sanity check:
```bash
readelf -S data/workspaces/yara-1/yara/buggy-1/test-api 2>&1 | grep .debug_info
# Expected: a `.debug_info ... PROGBITS ...` row.
```

## 4. Apptainer-on-HPC notes

Apptainer rootless `--fakeroot` on adroit fails the host-glibc fakeroot
helper (GLIBC_2.33 not found). Workaround: pass
`--ignore-fakeroot-command` and override APT's sandboxing inside the
container. Both are baked into `pipeline2/docker/gdb-yara-strace.def`
and the gdb-base Dockerfile.

The strace probe under amd64 emulation on Apple Silicon hits
`PTRACE_TRACEME: Function not implemented`. Run the rebuild + probe
on a linux/amd64 native host (adroit, della, …).

## What ends up shareable

After step 1: any teammate can `apptainer pull
docker://ghcr.io/<your-namespace>/chatdbgpro-gdb-<project>:latest`
without your token (assuming you flipped visibility to Public).

After step 2: `data/corpus.db` is populated for every bug. Ship the
db file with the repo (it's tracked) or share it directly.
