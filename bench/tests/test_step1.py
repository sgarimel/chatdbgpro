"""Pin the Step 1 refactor: verify that extracting tier-3 into a Driver
preserved the exact behaviour of the pre-refactor execute_run.

Each test checks one slice of the old behaviour — script content, argv,
env, cwd, timeout plumbing, clean_env stripping, compile-fail early
return, timeout early return, RunSpec defaults, run_id format, driver
registry — without requiring a real debugger subprocess or an LLM call.

Run with:
    python3 -m unittest bench.tests.test_step1 -v
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from bench.common import (
    BENCH_DIR,
    REPO_DIR,
    Case,
    RunSpec,
    build_matrix,
    discover_cases,
    run_id_for,
)
from bench.drivers import get_driver
from bench.drivers.tier3_gdb import (
    Tier3Driver,
    build_gdb_script,
    build_lldb_script,
    pick_debugger,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _dummy_case(case_id="dummy", args=None, stdin_file=None, language="c") -> Case:
    meta = {
        "id": case_id,
        "source_file": "prog.c",
        "language": language,
        "run": {"args": args or []},
    }
    if stdin_file:
        meta["run"]["stdin_file"] = stdin_file
    return Case(case_id=case_id, case_dir=Path("/tmp"), meta=meta)


def _real_case(case_id: str) -> Case:
    for c in discover_cases(only=[case_id]):
        return c
    raise AssertionError(f"No case named {case_id}")


def _real_cfg(name: str) -> Path:
    return (BENCH_DIR / "configs" / f"{name}.json").resolve()


def _fake_cp(args, returncode, stdout="", stderr=""):
    m = MagicMock()
    m.args = args
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


_TMP_ROOT = BENCH_DIR / "results" / "__test_step1__"
_TMP_COUNTER = [0]


def _tmp_run_dir(label: str) -> Path:
    _TMP_COUNTER[0] += 1
    p = _TMP_ROOT / f"{label}_{os.getpid()}_{_TMP_COUNTER[0]}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def setUpModule():
    if _TMP_ROOT.exists():
        shutil.rmtree(_TMP_ROOT)
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Factory / RunSpec / run_id
# --------------------------------------------------------------------------- #

class TestRunSpecAndFactory(unittest.TestCase):

    def test_runspec_tier_default_is_3(self):
        spec = RunSpec(
            case=_dummy_case(), model="m",
            tool_config_path=Path("/tmp/x.json"), trial=1,
        )
        self.assertEqual(spec.tier, 3)
        self.assertEqual(spec.context_lines, 10)

    def test_run_id_for_format(self):
        spec = RunSpec(
            case=_dummy_case(case_id="c1"),
            model="openrouter/foo/bar",
            tool_config_path=Path("/tmp/all_tools.json"),
            trial=2, context_lines=8, tier=3,
        )
        self.assertEqual(
            run_id_for(spec),
            "c1__tier3__openrouter_foo_bar__all_tools__ctx8__t2",
        )

    def test_run_id_for_differs_by_tier(self):
        mk = lambda tier: RunSpec(
            case=_dummy_case(case_id="c"),
            model="m", tool_config_path=Path("/x.json"),
            trial=1, tier=tier,
        )
        self.assertNotEqual(run_id_for(mk(1)), run_id_for(mk(3)))
        self.assertIn("tier1", run_id_for(mk(1)))
        self.assertIn("tier3", run_id_for(mk(3)))

    def test_get_driver_tier3(self):
        d = get_driver(3, debugger="lldb", dry_run=True)
        self.assertIsInstance(d, Tier3Driver)
        self.assertEqual(d.tier, 3)
        self.assertEqual(d.debugger, "lldb")
        self.assertTrue(d.dry_run)

    def test_get_driver_unimplemented_tiers(self):
        for t in (1, 2):
            with self.assertRaises(NotImplementedError):
                get_driver(t)

    def test_get_driver_invalid_tier(self):
        with self.assertRaises(ValueError):
            get_driver(99)


# --------------------------------------------------------------------------- #
# build_matrix with tiers
# --------------------------------------------------------------------------- #

class TestBuildMatrix(unittest.TestCase):

    def test_matrix_cardinality(self):
        case = _dummy_case()
        specs = build_matrix(
            cases=[case, case],
            models=["m1", "m2", "m3"],
            tool_configs=[Path("/a.json"), Path("/b.json")],
            trials=2,
            context_lines=[5, 10],
            tiers=[3],
        )
        self.assertEqual(len(specs), 2 * 3 * 2 * 2 * 2 * 1)

    def test_matrix_spans_tiers(self):
        case = _dummy_case()
        specs = build_matrix(
            cases=[case], models=["m"],
            tool_configs=[Path("/c.json")],
            trials=1, context_lines=[10],
            tiers=[1, 2, 3],
        )
        self.assertEqual(sorted(s.tier for s in specs), [1, 2, 3])

    def test_matrix_default_preserves_legacy(self):
        case = _dummy_case()
        specs = build_matrix(
            cases=[case], models=["m"],
            tool_configs=[Path("/c.json")],
            trials=1, context_lines=[10],
            tiers=[3],
        )
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].tier, 3)


# --------------------------------------------------------------------------- #
# Pure script builders (parity with pre-refactor output)
# --------------------------------------------------------------------------- #

class TestScriptBuilders(unittest.TestCase):

    def test_lldb_script_with_args(self):
        case = _dummy_case(args=["10", "20", "30"])
        got = build_lldb_script(Path("/tmp/prog"), case, "why-q")
        self.assertEqual(got, (
            "command script import chatdbg.chatdbg_lldb\n"
            "settings set target.run-args 10 20 30\n"
            "run\n"
            "why why-q\n"
        ))

    def test_lldb_script_no_args(self):
        got = build_lldb_script(Path("/tmp/prog"), _dummy_case(args=[]), "q")
        self.assertEqual(got, "command script import chatdbg.chatdbg_lldb\nrun\nwhy q\n")

    def test_lldb_script_quotes_special_chars(self):
        case = _dummy_case(args=["a b", "c;d"])
        got = build_lldb_script(Path("/tmp/prog"), case, "q")
        self.assertIn("settings set target.run-args 'a b' 'c;d'\n", got)

    def test_lldb_script_honours_stdin_file(self):
        case = _dummy_case(args=[], stdin_file="/tmp/in.txt")
        got = build_lldb_script(Path("/tmp/prog"), case, "q")
        self.assertIn("settings set target.input-path /tmp/in.txt\n", got)

    def test_gdb_script_basic(self):
        got = build_gdb_script(Path("/tmp/prog"), _dummy_case(args=["1"]), "q")
        self.assertEqual(got, "source -s chatdbg.chatdbg_gdb\nset args 1\nrun\nwhy q\n")


# --------------------------------------------------------------------------- #
# pick_debugger
# --------------------------------------------------------------------------- #

class TestPickDebugger(unittest.TestCase):

    def test_explicit_override_wins(self):
        self.assertEqual(pick_debugger("gdb"), "gdb")
        self.assertEqual(pick_debugger("lldb"), "lldb")

    def test_autodetect_on_darwin_prefers_lldb(self):
        with patch("bench.drivers.tier3_gdb.platform.system", return_value="Darwin"), \
             patch("bench.drivers.tier3_gdb.shutil.which",
                   side_effect=lambda n: "/usr/bin/lldb" if n == "lldb" else None):
            self.assertEqual(pick_debugger(None), "lldb")

    def test_autodetect_linux_prefers_gdb(self):
        with patch("bench.drivers.tier3_gdb.platform.system", return_value="Linux"), \
             patch("bench.drivers.tier3_gdb.shutil.which",
                   side_effect=lambda n: f"/usr/bin/{n}" if n in ("gdb", "lldb") else None):
            self.assertEqual(pick_debugger(None), "gdb")

    def test_autodetect_raises_when_neither_found(self):
        with patch("bench.drivers.tier3_gdb.platform.system", return_value="Linux"), \
             patch("bench.drivers.tier3_gdb.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError):
                pick_debugger(None)


# --------------------------------------------------------------------------- #
# Tier3Driver.run — happy path with mocked compile + debugger
# --------------------------------------------------------------------------- #

class TestTier3DriverHappyPath(unittest.TestCase):

    def test_happy_path_lldb(self):
        case = _real_case("off-by-one-crc")
        cfg = _real_cfg("all_tools")
        spec = RunSpec(case=case, model="fake-model", tool_config_path=cfg, trial=1)
        run_dir = _tmp_run_dir("happy_lldb")

        driver = Tier3Driver(debugger="lldb", dry_run=False)

        fake_binary = run_dir / "build" / "prog"
        fake_compile_cp = _fake_cp(
            args=["clang", "-g", case.source_path.name, "-o", str(fake_binary)],
            returncode=0,
        )

        captured = {}

        def fake_dbg_run(argv, **kwargs):
            # Simulate a successful debugger run; write collect.json so the
            # driver labels the run status="ok".
            (run_dir / "collect.json").write_text('{"meta": {}, "queries": []}')
            captured["argv"] = list(argv)
            captured["env"] = dict(kwargs.get("env") or {})
            captured["cwd"] = kwargs.get("cwd")
            captured["input"] = kwargs.get("input")
            captured["timeout"] = kwargs.get("timeout")
            return _fake_cp(args=argv, returncode=0, stdout="OUT", stderr="ERR")

        with patch("bench.drivers.tier3_gdb.compile_case",
                   return_value=(fake_compile_cp, fake_binary)), \
             patch("bench.drivers.tier3_gdb.lldb_binary", return_value="lldb"), \
             patch("bench.drivers.tier3_gdb.subprocess.run", side_effect=fake_dbg_run):
            result = driver.run(spec, run_dir, timeout=42.0)

        # Archived case source & metadata next to run
        self.assertTrue((run_dir / case.source_path.name).exists())
        self.assertTrue((run_dir / "case.yaml").exists())
        # Side-effects written in the right order
        self.assertIn("$ clang", (run_dir / "compile.log").read_text())
        self.assertEqual((run_dir / "stdout.log").read_text(), "OUT")
        self.assertEqual((run_dir / "stderr.log").read_text(), "ERR")
        # session.cmds matches the pre-refactor lldb script builder
        self.assertEqual(
            (run_dir / "session.cmds").read_text(),
            build_lldb_script(fake_binary, case, spec.question),
        )

        # argv: lldb reads commands from `-s session.cmds` rather than
        # via stdin. Piping via stdin makes the launched target inherit
        # lldb's stdin and prevents stop events from surfacing.
        self.assertEqual(captured["argv"], [
            "lldb",
            "-o", "settings set use-color false",
            "-s", str(run_dir / "session.cmds"),
            "--", str(fake_binary),
        ])
        # No stdin payload — the script is read via -s.
        self.assertIsNone(captured["input"])
        self.assertEqual(captured["timeout"], 42.0)
        self.assertEqual(Path(captured["cwd"]), run_dir)

        # env contains the exact CHATDBG_* keys the old code set
        env = captured["env"]
        self.assertEqual(env["CHATDBG_MODEL"], "fake-model")
        self.assertEqual(env["CHATDBG_TOOL_CONFIG"], str(cfg))
        self.assertEqual(env["CHATDBG_CONTEXT"], "10")
        self.assertEqual(env["CHATDBG_FORMAT"], "text")
        self.assertTrue(env["CHATDBG_COLLECT_DATA"].endswith("collect.json"))
        self.assertTrue(env["CHATDBG_LOG"].endswith("chatdbg.log.yaml"))
        # PYTHONPATH must prepend the repo's src/ so the local chatdbg wins
        self.assertEqual(
            env["PYTHONPATH"].split(os.pathsep)[0],
            str(REPO_DIR / "src"),
        )

        # Result dict
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["tier"], 3)
        self.assertEqual(result["case_id"], "off-by-one-crc")
        self.assertEqual(result["collect_path"], "collect.json")
        # And it's been persisted to result.json identically
        import json
        persisted = json.loads((run_dir / "result.json").read_text())
        self.assertEqual(persisted, result)

    def test_happy_path_gdb_argv_and_script(self):
        case = _real_case("off-by-one-crc")
        spec = RunSpec(case=case, model="m",
                       tool_config_path=_real_cfg("all_tools"), trial=1)
        run_dir = _tmp_run_dir("happy_gdb")
        driver = Tier3Driver(debugger="gdb", dry_run=False)

        fake_binary = run_dir / "build" / "prog"
        fake_cp = _fake_cp(args=["clang"], returncode=0)

        captured = {}

        def fake_dbg_run(argv, **kwargs):
            captured["argv"] = list(argv)
            return _fake_cp(args=argv, returncode=0)

        with patch("bench.drivers.tier3_gdb.compile_case",
                   return_value=(fake_cp, fake_binary)), \
             patch("bench.drivers.tier3_gdb.subprocess.run", side_effect=fake_dbg_run):
            driver.run(spec, run_dir, timeout=10.0)

        self.assertEqual(captured["argv"], [
            "gdb", "-nx", "-batch-silent",
            "-ex", "source /dev/stdin", str(fake_binary),
        ])
        self.assertEqual(
            (run_dir / "session.cmds").read_text(),
            build_gdb_script(fake_binary, case, spec.question),
        )


# --------------------------------------------------------------------------- #
# Tier3Driver.run — error / edge paths
# --------------------------------------------------------------------------- #

class TestTier3DriverErrorPaths(unittest.TestCase):

    def test_dry_run_short_circuits_after_compile(self):
        case = _real_case("off-by-one-crc")
        spec = RunSpec(case=case, model="m",
                       tool_config_path=_real_cfg("all_tools"), trial=1)
        run_dir = _tmp_run_dir("dryrun")
        driver = Tier3Driver(debugger="lldb", dry_run=True)

        dbg_called = []

        def fake_dbg_run(argv, **kwargs):
            dbg_called.append(argv)
            return _fake_cp(args=argv, returncode=0)

        with patch("bench.drivers.tier3_gdb.compile_case",
                   return_value=(_fake_cp(args=["clang"], returncode=0),
                                  run_dir / "build/prog")), \
             patch("bench.drivers.tier3_gdb.subprocess.run", side_effect=fake_dbg_run):
            result = driver.run(spec, run_dir, timeout=10.0)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(dbg_called, [], "debugger must not be launched in dry-run")
        self.assertFalse((run_dir / "session.cmds").exists())

    def test_compile_failed_short_circuits(self):
        case = _real_case("off-by-one-crc")
        spec = RunSpec(case=case, model="m",
                       tool_config_path=_real_cfg("all_tools"), trial=1)
        run_dir = _tmp_run_dir("compilefail")
        driver = Tier3Driver(debugger="lldb", dry_run=False)

        fake_cp = _fake_cp(args=["clang", "bad.c"], returncode=1,
                           stderr="error: blah")

        dbg_called = []
        def fake_dbg_run(argv, **kwargs):
            dbg_called.append(argv)
            return _fake_cp(args=argv, returncode=0)

        with patch("bench.drivers.tier3_gdb.compile_case",
                   return_value=(fake_cp, run_dir / "build/prog")), \
             patch("bench.drivers.tier3_gdb.subprocess.run", side_effect=fake_dbg_run):
            result = driver.run(spec, run_dir, timeout=10.0)

        self.assertEqual(result["status"], "compile_failed")
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("error: blah", (run_dir / "compile.log").read_text())
        self.assertEqual(dbg_called, [])

    def test_timeout_writes_partial_logs_and_marks_status(self):
        case = _real_case("off-by-one-crc")
        spec = RunSpec(case=case, model="m",
                       tool_config_path=_real_cfg("all_tools"), trial=1)
        run_dir = _tmp_run_dir("timeout")
        driver = Tier3Driver(debugger="lldb", dry_run=False)

        def fake_dbg_run(argv, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd=argv, timeout=1, output="partial-out", stderr="partial-err",
            )

        with patch("bench.drivers.tier3_gdb.compile_case",
                   return_value=(_fake_cp(args=["clang"], returncode=0),
                                  run_dir / "build/prog")), \
             patch("bench.drivers.tier3_gdb.subprocess.run", side_effect=fake_dbg_run):
            result = driver.run(spec, run_dir, timeout=1.0)

        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["exit_code"], -1)
        self.assertEqual((run_dir / "stdout.log").read_text(), "partial-out")
        self.assertEqual((run_dir / "stderr.log").read_text(), "partial-err")

    def test_no_collect_when_collect_json_not_emitted(self):
        case = _real_case("off-by-one-crc")
        spec = RunSpec(case=case, model="m",
                       tool_config_path=_real_cfg("all_tools"), trial=1)
        run_dir = _tmp_run_dir("nocollect")
        driver = Tier3Driver(debugger="lldb", dry_run=False)

        def fake_dbg_run(argv, **kwargs):
            return _fake_cp(args=argv, returncode=0)  # no collect.json written

        with patch("bench.drivers.tier3_gdb.compile_case",
                   return_value=(_fake_cp(args=["clang"], returncode=0),
                                  run_dir / "build/prog")), \
             patch("bench.drivers.tier3_gdb.subprocess.run", side_effect=fake_dbg_run):
            result = driver.run(spec, run_dir, timeout=10.0)

        self.assertEqual(result["status"], "no_collect")
        self.assertIsNone(result["collect_path"])

    def test_clean_env_strips_user_variables(self):
        case = _real_case("null-deref-env")
        self.assertTrue(case.meta.get("run", {}).get("clean_env"),
                        "precondition: null-deref-env must have clean_env=true")

        spec = RunSpec(case=case, model="m",
                       tool_config_path=_real_cfg("all_tools"), trial=1)
        run_dir = _tmp_run_dir("cleanenv")
        driver = Tier3Driver(debugger="lldb", dry_run=False)

        captured = {}

        def fake_dbg_run(argv, **kwargs):
            captured["env"] = dict(kwargs.get("env") or {})
            return _fake_cp(args=argv, returncode=0)

        with patch.dict(os.environ,
                        {"USER": "alice", "LOGNAME": "alice", "ADMIN_USER": "bob"}), \
             patch("bench.drivers.tier3_gdb.compile_case",
                   return_value=(_fake_cp(args=["clang"], returncode=0),
                                  run_dir / "build/prog")), \
             patch("bench.drivers.tier3_gdb.subprocess.run", side_effect=fake_dbg_run):
            driver.run(spec, run_dir, timeout=10.0)

        for k in ("USER", "LOGNAME", "ADMIN_USER"):
            self.assertNotIn(k, captured["env"],
                             f"{k} should have been stripped by clean_env")


# --------------------------------------------------------------------------- #
# Case discovery finds all 8 synthetic + 5 injected-repo cases
# --------------------------------------------------------------------------- #

_SYNTHETIC_IDS = [
    "double-free-errpath",
    "heap-overflow-csv",
    "intoverflow-alloc",
    "null-deref-env",
    "off-by-one-crc",
    "signed-unsigned-loop",
    "uaf-linked-list",
    "uninit-stack-accumulator",
]

_INJECTED_IDS = [
    "cjson-parse-string-oob",
    "lua-string-use-after-free",
    "mongoose-http-uninit",
    "sqlite-shell-null-deref",
    "zlib-inflate-dict-oob",
]


class TestCaseDiscovery(unittest.TestCase):

    def test_all_cases_discovered(self):
        ids = sorted(c.case_id for c in discover_cases())
        self.assertEqual(ids, sorted(_SYNTHETIC_IDS + _INJECTED_IDS))

    def test_filter_by_case_id(self):
        found = discover_cases(only=["off-by-one-crc"])
        self.assertEqual([c.case_id for c in found], ["off-by-one-crc"])

    def test_injected_cases_discovered_nested(self):
        """discover_cases must descend one level into cases/injected/."""
        found = {c.case_id: c for c in discover_cases(only=_INJECTED_IDS)}
        self.assertEqual(sorted(found), sorted(_INJECTED_IDS))
        for cid, case in found.items():
            self.assertEqual(case.kind, "injected_repo",
                             f"{cid} should have kind=injected_repo")
            self.assertEqual(case.case_dir.parent.name, "injected",
                             f"{cid} should live under cases/injected/")

    def test_synthetic_cases_have_default_kind(self):
        for c in discover_cases(only=_SYNTHETIC_IDS):
            self.assertEqual(c.kind, "synthetic_single_file")


if __name__ == "__main__":
    unittest.main(verbosity=2)
