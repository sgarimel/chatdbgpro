"""Smoke + behavior tests for bench/drivers/container_session.py.

These tests need a running Docker daemon. They use small images already
on most dev machines (ubuntu:24.04 multi-arch). Skipped if `docker
info` fails.

Run: python -m pytest bench/tests/test_container_session.py -xvs
or:  python bench/tests/test_container_session.py    (smoke only)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from bench.drivers.container_session import ContainerSession, Mount, prune_sweep


def _docker_available() -> bool:
    try:
        r = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


@unittest.skipUnless(_docker_available(), "docker daemon required")
class ContainerSessionTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Use the host's native arch to avoid emulation cost in CI/dev.
        # This test is about the ContainerSession API, not amd64 emulation.
        import platform
        arch = platform.machine().lower()
        cls.platform = "linux/arm64" if arch in ("arm64", "aarch64") else "linux/amd64"
        cls.image = "ubuntu:24.04"
        # Make sure image is present (multi-arch manifest, pulls once).
        subprocess.run(
            ["docker", "pull", "--platform", cls.platform, cls.image],
            capture_output=True, text=True, timeout=120,
        )

    def _make_workspace(self) -> Path:
        ws = Path(tempfile.mkdtemp(prefix="ws-test-"))
        (ws / "hello.txt").write_text("hi\n")
        (ws / "subdir").mkdir()
        (ws / "subdir" / "nested.txt").write_text("nested\n")
        return ws

    def test_smoke_lifecycle(self):
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="run-test-"))
        with ContainerSession(
            image=self.image, workspace_src=ws, run_dir=run_dir,
            platform=self.platform,
        ) as s:
            r = s.exec("echo hello")
            self.assertTrue(r.ok, f"exec failed: {r}")
            self.assertEqual(r.stdout.strip(), "hello")

    def test_workspace_mounted_at_work(self):
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="run-test-"))
        with ContainerSession(
            image=self.image, workspace_src=ws, run_dir=run_dir,
            platform=self.platform,
        ) as s:
            r = s.exec("cat /work/hello.txt")
            self.assertEqual(r.stdout, "hi\n")
            r = s.exec("cat /work/subdir/nested.txt")
            self.assertEqual(r.stdout, "nested\n")

    def test_hermetic_workspace(self):
        """Mutations inside the container must NOT touch workspace_src."""
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="run-test-"))
        with ContainerSession(
            image=self.image, workspace_src=ws, run_dir=run_dir,
            platform=self.platform, hermetic_workspace=True,
        ) as s:
            r = s.exec("echo polluted > /work/hello.txt && cat /work/hello.txt")
            self.assertIn("polluted", r.stdout)
        # Original workspace should be unchanged.
        self.assertEqual((ws / "hello.txt").read_text(), "hi\n")

    def test_run_dir_writable(self):
        """collect.json round-trip via /run mount."""
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="run-test-"))
        with ContainerSession(
            image=self.image, workspace_src=ws, run_dir=run_dir,
            platform=self.platform,
        ) as s:
            r = s.exec("echo '{\"x\":1}' > /run/result.json")
            self.assertTrue(r.ok)
        self.assertEqual((run_dir / "result.json").read_text().strip(), '{"x":1}')

    def test_cwd_preserved_within_session(self):
        """Implicit: each exec is its own bash, so cwd doesn't persist
        across exec calls. We DO support explicit cwd= per call. This is
        the documented behavior — model uses absolute paths or `cd`
        inside one command."""
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="run-test-"))
        with ContainerSession(
            image=self.image, workspace_src=ws, run_dir=run_dir,
            platform=self.platform,
        ) as s:
            r = s.exec("pwd", cwd="/run")
            self.assertEqual(r.stdout.strip(), "/run")
            r = s.exec("pwd")
            self.assertEqual(r.stdout.strip(), "/work")

    def test_env_passthrough(self):
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="run-test-"))
        with ContainerSession(
            image=self.image, workspace_src=ws, run_dir=run_dir,
            platform=self.platform, env={"FOO": "bar123"},
        ) as s:
            r = s.exec("echo $FOO")
            self.assertEqual(r.stdout.strip(), "bar123")
            # Per-exec override.
            r = s.exec("echo $BAR", env={"BAR": "perexec"})
            self.assertEqual(r.stdout.strip(), "perexec")

    def test_timeout(self):
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="run-test-"))
        with ContainerSession(
            image=self.image, workspace_src=ws, run_dir=run_dir,
            platform=self.platform,
        ) as s:
            r = s.exec("sleep 5", timeout=1.5)
            self.assertTrue(r.timed_out, f"expected timeout, got {r}")

    def test_streaming_for_interactive_subproc(self):
        """exec_streaming returns a Popen with line-buffered text I/O."""
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="run-test-"))
        with ContainerSession(
            image=self.image, workspace_src=ws, run_dir=run_dir,
            platform=self.platform,
        ) as s:
            # `cat` with stdin echoed line-by-line — same shape as gdb.
            proc = s.exec_streaming(["cat"])
            try:
                proc.stdin.write("hello\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
                self.assertEqual(line.strip(), "hello")
            finally:
                proc.stdin.close()
                proc.wait(timeout=5)

    def test_cleanup_on_exception(self):
        """If an error happens between __enter__ and __exit__, the
        container is still removed."""
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="run-test-"))
        name = None
        try:
            with ContainerSession(
                image=self.image, workspace_src=ws, run_dir=run_dir,
                platform=self.platform,
            ) as s:
                name = s.container_name
                # Verify it's there:
                r = subprocess.run(
                    ["docker", "ps", "--filter", f"name={name}", "-q"],
                    capture_output=True, text=True,
                )
                self.assertTrue(r.stdout.strip(), "container should be running")
                raise RuntimeError("boom")
        except RuntimeError as e:
            self.assertEqual(str(e), "boom")
        # Container should be gone.
        r = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={name}", "-q"],
            capture_output=True, text=True,
        )
        self.assertFalse(r.stdout.strip(), f"container {name} not cleaned up")

    def test_extra_mount_readonly(self):
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="run-test-"))
        ro_src = Path(tempfile.mkdtemp(prefix="ro-test-"))
        (ro_src / "fact.txt").write_text("read-only\n")
        with ContainerSession(
            image=self.image, workspace_src=ws, run_dir=run_dir,
            platform=self.platform,
            extra_mounts=[Mount(host=ro_src, container="/aux", readonly=True)],
        ) as s:
            r = s.exec("cat /aux/fact.txt")
            self.assertEqual(r.stdout, "read-only\n")
            r = s.exec("echo nope > /aux/fact.txt 2>&1")
            self.assertNotEqual(r.returncode, 0)

    def test_sweep_label_prune(self):
        ws = self._make_workspace()
        run_dir = Path(tempfile.mkdtemp(prefix="run-test-"))
        sweep = f"test-sweep-{os.getpid()}-{int(time.time())}"
        with ContainerSession(
            image=self.image, workspace_src=ws, run_dir=run_dir,
            platform=self.platform, sweep_label=sweep,
        ) as s:
            self.assertTrue(s.exec("true").ok)
            # Don't __exit__ — emulate a leaked container by NOT cleaning.
            # (We can't really "leak" inside a with block, so just verify
            # prune_sweep finds 0 after __exit__.)
            pass
        n = prune_sweep(sweep)
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
