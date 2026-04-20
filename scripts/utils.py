"""
scripts/utils.py
Shared constants and helper functions used across all pipeline scripts.
Import from here rather than duplicating path logic or DB setup.
"""

import os
import sqlite3
import subprocess
import json
from collections import Counter
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

# Projects to skip (demo/sanitizer variants that aren't real bugs)
SKIP_PROJECTS = {"example"}


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


def _extract_trigger(defect):
    """Return the first failing extra_test command, or None."""
    for test_variants in defect.get("extra_tests", []):
        for test in test_variants:
            if not test.get("is_pass", True):
                lines = test.get("lines", [])
                if lines:
                    return lines[0]
    return None


def load_bugscpp_metadata_from_taxonomy():
    """
    Read BugsC++ metadata from the cloned repo's taxonomy directories.

    Structure: bugscpp/taxonomy/<project>/meta.json
    Each meta.json has a "defects" array with id, tags, description, extra_tests.

    Returns a flat list of bug dicts with keys:
      project, index, bug_type, cve_id, trigger_command, docker_image
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

        for defect in meta.get("defects", []):
            idx = defect["id"]
            bugs.append({
                "project":         project,
                "index":           int(idx),
                "bug_type":        _extract_bug_type(defect.get("tags", [])),
                "cve_id":          _extract_cve(defect.get("description")),
                "trigger_command": _extract_trigger(defect),
                "docker_image":    f"bugscpp/{project}:{idx}",
            })

    return bugs
