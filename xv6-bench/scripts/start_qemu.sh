#!/bin/bash
# Start QEMU with GDB stub for a built xv6 directory.
# Usage: ./scripts/start_qemu.sh build-bug1
#
# This starts QEMU paused (-S) with GDB stub on port 1234.
# Connect with: lldb kernel/kernel -o "gdb-remote 1234"
# Or run: python3 scripts/run_chatdbg_xv6.py --build-dir build-bug1

set -e
BUILD_DIR="${1:?Usage: $0 <build-dir>}"
cd "$(dirname "$0")/.."

KERN="${BUILD_DIR}/kernel/kernel"
FSIMG="${BUILD_DIR}/fs.img"

[ -f "$KERN" ] || { echo "ERROR: $KERN not found"; exit 1; }
[ -f "$FSIMG" ] || { echo "ERROR: $FSIMG not found"; exit 1; }

echo "Starting QEMU with GDB stub on port 1234..."
echo "Connect with: lldb $KERN -o 'gdb-remote 1234'"
echo "Press Ctrl-A X to quit QEMU."
echo ""

exec qemu-system-riscv64 \
  -machine virt -bios none \
  -kernel "$KERN" \
  -m 128M -smp 1 -nographic \
  -global virtio-mmio.force-legacy=false \
  -drive file="$FSIMG",if=none,format=raw,id=x0 \
  -device virtio-blk-device,drive=x0,bus=virtio-mmio-bus.0 \
  -S -gdb tcp::1234
