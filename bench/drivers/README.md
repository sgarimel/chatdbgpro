# DockerDriver — Running ChatDBG inside BugsCPP containers

## Overview

The DockerDriver lets the orchestrator run ChatDBG at any tier inside a BugsCPP Docker container. Each BugsCPP bug ships as a Docker image (`bugscpp/<project>:<index>`) with the buggy codebase pre-built. The driver bind-mounts ChatDBG source and a results directory into the container, runs GDB with ChatDBG loaded, and `collect.json` appears on the host when the container exits.

This builds on top of Anika's pipeline PR (#2) which provides:
- `docker/gdb-base.Dockerfile` — parameterized Dockerfile that adds gdb to any BugsCPP base image
- `scripts/ensure_gdb_image.py` — idempotent builder for `chatdbgpro/gdb-<project>:latest` images
- `scripts/utils.py:gdb_image_for()` — helper that returns the image tag for a project

The DockerDriver is the bridge from the **corpus pipeline** (checkout, build, crash filter) to the **benchmarking pipeline** (run ChatDBG, collect results, judge).

## Architecture

```
Host                                    Container (chatdbgpro/gdb-<project>)
─────────────────────────────────────   ─────────────────────────────────────
ChatDBG/src/  ──bind-mount──────────>   /chatdbg-src/     (PYTHONPATH)
data/workspaces/<proj>-<idx>/  ─────>   /work/            (cwd, buggy source)
bench/results/<name>/<run_id>/ ─────>   /results/         (collect.json output)
OPENROUTER_API_KEY  ── -e ──────────>   env var passthrough
```

The tier (1/2/3) determines which tool config the model sees, not where execution happens. All tiers run inside the same container.

## Files

| File | Role |
|------|------|
| `docker/gdb-base.Dockerfile` | Parameterized Dockerfile (from Anika's PR #2). Takes `ARG BASE_IMAGE`, adds gdb + libtool. |
| `scripts/ensure_gdb_image.py` | Builds `chatdbgpro/gdb-<project>:latest` on demand (from PR #2). Supports `--all` to build all 22 project images. |
| `bench/drivers/docker_gdb.py` | `DockerDriver` class implementing the `Driver` protocol. Handles workspace validation, image building (via `ensure_gdb_image`), trigger command parsing, GDB script generation, `docker run` invocation, and result collection. |
| `bench/common.py` | `DockerCase` dataclass (loaded from corpus.db) and `discover_docker_cases()` — the Docker equivalent of `Case` / `discover_cases()`. |

## Setup for Anika

### Prerequisites

1. **Docker running** on an x86_64 Linux machine (the BugsCPP images are amd64-only — they don't work under Rosetta on Apple Silicon).
2. **Clone the repo** and install deps:
   ```
   git clone https://github.com/sgarimel/chatdbgpro.git && cd chatdbgpro/ChatDBG
   python3 -m venv .venv && source .venv/bin/activate
   pip install -e . && pip install pyyaml gitpython tqdm
   ```
3. **Clone BugsCPP** adjacent to the ChatDBG repo:
   ```
   git clone https://github.com/Suresoft-GLaDOS/bugscpp.git ../bugscpp
   ```
4. **Set API key** in `.env` at repo root:
   ```
   OPENROUTER_API_KEY=sk-or-...
   ```
5. **Build all gdb Docker images** (one-time, ~10 min):
   ```
   python scripts/ensure_gdb_image.py --all
   ```
6. **Seed the corpus DB and run the pipeline** (checkout + build + crash filter):
   ```
   cd scripts && python seed_db.py && python build_filter.py --workers 4 && python crash_filter.py --workers 4 && python extract_crash_location.py --workers 4 && python extract_patches.py --workers 4 && python finalize_corpus.py && cd ..
   ```

### Running ChatDBG benchmarks

Single bug, one model:
```
.venv/bin/python3 bench/orchestrator.py --docker --bug-ids jerryscript-1 --models openrouter/nvidia/nemotron-3-nano-30b-a3b --tool-configs tier3_gdb_only.json --tiers 3 --name docker-jerry1
```

Multiple bugs, both study models:
```
.venv/bin/python3 bench/orchestrator.py --docker --bug-ids jerryscript-1 jerryscript-2 jerryscript-3 --models openrouter/nvidia/nemotron-3-nano-30b-a3b openrouter/qwen/qwen3-30b-a3b-instruct-2507 --tool-configs tier3_gdb_only.json --tiers 3 --name docker-jerry-both
```

All corpus cases with trigger commands:
```
.venv/bin/python3 bench/orchestrator.py --docker --models openrouter/nvidia/nemotron-3-nano-30b-a3b openrouter/qwen/qwen3-30b-a3b-instruct-2507 --tool-configs tier3_gdb_only.json --tiers 3 --name docker-full-corpus
```

Dry run (validates case discovery + image build, skips GDB):
```
.venv/bin/python3 bench/orchestrator.py --docker --bug-ids jerryscript-1 --models openrouter/nvidia/nemotron-3-nano-30b-a3b --tool-configs tier3_gdb_only.json --dry-run --name docker-dryrun
```

### Orchestrator flags for Docker mode

| Flag | Description |
|------|-------------|
| `--docker` | Cases come from corpus.db, runs happen inside containers |
| `--db PATH` | Path to corpus.db (default: `data/corpus.db`) |
| `--bug-ids ID [ID ...]` | Filter which bugs to run (e.g. `libtiff-2 jerryscript-1`) |

All other flags (`--models`, `--tool-configs`, `--tiers`, `--trials`, `--timeout`, `--name`, `--dry-run`) work the same.

## Output

Results land in `bench/results/<name>/<run_id>/`:

```
bench/results/docker-jerry1/
  jerryscript-1__tier3__...__tier3_gdb_only__ctx10__t1/
    collect.json          # ChatDBG session data — main output for LLM judge
    result.json           # run metadata (status, elapsed, model, tier)
    tool_config.json      # copy of tool config used
    stdout.log            # container stdout
    stderr.log            # container stderr
    chatdbg.log.yaml      # ChatDBG internal log
  index.json              # summary of all runs
```

`collect.json` contains: model's diagnosis text, proposed code fixes, every debugger tool call made, token counts, and timing. This is what the LLM judge (step 7) scores against the ground truth in corpus.db.

## How it works inside the container

1. `LD_LIBRARY_PATH` is set to include all `.libs/` directories (libtool projects).
2. Libtool wrapper scripts are resolved to real ELFs under `.libs/`.
3. A GDB session script loads `chatdbg_gdb.py`, runs the buggy binary, asks `why`.
4. ChatDBG calls the LLM (OpenRouter), the LLM issues GDB tool calls to debug.
5. `CHATDBG_COLLECT_DATA=/results/collect.json` writes output to the bind-mounted results dir.

## Known limitations

- **amd64 only.** The BugsCPP Docker images don't work on Apple Silicon / arm64. Run on a Linux x86_64 machine.
- **Base images lack gdb.** `docker/gdb-base.Dockerfile` layers gdb on top. `ensure_gdb_image.py --all` builds 22/23 projects (yaml_cpp fails — its base image isn't on Docker Hub).
- **Workspace checkout is separate.** If the workspace is missing, the run returns `status: workspace_missing`. Run the pipeline scripts first.
- **ChatDBG Python deps.** The gdb-base Dockerfile only installs gdb + libtool, not ChatDBG's Python deps (litellm, openai, etc.). These are picked up from the bind-mounted source via PYTHONPATH. If a dep is missing inside the container, you may need to extend the Dockerfile or pip install at runtime.
