"""Smoke test the apptainer backend of ContainerSession.

Exercises the four properties that matter for hosting BugsCPP T2/T3:

  1. instance start / exec / stop lifecycle works
  2. bind mounts survive (workspace at /work, run_dir at /run)
  3. ptrace works inside the container (gdb on a real ELF)
  4. exec_streaming pipes line-buffered stdio (for persistent gdb)

Designed to run on a fresh adroit account with no chatdbgpro images
present — uses `docker://docker.io/library/alpine:latest` (small) for
lifecycle tests and falls back to building a minimal Ubuntu image with
gcc+gdb at first call for the ptrace test.

Run:
  python bench/tests/test_apptainer_smoke.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from bench.drivers.container_session import (
    ContainerSession, Mount, prune_sweep, set_default_runtime,
)


def _have_apptainer() -> bool:
    return bool(shutil.which("apptainer") or shutil.which("singularity"))


# Small lifecycle image — alpine is ~5MB, pulls fast.
SMALL_IMAGE = os.environ.get(
    "BENCH_APPTAINER_SMOKE_IMAGE",
    "docker://docker.io/library/alpine:latest",
)
# gdb-capable image — ubuntu:24.04 ships gdb in its package mirror; we
# install at first run inside the container so we don't need a custom
# .sif. ~80MB pull. Override via env var if you have a pre-built sif.
GDB_IMAGE = os.environ.get(
    "BENCH_APPTAINER_GDB_IMAGE",
    "docker://docker.io/library/ubuntu:24.04",
)


@unittest.skipUnless(_have_apptainer(), "apptainer not on PATH")
class ApptainerSmokeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        set_default_runtime("apptainer")

    @classmethod
    def tearDownClass(cls):
        set_default_runtime(None)

    def _make_workspace(self) -> Path:
        ws = Path(tempfile.mkdtemp(prefix="aptw-"))
        (ws / "hello.txt").write_text("hi\n")
        return ws

    def test_lifecycle(self):
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="aptr-"))
        with ContainerSession(
            image=SMALL_IMAGE, workspace_src=ws, run_dir=run_dir,
            runtime="apptainer",
        ) as s:
            r = s.exec("echo hello")
            self.assertTrue(r.ok, f"exec failed: rc={r.returncode} stderr={r.stderr}")
            self.assertEqual(r.stdout.strip(), "hello")

    def test_workspace_mount(self):
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="aptr-"))
        with ContainerSession(
            image=SMALL_IMAGE, workspace_src=ws, run_dir=run_dir,
            runtime="apptainer",
        ) as s:
            r = s.exec("cat /work/hello.txt")
            self.assertEqual(r.stdout, "hi\n")

    def test_run_dir_writable(self):
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="aptr-"))
        with ContainerSession(
            image=SMALL_IMAGE, workspace_src=ws, run_dir=run_dir,
            runtime="apptainer",
        ) as s:
            r = s.exec("echo '{\"x\":1}' > /run/result.json")
            self.assertTrue(r.ok)
        self.assertEqual(
            (run_dir / "result.json").read_text().strip(), '{"x":1}',
        )

    def test_env_passthrough(self):
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="aptr-"))
        with ContainerSession(
            image=SMALL_IMAGE, workspace_src=ws, run_dir=run_dir,
            runtime="apptainer", env={"FOO": "bar123"},
        ) as s:
            r = s.exec("echo $FOO")
            self.assertEqual(r.stdout.strip(), "bar123")

    def test_ptrace_inside_container(self):
        """The crown jewel: confirm gdb's ptrace works inside an
        apptainer-managed container (which is the actual blocker on
        Apple Silicon's docker/Rosetta path)."""
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="aptr-"))
        with ContainerSession(
            image=GDB_IMAGE, workspace_src=ws, run_dir=run_dir,
            runtime="apptainer", ptrace=True,
        ) as s:
            # ubuntu:24.04 ships without gcc/gdb; install first.
            install = s.exec(
                "apt-get update -qq >/dev/null 2>&1 && "
                "apt-get install -y -qq gcc gdb >/dev/null 2>&1; "
                "command -v gcc && command -v gdb",
                timeout=300.0,
            )
            if not install.ok:
                # On adroit, apt won't have privileges; skip with a
                # diagnostic. The actual pilot will use chatdbgpro/gdb-*
                # images which already contain gdb so this isn't a
                # regression of the harness — just of the smoke test.
                self.skipTest(
                    f"can't install gcc/gdb in this image: {install.stdout}\n"
                    f"{install.stderr}"
                )
            # Compile a SEGV program.
            compile_r = s.exec(
                "cat > /tmp/t.c << 'EOF'\n"
                "int main(){ int *p = 0; *p = 1; return 0; }\n"
                "EOF\n"
                "gcc -g /tmp/t.c -o /tmp/t",
                timeout=30.0,
            )
            self.assertTrue(compile_r.ok, f"compile failed: {compile_r.stderr}")
            # Run gdb. ptrace works → real backtrace; ptrace blocked →
            # 'Function not implemented' (or worse).
            gdb_r = s.exec(
                "gdb -nx -batch -ex run -ex 'bt 1' -ex quit /tmp/t 2>&1",
                timeout=30.0,
            )
            self.assertNotIn("Function not implemented", gdb_r.stdout,
                             f"ptrace blocked: {gdb_r.stdout}")
            self.assertNotIn("Cannot PTRACE_GETREGS", gdb_r.stdout,
                             f"PTRACE_GETREGS broken: {gdb_r.stdout}")
            self.assertIn("SIGSEGV", gdb_r.stdout,
                          f"expected SIGSEGV; got: {gdb_r.stdout}")
            self.assertIn("main", gdb_r.stdout,
                          f"expected backtrace frame in main; got: {gdb_r.stdout}")

    def test_streaming_for_gdb(self):
        """exec_streaming returns a Popen with line-buffered text I/O;
        T2's GdbSession depends on the same protocol working under
        apptainer as it does under docker."""
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="aptr-"))
        with ContainerSession(
            image=SMALL_IMAGE, workspace_src=ws, run_dir=run_dir,
            runtime="apptainer",
        ) as s:
            proc = s.exec_streaming(["cat"])
            try:
                proc.stdin.write("hello\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
                self.assertEqual(line.strip(), "hello")
            finally:
                proc.stdin.close()
                proc.wait(timeout=10)

    def test_cleanup_on_exception(self):
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="aptr-"))
        name = None
        try:
            with ContainerSession(
                image=SMALL_IMAGE, workspace_src=ws, run_dir=run_dir,
                runtime="apptainer",
            ) as s:
                name = s.container_name
                # Verify instance exists.
                cli = shutil.which("apptainer") or shutil.which("singularity")
                r = subprocess.run([cli, "instance", "list"],
                                   capture_output=True, text=True)
                self.assertIn(name, r.stdout, "instance not in list")
                raise RuntimeError("boom")
        except RuntimeError as e:
            self.assertEqual(str(e), "boom")
        # Verify cleaned up.
        cli = shutil.which("apptainer") or shutil.which("singularity")
        r = subprocess.run([cli, "instance", "list"],
                           capture_output=True, text=True)
        self.assertNotIn(name, r.stdout, f"instance {name} not cleaned up")


if __name__ == "__main__":
    unittest.main(verbosity=2)
