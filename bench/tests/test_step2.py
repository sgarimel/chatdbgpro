"""Step 2: enable_bash flag + llm_bash tool.

Run with:
    python3 -m unittest bench.tests.test_step2 -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from chatdbg.native_util.dbg_dialog import DBGDialog  # noqa: E402
from chatdbg.util.config import ChatDBGConfig, chatdbg_config  # noqa: E402


# --------------------------------------------------------------------------- #
# Config flag
# --------------------------------------------------------------------------- #

class TestEnableBashFlag(unittest.TestCase):

    def test_flag_is_registered(self):
        self.assertIn("enable_bash", ChatDBGConfig._tool_flags)

    def test_flag_defaults_to_true(self):
        cfg = ChatDBGConfig()
        self.assertTrue(cfg.enable_bash)

    def test_tier2_preset_enables_bash(self):
        cfg = ChatDBGConfig()
        cfg.tool_config = str(_REPO / "bench/configs/tier2_bash_plus_gdb.json")
        cfg.apply_tool_config()
        self.assertTrue(cfg.enable_bash)
        self.assertTrue(cfg.enable_native_debug)

    def test_tier3_preset_disables_bash(self):
        cfg = ChatDBGConfig()
        cfg.tool_config = str(_REPO / "bench/configs/tier3_gdb_only.json")
        cfg.apply_tool_config()
        self.assertFalse(cfg.enable_bash)
        self.assertTrue(cfg.enable_native_debug)

    def test_ad_hoc_config_false(self):
        cfg = ChatDBGConfig()
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"enable_bash": False}, f)
            path = f.name
        try:
            cfg.tool_config = path
            cfg.apply_tool_config()
            self.assertFalse(cfg.enable_bash)
        finally:
            os.unlink(path)


# --------------------------------------------------------------------------- #
# llm_bash tool
# --------------------------------------------------------------------------- #

class TestLlmBashTool(unittest.TestCase):

    def setUp(self):
        self.dlg = DBGDialog(prompt="")

    def test_tool_schema_valid_json(self):
        schema = json.loads(self.dlg.llm_bash.__doc__)
        self.assertEqual(schema["name"], "bash")
        self.assertEqual(schema["parameters"]["required"], ["command"])
        self.assertIn("command", schema["parameters"]["properties"])

    def test_basic_stdout(self):
        desc, body = self.dlg.llm_bash("echo hello")
        self.assertEqual(desc, "bash: echo hello")
        self.assertIn("hello", body)
        self.assertIn("[exit=0]", body)

    def test_nonzero_exit_code_surfaces(self):
        _, body = self.dlg.llm_bash("false")
        self.assertIn("[exit=1]", body)

    def test_stderr_is_labelled(self):
        _, body = self.dlg.llm_bash("echo oops 1>&2")
        self.assertIn("[stderr]", body)
        self.assertIn("oops", body)

    def test_stdout_and_stderr_together(self):
        _, body = self.dlg.llm_bash("echo out; echo err 1>&2")
        self.assertIn("out", body)
        self.assertIn("[stderr]", body)
        self.assertIn("err", body)

    def test_no_output_placeholder(self):
        _, body = self.dlg.llm_bash("true")
        self.assertIn("[no output]", body)
        self.assertIn("[exit=0]", body)

    def test_large_output_is_truncated(self):
        # 10 000 'x' chars — blows through the 8 KB cap.
        _, body = self.dlg.llm_bash("python3 -c \"print('x' * 10000)\"")
        self.assertIn("truncated", body)
        # Still within a reasonable envelope around the cap.
        self.assertLess(len(body), 9000)

    def test_pipeline_and_redirect(self):
        _, body = self.dlg.llm_bash("printf 'a\\nb\\nc\\n' | wc -l")
        self.assertIn("3", body)
        self.assertIn("[exit=0]", body)

    def test_timeout(self):
        with patch(
            "chatdbg.native_util.dbg_dialog.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="sleep", timeout=30),
        ):
            desc, body = self.dlg.llm_bash("sleep 99")
        self.assertEqual(desc, "bash: sleep 99")
        self.assertIn("timed out", body.lower())

    def test_unexpected_exception(self):
        with patch(
            "chatdbg.native_util.dbg_dialog.subprocess.run",
            side_effect=OSError("boom"),
        ):
            _, body = self.dlg.llm_bash("ls")
        self.assertIn("bash call failed", body)
        self.assertIn("boom", body)

    def test_working_directory_is_inherited(self):
        """A fresh subprocess inherits the caller's cwd by default, so the
        bash tool should report the same path as os.getcwd()."""
        _, body = self.dlg.llm_bash("pwd")
        self.assertIn(os.getcwd(), body)


# --------------------------------------------------------------------------- #
# _supported_functions wiring
# --------------------------------------------------------------------------- #

class TestSupportedFunctionsWiring(unittest.TestCase):

    def setUp(self):
        self._saved = chatdbg_config.enable_bash

    def tearDown(self):
        chatdbg_config.enable_bash = self._saved

    def test_included_when_enabled(self):
        chatdbg_config.enable_bash = True
        dlg = DBGDialog(prompt="")
        names = [f.__name__ for f in dlg._supported_functions()]
        self.assertIn("llm_bash", names)

    def test_excluded_when_disabled(self):
        chatdbg_config.enable_bash = False
        dlg = DBGDialog(prompt="")
        names = [f.__name__ for f in dlg._supported_functions()]
        self.assertNotIn("llm_bash", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
