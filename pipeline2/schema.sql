-- pipeline2/schema.sql
-- BugsC++ Pipeline v2 corpus DB. Single table; no audit tables.
-- Apply with: sqlite3 data/corpus.db < pipeline2/schema.sql

CREATE TABLE IF NOT EXISTS bugs (
    case_id             TEXT PRIMARY KEY,      -- "bugscpp-libtiff-2"
    project             TEXT NOT NULL,
    bug_index           INTEGER NOT NULL,
    language            TEXT NOT NULL,         -- "c" or "cpp"
    bug_type            TEXT,
    cve_id              TEXT,

    -- Populated by seed.py
    gdb_image           TEXT NOT NULL,         -- "chatdbgpro/gdb-libtiff:latest"
    trigger_argv_json   TEXT,                  -- JSON array, post bash-c unwrap

    -- Populated by build_and_probe.py
    workspace_path      TEXT,                  -- absolute host path bind-mounted at /work
    gdb_command         TEXT,                  -- full `docker run ... bash -c "..."` shell string

    build_ok            INTEGER,
    build_error         TEXT,
    crash_signal        TEXT,                  -- "SIGSEGV" / "SIGABRT" / "SIGFPE" / "SIGBUS" / NULL
    crash_reproducible  INTEGER,               -- 1 iff same signal observed on all 3 runs

    frame0_function     TEXT,
    frame0_file         TEXT,
    frame0_line         INTEGER,
    user_frame_function TEXT,
    user_frame_file     TEXT,
    user_frame_line     INTEGER,
    backtrace_path      TEXT,                  -- "backtraces/<case_id>.txt"

    -- Developer ground-truth patch (unified diff buggy -> fixed, source files only)
    patch_diff          TEXT,
    patch_files_json    TEXT,                  -- JSON array of touched paths

    -- Bench-framework cross-reference
    case_yaml_path      TEXT,                  -- "bench/cases/<case_id>/case.yaml"

    -- Gate: 1 iff build_ok=1 AND crash_reproducible=1
    --        AND user_frame_file IS NOT NULL AND patch_diff IS NOT NULL
    --        AND case_yaml_path IS NOT NULL
    included_in_corpus  INTEGER DEFAULT 0,

    probed_at           TEXT
);

CREATE INDEX IF NOT EXISTS idx_bugs_project ON bugs(project);
CREATE INDEX IF NOT EXISTS idx_bugs_included ON bugs(included_in_corpus);
