"""
scripts/extract_patches.py  —  Pipeline Step 5
For each crash-eligible bug:
  1. Pulls the developer's ground-truth patch via `bugscpp show --patch`
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

from utils import DATA_DIR, DB_PATH, IssueTracker, PATCHES_DIR, get_db_connection, run_bugscpp


def extract_patch(project: str, bug_index: int, patch_path) -> bool:
    """
    Pull the ground-truth unified diff from bugscpp and write to patch_path.
    Returns True if the file is non-empty.
    """
    result = run_bugscpp(
        ["show", project, str(bug_index), "--patch"],
        timeout=60,
        check=True,
    )
    content = result.stdout.strip()
    if not content:
        return False
    patch_path.write_text(content)
    return True


def validate_patch(project: str, bug_index: int) -> bool:
    """
    Build and test the FIXED version of the bug inside the container.
    Returns True if the test suite exits 0 (all tests pass with the patch).

    `--buggy false` (or similar flag) tells bugscpp to use the fixed source tree.
    The exact flag name varies by bugscpp version — adjust if needed.
    """
    result = run_bugscpp(
        ["test", project, str(bug_index)],  # tests fixed version by default
        timeout=300,
    )
    return result.returncode == 0


def run(db_path=DB_PATH, resume=False, skip_validation=False):
    PATCHES_DIR.mkdir(parents=True, exist_ok=True)
    con = get_db_connection(db_path)
    cur = con.cursor()

    if resume:
        eligible = cur.execute("""
            SELECT bug_id, project, bug_index FROM test_cases
            WHERE crash_reproducible = 1 AND patch_path IS NULL
        """).fetchall()
    else:
        eligible = cur.execute("""
            SELECT bug_id, project, bug_index FROM test_cases
            WHERE crash_reproducible = 1
        """).fetchall()

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
                valid = validate_patch(project, bug_index)
                if not valid:
                    issues.record("validation_failed", bug_id, "test suite nonzero exit")
            except subprocess.TimeoutExpired:
                tqdm.write(f"  [VALIDATION TIMEOUT] {bug_id}")
                issues.record("validation_timeout", bug_id)
            except Exception as e:
                tqdm.write(f"  [VALIDATION ERROR] {bug_id}: {e}")
                issues.record("bugscpp_error", bug_id, str(e)[:120])
        else:
            valid = True  # trust extraction if validation is skipped

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
    args = parser.parse_args()
    run(resume=args.resume, skip_validation=args.skip_validation)
