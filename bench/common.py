"""Shared types, constants, and helpers used by the orchestrator and
per-tier drivers.

Anything that depends only on a case's source/metadata (not on how a
particular tier interacts with the program) lives here, so drivers in
bench/drivers/ can import without pulling in the CLI layer.
"""
from __future__ import annotations

import json
import platform as _platform
import shlex
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML required. Install with: pip install pyyaml\n")
    raise


BENCH_DIR = Path(__file__).resolve().parent
REPO_DIR = BENCH_DIR.parent
CASES_DIR = BENCH_DIR / "cases"
CONFIGS_DIR = BENCH_DIR / "configs"
RESULTS_DIR = BENCH_DIR / "results"
WORKSPACE_CACHE = BENCH_DIR / ".workspace-cache"
DATA_DIR = REPO_DIR / "data"


def current_platform() -> str:
    """Return `linux`, `darwin`, or the raw platform.system().lower().

    Used to gate platform-limited cases (e.g. MSan is Linux-only)."""
    return _platform.system().lower()

DEFAULT_QUESTION = (
    "What is the root cause of this crash? Walk through the program "
    "state, identify the defect, and propose a fix in code. Cover both "
    "a minimal local fix and a more thorough root-cause fix if they differ."
)


@dataclass
class Case:
    case_id: str
    case_dir: Path
    meta: dict

    @property
    def source_path(self) -> Path:
        # Only meaningful for `kind=synthetic_single_file`; injected-repo
        # cases resolve sources after the repo is cloned + patched.
        return self.case_dir / self.meta["source_file"]

    @property
    def language(self) -> str:
        return self.meta.get("language", "c")

    @property
    def kind(self) -> str:
        # "synthetic_single_file" = the existing one-program.c-per-dir model.
        # "injected_repo"         = clone repo@sha, apply bug.patch, run repro.sh.
        return self.meta.get("kind", "synthetic_single_file")

    @property
    def platforms(self) -> list[str]:
        """Platforms on which this case is expected to compile & repro.

        Empty list means "any" (the default). A non-empty list acts as a
        hard filter: if the host's current_platform() isn't listed, the
        driver returns status=skipped_platform instead of attempting the
        run. This exists because MSan cases can't be built on macOS
        arm64, but they remain semantically correct Linux cases."""
        return list(self.meta.get("build", {}).get("platforms", []) or [])

    def platform_supported(self) -> bool:
        p = self.platforms
        if not p:
            return True
        return current_platform() in p


@dataclass
class RunSpec:
    case: Case
    model: str
    tool_config_path: Path
    trial: int
    context_lines: int = 10
    tier: int = 3
    question: str = DEFAULT_QUESTION
    # S5(b): for BugsC++ cases without a crash, set a breakpoint at the
    # patch site so the model can inspect locals at the defect instead
    # of staring at exit() / __libc_start_main.
    breakpoint_at_patch: bool = False
    # B3: ask a structural-fix follow-up after the first answer.
    structural_fix_turn: bool = False


def _validate_case_meta(meta: dict, case_dir: Path) -> list[str]:
    """C7: schema validation for synthetic / injected case.yaml manifests.

    Returns a list of human-readable problems (empty list = valid).
    Validates only the fields the harness actually consumes — keeps the
    schema lightweight and additive."""
    errs: list[str] = []
    if not isinstance(meta, dict):
        return [f"{case_dir.name}: case.yaml is not a YAML mapping"]
    kind = meta.get("kind", "synthetic_single_file")
    # Required across all kinds:
    for key in ("id", "language"):
        if not meta.get(key):
            errs.append(f"{case_dir.name}: missing required field '{key}'")
    crit = meta.get("criteria") or {}
    for axis in ("root_cause", "local_fix", "global_fix"):
        if not crit.get(axis):
            errs.append(f"{case_dir.name}: missing criteria.{axis}")
    if kind == "synthetic_single_file":
        sf = meta.get("source_file")
        if not sf:
            errs.append(f"{case_dir.name}: synthetic case missing source_file")
        elif not (case_dir / sf).exists():
            errs.append(f"{case_dir.name}: source_file '{sf}' not on disk")
        flags = meta.get("build", {}).get("flags")
        if flags and not isinstance(flags, list):
            errs.append(f"{case_dir.name}: build.flags must be a list")
    elif kind == "injected_repo":
        repo = meta.get("repo") or {}
        if not repo.get("url") or not repo.get("sha"):
            errs.append(f"{case_dir.name}: injected case missing repo.url or repo.sha")
        if not meta.get("bug", {}).get("root_cause_file"):
            errs.append(f"{case_dir.name}: injected case missing bug.root_cause_file")
    return errs


def discover_cases(only: list[str] | None = None,
                   strict_schema: bool = False) -> list[Case]:
    """Walk CASES_DIR for case.yaml manifests.

    Supports two layouts:
      - flat:    bench/cases/<case_id>/case.yaml     (existing synthetic cases)
      - nested:  bench/cases/<group>/<case_id>/case.yaml
                 (e.g. injected/cjson-parse-string-oob/ for repo-based bugs)

    A directory without its own case.yaml is treated as a group and its
    immediate subdirectories are scanned. This is intentionally just one
    level of nesting to keep discovery predictable.

    C7: when `strict_schema=True`, raise on any case whose case.yaml
    fails validation. Default is to print warnings and skip the case
    so a single typo doesn't kill a whole sweep.
    """
    cases: list[Case] = []
    schema_errors: list[str] = []

    def consider(case_dir: Path) -> None:
        manifest = case_dir / "case.yaml"
        if not manifest.exists():
            return
        try:
            with open(manifest) as f:
                meta = yaml.safe_load(f)
        except yaml.YAMLError as e:
            schema_errors.append(f"{case_dir.name}: invalid YAML: {e}")
            return
        problems = _validate_case_meta(meta, case_dir)
        if problems:
            schema_errors.extend(problems)
            return
        case_id = meta.get("id", case_dir.name)
        if only and case_id not in only and case_dir.name not in only:
            return
        cases.append(Case(case_id=case_id, case_dir=case_dir, meta=meta))

    for entry in sorted(CASES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / "case.yaml").exists():
            consider(entry)
        else:
            for child in sorted(entry.iterdir()):
                if child.is_dir():
                    consider(child)

    if schema_errors:
        msg = "case.yaml schema problems:\n  " + "\n  ".join(schema_errors)
        if strict_schema:
            raise ValueError(msg)
        sys.stderr.write(f"[discover] {msg}\n")

    return cases


@dataclass
class InjectedPrepResult:
    """Outcome of prepare_injected_workspace."""
    workdir: Path | None
    binary: Path | None
    status: str         # "ok" | "clone_failed" | "patch_failed" | "build_failed"
    log: str


def _apply_patch_ops(workdir: Path, ops: list[dict]) -> tuple[bool, str]:
    """Apply a list of single-match text substitutions to files in `workdir`.

    Each op is `{file: <relpath>, before: <str>, after: <str>}`. We require
    `before` to appear *exactly once* in the file — any other count is an
    error, since the whole point of this format is to be obviously-correct
    without carrying line numbers. Returns (ok, log)."""
    log_lines: list[str] = []
    for op in ops:
        rel = op["file"]
        before = op["before"]
        after = op["after"]
        target = workdir / rel
        if not target.exists():
            return False, f"patch target missing: {rel}\n"
        text = target.read_text()
        count = text.count(before)
        if count != 1:
            return False, (
                f"patch_op match count != 1 (got {count}) in {rel}\n"
                f"---before---\n{before}\n---end---\n"
            )
        target.write_text(text.replace(before, after, 1))
        log_lines.append(f"patched: {rel}\n")
    return True, "".join(log_lines)


def prepare_injected_workspace(
    case: Case, *, rebuild: bool = False,
    cache_dir: Path | None = None,
) -> InjectedPrepResult:
    """Clone repo @ sha, apply patch_ops, run build.commands.

    The built tree lives at `<cache_dir or WORKSPACE_CACHE>/<case_id>/`.
    A sentinel file `.prepared.<hash>.ok` (hash over repo+build+patch_ops)
    marks a successful prep so repeated runs across (model × trial)
    reuse the same tree. Set `rebuild=True` to blow the cache and
    start over (useful during step-4 calibration).

    The optional `cache_dir` argument lets callers separate caches
    by toolchain so a host-built (mach-o) and container-built (ELF)
    workspace for the same case_id don't collide. The Tier 2 Linux-
    container driver passes `cache_dir=bench/.workspace-cache-linux`.
    """
    repo_info = case.meta.get("repo", {})
    url = repo_info.get("url")
    sha = str(repo_info.get("sha", ""))
    if not url or not sha:
        return InjectedPrepResult(None, None, "clone_failed",
                                  f"case {case.case_id}: missing repo.url or repo.sha\n")

    cache_root = cache_dir if cache_dir is not None else WORKSPACE_CACHE
    workdir = cache_root / case.case_id
    build_cfg = case.meta.get("build", {})
    binary_rel = build_cfg.get("binary")
    binary_path = workdir / binary_rel if binary_rel else None

    # A4: hash-keyed sentinel — invalidate the cached build whenever
    # any field that influences the build changes (repo sha, build
    # commands, patch_ops, asset list). Previously the sentinel was a
    # static `.prepared.ok` and stale builds silently survived
    # case.yaml edits, hiding calibration mistakes.
    import hashlib
    cache_key_blob = json.dumps({
        "repo": case.meta.get("repo", {}),
        "build": build_cfg,
        "patch_ops": case.meta.get("bug", {}).get("patch_ops", []),
    }, sort_keys=True).encode("utf-8")
    cache_key = hashlib.sha256(cache_key_blob).hexdigest()[:16]
    sentinel = workdir / f".prepared.{cache_key}.ok"

    if sentinel.exists() and not rebuild and binary_path and binary_path.exists():
        return InjectedPrepResult(workdir, binary_path, "ok",
                                  f"reusing cached workspace: {workdir} (key={cache_key})\n")

    if workdir.exists():
        shutil.rmtree(workdir)
    cache_root.mkdir(parents=True, exist_ok=True)

    log: list[str] = []
    def run(cmd: list[str], cwd: Path | None = None) -> int:
        log.append("$ " + " ".join(cmd) + (f"   (cwd={cwd})" if cwd else "") + "\n")
        cp = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if cp.stdout:
            log.append(cp.stdout if cp.stdout.endswith("\n") else cp.stdout + "\n")
        if cp.stderr:
            log.append(cp.stderr if cp.stderr.endswith("\n") else cp.stderr + "\n")
        return cp.returncode

    # Shallow clone first, then fetch the exact sha. Works for both tags
    # (like v1.7.18) and raw commit shas.
    if run(["git", "clone", "--quiet", url, str(workdir)]) != 0:
        return InjectedPrepResult(None, None, "clone_failed", "".join(log))
    if run(["git", "checkout", "--quiet", sha], cwd=workdir) != 0:
        return InjectedPrepResult(None, None, "clone_failed", "".join(log))

    patch_ops = case.meta.get("bug", {}).get("patch_ops", [])
    if patch_ops:
        ok, patch_log = _apply_patch_ops(workdir, patch_ops)
        log.append(patch_log)
        if not ok:
            return InjectedPrepResult(None, None, "patch_failed", "".join(log))

    for asset in build_cfg.get("assets", []) or []:
        src = case.case_dir / asset["src"]
        dst = workdir / asset["dst"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)
        log.append(f"copied asset: {asset['src']} -> {asset['dst']}\n")

    for prep_cmd in build_cfg.get("prepare", []) or []:
        if run(["bash", "-c", prep_cmd], cwd=workdir) != 0:
            return InjectedPrepResult(None, None, "build_failed", "".join(log))

    for build_cmd in build_cfg.get("commands", []) or []:
        if run(["bash", "-c", build_cmd], cwd=workdir) != 0:
            return InjectedPrepResult(None, None, "build_failed", "".join(log))

    if binary_path and not binary_path.exists():
        log.append(f"build completed but binary missing: {binary_rel}\n")
        return InjectedPrepResult(None, None, "build_failed", "".join(log))

    sentinel.write_text("")
    return InjectedPrepResult(workdir, binary_path, "ok", "".join(log))


def compile_case(case: Case, build_dir: Path) -> tuple[subprocess.CompletedProcess, Path]:
    build_dir.mkdir(parents=True, exist_ok=True)
    binary = build_dir / "prog"
    build_cfg = case.meta.get("build", {})
    default_compiler = "clang++" if case.language in ("cpp", "c++") else "clang"
    compiler = build_cfg.get("compiler", default_compiler)
    flags = list(build_cfg.get("flags", []))
    cmd = [compiler, *flags, str(case.source_path), "-o", str(binary)]
    cp = subprocess.run(cmd, capture_output=True, text=True)
    return cp, binary


def run_id_for(spec: RunSpec) -> str:
    model_slug = spec.model.replace("/", "_").replace(":", "_")
    cfg_slug = spec.tool_config_path.stem
    return (
        f"{spec.case.case_id}__tier{spec.tier}__{model_slug}"
        f"__{cfg_slug}__ctx{spec.context_lines}__t{spec.trial}"
    )


def finalize_result(
    run_dir: Path,
    spec: RunSpec,
    *,
    status: str,
    exit_code: int,
    elapsed_s: float,
) -> dict:
    result = {
        "run_id": run_dir.name,
        "status": status,
        "exit_code": exit_code,
        "elapsed_s": round(elapsed_s, 3),
        "model": spec.model,
        "tool_config": spec.tool_config_path.name,
        "context_lines": spec.context_lines,
        "tier": spec.tier,
        "trial": spec.trial,
        "case_id": spec.case.case_id,
        "language": spec.case.language,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "collect_path": "collect.json" if (run_dir / "collect.json").exists() else None,
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2))
    return result


def build_matrix(
    cases: list,
    models: list[str],
    tool_configs: list[Path],
    trials: int,
    context_lines: list[int],
    tiers: list[int],
    *,
    breakpoint_at_patch: bool = False,
    structural_fix_turn: bool = False,
) -> list[RunSpec]:
    specs: list[RunSpec] = []
    for case in cases:
        for tier in tiers:
            for model in models:
                for cfg in tool_configs:
                    for ctx in context_lines:
                        for t in range(1, trials + 1):
                            specs.append(RunSpec(
                                case=case, model=model,
                                tool_config_path=cfg,
                                context_lines=ctx, trial=t,
                                tier=tier,
                                breakpoint_at_patch=breakpoint_at_patch,
                                structural_fix_turn=structural_fix_turn,
                            ))
    return specs


# ---------------------------------------------------------------------------
# BugsCPP Docker-based cases (from corpus.db)
# ---------------------------------------------------------------------------

@dataclass
class DockerCase:
    """A BugsCPP test case loaded from the corpus SQLite database."""
    bug_id: str
    project: str
    bug_index: int
    gdb_image: str
    trigger_argv: list[str]
    workspace_path: Path
    crash_signal: str | None = None
    user_frame_function: str | None = None
    user_frame_file: str | None = None
    user_frame_line: int | None = None
    patch_path: str | None = None
    patch_diff: str | None = None
    patch_first_file: str | None = None
    patch_first_line: int | None = None
    bug_type: str | None = None
    db_language: str | None = None
    bug_observed: str | None = None
    buggy_binary_path: str | None = None
    buggy_binary_argv: list[str] | None = None

    # Duck-type compatibility with Case so run_id_for / finalize_result work.
    @property
    def case_id(self) -> str:
        return self.bug_id

    @property
    def language(self) -> str:
        return self.db_language or "c"

    @property
    def kind(self) -> str:
        return "docker_bugscpp"

    def platform_supported(self) -> bool:
        return True  # Docker handles cross-platform


# Shell-wrapper command names BugsC++ uses for triggers. argv[0] in the
# corpus is recorded both as bare names ('bash', 'sed') and absolute
# paths ('/bin/bash'); we match the basename to handle both.
_SYSTEM_TRIGGER_WRAPPERS = frozenset({
    "bash", "sh", "zsh", "dash",
    "sed", "awk", "grep",
    "find", "make", "cmake", "gmake",
})


def is_system_trigger_wrapper(trigger_argv: list[str]) -> bool:
    """S1: True if trigger_argv[0] is a known shell wrapper (bash, sed,
    find, make, ...) rather than the actual buggy binary. The DockerDriver
    will attach gdb to the wrapper, not the bug — runs from such cases
    are noise and should be flagged at discovery time.

    Matches both bare command names ('bash') and absolute paths
    ('/bin/bash', '/usr/local/bin/bash')."""
    if not trigger_argv:
        return False
    head = trigger_argv[0]
    # basename matching handles both 'bash' and '/usr/bin/bash'
    name = head.rsplit("/", 1)[-1] if "/" in head else head
    return name in _SYSTEM_TRIGGER_WRAPPERS


def discover_docker_cases(
    db_path: Path | None = None,
    only: list[str] | None = None,
    crash_only: bool = False,
    skip_system_triggers: bool = False,
) -> list[DockerCase]:
    """Load pipeline2 BugsCPP cases from the corpus DB.

    If `only` is given, filters by bug_id. Otherwise returns all cases
    included in the corpus that have a trigger argv (needed to launch
    gdb --args)."""
    if db_path is None:
        db_path = DATA_DIR / "corpus.db"
    if not db_path.exists():
        raise FileNotFoundError(f"Corpus DB not found: {db_path}")

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row

    tables = {
        r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "bugs" not in tables:
        con.close()
        raise RuntimeError(
            f"{db_path} does not contain pipeline2 table 'bugs'. "
            "Run pipeline2/seed.py or pipeline2/run_all.py first."
        )

    sql = """
        SELECT bug_id, project, bug_index, gdb_image, trigger_argv_json,
               workspace_path,
               crash_signal, user_frame_function, user_frame_file,
               user_frame_line, patch_path,
               patch_diff, patch_first_file, patch_first_line,
               bug_type, language,
               bug_observed, buggy_binary_path, buggy_binary_argv_json
        FROM bugs
        WHERE trigger_argv_json IS NOT NULL
          AND included_in_corpus = 1
    """
    params: tuple = ()
    if only:
        placeholders = ",".join("?" for _ in only)
        sql += f" AND bug_id IN ({placeholders})"
        params = tuple(only)
    if crash_only:
        # S5(a): only schedule cases that pipeline2/probe.py confirmed
        # actually crash. Many BugsC++ "bugs" are wrong-output (clean
        # exit(0)), and ChatDBG's lldb-runs-until-crash session has
        # nothing to debug for those. crash_signal is populated by
        # pipeline2/probe.py — NULL means probe didn't see a signal.
        sql += " AND crash_signal IS NOT NULL"
    sql += " ORDER BY bug_id"

    rows = con.execute(sql, params).fetchall()
    con.close()

    cases = []
    skipped_wrong_binary = []
    for r in rows:
        trigger_argv = json.loads(r["trigger_argv_json"])
        if skip_system_triggers and is_system_trigger_wrapper(trigger_argv):
            # S1: trigger is bash/sed/find/make → gdb attaches to a
            # shell wrapper instead of the buggy binary. Drop and warn.
            skipped_wrong_binary.append(r["bug_id"])
            continue
        cases.append(DockerCase(
            bug_id=r["bug_id"],
            project=r["project"],
            bug_index=r["bug_index"],
            gdb_image=r["gdb_image"],
            trigger_argv=json.loads(r["trigger_argv_json"]),
            workspace_path=Path(r["workspace_path"]),
            crash_signal=r["crash_signal"],
            user_frame_function=r["user_frame_function"],
            user_frame_file=r["user_frame_file"],
            user_frame_line=r["user_frame_line"],
            patch_path=r["patch_path"],
            patch_diff=r["patch_diff"],
            patch_first_file=r["patch_first_file"],
            patch_first_line=r["patch_first_line"],
            bug_type=r["bug_type"],
            db_language=r["language"],
            bug_observed=r["bug_observed"],
            buggy_binary_path=r["buggy_binary_path"],
            buggy_binary_argv=(
                json.loads(r["buggy_binary_argv_json"])
                if r["buggy_binary_argv_json"] else None
            ),
        ))
    if skipped_wrong_binary:
        sys.stderr.write(
            f"[discover] skipped {len(skipped_wrong_binary)} BugsC++ case(s) "
            f"whose trigger_argv[0] is a shell wrapper (gdb would attach to "
            f"bash/sed/find/make, not the bug). Pass skip_system_triggers=False "
            f"to include them. Sample: {skipped_wrong_binary[:5]}\n"
        )
    return cases


def build_oracle_strings(case: DockerCase) -> dict[str, str]:
    """Build the CHATDBG_PROMPT_* env-var values for a BugsCPP case.

    Returns a dict with up to three keys (CHATDBG_PROMPT_BINARY,
    CHATDBG_PROMPT_ERROR, CHATDBG_PROMPT_EXTRA). Missing keys mean the
    harness shouldn't override that aspect of ChatDBG's default prompt.

    Policy (per the harness restructure plan):
      - BINARY: real buggy-binary path if known, else absent (let ChatDBG's
        default `progspace.filename` show through).
      - ERROR : behavioral oracle for non-crash bugs ("test exited with
        code N, expected: pass"); descriptive crash label for crash bugs.
        Never leaks file/line/function — those stay in the judge's rubric.
      - EXTRA : project + language + workspace, so the model knows what
        kind of codebase it's looking at.
    """
    out: dict[str, str] = {}

    if case.buggy_binary_path:
        # If we captured the full argv from strace, surface it so the LLM
        # sees the exact failing-test invocation (e.g. "./berry tests/x.be")
        # — without it the model is just told "the binary is /work/berry"
        # and has no idea how the test exercised it. argv[0] is preserved
        # as-typed (often "./berry"); we prefix the resolved path for
        # clarity. Args after argv[0] are shell-quoted.
        if case.buggy_binary_argv:
            argv = case.buggy_binary_argv
            args_part = " ".join(shlex.quote(a) for a in argv[1:])
            out["CHATDBG_PROMPT_BINARY"] = (
                f"/work/{case.buggy_binary_path} {args_part}".rstrip()
            )
        else:
            out["CHATDBG_PROMPT_BINARY"] = f"/work/{case.buggy_binary_path}"

    obs = case.bug_observed or ""
    if obs.startswith("crash:"):
        sig = obs.split(":", 1)[1] or "unknown signal"
        out["CHATDBG_PROMPT_ERROR"] = f"Program crashed with {sig}"
    elif obs.startswith("exit_code:"):
        rc = obs.split(":", 1)[1]
        out["CHATDBG_PROMPT_ERROR"] = (
            f"The bugscpp test for this bug failed: the program exited with "
            f"code {rc} but the test oracle expected a passing run. The "
            f"program does not crash — the defect causes incorrect behavior "
            f"that the test catches."
        )
    elif obs == "timeout":
        out["CHATDBG_PROMPT_ERROR"] = (
            "The bugscpp test for this bug failed: the program timed out. "
            "The defect may be causing an infinite loop or deadlock."
        )
    # 'no_observation' / unknown → leave unset, fall through to ChatDBG's
    # signal-based default.

    extras = []
    if case.project:
        extras.append(f"project={case.project}")
    if case.db_language:
        extras.append(f"language={case.db_language}")
    extras.append("workspace=/work")
    if case.bug_type:
        extras.append(f"bug_type={case.bug_type}")
    if extras:
        out["CHATDBG_PROMPT_EXTRA"] = ", ".join(extras)

    return out


def write_docker_case_yaml(case: DockerCase, run_dir: Path) -> bool:
    """Write case.yaml and sliced source file into run_dir for the judge.

    Returns True if successful, False if the source file couldn't be found."""
    source_basename = Path(case.patch_first_file).name if case.patch_first_file else None
    if not source_basename:
        return False

    # Find the source file in the workspace
    source_in_workspace = case.workspace_path / case.patch_first_file
    if not source_in_workspace.exists():
        return False

    # Slice ±50 lines around patch_first_line. Source files in BugsCPP
    # workspaces are not always pure ASCII/UTF-8 (latin-1 fragments,
    # generated parser tables, etc.); decode permissively so the
    # backfill never aborts mid-corpus on a single odd byte.
    full_source = source_in_workspace.read_text(encoding="utf-8", errors="replace")
    lines = full_source.splitlines(keepends=True)
    if case.patch_first_line and case.patch_first_line > 0:
        center = case.patch_first_line - 1  # 0-indexed
        start = max(0, center - 50)
        end = min(len(lines), center + 51)
        sliced = "".join(lines[start:end])
    else:
        # No line info — include the whole file (truncated by judge if needed)
        sliced = full_source

    (run_dir / source_basename).write_text(sliced, encoding="utf-8")

    # Build criteria from ground truth
    loc = f"{case.patch_first_file}:{case.patch_first_line}" if case.patch_first_line else case.patch_first_file or "unknown"
    func = case.user_frame_function or "unknown"
    crash_note = f" (crash signal: {case.crash_signal})" if case.crash_signal else ""
    bug_class = f" The bug class is {case.bug_type}." if case.bug_type else ""

    root_cause = (
        f"Diagnosis must identify the defect at {loc} "
        f"in function {func}{crash_note}."
    )

    patch_text = case.patch_diff or "(no patch available)"
    local_fix = (
        f"The model's suggested code change is consistent with this "
        f"developer patch (correct file, correct site, equivalent fix):\n{patch_text}"
    )
    global_fix = (
        f"The model's reasoning correctly explains WHY the bug exists — "
        f"not just what line to change, but the underlying cause "
        f"(e.g. missing bounds check, use-after-free pattern, integer overflow). "
        f"The explanation must go beyond 'change line X' and demonstrate "
        f"understanding of the root cause.{bug_class}"
    )

    case_data = {
        "id": case.bug_id,
        "language": case.language,
        "source_file": source_basename,
        "criteria": {
            "root_cause": root_cause,
            "local_fix": local_fix,
            "global_fix": global_fix,
        },
    }
    with open(run_dir / "case.yaml", "w") as f:
        yaml.dump(case_data, f, default_flow_style=False, sort_keys=False)
    return True
