#!/bin/bash
# Build xv6-riscv with a specific bug patch and trigger program.
# Usage: build_bug.sh <bug_id> <patch_file> <trigger_src>
#
# This script:
#   1. Copies clean xv6 source to a build directory
#   2. Applies the bug patch
#   3. Adds the trigger program to the Makefile's UPROGS
#   4. Builds the kernel + filesystem image
#
# Must be run inside the Docker container.

set -e

BUG_ID="$1"
PATCH_FILE="$2"
TRIGGER_SRC="$3"
BUILD_DIR="/xv6/builds/${BUG_ID}"

echo "[build_bug] Bug: ${BUG_ID}"
echo "[build_bug] Patch: ${PATCH_FILE}"
echo "[build_bug] Trigger: ${TRIGGER_SRC}"

# Clean build directory
rm -rf "${BUILD_DIR}"
cp -r /xv6/xv6-riscv "${BUILD_DIR}"

# Copy trigger program into user/
TRIGGER_NAME=$(basename "${TRIGGER_SRC}" .c)
cp "${TRIGGER_SRC}" "${BUILD_DIR}/user/${TRIGGER_NAME}.c"

# Add trigger to UPROGS in Makefile
# Insert before the last backslash-continuation line in UPROGS
sed -i "/\\\$U\/_zombie\\\\$/a\\\\t\$U/_${TRIGGER_NAME}\\\\" "${BUILD_DIR}/Makefile"

# Apply bug patch
cd "${BUILD_DIR}"
patch -p1 < "${PATCH_FILE}"

# Build
echo "[build_bug] Building xv6 with bug ${BUG_ID}..."
make -j$(nproc) kernel/kernel fs.img 2>&1 | tail -5

echo "[build_bug] Build complete: ${BUILD_DIR}"
ls -la "${BUILD_DIR}/kernel/kernel" "${BUILD_DIR}/fs.img"
