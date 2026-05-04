#!/usr/bin/env bash
# Rebuild every yara-N workspace inside the strace-bearing apptainer SIF
# with `-g -O0` so gdb can show source-line frames, then run `make check`
# for the case-specific lua selector and record which test binary failed.
# Output: per-workspace build log + a summary mapping bug_id -> test binary.
#
# Run on adroit (or any apptainer host). Expects:
#   - $HOME/sif/gdb-yara.sif exists (built from gdb-yara-strace.def)
#   - $HOME/chatdbgpro_bench is the working clone with data/workspaces/yara-*
set +e

REPO="${REPO:-$HOME/chatdbgpro_bench}"
SIF="${SIF:-$HOME/sif/gdb-yara.sif}"
LOG_DIR="${LOG_DIR:-$HOME/yara-rebuild-logs}"
SUMMARY="$LOG_DIR/summary.tsv"
mkdir -p "$LOG_DIR"
: > "$SUMMARY"

cd "$REPO" || { echo "no repo at $REPO"; exit 1; }

CASES=(
    "yara-1 1 55"
    "yara-2 2 232"
    "yara-3 3 102"
    "yara-4 4 233"
    "yara-5 5 238"
)

for entry in "${CASES[@]}"; do
    read -r BUG_ID IDX CASE_NUM <<<"$entry"
    WS="$REPO/data/workspaces/$BUG_ID/yara/buggy-$IDX"
    LOG="$LOG_DIR/$BUG_ID.log"
    if [ ! -d "$WS" ]; then
        echo "[$BUG_ID] SKIP: workspace missing" | tee -a "$SUMMARY"
        continue
    fi
    echo "=== [$BUG_ID] case=$CASE_NUM ws=$WS ==="
    {
        echo "=== START $(date -u +%FT%TZ) [$BUG_ID] ==="
        # `make distclean` to wipe any prior CFLAGS, then configure with -g.
        # CFLAGS replicates yara's autodetected flags so we don't lose
        # USE_LINUX_PROC etc. — checked via head of an existing Makefile.
        # bugscpp's configure already wired up lua / autotools — `make
        # distclean` wipes that and yara's own configure can't find lua.
        # Keep configure state; just rebuild with CFLAGS override to
        # inject -g without losing detected libs.
        apptainer exec --writable-tmpfs \
            --bind "$WS:/work" --pwd /work "$SIF" bash -c '
                set -x
                make clean 2>&1 | tail -5
                find . -name "*.o" -delete 2>/dev/null
                find . -name "*.lo" -delete 2>/dev/null
                find . -name "*.la" -delete 2>/dev/null
                echo "return '$CASE_NUM'" > tests/defects4cpp.lua
                make -j$(nproc) CFLAGS="-g -O0 -DUSE_LINUX_PROC -pthread -DHASH_MODULE" CXXFLAGS="-g -O0" 2>&1 | tail -30
                make -j1 check CFLAGS="-g -O0 -DUSE_LINUX_PROC -pthread -DHASH_MODULE" 2>&1 | tail -40
                echo "=== make check rc=$? ==="
                ls -la tests/ | grep -E "^-.{8}x" | head -20
                echo "=== TEST RESULT FILES ==="
                cat tests/test-suite.log 2>/dev/null | tail -60
                for trs in tests/test-*.trs; do
                    [ -f "$trs" ] && echo "$trs:" && grep -E "^:test-result:" "$trs"
                done
            '
        echo "=== END $(date -u +%FT%TZ) [$BUG_ID] ==="
    } >"$LOG" 2>&1

    # Extract failing test name. Two sources:
    #   1. tests/test-suite.log lists FAIL: test-name
    #   2. .trs files have ":test-result: FAIL" lines
    FAILING=$(grep -E "^FAIL: test-" "$LOG" | head -1 | awk '{print $2}')
    if [ -z "$FAILING" ]; then
        # Fallback: any test that exited nonzero from .trs
        FAILING=$(awk '/^tests\/test-.*\.trs:/{f=$1} /:test-result: FAIL/{print f; exit}' "$LOG" \
                  | sed -E 's|tests/(test-[^.]+)\.trs:|\1|')
    fi
    echo -e "$BUG_ID\t$CASE_NUM\ttests/$FAILING" | tee -a "$SUMMARY"
done

echo
echo "=== SUMMARY ==="
cat "$SUMMARY"
