#!/usr/bin/env bash
# bench/run_pilot.sh — single-command pilot driver.
#
# What it does (in order):
#   1. Sources .env so OPENROUTER_API_KEY etc are visible.
#   2. Verifies bugscpp clone + venv + corpus.db + workspaces are present
#      for the requested project; bootstraps each piece if missing.
#   3. Pre-builds the per-project gdb image (chatdbgpro/gdb-<project>)
#      and the synthetic-runner image. ContainerSession does this on
#      demand too, but doing it upfront fails fast on docker / arch
#      issues before you've burned API spend on the first cell.
#   4. Runs the (case × model × tier) sweep with --skip-existing.
#      Apple Silicon hosts auto-skip T2/T3 BugsCPP cells with
#      status=skipped_platform — no fake T2→T1 fallback.
#   5. Judges the sweep with gpt-4o.
#   6. Enriches per-run costs via OpenRouter pricing.
#   7. Generates the cross-tier PDF.
#
# Usage:
#   bench/run_pilot.sh                              # defaults — yara, haiku+sonnet, all 4 tiers
#   bench/run_pilot.sh --project libtiff            # different bugscpp project
#   bench/run_pilot.sh --bug-ids yara-1 yara-3      # subset of bugs
#   bench/run_pilot.sh --models sonnet only         # subset of models (claude only)
#   bench/run_pilot.sh --skip-judge                 # sweep only, no judge
#   bench/run_pilot.sh --name my-pilot              # custom name (default: pilot-<project>-<date>)
#
# Environment:
#   OPENROUTER_API_KEY   required for T1/T2/T3
#   ANTHROPIC_API_KEY    | one of these required for T4 (or `claude /login`)
#   ANTHROPIC_AUTH_TOKEN |
#   CLAUDE_CODE_OAUTH_TOKEN |
#   BUGSCPP_REPO         optional (default: ../bugscpp; auto-cloned if absent)
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ───── defaults ─────────────────────────────────────────────────────────────

PROJECT="yara"
BUG_IDS=()
MODELS_OPENROUTER=(
    openrouter/anthropic/claude-haiku-4.5
    openrouter/anthropic/claude-sonnet-4.5
)
MODELS_CLAUDE=(haiku sonnet)
TIERS=(1 2 3 4)
TRIALS=1
TIMEOUT=300
NAME=""
SKIP_JUDGE=0
JUDGE_MODEL="openrouter/openai/gpt-4o"
ONLY_MODELS=""
RUNTIME=""

# ───── arg parsing ──────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)       PROJECT="$2"; shift 2 ;;
        --bug-ids)       shift; while [[ $# -gt 0 && "$1" != --* ]]; do BUG_IDS+=("$1"); shift; done ;;
        --models)        ONLY_MODELS="$2"; shift 2 ;;
        --tiers)         shift; TIERS=(); while [[ $# -gt 0 && "$1" != --* ]]; do TIERS+=("$1"); shift; done ;;
        --trials)        TRIALS="$2"; shift 2 ;;
        --timeout)       TIMEOUT="$2"; shift 2 ;;
        --name)          NAME="$2"; shift 2 ;;
        --skip-judge)    SKIP_JUDGE=1; shift ;;
        --judge-model)   JUDGE_MODEL="$2"; shift 2 ;;
        --runtime)       RUNTIME="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,30p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

if [[ -z "$NAME" ]]; then
    NAME="pilot-${PROJECT}-$(date +%Y%m%d-%H%M%S)"
fi

if [[ ${#BUG_IDS[@]} -eq 0 ]]; then
    # Default: every included bug for the project.
    # `mapfile` requires bash ≥4; macOS ships /bin/bash 3.2. Use a
    # portable read loop instead.
    BUG_IDS=()
    while IFS= read -r line; do
        [[ -n "$line" ]] && BUG_IDS+=("$line")
    done < <(
        sqlite3 data/corpus.db \
            "SELECT bug_id FROM bugs WHERE project='$PROJECT' AND included_in_corpus=1 ORDER BY bug_index" \
            2>/dev/null || true
    )
    if [[ ${#BUG_IDS[@]} -eq 0 ]]; then
        echo "[pilot] No included bugs for project '$PROJECT' yet — bootstrapping (clone+seed+build)..."
    fi
fi

# Filter models per --models option.
case "$ONLY_MODELS" in
    "" | "all")     ;;  # keep both lists
    "openrouter")   MODELS_CLAUDE=() ;;
    "claude")       MODELS_OPENROUTER=() ;;
    "haiku")        MODELS_OPENROUTER=(openrouter/anthropic/claude-haiku-4.5); MODELS_CLAUDE=(haiku) ;;
    "sonnet")       MODELS_OPENROUTER=(openrouter/anthropic/claude-sonnet-4.5); MODELS_CLAUDE=(sonnet) ;;
    *)              echo "[pilot] unknown --models value: $ONLY_MODELS"; exit 2 ;;
esac

# ───── env + secrets ────────────────────────────────────────────────────────

if [[ -f .env ]]; then
    # shellcheck disable=SC1091
    source .env
    export OPENROUTER_API_KEY OPENAI_API_KEY OPENROUTER_API_BASE \
           ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN CLAUDE_CODE_OAUTH_TOKEN || true
fi

if [[ -z "${OPENROUTER_API_KEY:-}" && -n "${MODELS_OPENROUTER[*]:-}" ]]; then
    echo "[pilot] OPENROUTER_API_KEY required for T1-T3 sweeps. Set it in .env or environment." >&2
    exit 1
fi

# ───── arch detection (just informational; the orchestrator enforces) ───────

ARCH="$(uname -m)"
HOST_OS="$(uname -s)"
echo "[pilot] host: $HOST_OS / $ARCH"
if [[ "$ARCH" == "arm64" || "$ARCH" == "aarch64" ]]; then
    echo "[pilot] note: Apple Silicon detected — T2/T3 BugsCPP cells will auto-skip"
    echo "[pilot]       (amd64 ptrace is broken under Rosetta and QEMU-user)."
fi

# ───── bootstrap: bugscpp clone, venv, corpus, workspaces ───────────────────

BUGSCPP_REPO="${BUGSCPP_REPO:-$REPO_ROOT/../bugscpp}"
export BUGSCPP_REPO DOCKER_DEFAULT_PLATFORM=linux/amd64

if [[ ! -d "$BUGSCPP_REPO/bugscpp/taxonomy" ]]; then
    echo "[pilot] cloning bugscpp upstream → $BUGSCPP_REPO"
    git clone --depth 1 https://github.com/Suresoft-GLaDOS/bugscpp.git "$BUGSCPP_REPO"
fi
if [[ ! -x "$BUGSCPP_REPO/.venv/bin/python" ]]; then
    echo "[pilot] setting up bugscpp venv"
    python3 -m venv "$BUGSCPP_REPO/.venv"
    "$BUGSCPP_REPO/.venv/bin/pip" install -q --upgrade pip
    "$BUGSCPP_REPO/.venv/bin/pip" install -q -r "$BUGSCPP_REPO/requirements.txt"
fi

# Apply our local docker-platform patch to bugscpp's Python SDK call so
# Apple Silicon/Linux-amd64 builds work uniformly. Idempotent.
DOCKER_PY="$BUGSCPP_REPO/bugscpp/processor/core/docker.py"
if [[ -f "$DOCKER_PY" ]] && ! grep -q DOCKER_DEFAULT_PLATFORM "$DOCKER_PY"; then
    echo "[pilot] patching bugscpp's docker.py to honor DOCKER_DEFAULT_PLATFORM"
    python3 - <<'EOF'
import os, re, sys
p = os.environ["BUGSCPP_REPO"] + "/bugscpp/processor/core/docker.py"
s = open(p).read()
needle = "image, stream = client.images.build(rm=True, tag=tag, path=path, pull=True)"
repl = (
    "platform = os.environ.get('DOCKER_DEFAULT_PLATFORM')\n"
    "        build_kwargs = dict(rm=True, tag=tag, path=path, pull=True)\n"
    "        if platform:\n"
    "            build_kwargs['platform'] = platform\n"
    "        image, stream = client.images.build(**build_kwargs)"
)
if needle in s:
    open(p, "w").write(s.replace(needle, repl))
    print("[pilot] patched")
EOF
fi

if [[ ! -f data/corpus.db ]]; then
    echo "[pilot] initializing corpus.db schema"
    mkdir -p data
    sqlite3 data/corpus.db < pipeline2/schema.sql
fi

# Seed the corpus DB if we don't have rows for this project yet.
n_rows=$(sqlite3 data/corpus.db "SELECT COUNT(*) FROM bugs WHERE project='$PROJECT'" 2>/dev/null || echo 0)
if [[ "$n_rows" -eq 0 ]]; then
    echo "[pilot] seeding corpus.db from bugscpp taxonomy"
    .venv-bench-39/bin/python -m pipeline2.seed
fi

# Build any missing workspaces for this project.
n_built=$(sqlite3 data/corpus.db \
    "SELECT COUNT(*) FROM bugs WHERE project='$PROJECT' AND included_in_corpus=1" 2>/dev/null || echo 0)
if [[ "$n_built" -eq 0 ]]; then
    echo "[pilot] building workspaces for project '$PROJECT' (this can take 10-30 min)"
    .venv-bench-39/bin/python -m pipeline2.build --project "$PROJECT" --workers 1 --resume
fi

# Refresh BUG_IDS now that corpus has rows.
if [[ ${#BUG_IDS[@]} -eq 0 ]]; then
    BUG_IDS=()
    while IFS= read -r line; do
        [[ -n "$line" ]] && BUG_IDS+=("$line")
    done < <(
        sqlite3 data/corpus.db \
            "SELECT bug_id FROM bugs WHERE project='$PROJECT' AND included_in_corpus=1 ORDER BY bug_index"
    )
fi
echo "[pilot] bug_ids: ${BUG_IDS[*]}"

# ───── pre-build images (fail fast if docker/arch is broken) ────────────────

echo "[pilot] ensuring chatdbgpro/gdb-${PROJECT}:latest"
.venv-bench-39/bin/python -c "
from pipeline2.ensure_image import ensure_gdb_image
print('[pilot]  built:', ensure_gdb_image('${PROJECT}'))
"

if [[ " ${TIERS[*]} " == *" 3 "* ]]; then
    if ! docker image inspect chatdbgpro/synthetic-runner:latest >/dev/null 2>&1; then
        echo "[pilot] building chatdbgpro/synthetic-runner:latest (~5 min first time)"
        docker build -t chatdbgpro/synthetic-runner:latest \
            -f bench/drivers/synthetic_runner.Dockerfile bench/drivers/
    fi
fi

# ───── sweep ────────────────────────────────────────────────────────────────

mkdir -p bench/results
SWEEP_NAME="${NAME}"
SWEEP_DIR="bench/results/${SWEEP_NAME}"

# Single orchestrator invocation handles all (model × tier) combos.
# T1/T2/T3 use OpenRouter models; T4 uses Claude-CLI alias models.
# We dispatch them as separate orchestrator calls so the model lists
# don't cross-pollinate (T4 with `openrouter/anthropic/...` is an
# error; T1 with bare `sonnet` is an error).

ALL_TIERS_NON_T4=()
for t in "${TIERS[@]}"; do
    [[ "$t" != "4" ]] && ALL_TIERS_NON_T4+=("$t")
done

if [[ ${#ALL_TIERS_NON_T4[@]} -gt 0 && ${#MODELS_OPENROUTER[@]} -gt 0 ]]; then
    # Each tier maps to a single canonical tool-config. The orchestrator's
    # `build_matrix` pairs every tier with every tool-config — passing all
    # tiers + all configs in one invocation produces nonsensical
    # cross-pairs (T1 with the T3 prompt, etc.). We invoke once per tier
    # with the matching config so the output dir contains exactly one
    # cell per (case, tier, model, trial).
    for t in "${ALL_TIERS_NON_T4[@]}"; do
        case "$t" in
            1) CFG=bench/configs/tier1_bash_only.json ;;
            2) CFG=bench/configs/tier2_gdb_plus_bash.json ;;
            3) CFG=bench/configs/tier3_gdb_only.json ;;
            *) echo "[pilot] no tool-config mapped for tier $t"; continue ;;
        esac
        echo "[pilot] sweep T$t × ${#MODELS_OPENROUTER[@]} models × ${#BUG_IDS[@]} cases (× $TRIALS trials)"
        RUNTIME_ARGS=()
        [[ -n "$RUNTIME" ]] && RUNTIME_ARGS=(--runtime "$RUNTIME")
        .venv-bench-39/bin/python -m bench.orchestrator \
            --models "${MODELS_OPENROUTER[@]}" \
            --tool-configs "$CFG" \
            --tiers "$t" \
            --docker --bug-ids "${BUG_IDS[@]}" \
            --trials "$TRIALS" \
            --timeout "$TIMEOUT" \
            --name "$SWEEP_NAME" \
            --skip-existing \
            "${RUNTIME_ARGS[@]}"
    done
fi

if [[ " ${TIERS[*]} " == *" 4 "* && ${#MODELS_CLAUDE[@]} -gt 0 ]]; then
    echo "[pilot] sweep T4 × ${#MODELS_CLAUDE[@]} models × ${#BUG_IDS[@]} cases (× $TRIALS trials)"
    RUNTIME_ARGS=()
    [[ -n "$RUNTIME" ]] && RUNTIME_ARGS=(--runtime "$RUNTIME")
    .venv-bench-39/bin/python -m bench.orchestrator \
        --models "${MODELS_CLAUDE[@]}" \
        --tool-configs bench/configs/tier4_claude_code.json \
        --tiers 4 \
        --docker --bug-ids "${BUG_IDS[@]}" \
        --trials "$TRIALS" \
        --timeout "$TIMEOUT" \
        --name "$SWEEP_NAME" \
        --skip-existing \
        --tier4-bare auto \
        "${RUNTIME_ARGS[@]}"
fi

echo "[pilot] sweep complete: $SWEEP_DIR"

# ───── judge ────────────────────────────────────────────────────────────────

if [[ "$SKIP_JUDGE" -eq 0 ]]; then
    echo "[pilot] judging with $JUDGE_MODEL"
    .venv-bench-39/bin/python -m bench.judge \
        --judge-model "$JUDGE_MODEL" \
        "$SWEEP_DIR" || echo "[pilot] judge step failed — continuing"
fi

# ───── cost enrichment ──────────────────────────────────────────────────────

if [[ -f bench/analysis_artifacts/cost_enrich.py ]]; then
    echo "[pilot] enriching costs"
    # cost_enrich.py joins the arg under bench/results/, so pass just
    # the sweep name (last path component), not the full path.
    .venv-bench-39/bin/python bench/analysis_artifacts/cost_enrich.py \
        "$SWEEP_NAME" || echo "[pilot] cost enrich failed — continuing"
fi

# ───── PDF ──────────────────────────────────────────────────────────────────

# build_cross_tier_pdf needs pandas/matplotlib — they live in .venv-bench
# (Python 3.14), not .venv-bench-39 (Python 3.9, pinned to Apple lldb).
if [[ -f bench/analysis_artifacts/build_cross_tier_pdf.py ]]; then
    echo "[pilot] building cross-tier PDF"
    PDF_PY=".venv-bench/bin/python"
    [[ -x "$PDF_PY" ]] || PDF_PY="python3"
    "$PDF_PY" bench/analysis_artifacts/build_cross_tier_pdf.py \
        --suite "$SWEEP_DIR" \
        --out "bench/analysis_artifacts/figs/${SWEEP_NAME}.pdf" \
        || echo "[pilot] PDF step failed — continuing"
    ls -la "bench/analysis_artifacts/figs/${SWEEP_NAME}.pdf" 2>/dev/null || true
fi

echo "[pilot] done. Sweep: $SWEEP_DIR"
echo "[pilot] artifacts in:  $SWEEP_DIR"
echo "[pilot] PDF (if built): bench/analysis_artifacts/figs/${SWEEP_NAME}.pdf"
