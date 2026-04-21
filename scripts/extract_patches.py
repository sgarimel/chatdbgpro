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
    python scripts/extract_patches.py --resume   # skip bugs with patch_path set
    python scripts/extract_patches.py --skip-validation  # extract only, no test run
"""

import argparse
import subprocess

from tqdm import tqdm

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
    """
    Read the ground-truth unified diff from the taxonomy patch directory and
    write it to patch_path.
    Returns True if the file is non-empty.
    """
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
    Workflow (per bugscpp docs):
      1. `bugscpp checkout <project> <index> -t <target>` (no --buggy) ->
         creates <target>/<project>/fixed-<index>
      2. `bugscpp build <fixed_checkout_path>`
      3. `bugscpp test  <fixed_checkout_path> [--case <expr>]`

    Returns (ok, reason). `ok=True` iff the test suite exits 0.
    `reason` is one of: "ok", "checkout_failed: ...", "build_failed: ...",
    "tests_failed: ...".
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


def run(db_path=DB_PATH, resume=False, skip_validation=False, case_expr=None,
        bug_id=None):
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
        base_sql += " AND patch_path IS NULL"
    eligible = cur.execute(base_sql, params).fetchall()

    if not eligible:
        print("[extract_patches] No crash-eligible bugs to process.")
        return

    print(f"[extract_patches] Processing {len(eligible)} bug(s) "
          f"(skip_validation={skip_validation})")

    issues = IssueTracker("extract_patches")
    extracted = validated = skipped = 0

    for row in tqdm(eligible, desc="Patches", unit="bug"):
        bug_id, project, bug_index = row["bug_id"], row["project"], row["bug_index"]
        patch_path = PATCHES_DIR / f"{bug_id}.diff"

        # --- Extract ---
        try:
            ok = extract_patch(project, bug_index, patch_path)
        except subprocess.TimeoutExpired:
            tqdm.write(f"  [EXTRACT TIMEOUT] {bug_id}")
            issues.record("extract_timeout", bug_id)
            skipped += 1
            continue
        except Exception as e:
            tqdm.write(f"  [EXTRACT FAIL] {bug_id}: {e}")
            issues.record("extract_failed", bug_id, str(e)[:120])
            skipped += 1
            continue

        if not ok:
            tqdm.write(f"  [EMPTY PATCH] {bug_id}")
            issues.record("empty_patch", bug_id)
            skipped += 1
            continue

        extracted += 1
        rel_patch = patch_path.relative_to(DATA_DIR)

        # --- Validate (unless skipped) ---
        valid = False
        if not skip_validation:
            try:
                valid, reason = validate_patch(
                    project, bug_index, case_expr=case_expr,
                )
                if not valid:
                    kind = reason.split(":", 1)[0] or "validation_failed"
                    tqdm.write(f"  [VALIDATION FAIL] {bug_id}: {reason}")
                    issues.record(kind, bug_id, reason[:160])
            except subprocess.TimeoutExpired:
                tqdm.write(f"  [VALIDATION TIMEOUT] {bug_id}")
                issues.record("validation_timeout", bug_id)
            except Exception as e:
                tqdm.write(f"  [VALIDATION ERROR] {bug_id}: {e}")
                issues.record("bugscpp_error", bug_id, str(e)[:120])
        else:
            # Extraction-only mode: mark patch_validated=0 so finalize can
            # distinguish "extracted but not yet validated" from real pass.
            valid = False

        if valid:
            validated += 1
            tqdm.write(f"  [OK] {bug_id}")

        cur.execute(
            """
            UPDATE test_cases
            SET patch_path = ?, patch_validated = ?
            WHERE bug_id = ?
            """,
            (str(rel_patch), 1 if valid else 0, bug_id),
        )
        con.commit()

    con.close()
    print(
        f"[extract_patches] Done: {extracted} extracted, "
        f"{validated} validated, {skipped} skipped"
    )
    issues.print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true",
                        help="Skip bugs that already have patch_path set")
    parser.add_argument("--skip-validation", action="store_true",
                        help="Extract patches without running the test suite")
    parser.add_argument(
        "--case",
        default=None,
        help="Optional bugscpp --case expression for targeted validation tests",
    )
    parser.add_argument("--bug-id", default=None,
                        help="Process only this bug_id")
    parser.add_argument("--db", default=str(DB_PATH),
                        help="Path to sqlite DB (default: data/corpus.db)")
    args = parser.parse_args()
    run(db_path=args.db, resume=args.resume,
        skip_validation=args.skip_validation, case_expr=args.case,
        bug_id=args.bug_id)
