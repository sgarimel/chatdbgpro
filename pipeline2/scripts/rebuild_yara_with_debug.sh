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
        # bugscpp's yara recipe (taxonomy/yara/meta.json) is:
        #   ./bootstrap.sh
        #   ./configure LDFLAGS=-llua5.3
        #   make clean && make
        # Without LDFLAGS=-llua5.3 the test binaries fail to link
        # (defects4cpp.h calls luaL_newstate / lua_pcallk). We replicate
        # that, plus add CFLAGS=-g -O0 so gdb shows source-line frames.
        apptainer exec --writable-tmpfs \
            --bind "$WS:/work" --pwd /work "$SIF" bash -c '
                set -x
                ./bootstrap.sh 2>&1 | tail -3 || true
                ./configure LDFLAGS=-llua5.3 \
                    CFLAGS="-g -O0 -DUSE_LINUX_PROC -pthread -DHASH_MODULE" \
                    CXXFLAGS="-g -O0" 2>&1 | tail -5
                make clean 2>&1 | tail -3
                make -j$(nproc) 2>&1 | tail -10
                echo "return '$CASE_NUM'" > tests/defects4cpp.lua
                make -j1 check 2>&1 | tail -50
                echo "=== make check rc=$? ==="
                # NB: yara's check_PROGRAMS sit at the WORKSPACE ROOT
                # (no tests/Makefile.am), so binaries are bare names
                # like ./test-api, NOT tests/test-api.
                ls -la test-* 2>/dev/null | grep -vE "\.(log|trs|c|h|o)$" | head -15
                echo "=== TEST RESULT FILES ==="
                cat test-suite.log 2>/dev/null | tail -40
                echo "=== DEBUG SYMS ==="
                for t in test-api test-rules test-atoms; do
                    [ -x "$t" ] && readelf -S "$t" 2>/dev/null | grep -q "\.debug_info" \
                        && echo "$t: HAS .debug_info" || echo "$t: missing or no debug"
                done
            '
        echo "=== END $(date -u +%FT%TZ) [$BUG_ID] ==="
    } >"$LOG" 2>&1

    # Extract failing test name from `FAIL: test-X` lines (automake
    # parallel-tests harness output). Path is bare — the binary lives
    # at the workspace root, not under tests/.
    FAILING=$(grep -E "^FAIL: test-" "$LOG" | head -1 | awk '{print $2}')
    echo -e "$BUG_ID\t$CASE_NUM\t$FAILING" | tee -a "$SUMMARY"
done

echo
echo "=== SUMMARY ==="
cat "$SUMMARY"
