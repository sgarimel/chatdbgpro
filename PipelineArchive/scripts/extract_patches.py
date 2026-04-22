"""
scripts/extract_patches.py  —  Pipeline Step 5
For each crash-eligible bug:
  1. Reads the ground-truth patch directly from BugsC++ taxonomy patch files
  2. Saves it to data/patches/<bug_id>.diff
  3. Runs the fixed version's test suite to confirm the patch is valid
  4. Sets patch_validated = 1 in test_cases if validation passes

Bugs with patch_validated = 0 are excluded from the final corpus by
finalize_corpus.py. Investigate failures manually — they may indicate a
stale patch in BugsC++ or a container environment issue.

Usage:
    python scripts/extract_patches.py
    python scripts/extract_patches.py --resume   # skip bugs already patch_validated=1
    python scripts/extract_patches.py --skip-validation  # extract only, no test run
    python scripts/extract_patches.py --workers 4
"""

import argparse
import subprocess

from _parallel import BugResult, run_pipeline_step
from utils import (
    DATA_DIR,
    DB_PATH,
    IssueTracker,
    PATCHES_DIR,
    checkout_bug,
    get_db_connection,
    get_workspace_dir,
    read_taxonomy_patch,
    run_bugscpp,
)


def extract_patch(project: str, bug_index: int, patch_path) -> bool:
    content = read_taxonomy_patch(project, bug_index).strip()
    if not content:
        return False
    patch_path.write_text(content + "\n")
    return True


def validate_patch(
    project: str, bug_index: int, case_expr: str | None = None,
    build_timeout: int = 900, test_timeout: int = 600,
) -> tuple[bool, str]:
    """
    Build and test the FIXED version of the bug via the bugscpp CLI.
    Returns (ok, reason). `ok=True` iff the test suite exits 0.
    """
    fixed_dir = get_workspace_dir(project, bug_index, buggy=False)
    if not fixed_dir.exists():
        co = checkout_bug(project, bug_index, buggy=False, timeout=300)
        if co.returncode != 0:
            err = (co.stderr or co.stdout or "checkout failed").strip()[:200]
            return False, f"checkout_failed: {err}"

    build = run_bugscpp(["build", str(fixed_dir)], timeout=build_timeout)
    if build.returncode != 0:
        err = (build.stderr or build.stdout or "build failed").strip()[-200:]
        return False, f"build_failed: {err}"

    test_cmd = ["test", str(fixed_dir)]
    if case_expr:
        test_cmd += ["--case", case_expr]
    result = run_bugscpp(test_cmd, timeout=test_timeout)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "tests failed").strip()[-200:]
        return False, f"tests_failed: {err}"
    return True, "ok"


def process_one(row: dict, ctx: dict) -> BugResult:
    bug_id = row["bug_id"]
    project = row["project"]
    bug_index = row["bug_index"]
    skip_validation = ctx["skip_validation"]
    case_expr = ctx["case_expr"]

    patch_path = PATCHES_DIR / f"{bug_id}.diff"
    res = BugResult(bug_id=bug_id)

    try:
        ok = extract_patch(project, bug_index, patch_path)
    except subprocess.TimeoutExpired:
        res.log_lines.append(f"  [EXTRACT TIMEOUT] {bug_id}")
        res.issue_records.append(("extract_timeout", bug_id, ""))
        res.counters["skipped"] = 1
        return res
    except Exception as e:
        res.log_lines.append(f"  [EXTRACT FAIL] {bug_id}: {e}")
        res.issue_records.append(("extract_failed", bug_id, str(e)[:120]))
        res.counters["skipped"] = 1
        return res

    if not ok:
        res.log_lines.append(f"  [EMPTY PATCH] {bug_id}")
        res.issue_records.append(("empty_patch", bug_id, ""))
        res.counters["skipped"] = 1
        return res

    res.counters["extracted"] = 1
    rel_patch = patch_path.relative_to(DATA_DIR)

    valid = False
    if not skip_validation:
        try:
            valid, reason = validate_patch(project, bug_index, case_expr=case_expr)
            if not valid:
                kind = reason.split(":", 1)[0] or "validation_failed"
                res.log_lines.append(f"  [VALIDATION FAIL] {bug_id}: {reason}")
                res.issue_records.append((kind, bug_id, reason[:160]))
        except subprocess.TimeoutExpired:
            res.log_lines.append(f"  [VALIDATION TIMEOUT] {bug_id}")
            res.issue_records.append(("validation_timeout", bug_id, ""))
        except Exception as e:
            res.log_lines.append(f"  [VALIDATION ERROR] {bug_id}: {e}")
            res.issue_records.append(("bugscpp_error", bug_id, str(e)[:120]))

    if valid:
        res.counters["validated"] = 1
        res.log_lines.append(f"  [OK] {bug_id}")

    res.db_updates.append((
        "UPDATE test_cases SET patch_path = ?, patch_validated = ? WHERE bug_id = ?",
        (rel_patch.as_posix(), 1 if valid else 0, bug_id),
    ))
    return res


def run(db_path=DB_PATH, resume=False, skip_validation=False, case_expr=None,
        bug_id=None, workers=1):
    PATCHES_DIR.mkdir(parents=True, exist_ok=True)
    con = get_db_connection(db_path)
    cur = con.cursor()

    base_sql = (
        "SELECT bug_id, project, bug_index FROM test_cases "
        "WHERE crash_reproducible = 1"
    )
    params: tuple = ()
    if bug_id:
        base_sql += " AND bug_id = ?"
        params = (bug_id,)
    if resume:
        base_sql += " AND (patch_validated IS NULL OR patch_validated = 0)"
    eligible = cur.execute(base_sql, params).fetchall()

    if not eligible:
        print("[extract_patches] No crash-eligible bugs to process.")
        con.close()
        return

    rows = [dict(r) for r in eligible]
    print(f"[extract_patches] Processing {len(rows)} bug(s) "
          f"(skip_validation={skip_validation}, workers={workers})")

    issues = IssueTracker("extract_patches")
    counters = run_pipeline_step(
        bug_rows=rows,
        work_fn=process_one,
        ctx={"skip_validation": skip_validation, "case_expr": case_expr},
        workers=workers,
        desc="Patches",
        con=con,
        issue_tracker=issues,
    )
    con.close()

    extracted = counters.get("extracted", 0)
    validated = counters.get("validated", 0)
    skipped = counters.get("skipped", 0)
    print(f"[extract_patches] Done: {extracted} extracted, "
          f"{validated} validated, {skipped} skipped")
    issues.print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true",
                        help="Skip bugs whose patch already passed validation")
    parser.add_argument("--skip-validation", action="store_true",
                        help="Extract patches without running the test suite")
    parser.add_argument("--case", default=None,
                        help="Optional bugscpp --case expression for targeted tests")
    parser.add_argument("--bug-id", default=None,
                        help="Process only this bug_id")
    parser.add_argument("--db", default=str(DB_PATH),
                        help="Path to sqlite DB (default: data/corpus.db)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of parallel workers (default: 1 = serial)")
    args = parser.parse_args()
    run(db_path=args.db, resume=args.resume,
        skip_validation=args.skip_validation, case_expr=args.case,
        bug_id=args.bug_id, workers=args.workers)
