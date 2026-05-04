#!/bin/bash
# run_ablation.sh — Run tier1 (LLDB only) and tier2 (LLDB+bash) on all 3 bugs × 4 models.
#
# Usage: cd xv6-bench && bash run_ablation.sh
# Prereqs: brew install qemu riscv64-elf-gcc, OPENROUTER_API_KEY set
#
# Produces: results/xv6-ablation-<timestamp>/
#   <bug_id>__<model>__<tier>/
#     case.yaml, collect.json, result.json, kernel/<source>.c, lldb_stdout.log

set -uo pipefail
# Don't use -e: lldb/kill may return non-zero and that's OK
cd "$(dirname "$0")"

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

TIERS=("tier1_lldb_only" "tier2_lldb_plus_bash")

RUN_NAME="xv6-ablation-$(date +%Y%m%d_%H%M%S)"
RESULTS_DIR="$(pwd)/results/${RUN_NAME}"
CHATDBG_SRC="$(pwd)/../src"
QEMU_PORT=1234
TIMEOUT=180  # per-run timeout in seconds

[ -z "${OPENROUTER_API_KEY:-}" ] && echo "ERROR: OPENROUTER_API_KEY not set" && exit 1

TOTAL=$(( ${#BUGS[@]} * ${#MODELS[@]} * ${#TIERS[@]} ))
echo "============================================"
echo "  xv6-bench ablation"
echo "============================================"
echo "Bugs:   ${#BUGS[@]}"
echo "Models: ${#MODELS[@]}"
echo "Tiers:  ${#TIERS[@]} (tier1=lldb-only, tier2=lldb+bash)"
echo "Total:  ${TOTAL} runs"
echo "Output: ${RESULTS_DIR}"
echo ""

mkdir -p "${RESULTS_DIR}"
IDX=0

for BUG in "${BUGS[@]}"; do
    BUILD_DIR="$(pwd)/build-${BUG}"
    KERN="${BUILD_DIR}/kernel/kernel"
    FSIMG="${BUILD_DIR}/fs.img"

    if [ ! -f "$KERN" ] || [ ! -f "$FSIMG" ]; then
        echo "ERROR: Build dir missing for ${BUG}. Run build first."
        continue
    fi

    # Read bug config
    TRIGGER=$(python3 -c "import yaml; print(yaml.safe_load(open('bugs/${BUG}.yaml'))['trigger'])")

    for TIER in "${TIERS[@]}"; do
        # Select tool config
        if [ "$TIER" = "tier1_lldb_only" ]; then
            TOOL_CONFIG="$(pwd)/../bench/configs/tier3_gdb_only.json"
        else
            TOOL_CONFIG="$(pwd)/../bench/configs/tier2_bash_plus_gdb.json"
        fi

        for MODEL in "${MODELS[@]}"; do
            IDX=$((IDX + 1))
            MODEL_SLUG="${MODEL//\//_}"
            RUN_ID="${BUG}__${MODEL_SLUG}__${TIER}"
            RUN_DIR="${RESULTS_DIR}/${RUN_ID}"
            mkdir -p "${RUN_DIR}"

            echo "[${IDX}/${TOTAL}] ${BUG} × $(basename ${MODEL}) × ${TIER}"

            # Write case.yaml
            python3 -c "
import yaml, shutil
from pathlib import Path
cfg = yaml.safe_load(open('bugs/${BUG}.yaml'))
with open('${RUN_DIR}/case.yaml', 'w') as f:
    yaml.dump({
        'id': cfg['id'], 'language': 'c',
        'source_file': cfg['source_file'],
        'criteria': cfg['criteria'],
    }, f, default_flow_style=False)
# Copy buggy source
src = Path('${BUILD_DIR}') / cfg['source_file']
dest = Path('${RUN_DIR}') / cfg['source_file']
dest.parent.mkdir(parents=True, exist_ok=True)
if src.exists(): shutil.copy(src, dest)
"

            # Copy tool config
            cp "${TOOL_CONFIG}" "${RUN_DIR}/tool_config.json"

            # Start QEMU
            qemu-system-riscv64 \
                -machine virt -bios none \
                -kernel "$KERN" -m 128M -smp 1 -nographic \
                -global virtio-mmio.force-legacy=false \
                -drive file="$FSIMG",if=none,format=raw,id=x0 \
                -device virtio-blk-device,drive=x0,bus=virtio-mmio-bus.0 \
                -S -gdb "tcp::${QEMU_PORT}" \
                </dev/null >/dev/null 2>&1 &
            QPID=$!
            sleep 2

            # Write LLDB command file
            cat > "${RUN_DIR}/_lldb.cmd" << LLDBEOF
target create "${KERN}"
gdb-remote ${QEMU_PORT}
command script import $(pwd)/scripts/catch_fault.py
catch_fault
command script import ${CHATDBG_SRC}/chatdbg/chatdbg_lldb.py
why What is the root cause of this crash? Walk through the program state, identify the defect, and propose a fix in code. Cover both a minimal local fix and a more thorough root-cause fix if they differ.
quit
LLDBEOF

            # Run LLDB with ChatDBG
            START_T=$(python3 -c "import time; print(time.time())")

            CHATDBG_MODEL="${MODEL}" \
            CHATDBG_TOOL_CONFIG="${RUN_DIR}/tool_config.json" \
            CHATDBG_COLLECT_DATA="${RUN_DIR}/collect.json" \
            CHATDBG_FORMAT="text" \
            CHATDBG_LOG="${RUN_DIR}/chatdbg.log.yaml" \
            PYTHONPATH="${CHATDBG_SRC}" \
            OPENROUTER_API_KEY="${OPENROUTER_API_KEY}" \
            gtimeout ${TIMEOUT} lldb --batch -s "${RUN_DIR}/_lldb.cmd" \
                > "${RUN_DIR}/lldb_stdout.log" 2>&1 || true

            ELAPSED=$(python3 -c "import time; print(f'{time.time() - ${START_T}:.1f}')")

            # Kill QEMU
            kill $QPID 2>/dev/null; wait $QPID 2>/dev/null || true

            # Write result.json
            STATUS="ok"
            [ -f "${RUN_DIR}/collect.json" ] || STATUS="no_collect"
            python3 -c "
import json, time
with open('${RUN_DIR}/result.json', 'w') as f:
    json.dump({
        'run_id': '${RUN_ID}',
        'status': '${STATUS}',
        'exit_code': 0,
        'elapsed_s': ${ELAPSED},
        'model': '${MODEL}',
        'tool_config': '${TIER}',
        'tier': '${TIER}',
        'trial': 1,
        'case_id': '$(python3 -c "import yaml; print(yaml.safe_load(open(\"bugs/${BUG}.yaml\"))['id'])")',
        'language': 'c',
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'collect_path': 'collect.json',
    }, f, indent=2)
"

            # Quick summary
            if [ -f "${RUN_DIR}/collect.json" ]; then
                python3 -c "
import json
with open('${RUN_DIR}/collect.json') as f:
    c = json.load(f)
q = c.get('queries', [{}])[0]
tc = q.get('num_tool_calls', 0)
tf = q.get('tool_frequency', {})
tok = q.get('stats', {}).get('total_tokens', 0)
print(f'  {tc} tool calls, {tok} tokens, {${ELAPSED}}s')
print(f'  tools: {tf}')
"
            else
                echo "  NO COLLECT (timeout or error)"
            fi

        done
    done
done

echo ""
echo "============================================"
echo "  Done! Results: ${RESULTS_DIR}"
echo "============================================"
echo ""
echo "Next: run the judge:"
echo "  cd .. && python3 bench/judge.py --judge-model openrouter/openai/gpt-4o ${RESULTS_DIR}"
