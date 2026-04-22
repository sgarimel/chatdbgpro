#!/usr/bin/env bash
# scripts/verify_corpus.sh
# Run pre-commit sanity checks on the finalized corpus.
# Exits with code 1 if anything looks wrong.
# Usage: bash scripts/verify_corpus.sh

set -euo pipefail
DB="data/corpus.db"

if [ ! -f "$DB" ]; then
  echo "ERROR: $DB not found. Run the pipeline first."
  exit 1
fi

echo "=== Corpus summary ==="
sqlite3 "$DB" "
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN crash_signal = 'SIGSEGV' THEN 1 ELSE 0 END) as sigsegv,
    SUM(CASE WHEN crash_signal = 'SIGABRT' THEN 1 ELSE 0 END) as sigabrt,
    SUM(CASE WHEN crash_signal = 'SIGFPE'  THEN 1 ELSE 0 END) as sigfpe,
    SUM(CASE WHEN crash_signal = 'SIGBUS'  THEN 1 ELSE 0 END) as sigbus,
    SUM(CASE WHEN frame0_function != user_frame_function THEN 1 ELSE 0 END) as indirect_crashes
FROM test_cases WHERE included_in_corpus = 1;
" | column -t -s "|"

echo ""
echo "=== By project ==="
sqlite3 "$DB" "
SELECT project, COUNT(*) as n
FROM test_cases WHERE included_in_corpus = 1
GROUP BY project ORDER BY n DESC;
" | column -t -s "|"

echo ""
echo "=== Checking backtrace files on disk ==="
MISSING_BT=0
while IFS= read -r p; do
  if [ -n "$p" ] && [ ! -f "data/$p" ]; then
    echo "MISSING backtrace: data/$p"
    MISSING_BT=$((MISSING_BT + 1))
  fi
done < <(sqlite3 "$DB" "SELECT backtrace_path FROM test_cases WHERE included_in_corpus = 1;")

echo ""
echo "=== Checking patch files on disk ==="
MISSING_PATCH=0
while IFS= read -r p; do
  if [ -n "$p" ] && [ ! -f "data/$p" ]; then
    echo "MISSING patch: data/$p"
    MISSING_PATCH=$((MISSING_PATCH + 1))
  fi
done < <(sqlite3 "$DB" "SELECT patch_path FROM test_cases WHERE included_in_corpus = 1;")

echo ""
if [ "$MISSING_BT" -gt 0 ] || [ "$MISSING_PATCH" -gt 0 ]; then
  echo "FAILED: $MISSING_BT missing backtrace(s), $MISSING_PATCH missing patch(es)"
  exit 1
else
  echo "All files present. Corpus looks good."
fi
