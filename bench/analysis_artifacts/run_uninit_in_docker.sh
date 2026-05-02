#!/usr/bin/env bash
# Run the Tier-3 orchestrator on uninit-stack-accumulator inside a Linux
# container so MemorySanitizer is available. Mounts the host repo so
# results land back in bench/results/<name>/.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="chatdbg-uninit-runner:latest"
NAME="uninit-msan-linux"

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "OPENROUTER_API_KEY required" >&2
  exit 2
fi

echo "[runner] building $TAG"
docker build --platform=linux/amd64 \
  -t "$TAG" \
  -f "$REPO/bench/analysis_artifacts/uninit_runner.Dockerfile" \
  "$REPO" >&2

echo "[runner] running orchestrator in $TAG"
docker run --rm --platform=linux/amd64 \
  --user "$(id -u):$(id -g)" \
  -v "$REPO":/work -w /work \
  --tmpfs /work/.venv-bench-39 \
  --tmpfs /work/.venv-bench \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  -e PYTHONPATH=/work/src \
  "$TAG" \
  python3 -m bench.orchestrator \
    --cases uninit-stack-accumulator \
    --models \
        openrouter/openai/gpt-5.5 \
        openrouter/google/gemini-3.1-flash-lite-preview \
        openrouter/nvidia/nemotron-3-nano-30b-a3b \
        openrouter/qwen/qwen3-30b-a3b-instruct-2507 \
    --tool-configs tier3_gdb_only \
    --context-lines 10 --trials 1 \
    --name "$NAME" \
    --debugger lldb \
    --timeout 300

echo "[runner] merging into full-synthetic-v1-stripped"
SUITE="$REPO/bench/results/full-synthetic-v1-stripped"
# Drop stale Nemotron/Qwen uninit runs (compile failed on macOS, judge
# saw empty response and scored 0/0/0 — bogus signal). Replace with
# the new Linux runs below.
rm -rf "$SUITE"/uninit-stack-accumulator__*
for d in "$REPO/bench/results/$NAME"/*/; do
  name=$(basename "$d")
  rsync -a "$d" "$SUITE/$name/"
done

echo "[runner] done"
