#!/bin/bash
# run_new_ablations.sh — Three new ablations on synthetic cases
#
# Ablation 1: Context size (5, 20, 999 lines of source in stack trace)
# Ablation 2: Multi-turn (1 turn standard vs 3 follow-up turns)
# Ablation 3: GDB cheat sheet (inject command reference into system prompt)
#
# All use tier 3 (ChatDBG/LLDB) on the synthetic cases.
# Models: all 8.
# Cases: all synthetic (same as synth-8model-sweep).

set -uo pipefail
cd "$(dirname "$0")"

MODELS=(
    openrouter/openai/gpt-4o
    openrouter/openai/gpt-5.5
    openrouter/x-ai/grok-4
    openrouter/anthropic/claude-sonnet-4-5
    openrouter/google/gemini-2.5-flash
    openrouter/meta-llama/llama-3.1-8b-instruct
    openrouter/nvidia/nemotron-3-nano-30b-a3b
    openrouter/qwen/qwen3-30b-a3b-instruct-2507
)

MODELS_STR="${MODELS[*]}"

echo "============================================"
echo "  New Ablations"
echo "============================================"
echo ""

# ─────────────────────────────────────────────
# Ablation 1: Context size
# Default is 10 lines. Test 5, 20, and 999 (max/full file).
# Uses --context-lines flag which sets CHATDBG_CONTEXT env var.
# ─────────────────────────────────────────────
echo "=== Ablation 1: Context size (5, 20, 999 lines) ==="
for CTX in 5 20 999; do
    echo ""
    echo "--- Context = ${CTX} lines ---"
    python3 bench/orchestrator.py \
        --models ${MODELS_STR} \
        --tool-configs tier3_gdb_only.json \
        --tiers 3 \
        --trials 1 \
        --timeout 180 \
        --context-lines ${CTX} \
        --skip-existing \
        --name synth-ctx${CTX} \
        2>&1 &
done

echo ""
echo "All context ablations launched in parallel."
echo "Results: bench/results/synth-ctx5/, synth-ctx20/, synth-ctx999/"
echo ""

# ─────────────────────────────────────────────
# Ablation 3: GDB cheat sheet
# Override the instructions file to include the command reference.
# Uses CHATDBG_INSTRUCTIONS env var.
# ─────────────────────────────────────────────
echo "=== Ablation 3: GDB cheat sheet ==="
echo ""
# The cheat sheet instructions file is at:
# src/chatdbg/util/instructions/default_with_gdb_cheatsheet.txt
# We set it via CHATDBG_INSTRUCTIONS env var.

CHATDBG_INSTRUCTIONS="$(pwd)/src/chatdbg/util/instructions/default_with_gdb_cheatsheet.txt" \
python3 bench/orchestrator.py \
    --models ${MODELS_STR} \
    --tool-configs tier3_gdb_only.json \
    --tiers 3 \
    --trials 1 \
    --timeout 180 \
    --skip-existing \
    --name synth-gdb-cheatsheet \
    2>&1 &

echo "GDB cheat sheet ablation launched."
echo "Results: bench/results/synth-gdb-cheatsheet/"
echo ""

# ─────────────────────────────────────────────
# Ablation 2: Multi-turn (3 follow-up turns)
# Uses check-my-work with max-stale=3 but WITHOUT judge hints —
# just "investigate further and refine your answer."
# Actually, the simplest approach: use CMW with stale=3 and
# the judge model, which gives the model 3 chances to improve.
#
# NOTE: This is similar to CMW but tests whether plain
# "try again" (without detailed feedback) helps.
# For now, we'll use CMW as the multi-turn mechanism since
# it's already implemented. The baseline (1 turn) is the
# standard synth-8model-sweep T3 run.
# ─────────────────────────────────────────────
echo "=== Ablation 2: Multi-turn (3 turns via CMW) ==="
echo ""
echo "NOTE: Using CMW as multi-turn mechanism."
echo "Baseline (1 turn) = synth-8model-sweep T3 (already completed)"
echo "Treatment (3 turns) = synth-cmw-t3-sweep (already running/completed)"
echo ""
echo "If synth-cmw-t3-sweep is not yet done, check its status."

echo ""
echo "============================================"
echo "  Summary"
echo "============================================"
echo "Ablation 1 (context):    synth-ctx5, synth-ctx20, synth-ctx999 (parallel)"
echo "Ablation 2 (multi-turn): synth-8model-sweep (1 turn) vs synth-cmw-t3-sweep (3 turns)"
echo "Ablation 3 (cheatsheet): synth-gdb-cheatsheet"
echo ""
echo "Baseline for all:        synth-8model-sweep T3 (ctx=10, 1 turn, no cheatsheet)"
echo ""
echo "Judge all with:"
echo "  for d in synth-ctx5 synth-ctx20 synth-ctx999 synth-gdb-cheatsheet; do"
echo "    python3 bench/judge.py --judge-model openrouter/openai/gpt-4o bench/results/\$d"
echo "  done"
