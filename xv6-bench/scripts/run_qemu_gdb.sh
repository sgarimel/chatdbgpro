#!/bin/bash
# Boot xv6 in QEMU with GDB stub, run trigger program, capture panic.
# Usage: run_qemu_gdb.sh <bug_id> <trigger_name> <results_dir> <timeout_secs>
#
# This script:
#   1. Starts QEMU with GDB stub on port 1234
#   2. Connects GDB, sets breakpoint on panic()
#   3. Boots xv6, which runs init -> sh
#   4. Sends the trigger command to the xv6 console via QEMU monitor
#   5. Waits for panic breakpoint to hit (or timeout)
#   6. Dumps backtrace + relevant state to files for ChatDBG
#
# Must be run inside the Docker container.

set -e

BUG_ID="$1"
TRIGGER_NAME="$2"
RESULTS_DIR="$3"
TIMEOUT="${4:-120}"
BUILD_DIR="/xv6/builds/${BUG_ID}"

mkdir -p "${RESULTS_DIR}"

GDB_PORT=1234
QEMU_PID=""

cleanup() {
    if [ -n "$QEMU_PID" ] && kill -0 "$QEMU_PID" 2>/dev/null; then
        kill "$QEMU_PID" 2>/dev/null || true
        wait "$QEMU_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "[run] Starting QEMU for ${BUG_ID}..."

# Start QEMU in background with GDB stub and monitor on unix socket
cd "${BUILD_DIR}"
qemu-system-riscv64 \
    -machine virt -bios none \
    -kernel kernel/kernel \
    -m 128M -smp 1 -nographic \
    -global virtio-mmio.force-legacy=false \
    -drive file=fs.img,if=none,format=raw,id=x0 \
    -device virtio-blk-device,drive=x0,bus=virtio-mmio-bus.0 \
    -S -gdb tcp::${GDB_PORT} \
    -monitor unix:/tmp/qemu-monitor.sock,server,nowait \
    -serial unix:/tmp/qemu-serial.sock,server,nowait \
    &
QEMU_PID=$!
sleep 2

# Create GDB script that:
# 1. Connects to QEMU
# 2. Sets breakpoint on panic
# 3. Continues (boots xv6)
# 4. After boot, sends trigger command via QEMU monitor
# 5. When panic hits, dumps state
cat > /tmp/gdb_session.py << 'GDBSCRIPT'
import gdb
import subprocess
import time
import socket
import os
import json

TRIGGER_NAME = os.environ.get("TRIGGER_NAME", "trigfork")
RESULTS_DIR = os.environ.get("RESULTS_DIR", "/results")

def send_to_serial(text):
    """Send keystrokes to xv6 console via QEMU monitor."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect("/tmp/qemu-monitor.sock")
        sock.settimeout(2)
        # Drain any initial prompt
        try:
            sock.recv(4096)
        except:
            pass
        # Send keystrokes one at a time via monitor
        for ch in text:
            if ch == '\n':
                sock.sendall(b'sendkey ret\n')
            else:
                sock.sendall(f'sendkey {ch}\n'.encode())
            time.sleep(0.05)
        sock.close()
    except Exception as e:
        print(f"[gdb] Warning: could not send to serial: {e}")

class PanicBreakpoint(gdb.Breakpoint):
    """Custom breakpoint that fires when xv6 kernel calls panic()."""
    def __init__(self):
        super().__init__("panic", gdb.BP_BREAKPOINT)
        self.hit = False

    def stop(self):
        self.hit = True
        print("[gdb] *** PANIC breakpoint hit ***")

        # Capture backtrace
        bt = gdb.execute("bt", to_string=True)
        with open(f"{RESULTS_DIR}/backtrace.txt", "w") as f:
            f.write(bt)
        print(bt)

        # Capture panic message (first argument to panic)
        try:
            msg = gdb.execute("print (char*)$a0", to_string=True)
        except:
            msg = "(could not read panic message)"
        with open(f"{RESULTS_DIR}/panic_msg.txt", "w") as f:
            f.write(msg)

        # Capture local variables for each frame
        frame_info = []
        frame = gdb.newest_frame()
        depth = 0
        while frame and depth < 15:
            try:
                frame.select()
                name = frame.name() or "??"
                sal = frame.find_sal()
                filename = sal.symtab.filename if sal.symtab else "??"
                line = sal.line
                locals_str = gdb.execute("info locals", to_string=True)
                args_str = gdb.execute("info args", to_string=True)
                frame_info.append({
                    "depth": depth,
                    "function": name,
                    "file": filename,
                    "line": line,
                    "locals": locals_str.strip(),
                    "args": args_str.strip(),
                })
            except Exception as e:
                frame_info.append({"depth": depth, "error": str(e)})
            frame = frame.older()
            depth += 1

        with open(f"{RESULTS_DIR}/frames.json", "w") as f:
            json.dump(frame_info, f, indent=2)

        # Signal that we're done
        with open(f"{RESULTS_DIR}/panic_captured.flag", "w") as f:
            f.write("1")

        return True  # stop execution

# Also break on scause handler for page faults that don't reach panic
class UsertrapBreak(gdb.Breakpoint):
    """Break when usertrap handles an unexpected fault."""
    def __init__(self):
        # We set a conditional breakpoint in usertrap where it prints
        # "unexpected scause" and calls setkilled
        super().__init__("usertrap", gdb.BP_BREAKPOINT)
        self.count = 0

    def stop(self):
        self.count += 1
        # Only stop if this looks like a fatal fault (scause indicates fault)
        try:
            scause = gdb.execute("print/x $scause", to_string=True)
            # Page faults are scause 13 (load) or 15 (store) or 12 (instr)
            if any(x in scause for x in ["0xd", "0xf", "0xc"]):
                print(f"[gdb] *** Page fault in usertrap (scause={scause.strip()}) ***")

                bt = gdb.execute("bt", to_string=True)
                with open(f"{RESULTS_DIR}/backtrace.txt", "w") as f:
                    f.write(bt)

                frame_info = []
                frame = gdb.newest_frame()
                depth = 0
                while frame and depth < 15:
                    try:
                        frame.select()
                        name = frame.name() or "??"
                        sal = frame.find_sal()
                        filename = sal.symtab.filename if sal.symtab else "??"
                        line = sal.line
                        locals_str = gdb.execute("info locals", to_string=True)
                        args_str = gdb.execute("info args", to_string=True)
                        frame_info.append({
                            "depth": depth,
                            "function": name,
                            "file": filename,
                            "line": line,
                            "locals": locals_str.strip(),
                            "args": args_str.strip(),
                        })
                    except Exception as e:
                        frame_info.append({"depth": depth, "error": str(e)})
                    frame = frame.older()
                    depth += 1

                with open(f"{RESULTS_DIR}/frames.json", "w") as f:
                    json.dump(frame_info, f, indent=2)

                with open(f"{RESULTS_DIR}/panic_captured.flag", "w") as f:
                    f.write("1")
                return True  # stop
        except:
            pass
        return False  # don't stop for normal traps

# Set up
print("[gdb] Connecting to QEMU...")
gdb.execute("set pagination off")
gdb.execute("set confirm off")
gdb.execute(f"file {os.environ.get('BUILD_DIR', '/xv6/builds/bug1')}/kernel/kernel")
gdb.execute("target remote :1234")

# Set breakpoints
pb = PanicBreakpoint()

print("[gdb] Continuing boot...")
gdb.execute("continue &")

# Wait for xv6 to boot (it prints "init: starting sh" and "$" prompt)
time.sleep(8)

# Send trigger command
print(f"[gdb] Sending trigger command: {TRIGGER_NAME}")
send_to_serial(f"{TRIGGER_NAME}\n")

# Wait for breakpoint or timeout
import signal
def timeout_handler(signum, frame):
    print("[gdb] Timeout reached")
    # Interrupt and capture whatever state we have
    gdb.execute("interrupt")
    bt = gdb.execute("bt", to_string=True)
    with open(f"{RESULTS_DIR}/backtrace.txt", "w") as f:
        f.write(f"TIMEOUT - current state:\n{bt}")
    with open(f"{RESULTS_DIR}/panic_captured.flag", "w") as f:
        f.write("timeout")

TIMEOUT_SECS = int(os.environ.get("TIMEOUT", "60"))
signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(TIMEOUT_SECS)

# Wait for the panic breakpoint to fire
while not os.path.exists(f"{RESULTS_DIR}/panic_captured.flag"):
    time.sleep(1)

print("[gdb] Done. Quitting.")
gdb.execute("quit")
GDBSCRIPT

# Run GDB with the script
echo "[run] Launching GDB..."
TRIGGER_NAME="${TRIGGER_NAME}" \
RESULTS_DIR="${RESULTS_DIR}" \
BUILD_DIR="${BUILD_DIR}" \
TIMEOUT="${TIMEOUT}" \
gdb-multiarch -nx -batch -x /tmp/gdb_session.py 2>&1 | tee "${RESULTS_DIR}/gdb_output.log"

echo "[run] GDB session complete."
