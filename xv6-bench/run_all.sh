#!/bin/bash
# run_all.sh — Run all 3 xv6 bugs across all 4 models.
#
# Usage:  cd chatdbgpro/xv6-bench && bash run_all.sh
# Prereq: Docker running, OPENROUTER_API_KEY set, ~4GB free disk
#
# Steps:
#   1. Build Docker image (RISC-V toolchain + QEMU + GDB)
#   2. For each bug: build xv6, boot QEMU, capture panic via GDB
#   3. For each (bug, model): send crash context to LLM
#   4. Run judge on all results

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

MODELS=(
    "openrouter/openai/gpt-4o"
    "openrouter/meta-llama/llama-3.1-8b-instruct"
    "openrouter/nvidia/nemotron-3-nano-30b-a3b"
    "openrouter/qwen/qwen3-30b-a3b-instruct-2507"
)

BUGS=(
    "bug1-uvmcopy-perm"
    "bug2-pipewrite-off-by-one"
    "bug3-kalloc-double-link"
)

RUN_NAME="xv6-run-$(date +%Y%m%d_%H%M%S)"
RESULTS_DIR="${SCRIPT_DIR}/results/${RUN_NAME}"
IMAGE_TAG="xv6-bench:latest"
TIMEOUT=90

echo "============================================"
echo "  xv6-bench: Novel Kernel Debugging Benchmark"
echo "============================================"
echo "Runs: $(( ${#MODELS[@]} * ${#BUGS[@]} )) (${#BUGS[@]} bugs x ${#MODELS[@]} models)"
echo "Output: ${RESULTS_DIR}"
echo ""

[ -z "${OPENROUTER_API_KEY:-}" ] && echo "ERROR: OPENROUTER_API_KEY not set" && exit 1

# ── Step 1: Docker image ──────────────────────────────────────────
echo "[1/4] Building Docker image..."
docker build --platform linux/amd64 -t "${IMAGE_TAG}" . 2>&1 | tail -3
echo ""

# ── Step 2: Build + capture crash state (once per bug) ────────────
echo "[2/4] Building xv6 with each bug and capturing crash states..."
mkdir -p "${RESULTS_DIR}"

for BUG in "${BUGS[@]}"; do
    TRIGGER=$(python3 -c "
import yaml
with open('bugs/${BUG}.yaml') as f: print(yaml.safe_load(f)['trigger'])")

    echo "  Building & capturing: ${BUG} (trigger: ${TRIGGER})..."

    docker run --rm --platform linux/amd64 \
        -v "${SCRIPT_DIR}/xv6-riscv:/xv6/xv6-riscv:ro" \
        -v "${SCRIPT_DIR}/bugs:/xv6/bugs:ro" \
        -v "${SCRIPT_DIR}/trigger-programs:/xv6/trigger-programs:ro" \
        -v "${SCRIPT_DIR}/scripts:/xv6/scripts:ro" \
        -v "${RESULTS_DIR}:/xv6/results" \
        "${IMAGE_TAG}" \
        bash -c "
            chmod +x /xv6/scripts/*.sh
            bash /xv6/scripts/build_bug.sh \
                '${BUG}' '/xv6/bugs/${BUG}.patch' \
                '/xv6/trigger-programs/${TRIGGER}.c'
            bash /xv6/scripts/run_qemu_gdb.sh \
                '${BUG}' '${TRIGGER}' \
                '/xv6/results/crash_state_${BUG}' '${TIMEOUT}'
        " 2>&1 | tee "${RESULTS_DIR}/capture_${BUG}.log"
done
echo ""

# ── Step 3: LLM evaluation (each bug × each model) ───────────────
echo "[3/4] Running LLM evaluations..."

for BUG in "${BUGS[@]}"; do
    for MODEL in "${MODELS[@]}"; do
        MODEL_SLUG="${MODEL//\//_}"
        echo "  ${BUG} × $(basename ${MODEL})..."

        docker run --rm --platform linux/amd64 \
            -v "${SCRIPT_DIR}/xv6-riscv:/xv6/xv6-riscv:ro" \
            -v "${SCRIPT_DIR}/bugs:/xv6/bugs:ro" \
            -v "${SCRIPT_DIR}/trigger-programs:/xv6/trigger-programs:ro" \
            -v "${SCRIPT_DIR}/scripts:/xv6/scripts:ro" \
            -v "${RESULTS_DIR}:/xv6/results" \
            -e "OPENROUTER_API_KEY=${OPENROUTER_API_KEY}" \
            "${IMAGE_TAG}" \
            python3 /xv6/scripts/run_xv6_bench.py \
                --bug "${BUG}" --model "${MODEL}" \
                --skip-build --skip-qemu \
                --results-dir /xv6/results \
            2>&1 | tee "${RESULTS_DIR}/llm_${BUG}__${MODEL_SLUG}.log"
    done
done
echo ""

# ── Step 4: Judge ─────────────────────────────────────────────────
echo "[4/4] Running judge..."
cd "${SCRIPT_DIR}/.."
python3 bench/judge.py --results-dir "${RESULTS_DIR}" 2>&1 | tee "${RESULTS_DIR}/judge.log"

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  Results: ${RESULTS_DIR}"
echo "============================================"
for d in "${RESULTS_DIR}"/xv6-bug*; do
    [ -f "$d/score.json" ] || continue
    echo "  $(basename $d):"
    python3 -c "
import json
with open('$d/score.json') as f: s = json.load(f)
sc = s.get('scores',{})
print(f'    RC={sc.get(\"root_cause\",\"?\")}  LF={sc.get(\"local_fix\",\"?\")}  GF={sc.get(\"global_fix\",\"?\")}')"
done
