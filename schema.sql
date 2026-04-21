-- schema.sql
-- ChatDBG evaluation corpus database schema.
-- Run once to initialize: sqlite3 data/corpus.db < schema.sql
-- Tables: test_cases (primary), filter_log (per-run crash records), build_log (build attempts)

CREATE TABLE IF NOT EXISTS test_cases (
    bug_id              TEXT PRIMARY KEY,   -- e.g. "libtiff-2"
    project             TEXT NOT NULL,      -- e.g. "libtiff"
    bug_index           INTEGER NOT NULL,   -- BugsC++ index within project (1-based)
    docker_image        TEXT NOT NULL,      -- e.g. "bugscpp/libtiff:2"
    bug_type            TEXT,               -- "buffer_overflow", "use_after_free", "null_deref", etc.
    cve_id              TEXT,               -- e.g. "CVE-2016-10092", NULL if none

    -- Crash info (populated by crash_filter.py)
    crash_signal        TEXT,               -- "SIGSEGV", "SIGABRT", "SIGFPE", "SIGBUS"
    crash_reproducible  INTEGER,            -- 1 if crashed all 3 filter runs, 0 otherwise

    -- Frame 0: where execution stopped (may be inside libc/system lib)
    frame0_function     TEXT,
    frame0_file         TEXT,
    frame0_line         INTEGER,

    -- User frame: first frame in project source code (what we score predictions against)
    user_frame_function TEXT,
    user_frame_file     TEXT,
    user_frame_line     INTEGER,

    -- Trigger command (relative to build dir inside container)
    trigger_command     TEXT,               -- e.g. "./tiff2pdf input.tif /dev/null"

    -- Relative paths from data/ directory
    backtrace_path      TEXT,               -- e.g. "backtraces/libtiff-2.txt"
    patch_path          TEXT,               -- e.g. "patches/libtiff-2.diff"
    inputs_dir          TEXT,               -- e.g. "inputs/libtiff-2/" or NULL

    -- Validation flags
    patch_validated     INTEGER DEFAULT 0,  -- 1 if fixed version passes test suite
    included_in_corpus  INTEGER DEFAULT 0,  -- 1 if this case passes ALL filters

    created_at          TEXT DEFAULT (datetime('now'))
);

-- One row per GDB run attempt (3 runs per bug in crash_filter.py)
CREATE TABLE IF NOT EXISTS filter_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bug_id          TEXT NOT NULL,
    run_number      INTEGER NOT NULL,       -- 1, 2, or 3
    crashed         INTEGER NOT NULL,       -- 1 or 0
    signal          TEXT,                   -- signal observed ("SIGSEGV" etc.), or NULL
    gdb_exit_code   INTEGER,
    raw_output_path TEXT,                   -- path to raw GDB stdout for this run
    ran_at          TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (bug_id) REFERENCES test_cases(bug_id)
);

-- One row per build attempt
CREATE TABLE IF NOT EXISTS build_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bug_id      TEXT NOT NULL,
    success     INTEGER NOT NULL,           -- 1 or 0
    error_msg   TEXT,                       -- NULL if success
    built_at    TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (bug_id) REFERENCES test_cases(bug_id)
);
