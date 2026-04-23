-- pipeline2/schema.sql
-- BugsC++ Pipeline v2 corpus DB. Single table; no audit tables.
-- Apply with: sqlite3 data/corpus.db < pipeline2/schema.sql

CREATE TABLE IF NOT EXISTS bugs (
    bug_id              TEXT PRIMARY KEY,      -- "libtiff-2"  (no "bugscpp-" prefix)
    project             TEXT NOT NULL,
    bug_index           INTEGER NOT NULL,
    language            TEXT NOT NULL,         -- "c" or "cpp"
    bug_type            TEXT,
    cve_id              TEXT,

    -- Populated by seed.py
    gdb_image           TEXT NOT NULL,         -- "chatdbgpro/gdb-libtiff:latest"
    trigger_argv_json   TEXT,                  -- JSON array, post bash-c unwrap

    -- Developer fix patch (buggy -> fixed, source files only); reversed from
    -- taxonomy/<project>/patch/<NNNN>-buggy.patch. Also written to disk at
    -- data/<patch_path>; DockerDriver+judge read the file.
    patch_diff             TEXT,
    patch_files_json       TEXT,               -- JSON array of touched in-project paths
    patch_path             TEXT,               -- "patches/<bug_id>.diff", relative to data/
    patch_first_file       TEXT,               -- first hunk file, e.g. "tools/tiffcrop.c"
    patch_first_line       INTEGER,            -- first changed line in BUGGY-tree coordinates
    patch_line_ranges_json TEXT,               -- JSON: [{"file":"...","start":L,"end":L}, ...]

    -- Canonical workspace location the DockerDriver bind-mounts at /work.
    -- Computed at seed time; materialized by build.py. Format:
    --   data/workspaces/<bug_id>/<project>/buggy-<bug_index>
    workspace_path      TEXT,
    gdb_command         TEXT,                  -- full `docker run ... bash -c "..."` shell string

    build_ok            INTEGER,
    build_error         TEXT,

    -- Informational probe results (optional — judge's structured-field rubric reads these).
    crash_signal        TEXT,                  -- "SIGSEGV" / "SIGABRT" / ...
    crash_reproducible  INTEGER,               -- kept for compat; 1 iff single probe saw a signal
    frame0_function     TEXT,
    frame0_file         TEXT,
    frame0_line         INTEGER,
    user_frame_function TEXT,
    user_frame_file     TEXT,
    user_frame_line     INTEGER,
    backtrace_path      TEXT,                  -- "backtraces/<bug_id>.txt"

    -- Single string summarizing observed runtime behavior:
    --   "crash:SIGSEGV" | "exit_code:N" | "no_observation"
    bug_observed        TEXT,

    -- Gate: 1 iff build_ok=1 AND patch_first_file IS NOT NULL AND patch_path IS NOT NULL.
    -- Crash is NOT required — non-crash logical-error bugs are still debuggable via state inspection.
    included_in_corpus  INTEGER DEFAULT 0,

    built_at            TEXT,
    probed_at           TEXT
);

CREATE INDEX IF NOT EXISTS idx_bugs_project  ON bugs(project);
CREATE INDEX IF NOT EXISTS idx_bugs_included ON bugs(included_in_corpus);
