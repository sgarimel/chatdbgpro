#!/bin/bash
# Re-run just Sonnet 4.5 on all 4 xv6 tiers (fixed model ID)
set -uo pipefail
cd "$(dirname "$0")"

MODEL="openrouter/anthropic/claude-sonnet-4-5"
BUG="bug1-uvmcopy-perm"
BUILD_DIR="$(pwd)/build-${BUG}"
KERN="${BUILD_DIR}/kernel/kernel"
FSIMG="${BUILD_DIR}/fs.img"
CHATDBG_SRC="$(pwd)/../src"
QEMU_PORT=1234
TIMEOUT=180
RESULTS_DIR="$(pwd)/results/xv6-4tier-20260503_185537"

GARBAGE_Q="What is the root cause of this crash?"
ENRICHED_Q="What is the root cause of this page fault? The child process (created via fork) crashes immediately with an instruction page fault (scause=12) at address 0x370. The parent does not fault. This means the child page table lacks proper permission bits (PTE_U or PTE_X) for user-mode instruction fetch. The page table is created by uvmcopy() during fork. Trace the bug to the specific kernel function and line in kernel/vm.c."

BUG_ID=$(python3 -c "import yaml; print(yaml.safe_load(open('bugs/${BUG}.yaml'))['id'])")

[ -z "${OPENROUTER_API_KEY:-}" ] && echo "ERROR: OPENROUTER_API_KEY not set" && exit 1

echo "Re-running Sonnet 4.5 (fixed model ID) on all 4 tiers"

for TIER_NUM in 0 1 2 3; do
    case $TIER_NUM in
        0) TIER_NAME="tier0_garbage_all_tools"; TOOL_CONFIG="$(pwd)/../bench/configs/tier2_bash_plus_gdb.json"; QUESTION="$GARBAGE_Q" ;;
        1) TIER_NAME="tier1_enriched_all_tools"; TOOL_CONFIG="$(pwd)/../bench/configs/tier2_bash_plus_gdb.json"; QUESTION="$ENRICHED_Q" ;;
        2) TIER_NAME="tier2_enriched_lldb_only"; TOOL_CONFIG="$(pwd)/../bench/configs/tier3_gdb_only.json"; QUESTION="$ENRICHED_Q" ;;
        3) TIER_NAME="tier3_enriched_all_tools"; TOOL_CONFIG="$(pwd)/../bench/configs/tier2_bash_plus_gdb.json"; QUESTION="$ENRICHED_Q" ;;
    esac

    MODEL_SLUG="${MODEL//\//_}"
    RUN_ID="${BUG_ID}__${MODEL_SLUG}__${TIER_NAME}"
    RUN_DIR="${RESULTS_DIR}/${RUN_ID}"
    mkdir -p "${RUN_DIR}"

    echo "[${TIER_NUM}/3] Sonnet 4.5 × ${TIER_NAME}"

    # Write case.yaml + copy source
    python3 -c "
import yaml, shutil
from pathlib import Path
cfg = yaml.safe_load(open('bugs/${BUG}.yaml'))
with open('${RUN_DIR}/case.yaml', 'w') as f:
    yaml.dump({'id': cfg['id'], 'language': 'c', 'source_file': cfg['source_file'],
               'criteria': cfg['criteria']}, f, default_flow_style=False)
src = Path('${BUILD_DIR}') / cfg['source_file']
dest = Path('${RUN_DIR}') / cfg['source_file']
dest.parent.mkdir(parents=True, exist_ok=True)
if src.exists(): shutil.copy(src, dest)
"
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

    cat > "${RUN_DIR}/_lldb.cmd" << LLDBEOF
target create "${KERN}"
gdb-remote ${QEMU_PORT}
command script import $(pwd)/scripts/catch_fault.py
catch_fault
command script import ${CHATDBG_SRC}/chatdbg/chatdbg_lldb.py
why ${QUESTION}
quit
LLDBEOF

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

    kill $QPID 2>/dev/null; wait $QPID 2>/dev/null || true

    STATUS="ok"
    [ -f "${RUN_DIR}/collect.json" ] || STATUS="no_collect"
    python3 -c "
import json, time
with open('${RUN_DIR}/result.json', 'w') as f:
    json.dump({
        'run_id': '${RUN_ID}', 'status': '${STATUS}', 'exit_code': 0,
        'elapsed_s': ${ELAPSED}, 'model': '${MODEL}',
        'tool_config': '${TIER_NAME}', 'tier': '${TIER_NAME}',
        'trial': 1, 'case_id': '${BUG_ID}', 'language': 'c',
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }, f, indent=2)
"

    if [ -f "${RUN_DIR}/collect.json" ]; then
        python3 -c "
import json
with open('${RUN_DIR}/collect.json') as f:
    c = json.load(f)
q = c.get('queries', [{}])[0]
tc = q.get('num_tool_calls', 0)
tf = q.get('tool_frequency', {})
print(f'  {tc} tool calls, ${ELAPSED}s')
print(f'  tools: {tf}')
"
    else
        echo "  NO COLLECT (timeout or error)"
    fi
done

echo ""
echo "Done! Now judge:"
echo "  cd .. && python3 bench/judge.py --judge-model openrouter/openai/gpt-4o xv6-bench/results/xv6-4tier-20260503_185537"
