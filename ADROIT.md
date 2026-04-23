# Running ChatDBG Pro on Adroit (Princeton HPC)

## Why Adroit

The BugsCPP Docker images are linux/amd64 only. They don't work on macOS Apple Silicon (Rosetta emulation breaks shared libraries). Adroit is native x86_64 Linux, so everything runs natively.

## One-time setup

### 1. SSH in

```
ssh <netid>@adroit.princeton.edu
```

### 2. Install Claude Code (optional, for interactive dev)

```
curl -fsSL https://claude.ai/install.sh | bash
```

First auth requires a browser. Either:
- SSH with port forwarding: `ssh -L 8080:localhost:8080 <netid>@adroit.princeton.edu`
- Or auth on your laptop first, then copy `~/.claude/` to Adroit

### 3. Clone the repo

```
git clone https://github.com/sgarimel/chatdbgpro.git && cd chatdbgpro/ChatDBG
```

### 4. Set up Python environment

```
module load anaconda3
python -m venv .venv && source .venv/bin/activate
pip install -e . && pip install pyyaml gitpython tqdm
```

### 5. Clone BugsCPP

```
git clone https://github.com/Suresoft-GLaDOS/bugscpp.git ../bugscpp
```

### 6. API key

```
echo "OPENROUTER_API_KEY=sk-or-..." > .env
```

## Docker vs Singularity

Adroit likely does **not** allow Docker (most HPC clusters don't for security reasons). Check:

```
which docker && docker info
```

If Docker is not available, you need **Singularity/Apptainer** instead. Convert Docker images:

```
module load singularity
singularity pull docker://hschoe/defects4cpp-ubuntu:jerryscript
```

This creates a `.sif` file. The DockerDriver would need to be adapted to use `singularity exec` instead of `docker run`. The bind-mount syntax is similar:

```
singularity exec --bind $(pwd)/data/workspaces/jerryscript-1/jerryscript/buggy-1:/work --bind $(pwd)/src:/chatdbg-src --bind $(pwd)/bench/results/run1:/results jerryscript.sif bash -c '...'
```

**If Docker IS available** (some clusters have it on specific nodes), skip Singularity and follow the standard pipeline below.

## Running the pipeline

### Build gdb Docker images (one-time, ~10 min)

```
python scripts/ensure_gdb_image.py --all
```

### Seed and run the corpus pipeline

```
cd scripts && python seed_db.py && python build_filter.py --workers 4 && python crash_filter.py --workers 4 && python extract_crash_location.py --workers 4 && python extract_patches.py --workers 4 && python finalize_corpus.py && cd ..
```

### Run ChatDBG benchmarks

Smoke test (single bug, single model):
```
.venv/bin/python3 bench/orchestrator.py --docker --bug-ids jerryscript-1 --models openrouter/nvidia/nemotron-3-nano-30b-a3b --tool-configs tier3_gdb_only.json --tiers 3 --name adroit-smoke
```

Full corpus, both models:
```
.venv/bin/python3 bench/orchestrator.py --docker --models openrouter/nvidia/nemotron-3-nano-30b-a3b openrouter/qwen/qwen3-30b-a3b-instruct-2507 --tool-configs tier3_gdb_only.json --tiers 3 --name adroit-full-corpus
```

### Running as a Slurm job

For long runs, submit as a batch job so it doesn't die when your SSH session ends:

```
sbatch <<'EOF'
#!/bin/bash
#SBATCH --job-name=chatdbg-bench
#SBATCH --time=04:00:00
#SBATCH --mem=8G
#SBATCH --cpus-per-task=4
#SBATCH --output=logs/chatdbg-bench-%j.log

module load anaconda3
source .venv/bin/activate

.venv/bin/python3 bench/orchestrator.py --docker --models openrouter/nvidia/nemotron-3-nano-30b-a3b openrouter/qwen/qwen3-30b-a3b-instruct-2507 --tool-configs tier3_gdb_only.json --tiers 3 --name adroit-full-$(date +%Y%m%d)
EOF
```

Check status with `squeue -u <netid>`, logs in `logs/`.

## Results

All output lands in `bench/results/<name>/`. Each run produces:
- `collect.json` — ChatDBG session data (diagnosis, tool calls, tokens, timing)
- `result.json` — run metadata (status, model, tier, elapsed time)
- `index.json` — summary of all runs in the batch

Copy results back to your laptop:
```
scp -r <netid>@adroit.princeton.edu:~/chatdbgpro/ChatDBG/bench/results/<name> bench/results/
```

## Project context

This is a COS 484 research project. We're comparing how well different LLMs debug C/C++ programs using ChatDBG (an AI-powered GDB assistant). The study has three tiers:

| Tier | Tools | Config |
|------|-------|--------|
| 1 | bash only | mini-swe-agent (not yet built) |
| 2 | bash + gdb | `tier2_bash_plus_gdb.json` (not yet built) |
| 3 | gdb only | `tier3_gdb_only.json` (working) |

Two model families being compared:
- `openrouter/nvidia/nemotron-3-nano-30b-a3b` — fires near-zero tool calls, pure text reasoning
- `openrouter/qwen/qwen3-30b-a3b-instruct-2507` — actively debugs with 7-14 tool calls

The pipeline: build buggy program in Docker -> run ChatDBG (model debugs via GDB) -> collect.json -> LLM judge scores diagnosis against ground truth.

What's done: tier 3 driver (native + Docker), 8 synthetic cases verified, 1 injected case (cJSON) verified, 31 BugsCPP cases with triggers in corpus.db.

What's left: tier 1/2 drivers, scoring harness (LLM judge), full corpus run, paper figures.
