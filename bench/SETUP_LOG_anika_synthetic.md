# Setup log — Anika synthetic-panel runner (WSL2 Ubuntu)

Owner: Anika · Branch: `push/local-runs-anika` · Started: 2026-05-10

This file is the **canonical reproducibility record** for getting the
synthetic panel runnable on Anika's machine. Every command that touches
the environment is logged here verbatim, including what failed and how
it was fixed. Pass this file (or its committed copy on
`push/local-runs-anika`) to any future Claude/teammate session that
needs to mirror the setup — Adroit Linux included, with the small
deltas called out in §"Adroit deltas".

Companion files this log refers to:
- `bench_execution_plan.md` — overall plan
- `bench/RUNNER_HANDOFF_anika.md` — original handoff (slightly out of date; see §1)
- `bench/RUNNER_HANDOFF_ibraheem.md` — Adroit handoff
- `bench/results/final_paper_bench/_runset_locked.tsv` — work list

---

## §0. Host context

- Windows 11 Home 10.0.26200, default WSL distro `docker-desktop` (helper),
  user-facing Linux distro `Ubuntu` (WSL2, kernel 6.6.87.2-microsoft-standard).
- Repo lives in OneDrive: `C:\Users\Owner\OneDrive\Documents\Classes\COS\COS484\chatdbgpro`.
- Inside WSL Ubuntu the same repo is reachable at
  `/mnt/c/Users/Owner/OneDrive/Documents/Classes/COS/COS484/chatdbgpro`.
- Native Windows venv `chatdbg-eval-env/` (Windows Python). Used only for
  the pure-Python helper scripts in §2 (audit_bound_cells, build_runset).
  All actual sweep runs go through the new Linux venv set up below.

## §1. Pivot rationale (why WSL2, not native Windows, not Docker)

Plan-doc `bench/RUNNER_HANDOFF_anika.md` says use docker via parallel_run.
Two issues forced a pivot:

1. **Synthetic case ids are not in corpus.db.** parallel_run.py's
   `--docker --bug-ids` path goes through `discover_docker_cases`,
   which queries SQLite. The 20 synthetic case ids
   (`cjson-parse-string-oob`, `test-overflow`, etc.) live as on-disk
   `case.yaml` manifests under `bench/cases/` and aren't in the DB.
   Result: every shard call would return "no cases match the filter".

   Fix landed in this branch: `parallel_run.py` got a `--no-docker`
   flag and `run_runset_shard.py` auto-passes it for `--panel synthetic`.
   Now synthetic shards route through `orchestrator --cases` (on-disk
   discovery), which doesn't need Docker at all.

2. **Native Windows lacks a C/C++ compiler and a POSIX bash.** Smoke test
   on Windows died at `compile_case` with `FileNotFoundError` because
   `clang` is not on PATH. Even with a compiler installed, mini-swe-agent's
   bash sandbox expects POSIX bash, and tier-3 (gdb) breaks on Windows
   anyway because the persistent gdb session uses `select.select` over
   POSIX pipe FDs (project memory: `project_windows_bench_blockers.md`).

   Fix: run inside WSL2 Ubuntu, which has gcc 13 + clang 18 + python 3.12
   pre-installed and behaves like native Linux for everything mini-swe-agent
   and the gdb driver expect.

## §2. Pre-flight done on Windows (already complete)

These three steps ran natively on Windows in `chatdbg-eval-env\` (no Linux
deps required) and are pushed to `push/local-runs-anika`:

```powershell
# Build the bound-cell parity list
.\chatdbg-eval-env\Scripts\python.exe -m bench.audit_bound_cells `
    --provenance bench/results/final_paper_bench/_provenance.json `
    --archive    bench/results/archive `
    --out        bench/results/final_paper_bench/_bound_cells.csv
# -> 275 provenance entries scanned, 5 bound

# Lock the runset
.\chatdbg-eval-env\Scripts\python.exe -m bench.build_runset `
    --missing-synthetic bench/results/final_paper_bench/_missing_synthetic.txt `
    --missing-realworld bench/results/final_paper_bench/_missing_realworld.txt `
    --bound-csv         bench/results/final_paper_bench/_bound_cells.csv `
    --out               bench/results/final_paper_bench/_runset_locked.tsv
# -> 370 cells: synthetic 209 (T1=128 + T3=81) + realworld 161 (T1=85 + T3=76)

# Push so Ibraheem can pick up the runset
bash bench/sync_results_to_repo.sh `
    bench/results/final_paper_bench/_runset_locked.tsv `
    bench/results/final_paper_bench/_bound_cells.csv
# -> commit fc6385ac
```

## §3. WSL2 Ubuntu environment build

Goal: a Linux Python 3.12 venv with:
- editable install of this repo (`pip install -e .`)
- `mini-swe-agent` (>= 2.2.8)
- `litellm`, `pyyaml`, `gitpython`, `tqdm`, `python-dotenv`

### Venv location

**The venv lives at `$HOME/.venvs/chatdbg-bench`, NOT inside the repo.**

First attempt put it at `<repo>/.venv-bench/` to match the handoff path,
but pip install on /mnt/c (OneDrive-tracked NTFS via the WSL FS proxy)
was unusably slow — `ensurepip --upgrade` alone burned >60 s of CPU and
hadn't finished. Killed that, removed the half-built venv, switched to
`$HOME/.venvs/chatdbg-bench` (native ext4 inside WSL2), and reran.

The path is overridable via `CHATDBG_VENV` env var. The orchestrator's
tier-1 driver finds the Python via `CHATDBG_MINI_PY`
(`bench/drivers/tier1_minisweagent.py:52`); the wrapper script
`bench/run_synthetic_with_venv.sh` exports both before invoking the
shard runner.

Adroit note: the same `$HOME/.venvs/chatdbg-bench` default is fine on
Adroit; $HOME is native and fast there. No deltas needed.

### Tooling probe (Ubuntu inside WSL2)

```
$ uname -a
Linux ANIKA-SURFACE-STUDIO-2 6.6.87.2-microsoft-standard-WSL2 #1 SMP PREEMPT_DYNAMIC Thu Jun  5 18:30:46 UTC 2025 x86_64 x86_64 x86_64 GNU/Linux
$ python3 --version
Python 3.12.3
$ gcc --version | head -1
gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
$ clang --version | head -1
Ubuntu clang version 18.1.3 (1ubuntu1)
$ dpkg -l python3-venv | tail -1
ii  python3-venv  3.12.3-0ubuntu2.1  amd64  venv module for python3
```

System python3 doesn't ship pip, but the `python3-venv` apt package
includes `ensurepip` so `python3 -m venv .venv-bench` boots pip into
the venv at create time. No further apt installs needed.

### Setup driver

`bench/setup_wsl_venv.sh` is the one-shot installer. Idempotent —
re-running just refreshes deps. Reproducible on Adroit.

```
wsl -d Ubuntu -e bash -lc \
  "cd /mnt/c/.../chatdbgpro && bash bench/setup_wsl_venv.sh 2>&1 \
   | tee bench/_logs_setup_wsl_venv.txt"
```

After install:

- venv at `$HOME/.venvs/chatdbg-bench` (~600 MB once full)
- `bench/run_synthetic_with_venv.sh` is the runtime entry point —
  sources the venv, exports `CHATDBG_MINI_PY`, runs `bench.run_runset_shard`
  with whatever args you pass.

## §4. Live install transcript

Appended as events land. Each section: exact commands, relevant output,
status.

### §4.1 Setup attempts

- **Attempt 1 — venv at `<repo>/.venv-bench/` on /mnt/c.** Aborted ~60 s in
  during `ensurepip --upgrade`. /mnt/c FS proxy too slow for thousands
  of small site-packages writes. Removed half-built venv, switched
  default to `$HOME/.venvs/chatdbg-bench`.
- **Attempt 2 — single venv at `$HOME/.venvs/chatdbg-bench`.** Failed at
  the dependency resolver: `mini-swe-agent>=2.2.8` requires
  `litellm>=1.75.5`, but `pyproject.toml` pins `litellm==1.55.9`. The
  driver design already anticipates this (see
  `bench/drivers/tier1_minisweagent.py:8-19` — two-venv split is the
  intended architecture). Splitting into:
    - `$HOME/.venvs/chatdbg-bench` — orchestrator (chatdbg + litellm 1.55.9)
    - `$HOME/.venvs/chatdbg-mini`  — mini-swe-agent runner (litellm 1.83.x)
  Driver crosses between them via `$CHATDBG_MINI_PY` env var.
- **Attempt 3 — two venvs.** Both venvs built clean. Smoke import via
  `from bench.drivers import tier1_minisweagent as t1; t1._resolve_mini_py()`
  resolved `/root/.venvs/chatdbg-mini/bin/python3` (exists=True).
  `import minisweagent` ok inside the mini venv. Final sizes:
  orch ~540 MB, mini ~370 MB.

### §4.2 Smoke test — one synthetic T1 cell

```bash
wsl -d Ubuntu -e bash -lc "
  cd /mnt/c/.../chatdbgpro &&
  source /root/.venvs/chatdbg-bench/bin/activate &&
  export CHATDBG_MINI_PY=/root/.venvs/chatdbg-mini/bin/python3 &&
  python -m bench.orchestrator \
      --models openrouter/google/gemini-3.1-flash-lite-preview \
      --tool-configs bench/configs/tier1_bash_only.json \
      --tiers 1 --trials 1 --timeout 600 \
      --name anika-smoke-synthetic-T1-2026-05-10 \
      --skip-existing --cases test-overflow"
```

Result: `status=ok`, `elapsed_s=36.053`, model produced a valid
ROOT CAUSE / LOCAL FIX / GLOBAL FIX response after 7 tool calls. Cell
artifacts (case.yaml, program.cpp, build/, compile.log, prog_asan,
collect.json, result.json, session.cmds, stdout.log, stderr.log,
task.md, trajectory.json) all landed.

The synthetic-panel pipeline is unblocked.

## §5. Adroit deltas (for Ibraheem's Claude session)

Anika's WSL2 setup is reproducible on Adroit Linux with two small
changes only — the rest is identical:

1. **Repo path**: replace `/mnt/c/.../chatdbgpro` with whatever Adroit
   absolute path Ibraheem cloned to (likely `~/chatdbgpro` or
   `/scratch/.../chatdbgpro`). Everything below is path-relative.
2. **Compiler module**: Adroit may need `module load gcc` or similar
   before `bash bench/setup_wsl_venv.sh` succeeds. The script's tool
   probe will fail loudly with `FATAL: gcc not on PATH` if so.

Everything else (dual-venv layout, `CHATDBG_MINI_PY`, the wrapper
`bench/run_synthetic_with_venv.sh`, the parallel_run + run_runset_shard
patches that route synthetic through `--no-docker`) is portable.

Note Ibraheem's slice is **realworld** (Docker/apptainer + corpus.db),
not synthetic, so he won't actually need the mini venv. But if he ever
wants to mirror Anika's synthetic runs on Adroit (e.g. for verification),
the same three commands work:

```bash
bash bench/setup_wsl_venv.sh     # builds both venvs
bash bench/run_synthetic_with_venv.sh \
    --runset bench/results/final_paper_bench/_runset_locked.tsv \
    --panel synthetic --owner ibraheem --runtime docker \
    --workers 8 --timeout 600
```

## §6. State at end of setup

Files added/modified in this session, all tracked under
`push/local-runs-anika`:

- `bench/audit_bound_cells.py` (input — was on push pre-session)
- `bench/build_runset.py` (input)
- `bench/run_runset_shard.py` ← **patched**: auto-pass `--no-docker`
  when `--panel synthetic`
- `bench/parallel_run.py` ← **patched**: new `--no-docker` flag swaps
  `--docker --bug-ids` for `--cases` and drops `--runtime`
- `bench/setup_wsl_venv.sh` ← **new**: idempotent two-venv installer
- `bench/run_synthetic_with_venv.sh` ← **new**: wrapper that activates
  the orch venv, exports `CHATDBG_MINI_PY`, exec's `bench.run_runset_shard`
- `bench/SETUP_LOG_anika_synthetic.md` ← **this file**
- `bench/results/final_paper_bench/_bound_cells.csv` (input)
- `bench/results/final_paper_bench/_runset_locked.tsv` (input)
- `bench/_logs_setup_wsl_venv.txt` ← **transcript** (gitignored if too noisy)



