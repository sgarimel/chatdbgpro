"""Systematic audit of binary-resolution per BugsCPP case.

For every `included_in_corpus=1` bug in data/corpus.db, this simulates
the harness's binary-resolution logic (the same logic in
bench/drivers/docker_gdb.py at run time) and reports:

  - Which path the harness will pass to gdb (`gdb --args <binary> <args>`)
  - Where that path comes from (probed strace data, direct argv, bash-c
    extracted, raw bash, ...)
  - Confidence that gdb will end up attached to the right binary

The harness's logic (verbatim from docker_gdb.py:253-260):

    if case.buggy_binary_argv and case.buggy_binary_path:
        run_argv = [f"/work/{case.buggy_binary_path}"] + buggy_binary_argv[1:]
    else:
        run_argv = case.trigger_argv

So a case is "well-resolved" iff one of:
  (a) probed: buggy_binary_path AND buggy_binary_argv are set, OR
  (b) direct: trigger_argv[0] is a non-shell binary path (gdb attaches
      directly), OR
  (c) bash-extractable: trigger is `bash -c "<binary> ..."` with no
      shell metachars, AND `<binary>` looks like a binary path —
      gdb attaches to bash but `set follow-fork-mode child` chases
      into the named binary on the first exec().

Anything else (bash -c with metachars / pipes / heredocs / make / ctest)
is "fork-follow-only": gdb attaches to bash, then chases through an
opaque exec chain. May still work but the harness can't predict the
final binary. Strongly recommends running `pipeline2.build` to capture
the strace probe.

Run:
    python -m pipeline2.audit_binary_probe \
        [--out bench/analysis_artifacts/PROBE_AUDIT.md] \
        [--project NAME ...]   # filter to specific projects
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict, Counter

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "corpus.db"
DEFAULT_OUT = REPO_ROOT / "bench" / "analysis_artifacts" / "PROBE_AUDIT.md"

_SHELL_METACHARS = set("$`\\&|;<>()*?[]{}~!#")
# Same list bench/common.py:_SYSTEM_TRIGGER_WRAPPERS uses; mirrored
# locally so this audit doesn't have to import bench.common.
_SHELL_WRAPPERS = frozenset({
    "bash", "sh", "zsh", "dash", "sed", "awk", "grep",
    "find", "make", "cmake", "gmake", "ctest", "xargs", "env",
    "exec", "cd", "true", "false",
})
# Test-harness drivers worth flagging separately: they always fork
# the actual buggy binary so gdb-on-them attaches indirectly.
_TEST_RUNNERS = frozenset({"make", "cmake", "gmake", "ctest"})


def _looks_like_binary_path(token: str) -> bool:
    """A token looks like a runnable binary path if it has a path
    separator, doesn't contain shell metachars, and isn't a known
    shell-wrapper basename."""
    if not token or any(c in token for c in _SHELL_METACHARS):
        return False
    base = token.rsplit("/", 1)[-1]
    if base in _SHELL_WRAPPERS:
        return False
    # `./foo` or `foo/bar` patterns count as binary paths; bare
    # `foo` does not (could be a shell builtin or PATH binary).
    return "/" in token


def _try_unwrap_bash_c(argv: list[str]) -> tuple[list[str] | None, str]:
    """If argv is `bash -c <inner>` and <inner> can be safely shlex-split
    without surprises, return (inner_argv, "static-extracted").
    Otherwise return (None, reason)."""
    if len(argv) < 3 or argv[0] not in ("bash", "sh") or argv[1] != "-c":
        return None, "not-bash-c"
    inner = argv[2]
    if any(c in inner for c in _SHELL_METACHARS):
        return None, "shell-metachars"
    try:
        tokens = shlex.split(inner)
    except ValueError:
        return None, "unparseable"
    if not tokens:
        return None, "empty-inner"
    # Recurse: nested `bash -c "bash -c ..."` is common.
    if tokens[:2] in (["bash", "-c"], ["sh", "-c"]) and len(tokens) >= 3:
        sub, reason = _try_unwrap_bash_c(tokens)
        if sub is not None:
            return sub, reason
    return tokens, "static-extracted"


def _classify(case: dict) -> dict:
    """Classify a single case's binary-resolution prospects.

    Returns a dict with:
      verdict  — one of:
        probed         — strace-probed; harness uses buggy_binary_path directly
        direct-argv0   — trigger_argv[0] is a binary path; gdb --args picks it up
        bash-extracted — bash -c with cleanly extractable inner argv[0]
        bash-fork-make — bash + make/cmake → fork-follow chases into test binary
        bash-fork-ctest — bash + ctest → fork-follow chases through ctest
        bash-fork-other — bash -c with shell metachars; opaque chain
        empty-trigger  — no trigger argv at all (shouldn't happen for included)
      run_binary       — the path the harness will pass as argv[0] to gdb
      run_args         — args[1..] the harness will pass
      gdb_attaches_to  — what gdb will initially attach to (binary or bash)
      confidence       — high | medium | low
      notes            — human-readable diagnostic
    """
    trigger = case["trigger_argv"]
    bbp = case.get("buggy_binary_path")
    bba = case.get("buggy_binary_argv")

    if bba and bbp:
        return {
            "verdict": "probed",
            "run_binary": f"/work/{bbp}",
            "run_args": list(bba[1:]),
            "gdb_attaches_to": f"/work/{bbp}",
            "confidence": "high",
            "notes": "strace probe pinpointed the buggy binary; gdb attaches directly",
        }

    if not trigger:
        return {
            "verdict": "empty-trigger",
            "run_binary": None,
            "run_args": [],
            "gdb_attaches_to": None,
            "confidence": "low",
            "notes": "case has no trigger_argv; can't run anything",
        }

    head = trigger[0]
    head_base = head.rsplit("/", 1)[-1]

    if head_base not in _SHELL_WRAPPERS:
        # Direct: argv[0] is a real binary
        return {
            "verdict": "direct-argv0",
            "run_binary": head,
            "run_args": list(trigger[1:]),
            "gdb_attaches_to": head,
            "confidence": "high",
            "notes": f"trigger_argv[0]={head!r} is a binary; gdb attaches directly",
        }

    # head is a shell wrapper. Try to extract.
    if head_base in ("bash", "sh") and len(trigger) >= 3 and trigger[1] == "-c":
        unwrapped, reason = _try_unwrap_bash_c(trigger)
        if unwrapped is not None:
            inner_head = unwrapped[0] if unwrapped else ""
            inner_base = inner_head.rsplit("/", 1)[-1]
            if inner_base in _TEST_RUNNERS:
                # bash -c "make check" / "ctest ..." style
                return {
                    "verdict": (
                        "bash-fork-ctest" if inner_base == "ctest"
                        else "bash-fork-make"
                    ),
                    "run_binary": head,
                    "run_args": list(trigger[1:]),
                    "gdb_attaches_to": head,
                    "confidence": "low",
                    "notes": (
                        f"trigger is bash → {inner_base}; gdb attaches to bash, "
                        f"fork-follows through {inner_base} which spawns the "
                        f"actual test binary. Probe strongly recommended."
                    ),
                }
            if inner_base in _SHELL_WRAPPERS:
                # bash -c "sh -c ..." or other recursion we couldn't unwrap
                return {
                    "verdict": "bash-fork-other",
                    "run_binary": head,
                    "run_args": list(trigger[1:]),
                    "gdb_attaches_to": head,
                    "confidence": "low",
                    "notes": f"nested shell wrappers ({inner_base}); needs probe",
                }
            # inner_head is a real binary, we extracted it cleanly
            if _looks_like_binary_path(inner_head) or inner_head:
                return {
                    "verdict": "bash-extracted",
                    # The harness still passes the bash -c trigger to gdb,
                    # but `follow-exec-mode new` lands on inner_head.
                    "run_binary": head,
                    "run_args": list(trigger[1:]),
                    "gdb_attaches_to": f"bash → {inner_head} (via follow-exec)",
                    "confidence": "medium",
                    "notes": (
                        f"bash -c '{inner_head} ...'; gdb-on-bash chases into "
                        f"{inner_head} on first exec(). Probe would let gdb "
                        f"attach directly."
                    ),
                }
        # Couldn't unwrap (metachars / nested / unparseable).
        inner_text = trigger[2]
        first_tok = inner_text.lstrip().split(None, 1)[0] if inner_text else ""
        first_tok_base = first_tok.split("/")[-1]
        if first_tok_base in _TEST_RUNNERS:
            verdict = (
                "bash-fork-ctest" if first_tok_base == "ctest"
                else "bash-fork-make"
            )
        else:
            verdict = "bash-fork-other"
        return {
            "verdict": verdict,
            "run_binary": head,
            "run_args": list(trigger[1:]),
            "gdb_attaches_to": head,
            "confidence": "low",
            "notes": (
                f"bash -c with shell metachars ({reason}); gdb attaches to "
                f"bash and chases the exec chain. First inner token: "
                f"{first_tok!r}. Probe required for direct attach."
            ),
        }

    return {
        "verdict": "bash-fork-other",
        "run_binary": head,
        "run_args": list(trigger[1:]),
        "gdb_attaches_to": head,
        "confidence": "low",
        "notes": f"argv[0]={head!r} (wrapper); needs probe",
    }


def _verify_on_disk(case: dict, classify: dict, workspaces_dir: Path) -> str:
    """If the case has a workspace built locally, verify the predicted
    binary path actually exists on disk. Returns one of:
      'exists' — file at predicted path exists in the workspace
      'missing' — predicted path doesn't exist in the workspace
      'no-workspace' — workspace directory doesn't exist
      'no-prediction' — classify produced no predictable path
    """
    bug_id = case["bug_id"]
    ws_root = workspaces_dir / bug_id / case["project"] / f"buggy-{case['bug_index']}"
    if not ws_root.exists():
        return "no-workspace"
    bbp = case.get("buggy_binary_path")
    if bbp:
        return "exists" if (ws_root / bbp).is_file() else "missing"
    # No probed path; check if direct trigger_argv[0] exists
    if classify["verdict"] == "direct-argv0":
        head = case["trigger_argv"][0]
        if head.startswith("./"):
            head = head[2:]
        candidate = ws_root / head
        return "exists" if candidate.is_file() else "missing"
    if classify["verdict"] == "bash-extracted":
        # Extract inner head from trigger
        unwrapped, _ = _try_unwrap_bash_c(case["trigger_argv"])
        if unwrapped:
            head = unwrapped[0]
            if head.startswith("./"):
                head = head[2:]
            candidate = ws_root / head
            return "exists" if candidate.is_file() else "missing"
    return "no-prediction"


def load_cases(db_path: Path, project_filter: list[str] | None) -> list[dict]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    sql = """
        SELECT bug_id, project, bug_index, language, gdb_image,
               trigger_argv_json, workspace_path,
               buggy_binary_path, buggy_binary_argv_json,
               crash_signal, bug_observed,
               patch_first_file, patch_first_line,
               included_in_corpus
        FROM bugs
        WHERE included_in_corpus = 1
          AND trigger_argv_json IS NOT NULL
    """
    params: tuple = ()
    if project_filter:
        placeholders = ",".join("?" * len(project_filter))
        sql += f" AND project IN ({placeholders})"
        params = tuple(project_filter)
    sql += " ORDER BY project, bug_index"
    rows = []
    for r in con.execute(sql, params):
        d = dict(r)
        d["trigger_argv"] = json.loads(d["trigger_argv_json"]) if d["trigger_argv_json"] else []
        d["buggy_binary_argv"] = (
            json.loads(d["buggy_binary_argv_json"]) if d["buggy_binary_argv_json"] else None
        )
        rows.append(d)
    con.close()
    return rows


def render_markdown(rows: list[dict], workspaces_dir: Path) -> str:
    """Render a markdown report of the audit."""
    out: list[str] = []
    out.append("# BugsCPP binary-probe audit")
    out.append("")
    out.append(
        "Generated by `pipeline2/audit_binary_probe.py`. "
        "For every `included_in_corpus=1` bug, this simulates the "
        "harness's binary resolution at runtime "
        "(`bench/drivers/docker_gdb.py:253-260`) and reports what "
        "gdb command would actually be issued."
    )
    out.append("")
    out.append("**Verdicts** (worst-to-best for gdb attach precision):")
    out.append("")
    out.append("| Verdict | Means | gdb attaches to |")
    out.append("|---|---|---|")
    out.append("| `probed` | strace probe pinpointed the binary | binary directly |")
    out.append("| `direct-argv0` | trigger_argv[0] is a real binary path | binary directly |")
    out.append("| `bash-extracted` | `bash -c '<binary> ...'` with no metachars | bash → binary on follow-exec |")
    out.append("| `bash-fork-make` | `bash -c 'make ...'` | bash → make → … (multi-fork) |")
    out.append("| `bash-fork-ctest` | `bash -c 'ctest ...'` | bash → ctest → spawned test |")
    out.append("| `bash-fork-other` | `bash -c 'unparseable'` | bash, opaque chain |")
    out.append("")

    # Aggregate per project
    out.append("## Per-project summary")
    out.append("")
    out.append("| Project | Bugs | probed | direct-argv0 | bash-extracted | bash-fork-make | bash-fork-ctest | bash-fork-other |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    by_proj: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        c = _classify(r)
        r["_classify"] = c
        r["_disk"] = _verify_on_disk(r, c, workspaces_dir)
        by_proj[r["project"]].append(r)
    for proj in sorted(by_proj):
        v_counts = Counter(r["_classify"]["verdict"] for r in by_proj[proj])
        out.append(
            f"| {proj} | {len(by_proj[proj])} | "
            f"{v_counts.get('probed', 0)} | "
            f"{v_counts.get('direct-argv0', 0)} | "
            f"{v_counts.get('bash-extracted', 0)} | "
            f"{v_counts.get('bash-fork-make', 0)} | "
            f"{v_counts.get('bash-fork-ctest', 0)} | "
            f"{v_counts.get('bash-fork-other', 0)} |"
        )

    # Overall
    overall = Counter(r["_classify"]["verdict"] for r in rows)
    total = len(rows)
    out.append(f"| **TOTAL** | **{total}** | "
               f"**{overall.get('probed', 0)}** | "
               f"**{overall.get('direct-argv0', 0)}** | "
               f"**{overall.get('bash-extracted', 0)}** | "
               f"**{overall.get('bash-fork-make', 0)}** | "
               f"**{overall.get('bash-fork-ctest', 0)}** | "
               f"**{overall.get('bash-fork-other', 0)}** |")
    out.append("")

    high = sum(1 for r in rows if r["_classify"]["confidence"] == "high")
    med = sum(1 for r in rows if r["_classify"]["confidence"] == "medium")
    low = sum(1 for r in rows if r["_classify"]["confidence"] == "low")
    out.append(f"**Confidence distribution:** high={high}, medium={med}, low={low}")
    out.append("")
    out.append(f"**Tier compatibility:**")
    out.append(f"- T1 (mini-bash) and T4 (Claude Code) work for **all {total}** "
               f"included bugs — they run the trigger as-is via shell.")
    out.append(f"- T2/T3 (gdb-based) attach precisely for **{high}** "
               f"bugs (probed + direct-argv0); medium for **{med}** "
               f"(bash-extracted, gdb chases via follow-exec); low for "
               f"**{low}** (test-runner indirection, probe required).")
    out.append("")

    # On-disk verification
    on_disk = Counter(r["_disk"] for r in rows)
    if on_disk["exists"] + on_disk["missing"] > 0:
        out.append("## On-disk verification (where workspaces are built locally)")
        out.append("")
        out.append(f"- predicted path **exists** on disk: {on_disk['exists']}")
        out.append(f"- predicted path **missing** on disk: {on_disk['missing']}")
        out.append(f"- workspace not built locally: {on_disk['no-workspace']}")
        out.append("")

    # Per-bug detail tables
    out.append("## Per-bug detail")
    out.append("")
    for proj in sorted(by_proj):
        out.append(f"### {proj}")
        out.append("")
        out.append("| bug_id | verdict | conf | gdb_attaches_to | trigger preview | on-disk |")
        out.append("|---|---|---|---|---|---|")
        for r in sorted(by_proj[proj], key=lambda x: x["bug_index"]):
            c = r["_classify"]
            tprev = (json.dumps(r["trigger_argv"])[:80] + "…") if len(json.dumps(r["trigger_argv"])) > 80 else json.dumps(r["trigger_argv"])
            tprev = tprev.replace("|", "\\|")
            out.append(
                f"| `{r['bug_id']}` | `{c['verdict']}` | {c['confidence']} | "
                f"`{c['gdb_attaches_to']}` | `{tprev}` | {r['_disk']} |"
            )
        out.append("")

    return "\n".join(out) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help="Markdown report path")
    p.add_argument("--project", action="append",
                   help="Restrict to specific projects (repeatable)")
    p.add_argument("--workspaces", type=Path,
                   default=REPO_ROOT / "data" / "workspaces",
                   help="Workspaces dir for on-disk verification")
    args = p.parse_args()

    rows = load_cases(args.db, args.project)
    print(f"audit: {len(rows)} included bugs", file=sys.stderr)

    text = render_markdown(rows, args.workspaces)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)

    # Console summary
    overall = Counter()
    for r in rows:
        c = _classify(r)
        overall[c["verdict"]] += 1
    print(f"  probed:          {overall.get('probed', 0)}")
    print(f"  direct-argv0:    {overall.get('direct-argv0', 0)}")
    print(f"  bash-extracted:  {overall.get('bash-extracted', 0)}")
    print(f"  bash-fork-make:  {overall.get('bash-fork-make', 0)}")
    print(f"  bash-fork-ctest: {overall.get('bash-fork-ctest', 0)}")
    print(f"  bash-fork-other: {overall.get('bash-fork-other', 0)}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
