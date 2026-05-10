#!/usr/bin/env bash
# Push fresh sweep dirs to the shared coordination branch so the rest of the
# team can see / pull / judge them. Run this after every batch (or on a cron
# during long sweeps).
#
# Usage:
#     bench/sync_results_to_repo.sh <sweep-dir> [<sweep-dir> ...]
#
# Designed to be idempotent and survive concurrent pushes from teammates:
# pulls --rebase first, retries push up to 3 times if the remote has moved.
#
# Branch convention:
#   - Anika commits to:   push/local-runs-anika
#   - Ibraheem commits to: push/runs-ibraheem
#   Each person stays on their own branch; cross-pollination happens via
#   `git fetch origin && git merge origin/<other-branch>` when needed.
#   The branches are read-only as far as the *other* teammate is concerned —
#   never push to a branch that isn't yours.
#
# Env overrides:
#   GIT_USER_BRANCH   override which branch to push to (default: current)
#   SKIP_PUSH=1       commit but do not push (for dry runs)

set -euo pipefail

if [ $# -eq 0 ]; then
    echo "usage: $0 <sweep-dir> [<sweep-dir> ...]" >&2
    exit 64
fi

cd "$(git rev-parse --show-toplevel)"

BRANCH="${GIT_USER_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
echo "[sync] branch=$BRANCH"

# Stage the requested sweep dirs only (not the whole tree — avoids accidentally
# committing unrelated edits).
git add -- "$@" bench/results/final_paper_bench/_provenance.json 2>/dev/null || true

if git diff --cached --quiet; then
    echo "[sync] nothing to commit"
    exit 0
fi

DATE_TAG="$(date -u +%Y%m%dT%H%M%SZ)"
SUMMARY="bench/results: sync sweep dirs ($DATE_TAG)"
git commit -m "$SUMMARY" \
           -m "Synced: $*" \
           -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

if [ -n "${SKIP_PUSH:-}" ]; then
    echo "[sync] SKIP_PUSH set; commit made but not pushed"
    exit 0
fi

# Retry loop for concurrent-push contention.
for attempt in 1 2 3; do
    echo "[sync] push attempt $attempt -> origin/$BRANCH"
    if git pull --rebase origin "$BRANCH" 2>/dev/null && git push origin "$BRANCH"; then
        echo "[sync] pushed"
        exit 0
    fi
    echo "[sync] push failed; retrying after rebase..."
    sleep $((2 * attempt))
done

echo "[sync] push failed after 3 attempts. Resolve manually:" >&2
echo "       git pull --rebase origin $BRANCH && git push origin $BRANCH" >&2
exit 1
