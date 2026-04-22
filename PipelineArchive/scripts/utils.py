"""
scripts/utils.py
Shared constants and helper functions used across all pipeline scripts.
Import from here rather than duplicating path logic or DB setup.
"""

import os
import sqlite3
import subprocess
import json
import shlex
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
# All paths are relative to the project root (one level up from scripts/).
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR     = PROJECT_ROOT / "data"
DB_PATH      = DATA_DIR / "corpus.db"

PATCHES_DIR     = DATA_DIR / "patches"
BACKTRACES_DIR  = DATA_DIR / "backtraces"
INPUTS_DIR      = DATA_DIR / "inputs"
FILTER_RUNS_DIR = DATA_DIR / "filter_runs"

# ── Crash classification ──────────────────────────────────────────────────────
# Only these signals are treated as "interesting" crashes for the corpus.
CATCHABLE_SIGNALS = {"SIGSEGV", "SIGABRT", "SIGFPE", "SIGBUS"}

# ── BugsC++ metadata discovery ───────────────────────────────────────────────
# Set BUGSCPP_REPO env var if the repo is not adjacent to this project.
BUGSCPP_REPO = Path(os.environ.get("BUGSCPP_REPO", PROJECT_ROOT.parent / "bugscpp"))
# Taxonomy lives inside the bugscpp/ Python package subdirectory
BUGSCPP_TAXONOMY_DIR = BUGSCPP_REPO / "bugscpp" / "taxonomy"
WORKSPACES_DIR = DATA_DIR / "workspaces"

# Projects to skip (demo/sanitizer variants that aren't real bugs)
SKIP_PROJECTS = {"example"}


def gdb_image_for(project: str) -> str:
    """Per-project gdb-enabled image built by scripts/ensure_gdb_image.py."""
    return f"chatdbgpro/gdb-{project}:latest"


class IssueTracker:
    """
    Categorical counter for pipeline failure modes. Scripts bump a named
    bucket for each non-success outcome and print a breakdown at the end,
    so operators can see *which* failure modes dominated the run instead
    of scrolling through tqdm output.

    Known buckets used by the pipeline (extend freely):
      build_filter:  checkout_failed, build_timeout, build_failed, exception
      crash_filter:  timeout, no_signal, non_catchable, inconsistent_signal,
                     bugscpp_error
      extract_frames: timeout, empty_output, parse_failed, only_system_frames,
                      bugscpp_error
      extract_patches: extract_failed, empty_patch, validation_timeout,
                       validation_failed, bugscpp_error
    """

    def __init__(self, script_name: str):
        self.script_name = script_name
        self.counts: Counter = Counter()
        self.examples: dict[str, str] = {}

    def record(self, kind: str, bug_id: str | None = None, detail: str = ""):
        self.counts[kind] += 1
        if bug_id and kind not in self.examples:
            self.examples[kind] = f"{bug_id}: {detail}"[:160]

    def print_summary(self):
        if not self.counts:
            print(f"[{self.script_name}] No issues recorded.")
            return
        print(f"\n[{self.script_name}] Issue breakdown:")
        for kind, n in self.counts.most_common():
            ex = self.examples.get(kind, "")
            print(f"  {kind:22s} {n:4d}   e.g. {ex}")


def get_db_connection(db_path=DB_PATH):
    """Open a sqlite3 connection with foreign key enforcement enabled."""
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    con.row_factory = sqlite3.Row
    return con


def ensure_dirs():
    """Create all required data subdirectories if they don't exist."""
    for d in [PATCHES_DIR, BACKTRACES_DIR, INPUTS_DIR, FILTER_RUNS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def run_bugscpp(args, timeout=300, check=False):
    """
    Thin wrapper around subprocess.run for bugscpp CLI calls.
    Calls `python bugscpp/bugscpp.py <args>` from the cloned repo root.
    Returns CompletedProcess. Does NOT raise on non-zero exit unless check=True.
    """
    cmd = [
        "python",
        str(BUGSCPP_REPO / "bugscpp" / "bugscpp.py"),
    ] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def get_workspace_dir(project: str, bug_index: int, buggy: bool = True) -> Path:
    """
    Return expected checkout directory for a bug workspace.
    Layout follows BugsC++ docs:
      <target>/<project>/<buggy|fixed>-<index>
    where target is data/workspaces/<project>-<index>.
    """
    state = "buggy" if buggy else "fixed"
    target = WORKSPACES_DIR / f"{project}-{bug_index}"
    return target / project / f"{state}-{bug_index}"


def checkout_bug(project: str, bug_index: int, buggy: bool = True, timeout: int = 180):
    """Run bugscpp checkout for a bug into the canonical workspace target."""
    target = str(WORKSPACES_DIR / f"{project}-{bug_index}")
    args = ["checkout", project, str(bug_index), "--target", target]
    if buggy:
        args.append("--buggy")
    return run_bugscpp(args, timeout=timeout)


_SHELL_METACHARS = set("$`\\&|;<>()*?[]{}~!#")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _unwrap_bash_c(argv: list[str]) -> list[str]:
    """If argv is ['bash','-c','<single command, no shell metachars,
    no leading env assignments>'], return shlex.split of the inner command
    so gdb can attach directly. Otherwise return argv unchanged. Lets gdb
    skip the bash fork chain for literal extra_tests triggers like
    `bash -c "tools/tiffcrop ..."`."""
    if len(argv) != 3 or argv[0] != "bash" or argv[1] != "-c":
        return argv
    inner = argv[2]
    if any(c in _SHELL_METACHARS for c in inner):
        return argv
    try:
        inner_argv = shlex.split(inner)
    except ValueError:
        return argv
    if not inner_argv or _ENV_ASSIGN_RE.match(inner_argv[0]):
        return argv
    return inner_argv


def tokenize_trigger(trigger_command: str | None) -> list[str]:
    """Split trigger command into argv list for subprocess/GDB."""
    if not trigger_command:
        return []
    return _unwrap_bash_c(shlex.split(trigger_command))


def read_taxonomy_patch(project: str, bug_index: int) -> str:
    """
    Read patch data from BugsC++ taxonomy patch directory.
    Expected files:
      <idx:04d>-buggy.patch
      <idx:04d>-common.patch
    Returns concatenated patch text in stable order.
    """
    patch_dir = BUGSCPP_TAXONOMY_DIR / project / "patch"
    idx = f"{bug_index:04d}"
    paths = [
        patch_dir / f"{idx}-buggy.patch",
        patch_dir / f"{idx}-common.patch",
    ]

    chunks = []
    for p in paths:
        if p.exists():
            chunks.append(p.read_text())

    return "\n".join(c.strip("\n") for c in chunks if c).strip() + ("\n" if chunks else "")


def _extract_bug_type(tags):
    """Map BugsC++ tag list to a canonical bug_type string."""
    tag_set = set(tags)
    if "use-after-free" in tag_set:    return "use_after_free"
    if "null-deref" in tag_set:        return "null_deref"
    if "stack-overflow" in tag_set:    return "stack_overflow"
    if "buffer-overflow" in tag_set:   return "buffer_overflow"
    if "memory-error" in tag_set:      return "memory_error"
    return "other"


def _extract_cve(description):
    """Pull the first CVE-XXXX-XXXX string from a defect description."""
    import re
    if not description:
        return None
    m = re.search(r"CVE-\d{4}-\d+", description)
    return m.group(0) if m else None


def _run_in_workspace(
    workspace_dir: Path,
    command: list[str],
    docker_image: str | None,
    timeout: int = 90,
):
    """
    Run a command either natively (cwd=workspace_dir) or in docker
    (workspace bind-mounted at /work).
    """
    if docker_image:
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{workspace_dir.resolve()}:/work",
            "-w", "/work",
            docker_image,
        ] + command
        cwd = None
    else:
        cmd = command
        cwd = str(workspace_dir)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


def _normalize_workspace_argv(argv: list[str]) -> list[str]:
    """
    Rewrite absolute in-container workspace paths so they can be replayed from
    /work in crash_filter's docker invocation.
    """
    roots = ("/home/workspace", "/work")
    out = []
    for arg in argv:
        rewritten = arg
        for root in roots:
            if arg == root:
                rewritten = "."
                break
            if arg.startswith(root + "/"):
                rewritten = "." + arg[len(root):]
                break
        out.append(rewritten)
    return out


def _serialize_trigger_argv(workspace_dir: Path, argv: list[str]) -> str | None:
    """
    Normalize argv and ensure workspace-relative executables actually exist.
    """
    normalized = _normalize_workspace_argv(argv)
    if not normalized:
        return None
    exe = normalized[0]
    if exe.startswith("./") or exe.startswith("../") or ("/" in exe and not exe.startswith("/")):
        if not (workspace_dir / exe).exists():
            return None
    return shlex.join(normalized)


def _extract_ctest_command_from_json(raw_output: str, case_index: int) -> list[str] | None:
    """
    Parse `ctest --show-only=json-v1` output and return argv for case_index
    (1-based), if available.
    """
    start = raw_output.find("{")
    end = raw_output.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        payload = json.loads(raw_output[start:end + 1])
    except json.JSONDecodeError:
        return None

    tests = payload.get("tests")
    if not isinstance(tests, list):
        return None
    if case_index < 1 or case_index > len(tests):
        return None

    command = tests[case_index - 1].get("command")
    if isinstance(command, list):
        return [str(x) for x in command]
    if isinstance(command, str):
        try:
            return shlex.split(command)
        except ValueError:
            return [command]
    return None


def _extract_ctest_commands_from_verbose(raw_output: str) -> list[list[str]]:
    """
    Fallback for older CMake versions: parse `ctest -N -V` output lines.
    """
    commands: list[list[str]] = []
    for line in raw_output.splitlines():
        m = re.match(r"^\s*(?:\d+:\s+)?Test command:\s*(.+?)\s*$", line)
        if not m:
            continue
        cmd_text = m.group(1)
        try:
            commands.append(shlex.split(cmd_text))
        except ValueError:
            commands.append([cmd_text])
    return commands


def _extract_ctest_names(raw_output: str) -> list[str]:
    """Parse ordered test names from `ctest -N -V` output."""
    names: list[str] = []
    for line in raw_output.splitlines():
        m = re.match(r"^\s*Test\s*#\d+:\s*(.+?)\s*$", line)
        if m:
            names.append(m.group(1))
    return names


def _parse_add_test_args(line: str) -> tuple[str, list[str]] | None:
    """Parse one add_test(...) line into (test_name, argv)."""
    text = line.strip()
    if not text.startswith("add_test(") or not text.endswith(")"):
        return None
    inner = text[len("add_test("):-1]
    if not inner:
        return None
    try:
        tokens = shlex.split(inner)
    except ValueError:
        return None
    if not tokens:
        return None

    if tokens[0] == "NAME":
        if len(tokens) < 4 or "COMMAND" not in tokens:
            return None
        name = tokens[1]
        cmd_idx = tokens.index("COMMAND")
        argv = tokens[cmd_idx + 1:]
        return (name, argv) if argv else None

    if len(tokens) < 2:
        return None
    name = tokens[0]
    argv = tokens[1:]
    return (name, argv) if argv else None


def _find_ctest_add_test_command(build_dir: Path, test_name: str) -> list[str] | None:
    """
    Find a concrete argv for test_name by scanning CTestTestfile.cmake files.
    """
    if not build_dir.exists():
        return None
    for cmake_file in sorted(build_dir.rglob("CTestTestfile.cmake")):
        try:
            lines = cmake_file.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for line in lines:
            parsed = _parse_add_test_args(line)
            if not parsed:
                continue
            name, argv = parsed
            if name == test_name:
                return argv
    return None


def resolve_case_trigger_ctest(
    project: str,
    bug_index: int,
    case_index: int,
    workspace_dir: Path | None = None,
    docker_image: str | None = None,
) -> str | None:
    """
    Resolve a ctest case index (1-based) to a concrete argv string.
    Returns None if unavailable (missing workspace/build, unsupported ctest output, etc).
    """
    if case_index < 1:
        return None
    ws = workspace_dir or get_workspace_dir(project, bug_index, buggy=True)
    if not ws.exists():
        return None
    if not (ws / "build").exists():
        return None

    image = docker_image or gdb_image_for(project)

    # Preferred: JSON output with explicit command argv per test.
    try:
        res = _run_in_workspace(
            ws,
            ["ctest", "--show-only=json-v1", "--test-dir", "build"],
            docker_image=image,
            timeout=90,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    except Exception:
        return None

    if res.returncode == 0:
        argv = _extract_ctest_command_from_json(res.stdout, case_index)
        if argv:
            serialized = _serialize_trigger_argv(ws, argv)
            if serialized:
                return serialized

    # Fallback for older CMake where json-v1 is unavailable.
    try:
        fallback = _run_in_workspace(
            ws,
            ["ctest", "-N", "-V", "--test-dir", "build"],
            docker_image=image,
            timeout=90,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    except Exception:
        return None

    if fallback.returncode != 0:
        return None

    names = _extract_ctest_names(fallback.stdout)
    if case_index <= len(names):
        cmake_argv = _find_ctest_add_test_command(ws / "build", names[case_index - 1])
        if cmake_argv:
            serialized = _serialize_trigger_argv(ws, cmake_argv)
            if serialized:
                return serialized

    commands = _extract_ctest_commands_from_verbose(fallback.stdout)
    if case_index > len(commands):
        return None
    selected = commands[case_index - 1]
    if (
        case_index <= len(names)
        and len(selected) == 1
        and selected[0] == names[case_index - 1]
    ):
        # Older CTest can print only the test name when executable lookup fails.
        return None
    return _serialize_trigger_argv(ws, selected)


@dataclass
class TriggerResolution:
    """Outcome of attempting to derive a per-bug crash-trigger command.

    trigger_command: shell-ready string (passed through shlex.split by
        crash_filter). None when no handler succeeded.
    harness: which resolution path produced the result. One of:
        "extra_tests" — literal command from defect.extra_tests
        "ctest_json"  — concrete binary argv from ctest --show-only=json-v1
        "templated"   — rendered from common.test.commands with the case
                        index substituted; wrapped in `bash -c ...`
        "unsupported" — no handler matched; trigger_command is None
    case_index: which case[N] index this came from (None for extra_tests).
    status:  "resolved" (high-fidelity, gdb attaches directly to the binary),
             "wrapped"  (bash wrapper; gdb attaches to bash and may not
                         catch the underlying binary's crash without
                         follow-fork-mode child),
             "unsupported" (no trigger emitted),
             "error"    (handler raised).
    reason:  human-readable note, mostly for "wrapped"/"unsupported"/"error".
    """
    trigger_command: str | None
    harness: str
    case_index: int | None = None
    status: str = "resolved"
    reason: str | None = None


def _render_test_command_template(
    commands: list[dict] | None,
    case_index: int,
) -> str | None:
    """
    Render a BugsC++ common.test.commands template into a single bash -c
    invocation with $(cat DPP_TEST_INDEX) substituted by the literal case
    index.

    Returns None when commands is missing/empty so the caller can mark the
    bug unsupported.

    Notes:
      * BugsC++ test commands are bash-line lists; we join with " && " so
        any preparatory step (e.g., listing tests into AUTOMAKE_TEST_CASE.output)
        runs before the actual invocation.
      * @DPP_PARALLEL_BUILD@ is replaced with "1" (defects4cpp's default
        substitution when no -j override is set).
      * Both "$(cat DPP_TEST_INDEX)" and "$(cat ../DPP_TEST_INDEX)" appear
        in the taxonomy (exiv2 cd's into tests/ first); both are handled.
    """
    if not commands:
        return None
    lines: list[str] = []
    for cmd in commands:
        for line in cmd.get("lines", []):
            if line.strip():
                lines.append(line)
    if not lines:
        return None
    rendered = " && ".join(lines)
    rendered = rendered.replace("$(cat DPP_TEST_INDEX)", str(case_index))
    rendered = rendered.replace("$(cat ../DPP_TEST_INDEX)", str(case_index))
    rendered = rendered.replace("@DPP_PARALLEL_BUILD@", "1")
    return f"bash -c {shlex.quote(rendered)}"


def _resolve_via_ctest_json(
    project: str,
    bug_index: int,
    case_index: int,
    workspace_dir: Path | None,
    docker_image: str | None,
) -> str | None:
    """Tier-1 ctest path: returns a concrete argv string or None."""
    ws = workspace_dir or get_workspace_dir(project, bug_index, buggy=True)
    if not ws.exists() or not (ws / "build").exists():
        return None
    return resolve_case_trigger_ctest(
        project=project,
        bug_index=bug_index,
        case_index=case_index,
        workspace_dir=ws,
        docker_image=docker_image,
    )


def resolve_case_trigger(
    project: str,
    bug_index: int,
    case_index: int,
    *,
    test_type: str | None = None,
    common_test_commands: list[dict] | None = None,
    workspace_dir: Path | None = None,
    docker_image: str | None = None,
) -> TriggerResolution:
    """
    Two-tier case-format resolver.

    Tier 1 (preferred, ctest-only): if the project uses ctest *and* a built
    workspace is available, ask ctest --show-only=json-v1 for the actual
    test binary argv. This is what gdb can attach to directly with full
    fidelity.

    Tier 2 (fallback, all harnesses): render the project's
    common.test.commands template with the case index substituted. The
    result is a `bash -c '<command>'` trigger that the existing
    crash_filter can dispatch via gdb --args. Fidelity depends on whether
    gdb attaches to the right binary; the row is marked status="wrapped"
    so this can be filtered/audited later.
    """
    kind = (test_type or "").strip().lower()
    if case_index < 1:
        return TriggerResolution(
            None, "unsupported", case_index,
            "error", f"invalid case_index={case_index}",
        )

    # Tier 1: ctest with a built workspace.
    if kind == "ctest":
        try:
            argv = _resolve_via_ctest_json(
                project, bug_index, case_index, workspace_dir, docker_image,
            )
        except subprocess.SubprocessError as e:
            argv = None
            tier1_error = repr(e)[:200]
        else:
            tier1_error = None
        if argv:
            return TriggerResolution(argv, "ctest_json", case_index, "resolved", None)
    else:
        tier1_error = None

    # Tier 2: rendered template.
    rendered = _render_test_command_template(common_test_commands, case_index)
    if rendered:
        reason = (
            f"rendered from common.test.commands (test-type={kind or 'unknown'}); "
            "trigger runs through bash so gdb attaches to the wrapper, not "
            "the underlying binary"
        )
        if tier1_error:
            reason += f"; ctest-json fallback after error: {tier1_error}"
        return TriggerResolution(rendered, "templated", case_index, "wrapped", reason)

    return TriggerResolution(
        None, "unsupported", case_index, "unsupported",
        f"no template available for test-type={kind or 'unknown'} on {project}",
    )


def _extract_trigger_resolution(
    defect,
    *,
    project: str | None = None,
    test_type: str | None = None,
    common_test_commands: list[dict] | None = None,
    resolve_case_triggers: bool = False,
    workspace_dir: Path | None = None,
    docker_image: str | None = None,
) -> TriggerResolution | None:
    """
    Return a TriggerResolution describing how this defect's trigger was
    obtained, or None if no resolution was attempted.

    Order of preference:
      1. extra_tests (literal failing-test commands from the taxonomy)
      2. case[N] resolution via resolve_case_trigger() — only if
         resolve_case_triggers=True

    None is returned (i.e. resolution skipped entirely) when the defect has
    no extra_tests AND resolve_case_triggers is False, so the caller can
    distinguish "didn't try" from "tried and failed".
    """
    for test_variants in defect.get("extra_tests", []):
        for test in test_variants:
            if not test.get("is_pass", True):
                lines = test.get("lines", [])
                if lines:
                    return TriggerResolution(
                        lines[0], "extra_tests", None, "resolved", None,
                    )

    if not resolve_case_triggers:
        return None
    if not project:
        return None
    bug_index = defect.get("id")
    if bug_index is None:
        return None

    last: TriggerResolution | None = None
    for case_raw in defect.get("case", []):
        try:
            case_index = int(case_raw)
        except (TypeError, ValueError):
            continue
        try:
            res = resolve_case_trigger(
                project=project,
                bug_index=int(bug_index),
                case_index=case_index,
                test_type=test_type,
                common_test_commands=common_test_commands,
                workspace_dir=workspace_dir,
                docker_image=docker_image,
            )
        except Exception as e:  # noqa: BLE001 — surface handler bugs in the log
            res = TriggerResolution(
                None, "unsupported", case_index, "error", repr(e)[:200],
            )
        last = res
        if res.trigger_command is not None:
            return res

    return last


def _extract_trigger(
    defect,
    *,
    project: str | None = None,
    test_type: str | None = None,
    common_test_commands: list[dict] | None = None,
    resolve_case_triggers: bool = False,
):
    """Backwards-compatible string-only wrapper around _extract_trigger_resolution."""
    res = _extract_trigger_resolution(
        defect,
        project=project,
        test_type=test_type,
        common_test_commands=common_test_commands,
        resolve_case_triggers=resolve_case_triggers,
    )
    return res.trigger_command if res else None


def load_bugscpp_metadata_from_taxonomy(resolve_case_triggers: bool = False):
    """
    Read BugsC++ metadata from the cloned repo's taxonomy directories.

    Structure: bugscpp/taxonomy/<project>/meta.json
    Each meta.json has a "defects" array with id, tags, description, extra_tests.

    Returns a flat list of bug dicts with keys:
      project, index, bug_type, cve_id, trigger_command, docker_image
    Plus, when resolve_case_triggers=True, a "trigger_resolution" key holding
    a TriggerResolution describing harness/status/reason for the
    trigger_resolution_log table.
    """
    if not BUGSCPP_TAXONOMY_DIR.exists():
        raise FileNotFoundError(
            f"BugsC++ taxonomy dir not found: {BUGSCPP_TAXONOMY_DIR}\n"
            "Set BUGSCPP_REPO env var to the path of your cloned bugscpp repo."
        )

    bugs = []
    for proj_dir in sorted(BUGSCPP_TAXONOMY_DIR.iterdir()):
        if not proj_dir.is_dir():
            continue
        project = proj_dir.name
        if project in SKIP_PROJECTS:
            continue
        meta_file = proj_dir / "meta.json"
        if not meta_file.exists():
            continue

        with open(meta_file) as f:
            meta = json.load(f)

        common = meta.get("common", {})
        test_type = common.get("test-type")
        common_test_commands = (common.get("test") or {}).get("commands")

        for defect in meta.get("defects", []):
            idx = defect["id"]
            resolution = _extract_trigger_resolution(
                defect,
                project=project,
                test_type=test_type,
                common_test_commands=common_test_commands,
                resolve_case_triggers=resolve_case_triggers,
            )
            bugs.append({
                "project":            project,
                "index":              int(idx),
                "bug_type":           _extract_bug_type(defect.get("tags", [])),
                "cve_id":             _extract_cve(defect.get("description")),
                "trigger_command":    resolution.trigger_command if resolution else None,
                "trigger_resolution": resolution,
                "docker_image":       f"bugscpp/{project}:{idx}",
            })

    return bugs
