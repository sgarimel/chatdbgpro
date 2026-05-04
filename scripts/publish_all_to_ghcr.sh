#!/usr/bin/env bash
# One-shot: trigger the gdb-image matrix build, watch it, then print
# next-step commands for adroit + local use.
#
# Why this script: image distribution is just "build amd64 image, push
# to a registry". GitHub Actions runs the build on linux/amd64 native
# runners with built-in GHCR auth via GITHUB_TOKEN. SWE-Rex (which
# you mentioned) is a sandbox/runtime layer for AGENT runs, NOT for
# image distribution — it's irrelevant to this task.
#
# Prereqs:
#   - `gh` CLI authenticated (gh auth status). Token needs the
#     `workflow` scope to dispatch and `read:packages` to inspect.
#     `repo` scope is also required if the workflow file is in a
#     private repo.
#   - Push to main has happened (or PR merged). The workflow file
#     `.github/workflows/build-gdb-images.yml` must be on main.
#
# Usage:
#   scripts/publish_all_to_ghcr.sh                 # all 19 projects
#   scripts/publish_all_to_ghcr.sh yara libtiff    # subset
#   WATCH=0 scripts/publish_all_to_ghcr.sh         # fire-and-forget

set -euo pipefail

WORKFLOW='Build & publish gdb-base images to GHCR'
WATCH="${WATCH:-1}"

projects_csv=""
if (( $# > 0 )); then
    projects_csv=$(IFS=, ; echo "$*")
fi

owner=$(gh api user --jq .login | tr '[:upper:]' '[:lower:]')

# Pre-flight: gh auth has packages:read so we can inspect the result.
if ! gh auth status 2>&1 | grep -q "Token scopes:.*workflow"; then
    cat >&2 <<EOF
[publish_all_to_ghcr] gh CLI token is missing the 'workflow' scope.
  Run: gh auth refresh -h github.com -s workflow,read:packages,write:packages
EOF
    exit 1
fi

if [[ -n "$projects_csv" ]]; then
    echo "[publish_all_to_ghcr] dispatching subset: $projects_csv"
    gh workflow run "$WORKFLOW" -f "projects=$projects_csv"
else
    echo "[publish_all_to_ghcr] dispatching ALL 19 projects"
    gh workflow run "$WORKFLOW"
fi

# Resolve the run we just kicked off. `gh workflow run` doesn't print
# the run id, so we poll the recent-runs list for ~10s until the new
# run appears.
echo "[publish_all_to_ghcr] resolving run id…"
run_id=""
for _ in $(seq 1 10); do
    sleep 1
    run_id=$(gh run list --workflow "$WORKFLOW" --limit 1 --json databaseId,status,event \
             --jq '.[] | select(.event=="workflow_dispatch") | .databaseId' \
             | head -1)
    [[ -n "$run_id" ]] && break
done
if [[ -z "$run_id" ]]; then
    echo "[publish_all_to_ghcr] could not find dispatched run; check 'gh run list'"
    exit 1
fi
url=$(gh run view "$run_id" --json url --jq .url)
echo "[publish_all_to_ghcr] run $run_id → $url"

if [[ "$WATCH" != "0" ]]; then
    echo "[publish_all_to_ghcr] streaming run (Ctrl-C is safe — run keeps going)"
    gh run watch "$run_id" --exit-status || true
fi

cat <<EOF

============================================================
Next steps (after the matrix succeeds)
============================================================

1) Flip package visibility to public if you want unauth pulls.
   GitHub's API doesn't expose this for user-owned packages,
   so it's one click each at:

EOF

slugs=(berry coreutils cpp_peglib cppcheck dlt_daemon exiv2 libchewing libssh libtiff libucl libxml2 md4c ndpi proj wget2 wireshark yara zsh)
for s in "${slugs[@]}"; do
    echo "   https://github.com/users/$owner/packages/container/chatdbgpro-gdb-$s/settings"
done

cat <<EOF

2) On adroit (or any linux/amd64 host):

   export BENCH_APPTAINER_REGISTRY=ghcr.io/$owner

   # Pre-warm the apptainer cache for one project:
   apptainer pull docker://ghcr.io/$owner/chatdbgpro-gdb-yara:latest

   # Pre-warm all 19:
   for p in ${slugs[@]}; do
       apptainer pull docker://ghcr.io/$owner/chatdbgpro-gdb-\$p:latest
   done

   # Rebuild every workspace with -g and re-probe:
   python -m pipeline2.rebuild_with_debug --all --runtime apptainer --workers 4

3) Locally (Apple Silicon — slower under Rosetta but works for
   non-ptrace ops; the strace probe needs a native amd64 host):

   docker pull --platform linux/amd64 ghcr.io/$owner/chatdbgpro-gdb-yara:latest
   docker run --rm --platform linux/amd64 \\
       ghcr.io/$owner/chatdbgpro-gdb-yara:latest \\
       gdb --version

4) Re-run benchmarks against the new images:

   python -m bench.parallel_run \\
       --bug-ids yara-1 yara-2 yara-3 yara-4 yara-5 \\
       --tiers 1 2 3 \\
       --models openrouter/anthropic/claude-sonnet-4.6 \\
       --runtime apptainer --workers 8 \\
       --name yara-on-fresh-images
EOF
