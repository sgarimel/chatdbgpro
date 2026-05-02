"""Audit included_in_corpus rows and reset the ones whose trigger binary
isn't actually on disk.

Background: the original inclusion gate (build_ok=1 + patch metadata) was
satisfied even when bugscpp returned 0 without persisting build outputs to
the host workspace (a Windows ↔ Docker bind-mount quirk). This produced
~95 zombie rows that DockerDriver can't actually run. This script finds
those rows and clears their built_at + build_ok + included_in_corpus so
`pipeline2/build.py --resume` will retry them.

Run once before kicking the build retry. Idempotent.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "corpus.db"

sys.path.insert(0, str(REPO_ROOT / "pipeline2"))
from build import trigger_binary_path  # noqa: E402


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    if not db_path.exists():
        sys.exit(f"DB not found: {db_path}")

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row

    rows = con.execute(
        "SELECT bug_id, workspace_path, trigger_argv_json "
        "FROM bugs WHERE included_in_corpus = 1"
    ).fetchall()

    reset_ids: list[str] = []
    by_proj: dict[str, int] = {}
    for r in rows:
        if not r["workspace_path"] or not r["trigger_argv_json"]:
            continue
        argv = json.loads(r["trigger_argv_json"])
        bp = trigger_binary_path(Path(r["workspace_path"]), argv)
        if bp is None or not bp.exists():
            reset_ids.append(r["bug_id"])
            proj = r["bug_id"].rsplit("-", 1)[0]
            by_proj[proj] = by_proj.get(proj, 0) + 1

    print(f"[audit] {len(rows)} rows currently included_in_corpus=1")
    print(f"[audit] {len(reset_ids)} have a missing trigger binary on disk")
    if by_proj:
        print("[audit] by project:")
        for p, n in sorted(by_proj.items()):
            print(f"  {p:22} {n}")

    if not reset_ids:
        print("[audit] nothing to reset")
        return 0

    placeholders = ",".join("?" for _ in reset_ids)
    con.execute(
        f"UPDATE bugs SET built_at = NULL, build_ok = NULL, "
        f"  included_in_corpus = 0, "
        f"  build_error = 'reset by audit_and_reset: trigger binary missing' "
        f"WHERE bug_id IN ({placeholders})",
        reset_ids,
    )
    con.commit()
    print(f"[audit] reset {len(reset_ids)} rows; queued for rebuild")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
