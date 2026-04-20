#!/usr/bin/env bash
# run_pipeline.sh
# Runs all six corpus-building steps in order.
# Must be run on Linux (BugsC++ Docker images are linux/amd64 only).
#
# Prerequisites (see test_case_pipeline.md Part 1):
#   - Docker installed and running (current user in docker group)
#   - bugscpp CLI installed (pip install bugscpp)
#   - BugsC++ repo cloned — set BUGSCPP_REPO if not at ../bugscpp/
#   - Virtual env activated (source ~/chatdbg-eval-env/bin/activate)
#   - DB initialized: sqlite3 data/corpus.db < schema.sql
#
# Usage:
#   bash run_pipeline.sh            # full run from scratch
#   bash run_pipeline.sh --resume   # skip already-completed work in each step

set -euo pipefail

RESUME=""
if [[ "${1:-}" == "--resume" ]]; then
  RESUME="--resume"
  echo "[pipeline] Resume mode: skipping already-processed bugs"
fi

# ── 0. Initialize DB if it doesn't exist ─────────────────────────────────────
if [ ! -f "data/corpus.db" ]; then
  echo "[pipeline] Initializing database..."
  sqlite3 data/corpus.db < schema.sql
fi

# ── 1. Seed ───────────────────────────────────────────────────────────────────
echo ""
echo "[pipeline] Step 1/6: Seeding database with BugsC++ metadata..."
python scripts/seed_db.py

# ── 2. Build filter ───────────────────────────────────────────────────────────
echo ""
echo "[pipeline] Step 2/6: Building all candidates (~30-60 min)..."
python scripts/build_filter.py $RESUME

echo ""
sqlite3 data/corpus.db \
  "SELECT 'Build results: ' || success || '=' || COUNT(*) FROM build_log GROUP BY success;"

# ── 3. Crash filter ───────────────────────────────────────────────────────────
echo ""
echo "[pipeline] Step 3/6: Running crash filter — 3 GDB runs per bug (~2-4 hours)..."
python scripts/crash_filter.py $RESUME

echo ""
sqlite3 data/corpus.db \
  "SELECT crash_signal, COUNT(*) FROM test_cases WHERE crash_reproducible=1 GROUP BY crash_signal;"

# ── 4. Extract crash locations ────────────────────────────────────────────────
echo ""
echo "[pipeline] Step 4/6: Extracting crash frames (~20-40 min)..."
python scripts/extract_crash_location.py $RESUME

# ── 5. Extract and validate patches ──────────────────────────────────────────
echo ""
echo "[pipeline] Step 5/6: Extracting and validating patches (~30-60 min)..."
python scripts/extract_patches.py $RESUME

echo ""
sqlite3 data/corpus.db \
  "SELECT patch_validated, COUNT(*) FROM test_cases WHERE crash_reproducible=1 GROUP BY patch_validated;"

# ── 6. Finalize ───────────────────────────────────────────────────────────────
echo ""
echo "[pipeline] Step 6/6: Finalizing corpus..."
python scripts/finalize_corpus.py

# ── Verify ────────────────────────────────────────────────────────────────────
echo ""
echo "[pipeline] Running verification checks..."
bash scripts/verify_corpus.sh

echo ""
echo "[pipeline] Done. Commit with:"
echo "  git add data/corpus.db data/patches/ data/backtraces/"
echo "  git commit -m 'Add curated test case corpus'"
echo "  (do NOT commit data/filter_runs/ — it's large raw output)"
