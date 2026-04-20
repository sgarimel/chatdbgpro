"""Step 4: platform gate + injected-repo driver path.

Run with:
    python3 -m unittest bench.tests.test_step4 -v

These tests pin the two pieces of machinery step 4 added:
  - `Case.platform_supported()` and the `skipped_platform` status
    short-circuit in `Tier3Driver.run`.
  - `common._apply_patch_ops` unique-match contract, which is what
    makes `patch_ops` robust to upstream line-number drift.

They avoid real clones, real compiles, and real LLM calls: patch_ops
are exercised against a fake tmp tree, and the platform gate is
exercised by monkey-patching `current_platform`.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch as mock_patch

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from bench import common  # noqa: E402
from bench.common import (  # noqa: E402
    Case,
    RunSpec,
    _apply_patch_ops,
)
from bench.drivers.tier3_gdb import Tier3Driver  # noqa: E402


def _case(meta: dict, case_dir: Path | None = None) -> Case:
    return Case(
        case_id=meta.get("id", "x"),
        case_dir=case_dir or Path("/tmp/does-not-exist"),
        meta=meta,
    )


class TestPlatformGate(unittest.TestCase):

    def test_empty_platforms_means_any(self):
        c = _case({"build": {}})
        self.assertTrue(c.platform_supported())

    def test_matching_platform_supported(self):
        c = _case({"build": {"platforms": ["linux", "darwin"]}})
        with mock_patch.object(common, "current_platform", return_value="darwin"):
            self.assertTrue(c.platform_supported())

    def test_non_matching_platform_unsupported(self):
        c = _case({"build": {"platforms": ["linux"]}})
        with mock_patch.object(common, "current_platform", return_value="darwin"):
            self.assertFalse(c.platform_supported())

    def test_tier3_returns_skipped_platform_without_building(self):
        """If the case isn't supported here, the driver must short-circuit
        before any compile or subprocess work and emit a stable status."""
        with tempfile.TemporaryDirectory() as td:
            case_dir = Path(td) / "case"
            case_dir.mkdir()
            (case_dir / "case.yaml").write_text("id: x\n")  # content irrelevant
            meta = {
                "id": "plat-test",
                "kind": "injected_repo",
                "build": {"platforms": ["linux"]},
            }
            case = _case(meta, case_dir=case_dir)
            cfg_path = _REPO / "bench/configs/tier3_gdb_only.json"
            spec = RunSpec(
                case=case, model="fake/model",
                tool_config_path=cfg_path, trial=1,
            )
            run_dir = Path(td) / "run"
            drv = Tier3Driver(debugger="lldb")
            with mock_patch.object(common, "current_platform", return_value="darwin"):
                result = drv.run(spec, run_dir, timeout=10)
            self.assertEqual(result["status"], "skipped_platform")
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["elapsed_s"], 0.0)
            self.assertTrue((run_dir / "skip.log").exists())
            # No build/compile artifacts should have been produced.
            self.assertFalse((run_dir / "compile.log").exists())


class TestPatchOpsUniqueMatch(unittest.TestCase):

    def test_single_match_applies(self):
        with tempfile.TemporaryDirectory() as td:
            workdir = Path(td)
            (workdir / "src.c").write_text("int x = 1;\nreturn x;\n")
            ok, log = _apply_patch_ops(workdir, [
                {"file": "src.c", "before": "int x = 1;", "after": "int x = 2;"}
            ])
            self.assertTrue(ok, log)
            self.assertEqual((workdir / "src.c").read_text(),
                             "int x = 2;\nreturn x;\n")

    def test_zero_matches_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            workdir = Path(td)
            (workdir / "src.c").write_text("int x = 1;\n")
            ok, log = _apply_patch_ops(workdir, [
                {"file": "src.c", "before": "NOT THERE", "after": "x"}
            ])
            self.assertFalse(ok)
            self.assertIn("match count != 1", log)
            self.assertIn("0", log)  # reports the actual count

    def test_multiple_matches_fails_cleanly(self):
        """Ambiguous matches are the whole reason the format exists — a
        second copy of `before` must not be silently patched."""
        with tempfile.TemporaryDirectory() as td:
            workdir = Path(td)
            (workdir / "src.c").write_text("dup\n...\ndup\n")
            ok, log = _apply_patch_ops(workdir, [
                {"file": "src.c", "before": "dup", "after": "x"}
            ])
            self.assertFalse(ok)
            self.assertIn("match count != 1", log)

    def test_missing_file_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            ok, log = _apply_patch_ops(Path(td), [
                {"file": "no/such.c", "before": "x", "after": "y"}
            ])
            self.assertFalse(ok)
            self.assertIn("patch target missing", log)


class TestCjsonCaseShape(unittest.TestCase):
    """The cJSON injected case is the verified pilot; its manifest is the
    canonical example of the injected-repo schema. Guard the fields that
    the driver dispatches on so renames are caught locally."""

    def setUp(self):
        import yaml
        p = _REPO / "bench/cases/injected/cjson-parse-string-oob/case.yaml"
        self.meta = yaml.safe_load(p.read_text())

    def test_kind_is_injected_repo(self):
        self.assertEqual(self.meta["kind"], "injected_repo")

    def test_has_debug_block(self):
        self.assertIn("debug", self.meta)
        self.assertIn("stdin_data", self.meta["debug"])

    def test_has_patch_ops(self):
        ops = self.meta["bug"]["patch_ops"]
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["file"], "cJSON.c")

    def test_ships_driver_asset(self):
        assets = self.meta["build"]["assets"]
        self.assertTrue(any(a["dst"] == "bench_driver.c" for a in assets))

    def test_is_marked_verified(self):
        self.assertTrue(self.meta.get("verified"))


if __name__ == "__main__":
    unittest.main()
