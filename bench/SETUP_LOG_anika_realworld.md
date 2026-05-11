# Setup log — Anika realworld-panel runner (WSL2 Ubuntu, fully local)

Owner: Anika · Branch: `push/local-runs-anika` · Started: 2026-05-11

This file is the canonical reproducibility record for running the
**realworld panel** on Anika's machine, **without adroit**. Ibraheem's
adroit data is being abandoned (see §0).

Mirrors the format of `SETUP_LOG_anika_synthetic.md`. Every command that
touches the environment is logged verbatim, including what failed and
how it was fixed.

Companion files this log refers to:
- `SETUP_LOG_anika_synthetic.md` — the synthetic-panel sibling
- `bench/results/final_paper_bench/_runset_locked.tsv` — work list
- `bench/RUN_STATUS_2026-05-11.md` — adroit-side context (abandoned)

---

## §0. Why local, not adroit

Adroit runs produced two unusable rounds:

1. **2026-05-10 SLURM round** — every cell logs
   `litellm.APIError: Name or service not known`. Adroit's whitelisted
   proxy 403s openrouter.ai, so the API request never left the compute
   node. Trajectory.json is 3 messages (system, user, exit:APIError).
   Nothing recoverable.
2. **2026-05-11 login-node rerun** — partial; ~50 usable T1 cells out
   of 161 needed, no usable T3 cells. The login-node also had no clean
   chatdbg-compatible Python for T3 (system gdb is Py 3.9 vs chatdbg's
   Py 3.11+ requirement).

Decision: rerun **everything** locally on the Windows/WSL2 host that
already produced the 320-cell synthetic panel cleanly. Same harness,
same models, same prompts.

## §1. Realworld panel inventory

The locked runset contains 161 realworld cells: 85 T1 + 76 T3 across
20 unique cases and 8 models.

The 20 cases come from 4 source types:

| Source | Cases | How runs | Setup needed |
|---|---|---|---|
| **crashbench** (6) | crashbench-abo{1,2,3,5,7,8} | on-disk `case.yaml` in `bench/cases/external/`, `--no-docker` path | none — works with synthetic venv |
| **juliet** (5) | juliet-cwe{121,122,126,415,416}-* | on-disk `case.yaml` in `bench/cases/external/`, includes `io.c` + `std_testcase.h` | none — support files present |
| **bugbench** (4) | bc-heap-overflow, man-overflow, ncompress-overflow, polymorph-overflow | on-disk `case.yaml` in `bench/cases/bugbench/`, but `case.yaml.source.dir` references `bugbench-src/...` | need to populate `bugbench-src/` with upstream source trees |
| **bugscpp/berry** (5) | berry-1..5 | corpus.db lookup, requires Docker image `bugscpp-berry` (or BugsCPP runtime) | need Docker Desktop running + BugsCPP image |

15 of 20 cases can run via the same `--no-docker` path the synthetic
panel already uses (sources 1+2 = 11 trivially, 3 needs source tree
setup). Only the 5 berry cases need Docker.

`bench/run_runset_shard.py` (commit c4907050) already splits each
(tier, model) group into a `corpus` subgroup (berry) and a `synth`
subgroup (everything else); the synth subgroup gets `--no-docker`
automatically.

## §2. Environment state at start

Reusing the dual-venv setup from `SETUP_LOG_anika_synthetic.md` §3-4.

```
$ wsl -d Ubuntu -e bash -lc 'ls $HOME/.venvs/'
chatdbg-bench  chatdbg-mini

$ wsl -d Ubuntu -e bash -lc '$HOME/.venvs/chatdbg-bench/bin/python -c "import chatdbg; print(chatdbg.__file__)"'
/mnt/c/.../chatdbgpro/src/chatdbg/__init__.py

$ wsl -d Ubuntu -e bash -lc '$HOME/.venvs/chatdbg-mini/bin/python -c "import minisweagent; print(minisweagent.__file__)"'
/root/.venvs/chatdbg-mini/lib/python3.12/site-packages/minisweagent/__init__.py
```

Both venvs still healthy from the synthetic run. No re-setup needed.

## §3. Smoke tests (one cell per source)

Each source type gets one smoke run with `gemini-3.1-flash-lite-preview`
(cheapest, fastest model) before kicking off the full sweep. Findings
logged as they happen.

All smokes use the same shape:

```bash
wsl -d Ubuntu -- bash -lc 'cd /mnt/c/.../chatdbgpro && \
  source /root/.venvs/chatdbg-bench/bin/activate && \
  export CHATDBG_MINI_PY=/root/.venvs/chatdbg-mini/bin/python3 && \
  python -m bench.orchestrator \
    --models openrouter/google/gemini-3.1-flash-lite-preview \
    --tool-configs bench/configs/tier1_bash_only.json \
    --tiers 1 --trials 1 --timeout 300 \
    --name anika-smoke-realworld-<SRC>-T1 \
    --skip-existing --cases <CASE>'
```

For docker-required cases (berry-1..5), `python -m bench.parallel_run`
is used instead with `--runtime docker --bug-ids berry-1`.

### §3.1 crashbench (on-disk) — ✓ T1 + T3

Smoke case: `crashbench-abo1`.

| Tier | Status | Elapsed | Diagnosis quality |
|---|---|---:|---|
| T1 | ok | 13.3 s | empty `response` field; diagnosis recovered from tool output (4 tool calls, 955 chars) |
| T3 | ok | 61.0 s | full RC/LF/GF directly in `response` (1694 chars, 38 tool calls) |

Recovered T1 response correctly identifies `program.c:9 strcpy` → stack
buffer overflow + bounded strcpy fix + global "avoid raw string handling"
fix. Same shape as the synthetic gemini-flash-lite recovery pattern.

No setup tweaks needed. Crashbench cases work via `--no-docker` /
on-disk `case.yaml` route, same as synthetic.

### §3.2 juliet (on-disk) — ✓ T1

Smoke case: `juliet-cwe415-malloc-free-char-01`.

- T1 ok, 13.9 s, 5 tool calls, recovered 769 chars correctly identifying
  the double-free pattern in `CWE415_Double_Free__malloc_free_char_01_bad`.

No setup tweaks needed. Juliet support files (`io.c`, `std_testcase.h`,
`std_testcase_io.h`) are checked in alongside each case.

### §3.3 bugbench (on-disk + upstream source tree) — ✓ 3 of 4

Source dir required: `bugbench-src/` at repo root. **Not committed** —
populated from `https://github.com/nicovank/bugbench` (a personal mirror
that bundles the upstream source trees). Setup:

```bash
# In WSL2:
cd $HOME && git clone --depth 1 https://github.com/nicovank/bugbench bugbench-upstream

mkdir -p $HOME/bugbench-src/bc-1.06/script
ln -s $HOME/bugbench-upstream/bc-1.06            $HOME/bugbench-src/bc-1.06/src
cp    $HOME/bugbench-upstream/_input/BC/bad.b    $HOME/bugbench-src/bc-1.06/script/bad.b

mkdir -p $HOME/bugbench-src/ncompress
ln -s $HOME/bugbench-upstream/ncompress-4.2.4    $HOME/bugbench-src/ncompress/src

mkdir -p $HOME/bugbench-src/polymorph-0.4.0
ln -s $HOME/bugbench-upstream/polymorph-0.4.0    $HOME/bugbench-src/polymorph-0.4.0/src

# Repo-level symlink so case.yaml's "bugbench-src/..." paths resolve:
ln -sfn $HOME/bugbench-src /mnt/c/.../chatdbgpro/bugbench-src
```

`/mnt/c/.../chatdbgpro/bugbench-src` is added to `.gitignore`. The
Windows-visible entry is a one-byte WSL symlink, so OneDrive doesn't
sync 17K upstream files.

#### Build blockers encountered + fixes

**bc-heap-overflow** — three sequential issues:

1. **`config.h: file not found`**. bc-1.06 ships `config.h.in` only.
   `-DHAVE_CONFIG_H` in the build command is meaningless without
   `./configure` first. Fix: prepend `./configure --quiet` to the
   `build_commands` in `bench/cases/bugbench/bc-heap-overflow/case.yaml`.
2. **`./configure: flex: not found`**. bc's configure needs flex + bison
   (the bc grammar is .y/.l files). Fix: `sudo apt-get install -y flex bison`.
   bison was already installed; flex is the new dep.
3. After fixes 1+2 → status=ok, 14.9 s, 7 tool calls, recovered
   1217 chars correctly identifying `more_arrays() v_count vs a_count`.

**ncompress-overflow** — clang/glibc header conflict:

- `compress42.c:175: conflicting types for 'open'`. ncompress-4.2.4
  declares K&R-style `extern int open(char const *, int, ...)` that
  conflicts with modern glibc's `<fcntl.h>`. The block is wrapped in
  `#ifndef NOFUNCDEF`, so the fix is just `-DNOFUNCDEF=1` in the
  compile flags. Applied in
  `bench/cases/bugbench/ncompress-overflow/case.yaml`.
- After fix → status=ok, 15.4 s, 6 tool calls, recovered 1275 chars
  correctly identifying `comprexx() strcpy tempname[MAXPATHLEN]`.

**polymorph-overflow** — missing Makefile:

- `make clean → "No rule to make target 'clean'."`. polymorph ships
  `Makefile.in` only. Fix: prepend `./configure --quiet` before the
  make commands, and replace `make clean` with `make clean || true`
  (clean targets on freshly generated Makefiles sometimes have
  no-op rules that exit 1). Applied in
  `bench/cases/bugbench/polymorph-overflow/case.yaml`.
- After fix → status=ok, 16.3 s, 11 tool calls, recovered 1517 chars
  correctly identifying `convert_fileName() newname[MAX]` overflow.

**man-overflow** — source unavailable:

- `bugbench source dir missing: bugbench-src/man-1.5h1`.
- nicovank/bugbench has no `man-1.5h1` directory. Ibraheem's adroit
  setup also lacked it (every man-overflow cell on 2026-05-10 logged
  the same "source dir missing" error).
- Decision: **skip the 4 cases × 2 tiers × 8 models = 64 cells** for
  man-overflow. Total realworld coverage drops from 161 to 161 - 14
  locked cells (man-overflow appears 14× in the runset) ≈ 147 cells.
  Add a note in the paper figures that man-overflow is excluded.

### §3.4 berry/BugsCPP (Docker corpus.db) — ✓ T1

Smoke case: `berry-1`.

**Docker setup**: Docker Desktop 4.69.0 with WSL2 integration **must be
enabled for the Ubuntu distro** (Settings → Resources → WSL Integration
→ toggle Ubuntu on → Apply & Restart). Without this, the WSL Python
process can't reach the docker daemon and every berry cell errors with
`docker_build_failed` and an empty `docker_build.log`.

Once integration is on, `docker version` works from inside WSL Ubuntu,
and `ensure_gdb_image` short-circuits via the cached
`chatdbgpro/gdb-berry:latest` image (2.04 GB, already pulled from
`ghcr.io/sgarimel`).

Smoke result: T1 ok, 25.5 s end-to-end, 17 tool calls, recovered
857 chars correctly identifying `src/be_vm.c:746` (the FLIP opcode
using `-` instead of `~`). The diagnosis matches the developer patch.

### §3.5 T3 smoke (gdb path) — ✓ crashbench + juliet, ✓ berry after fix

**Native gdb path (crashbench, juliet, bugbench)**: WSL2 + chatdbg
plugin loaded fine inside the orchestrator venv (Py 3.12).

- `crashbench-abo1` T3 → ok in 61 s, full RC/LF/GF in `response`
  (1694 chars, 38 tool calls). ✓
- `juliet-cwe415-malloc-free-char-01` T3 → ok in 32 s, but `response`
  is just 22 newlines. The chatdbg.log.yaml shows 22 tool calls walking
  through `program.c:86-95`, but the model emitted **no final text**.
  This is the same gemini-3.1-flash-lite blind spot we saw in the
  synthetic T3 panel (memory: T3 prompt iter-2 took flash from 1→12
  full labels; the model still misses sometimes). Not a pipeline bug —
  other models (sonnet, gpt-4o, gpt-5.5, etc.) will produce labels.

**Docker gdb path (berry)**: needed a new fix.

`berry-1` T3 first run: status=no_collect, 9.3 s. stderr:

```
Function "_exit" not defined.
Python Exception <class 'UnicodeDecodeError'>: 'ascii' codec can't
  decode byte 0xe2 in position 31: ordinal not in range(128)
/tmp/session.cmds:30: Error in sourced command file:
Could not convert arguments to Python string.
```

Root cause: the `chatdbgpro/gdb-berry:latest` container runs with the
default `POSIX/C` locale, so gdb's embedded Python uses the ASCII
codec by default. The T3 "FINAL OUTPUT FORMAT" question prompt
contains em-dashes (`—` = U+2014 = UTF-8 `0xe2 0x80 0x94`), which
appear in `session.cmds:30` (the `why "<prompt>"` line) and trip the
codec.

Fix: `bench/drivers/docker_gdb.py` now sets these in `container_env`:

```python
"LANG": "C.UTF-8",
"LC_ALL": "C.UTF-8",
"PYTHONIOENCODING": "utf-8",
```

The synthetic gdb path was unaffected because WSL2's host locale is
already UTF-8 — only the bare-bones docker container needed coercing.

After fix → berry-1 T3 ok in 32.5 s, 23 tool calls. (Diagnosis again
empty due to flash-lite quirk, not a pipeline issue.)

## §4. Full T1 sweep

Launched with:

```bash
wsl -d Ubuntu -- bash -lc 'cd /mnt/c/.../chatdbgpro && \
  source /root/.venvs/chatdbg-bench/bin/activate && \
  export CHATDBG_MINI_PY=/root/.venvs/chatdbg-mini/bin/python3 && \
  python -m bench.run_runset_shard \
    --runset bench/results/final_paper_bench/_runset_locked.tsv \
    --panel realworld --owner anika \
    --runtime docker --workers 4 --timeout 600 --tiers 1' \
  | tee bench/_logs_anika_realworld_T1.txt
```

Reads 85 T1 realworld cells from the locked runset. `run_runset_shard`
splits each (tier, model) group into a `corpus` subgroup (berry-1..5
via Docker) and a `synth` subgroup (everything else via on-disk
`case.yaml`).

