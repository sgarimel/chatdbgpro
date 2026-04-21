# ChatDBG Test Case Database
## COS 484 Research Project — Curation, Structure, and Setup Guide

---

## Overview

This document covers everything needed to build and store the test case database for the ChatDBG evaluation project. The database is a curated subset of BugsC++ bugs that reproducibly crash under GDB, annotated with ground-truth crash locations and developer patches. It is the only input the evaluation harness needs to run experiments.

The output of this pipeline is a directory on disk with a well-defined structure: one SQLite database file (`corpus.db`) as the primary index and query interface, plus a companion directory tree of flat files (patches, backtraces, input files) referenced by the database. The whole thing can be committed to the project repo and shared across machines.

---

## Part 1: Environment Setup

Everything in this pipeline runs on Linux. macOS will not work — BugsC++ Docker images are built for `linux/amd64` and GDB behavior on macOS differs. Use a Linux machine, a Linux VM, or a Princeton HPC (Tinker) interactive session.

### 1.1 System Dependencies

Install the following via your package manager before anything else:

```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y \
    docker.io \          # container runtime
    gdb \                # debugger (must be >= 9.0)
    python3 \
    python3-pip \
    git \
    jq \                 # for quick JSON inspection at the command line
    patch                # for applying diffs
```

Verify GDB version:
```bash
gdb --version
# Must print: GNU gdb (Ubuntu ...) 9.x or higher
```

Add your user to the `docker` group so you can run containers without `sudo`:
```bash
sudo usermod -aG docker $USER
newgrp docker             # applies immediately without logout
docker run hello-world    # verify it works
```

### 1.2 Python Dependencies

Create a virtual environment for this project. Everything lives here — do not install into the system Python.

```bash
python3 -m venv ~/chatdbg-eval-env
source ~/chatdbg-eval-env/bin/activate

pip install \
    bugscpp \           # BugsC++ CLI
    requests \          # HTTP for any API calls
    tqdm                # progress bars for long loops
```

Verify the BugsC++ CLI installed correctly:
```bash
bugscpp --version
# Should print a version string without errors
```

### 1.3 Cloning BugsC++

```bash
git clone https://github.com/Suresoft-GLaDOS/bugscpp.git
cd bugscpp
```

The BugsC++ repo contains metadata for all defects (currently 215 across 24 projects, excluding the example project in most runs): project names, bug indices, trigger commands, and tags. You do not need to build BugsC++ from source for this pipeline.

### 1.4 Cloning Your Project Repo

```bash
git clone <your-project-repo-url> chatdbg-eval
cd chatdbg-eval
mkdir -p data/corpus data/patches data/backtraces data/inputs
```

The `data/` directory will hold all pipeline outputs. Structure:

```
data/
├── corpus.db               # SQLite database (primary index)
├── patches/                # ground-truth .diff files, one per bug
│   ├── coreutils-1.diff
│   ├── libtiff-2.diff
│   └── ...
├── backtraces/             # raw GDB backtrace text, one per bug
│   ├── coreutils-1.txt
│   ├── libtiff-2.txt
│   └── ...
└── inputs/                 # trigger input files (binaries, test files)
    ├── libtiff-2/
    │   └── input.tif
    └── ...
```

### 1.5 Pulling BugsC++ Docker Images

This step downloads Docker images for the full dataset (~50-100 GB total). Run it once on a machine with good bandwidth. On Tinker, do this in a `tmux` session in case your connection drops.

```bash
# Pull all images — takes 30–60 minutes depending on connection
bugscpp pull --all

# Verify a specific image pulled correctly (spot check)
docker images | grep bugscpp
```

If storage is a concern, you can pull only the projects you plan to use:
```bash
bugscpp pull libtiff
bugscpp pull coreutils
bugscpp pull libxml2
# etc.
```

But pulling all upfront avoids repeated waits during the filter step.

---

## Part 2: Database Schema and Storage Format

### 2.1 Why SQLite

The test case database is a single SQLite file (`data/corpus.db`). The reasons for this choice over alternatives:

**Why not CSV?** CSV cannot store nested structures (a crash frame has function, file, and line — these don't flatten cleanly) and has no query interface. You'd write a lot of ad hoc parsing code every time you want to filter by project or signal type.

**Why not plain JSON?** One big JSON file is not queryable without loading everything into memory. A directory of per-bug JSON files is queryable but slow and requires custom tooling to aggregate.

**Why not PostgreSQL/MySQL?** A full server database requires setup, credentials, and a running process. SQLite is a single file, zero setup, and supports full SQL. For a corpus of ~150 rows it is more than sufficient and the file can be committed to git (it's small — a few MB).

**Why SQLite over JSON-per-file?** The flat files (patches, backtraces) are still stored as files because they are large text blobs that don't belong in a database. But all metadata — signals, frames, project info, filter results — lives in SQLite so you can write `SELECT * FROM test_cases WHERE crash_signal = 'SIGSEGV' AND project = 'libtiff'` without any custom code.

Large text blobs (full backtrace, full patch content) are stored as files on disk and referenced in the DB by relative path. The DB stores the path, not the content.

### 2.2 Schema

Three tables. Run this to create them:

```sql
-- schema.sql

CREATE TABLE IF NOT EXISTS test_cases (
    bug_id              TEXT PRIMARY KEY,   -- e.g. "libtiff-2"
    project             TEXT NOT NULL,      -- e.g. "libtiff"
    bug_index           INTEGER NOT NULL,   -- BugsC++ index within project (1-based)
    docker_image        TEXT NOT NULL,      -- e.g. "bugscpp/libtiff:2"
    bug_type            TEXT,               -- "buffer_overflow", "use_after_free", "null_deref", "stack_overflow", "other"
    cve_id              TEXT,               -- e.g. "CVE-2016-10092", NULL if none

    -- crash information (populated by filter script)
    crash_signal        TEXT,               -- "SIGSEGV", "SIGABRT", "SIGFPE", "SIGBUS"
    crash_reproducible  INTEGER,            -- 1 if crashed all 3 filter runs, 0 otherwise

    -- frame 0: where execution stopped (may be inside libc)
    frame0_function     TEXT,
    frame0_file         TEXT,
    frame0_line         INTEGER,

    -- user frame: first frame in project source code (what we score against)
    user_frame_function TEXT,
    user_frame_file     TEXT,
    user_frame_line     INTEGER,

    -- trigger command (relative to build directory inside container)
    trigger_command     TEXT,               -- e.g. "./tiff2pdf input.tif /dev/null"

    -- file paths (relative to data/)
    backtrace_path      TEXT,               -- e.g. "backtraces/libtiff-2.txt"
    patch_path          TEXT,               -- e.g. "patches/libtiff-2.diff"
    inputs_dir          TEXT,               -- e.g. "inputs/libtiff-2/" or NULL

    -- validation
    patch_validated     INTEGER DEFAULT 0,  -- 1 if fixed version passes test suite
    included_in_corpus  INTEGER DEFAULT 0,  -- 1 if this case passes all filters

    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS filter_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bug_id          TEXT NOT NULL,
    run_number      INTEGER NOT NULL,       -- 1, 2, or 3 (reproducibility runs)
    crashed         INTEGER NOT NULL,       -- 1 or 0
    signal          TEXT,                   -- signal observed, or NULL
    gdb_exit_code   INTEGER,
    raw_output_path TEXT,                   -- path to raw GDB stdout for this run
    ran_at          TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (bug_id) REFERENCES test_cases(bug_id)
);

CREATE TABLE IF NOT EXISTS build_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bug_id      TEXT NOT NULL,
    success     INTEGER NOT NULL,           -- 1 or 0
    error_msg   TEXT,                       -- NULL if success
    built_at    TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (bug_id) REFERENCES test_cases(bug_id)
);
```

Initialize the database:
```bash
sqlite3 data/corpus.db < schema.sql
```

### 2.3 Querying the Database

A few useful queries once the database is populated:

```bash
# How many bugs passed all filters?
sqlite3 data/corpus.db "SELECT COUNT(*) FROM test_cases WHERE included_in_corpus = 1;"

# Breakdown by signal type
sqlite3 data/corpus.db \
  "SELECT crash_signal, COUNT(*) FROM test_cases WHERE included_in_corpus = 1 GROUP BY crash_signal;"

# Breakdown by project
sqlite3 data/corpus.db \
  "SELECT project, COUNT(*) FROM test_cases WHERE included_in_corpus = 1 GROUP BY project ORDER BY COUNT(*) DESC;"

# Cases where the crash frame is in a system library (user_frame != frame0)
sqlite3 data/corpus.db \
  "SELECT bug_id, frame0_function, user_frame_function FROM test_cases
   WHERE included_in_corpus = 1 AND frame0_function != user_frame_function;"

# Export the full corpus as CSV for inspection
sqlite3 -header -csv data/corpus.db \
  "SELECT * FROM test_cases WHERE included_in_corpus = 1;" > corpus_export.csv
```

---

## Part 3: Building the Corpus — Step by Step

### 3.1 Seed the Database with BugsC++ Metadata

BugsC++ has a structured metadata file for each project that lists all bugs, their CVE IDs, and their categories. The first script reads this metadata and inserts a row for every candidate bug into `test_cases`, with `included_in_corpus = 0` until it passes all filters.

```python
# scripts/seed_db.py
"""
Reads BugsC++ metadata and inserts all bug candidates into test_cases
as candidate rows. Does not build or run anything.
"""

import sqlite3
import subprocess
import json
import sys

DB_PATH = "data/corpus.db"

def get_bugscpp_metadata():
    """
    Call the bugscpp CLI to list all projects and their bugs.
    Returns a list of dicts with keys: project, index, docker_image, cve_id, bug_type
    """
    result = subprocess.run(
        ["bugscpp", "list", "--json"],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)

def seed(db_path):
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    bugs = get_bugscpp_metadata()
    inserted = 0

    for bug in bugs:
        bug_id = f"{bug['project']}-{bug['index']}"
        docker_image = f"bugscpp/{bug['project']}:{bug['index']}"

        cur.execute("""
            INSERT OR IGNORE INTO test_cases
                (bug_id, project, bug_index, docker_image, bug_type, cve_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            bug_id,
            bug['project'],
            bug['index'],
            docker_image,
            bug.get('type'),        # may be None
            bug.get('cve_id'),      # may be None
        ))
        inserted += cur.rowcount

    con.commit()
    con.close()
    print(f"Seeded {inserted} bugs into {db_path}")

if __name__ == "__main__":
    seed(DB_PATH)
```

Run it:
```bash
python scripts/seed_db.py
# Expected: "Seeded <N> bugs into data/corpus.db" (typically ~214 when skipping example)
```

**Note:** The exact `bugscpp list --json` interface depends on the BugsC++ version. If it does not support `--json`, inspect the metadata directory in the cloned BugsC++ repo (`bugscpp/metadata/`) — each project has a JSON file listing its bugs. The seed script may need to read those files directly instead.

### 3.2 Build Filter: Compile Each Bug with Debug Symbols

Before running GDB, each bug must be checked out and built with debug symbols (`-g -O0`). This script attempts the build for every candidate and logs the result.

```python
# scripts/build_filter.py
"""
For each candidate bug in test_cases, checkout the buggy workspace and
build with debug symbols. Logs results to build_log.
"""

import sqlite3
import subprocess
import sys
from tqdm import tqdm

DB_PATH = "data/corpus.db"

def build_bug(bug_id, project, bug_index):
    """
    Use the bugscpp CLI to build the buggy version with debug symbols.
    Returns (success: bool, error_msg: str or None)
    """
    try:
        result = subprocess.run(
            ["bugscpp", "build", project, str(bug_index),
             "--coverage", "off",
             "--extra-cflags", "-g -O0"],
            capture_output=True, text=True, timeout=300   # 5 min timeout
        )
        if result.returncode == 0:
            return True, None
        else:
            return False, result.stderr[:2000]
    except subprocess.TimeoutExpired:
        return False, "build timed out after 300s"
    except Exception as e:
        return False, str(e)

def run(db_path):
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    candidates = cur.execute(
        "SELECT bug_id, project, bug_index FROM test_cases"
    ).fetchall()

    for bug_id, project, bug_index in tqdm(candidates, desc="Building"):
        success, error_msg = build_bug(bug_id, project, bug_index)
        cur.execute("""
            INSERT INTO build_log (bug_id, success, error_msg)
            VALUES (?, ?, ?)
        """, (bug_id, 1 if success else 0, error_msg))

    con.commit()
    con.close()

if __name__ == "__main__":
    run(DB_PATH)
```

Run it:
```bash
python scripts/build_filter.py
```

After this completes, check how many built successfully:
```bash
sqlite3 data/corpus.db \
  "SELECT success, COUNT(*) FROM build_log GROUP BY success;"
```

Bugs that fail to build are excluded from all subsequent steps. Do not delete them from `test_cases` — just leave `included_in_corpus = 0` and note the build failure.

### 3.3 Crash Filter: Run Each Bug Under GDB Three Times

This is the core filtering step. For each bug that built successfully, run the crash-triggering test input under GDB in batch mode and check whether the program crashes with a catchable signal. Repeat three times to confirm reproducibility.

Important CLI compatibility note: the documented BugsC++ CLI does **not** include `bugscpp exec`. The pipeline runs GDB directly from the checked-out local workspace directory instead.

```python
# scripts/crash_filter.py
"""
For each successfully-built bug, run it under GDB 3 times and record
whether it crashes with SIGSEGV, SIGABRT, SIGFPE, or SIGBUS each time.
A bug is crash-eligible if it crashes all 3 runs with the same signal.

Stores raw GDB output to data/filter_runs/<bug_id>_run<N>.txt
Updates filter_log and test_cases tables.
"""

import sqlite3
import subprocess
import os
import re
from tqdm import tqdm

DB_PATH = "data/corpus.db"
FILTER_RUN_DIR = "data/filter_runs"
CATCHABLE_SIGNALS = {"SIGSEGV", "SIGABRT", "SIGFPE", "SIGBUS"}

os.makedirs(FILTER_RUN_DIR, exist_ok=True)

GDB_BATCH_SCRIPT = """
set pagination off
set confirm off
run
bt
quit
"""

def get_trigger_command(project, bug_index):
    """
    Ask bugscpp for the command that triggers the bug.
    Returns (command_string, input_files_list)
    """
    result = subprocess.run(
        ["bugscpp", "show", project, str(bug_index), "--json"],
        capture_output=True, text=True, check=True
    )
    import json
    info = json.loads(result.stdout)
    return info.get("trigger_command"), info.get("trigger_inputs", [])

def run_gdb(bug_id, project, bug_index, run_number):
    """
    Run the buggy program under GDB from the checked-out buggy workspace.
    Returns (crashed: bool, signal: str or None, output: str)
    """
    raw_path = os.path.join(FILTER_RUN_DIR, f"{bug_id}_run{run_number}.txt")

    try:
        # Run gdb directly in the local buggy workspace directory
        result = subprocess.run(
            ["gdb", "-batch",
             "-ex", "set pagination off",
             "-ex", "set confirm off",
             "-ex", "run",
             "-ex", "bt",
             "-ex", "quit",
             "--args", "TRIGGER_PLACEHOLDER"],   # populate from trigger_command metadata
            capture_output=True, text=True, timeout=120, cwd="WORKSPACE_BUGGY_DIR"
        )
        output = result.stdout + result.stderr

        with open(raw_path, "w") as f:
            f.write(output)

        # Parse for signal
        signal = parse_signal(output)
        crashed = signal in CATCHABLE_SIGNALS

        return crashed, signal, raw_path

    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", raw_path
    except Exception as e:
        return False, f"ERROR: {e}", raw_path

def parse_signal(gdb_output):
    """
    Extract the signal name from GDB batch output.
    GDB prints lines like:
        Program received signal SIGSEGV, Segmentation fault.
        Program terminated with signal SIGABRT, ...
    """
    patterns = [
        r"Program received signal (\w+)",
        r"Program terminated with signal (\w+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, gdb_output)
        if m:
            return m.group(1)
    return None

def run_filter(db_path):
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # Only process bugs that built successfully
    built_bugs = cur.execute("""
        SELECT t.bug_id, t.project, t.bug_index
        FROM test_cases t
        JOIN build_log b ON t.bug_id = b.bug_id
        WHERE b.success = 1
    """).fetchall()

    for bug_id, project, bug_index in tqdm(built_bugs, desc="Crash filter"):
        signals_seen = []

        for run_num in range(1, 4):   # 3 runs for reproducibility
            crashed, signal, raw_path = run_gdb(bug_id, project, bug_index, run_num)

            cur.execute("""
                INSERT INTO filter_log (bug_id, run_number, crashed, signal, raw_output_path)
                VALUES (?, ?, ?, ?, ?)
            """, (bug_id, run_num, 1 if crashed else 0, signal, raw_path))

            if crashed:
                signals_seen.append(signal)

        # Reproducible = crashed all 3 times with the same catchable signal
        reproducible = (
            len(signals_seen) == 3 and
            len(set(signals_seen)) == 1 and
            signals_seen[0] in CATCHABLE_SIGNALS
        )

        if reproducible:
            final_signal = signals_seen[0]
            cur.execute("""
                UPDATE test_cases
                SET crash_signal = ?, crash_reproducible = 1
                WHERE bug_id = ?
            """, (final_signal, bug_id))
        else:
            cur.execute("""
                UPDATE test_cases SET crash_reproducible = 0 WHERE bug_id = ?
            """, (bug_id,))

    con.commit()
    con.close()

if __name__ == "__main__":
    run_filter(DB_PATH)
```

Run it:
```bash
python scripts/crash_filter.py
```

This is the slowest step — 3 GDB runs x ~200 bugs. On a fast machine, budget 2-4 hours. Run it in `tmux`.

After completion:
```bash
# How many bugs crash reproducibly?
sqlite3 data/corpus.db \
  "SELECT crash_signal, COUNT(*) FROM test_cases WHERE crash_reproducible = 1 GROUP BY crash_signal;"
```

### 3.4 Extract Crash Location from Backtrace

For each reproducibly crashing bug, run GDB one more time with a richer command set from the checked-out workspace to capture the full backtrace and extract the crash frames.

```python
# scripts/extract_crash_location.py
"""
For each crash-eligible bug, runs GDB to get a full backtrace, extracts:
  - frame0 (where execution stopped)
  - user_frame (first frame in project source, not libc/system)
Stores the raw backtrace to data/backtraces/<bug_id>.txt
Updates frame columns in test_cases.
"""

import sqlite3
import subprocess
import os
import re
from tqdm import tqdm

DB_PATH = "data/corpus.db"
BACKTRACE_DIR = "data/backtraces"

os.makedirs(BACKTRACE_DIR, exist_ok=True)

# Prefixes that indicate a system/library frame (not user code)
SYSTEM_PATH_PREFIXES = [
    "/usr/",
    "/lib/",
    "/build/",
    "??",           # GDB uses "??" for unknown source
]

def is_system_frame(file_path):
    if not file_path:
        return True
    for prefix in SYSTEM_PATH_PREFIXES:
        if file_path.startswith(prefix):
            return True
    return False

def parse_backtrace(gdb_output):
    """
    Parse GDB backtrace output into a list of frame dicts.
    GDB backtrace lines look like:
      #0  TIFFReadDirectory (tif=0x...) at tif_dirread.c:3973
      #1  0x00007f... in main (argc=2, argv=...) at tiff2pdf.c:121
    """
    frame_pattern = re.compile(
        r"#(\d+)\s+(?:0x[0-9a-f]+\s+in\s+)?(\S+)\s+\(.*?\)\s+at\s+([^:]+):(\d+)"
    )
    frames = []
    for line in gdb_output.splitlines():
        m = frame_pattern.search(line)
        if m:
            frames.append({
                "index": int(m.group(1)),
                "function": m.group(2),
                "file": m.group(3).strip(),
                "line": int(m.group(4)),
            })
    return frames

def extract_user_frame(frames):
    """Walk frames from 0 upward, return first frame in project source."""
    for frame in sorted(frames, key=lambda f: f["index"]):
        if not is_system_frame(frame["file"]):
            return frame
    return None

def run_extraction(db_path):
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    eligible = cur.execute("""
        SELECT bug_id, project, bug_index
        FROM test_cases
        WHERE crash_reproducible = 1
    """).fetchall()

    for bug_id, project, bug_index in tqdm(eligible, desc="Extracting frames"):
        backtrace_path = os.path.join(BACKTRACE_DIR, f"{bug_id}.txt")

        result = subprocess.run(
            ["bugscpp", "exec", project, str(bug_index),
             "--", "gdb", "-batch",
             "-ex", "set pagination off",
             "-ex", "run",
             "-ex", "bt full",
             "-ex", "quit",
             "--args", "TRIGGER_PLACEHOLDER"],
            capture_output=True, text=True, timeout=120
        )
        output = result.stdout + result.stderr

        with open(backtrace_path, "w") as f:
            f.write(output)

        frames = parse_backtrace(output)
        if not frames:
            # GDB produced output we couldn't parse — log and skip
            print(f"  WARNING: no parseable frames for {bug_id}")
            continue

        frame0 = frames[0]
        user_frame = extract_user_frame(frames) or frame0

        cur.execute("""
            UPDATE test_cases SET
                frame0_function = ?,
                frame0_file     = ?,
                frame0_line     = ?,
                user_frame_function = ?,
                user_frame_file     = ?,
                user_frame_line     = ?,
                backtrace_path      = ?
            WHERE bug_id = ?
        """, (
            frame0["function"], frame0["file"], frame0["line"],
            user_frame["function"], user_frame["file"], user_frame["line"],
            os.path.relpath(backtrace_path, "data"),
            bug_id,
        ))

    con.commit()
    con.close()

if __name__ == "__main__":
    run_extraction(DB_PATH)
```

Run it:
```bash
python scripts/extract_crash_location.py
```

Spot-check a few results:
```bash
sqlite3 data/corpus.db \
  "SELECT bug_id, frame0_function, user_frame_function, user_frame_file, user_frame_line
   FROM test_cases WHERE crash_reproducible = 1 LIMIT 10;" | column -t -s "|"
```

Manually inspect 2–3 of the raw backtrace files in `data/backtraces/` to confirm the parser is picking the right frame.

### 3.5 Extract and Validate Ground-Truth Patches

```python
# scripts/extract_patches.py
"""
For each crash-eligible bug:
1. Reads the developer's ground-truth patch from taxonomy patch files:
   `../bugscpp/bugscpp/taxonomy/<project>/patch/<idx:04d>-buggy.patch`
   and `../bugscpp/bugscpp/taxonomy/<project>/patch/<idx:04d>-common.patch`
2. Stores it to data/patches/<bug_id>.diff
3. Validates against the fixed version by running `bugscpp test`
4. Sets patch_validated = 1 if validation succeeds
5. Updates patch_path in test_cases
"""

import sqlite3
import subprocess
import os
from tqdm import tqdm

DB_PATH = "data/corpus.db"
PATCHES_DIR = "data/patches"

os.makedirs(PATCHES_DIR, exist_ok=True)

def extract_patch(project, bug_index, patch_path):
    """Read patch text from taxonomy files and write to file."""
    # Read 0001-buggy.patch and 0001-common.patch if present, concatenate.
    ...

def validate_patch(project, bug_index, case_expr=None):
    """
    Run tests on the fixed version. Returns True if tests pass.
    Optional: pass --case <EXPR> to target a subset of test IDs.
    """
    result = subprocess.run(
        ["bugscpp", "test", project, str(bug_index)],
        capture_output=True, text=True, timeout=300
    )
    return result.returncode == 0

def run(db_path):
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    eligible = cur.execute("""
        SELECT bug_id, project, bug_index
        FROM test_cases
        WHERE crash_reproducible = 1
    """).fetchall()

    for bug_id, project, bug_index in tqdm(eligible, desc="Extracting patches"):
        patch_path = os.path.join(PATCHES_DIR, f"{bug_id}.diff")
        rel_patch_path = os.path.relpath(patch_path, "data")

        # Extract
        try:
            ok = extract_patch(project, bug_index, patch_path)
        except Exception as e:
            print(f"  ERROR extracting patch for {bug_id}: {e}")
            continue

        if not ok:
            print(f"  WARNING: empty patch for {bug_id}")
            continue

        # Validate
        try:
            valid = validate_patch(project, bug_index)
        except subprocess.TimeoutExpired:
            valid = False
            print(f"  WARNING: test suite timed out for {bug_id}")
        except Exception as e:
            valid = False
            print(f"  ERROR validating {bug_id}: {e}")

        cur.execute("""
            UPDATE test_cases
            SET patch_path = ?, patch_validated = ?
            WHERE bug_id = ?
        """, (rel_patch_path, 1 if valid else 0, bug_id))

    con.commit()
    con.close()

if __name__ == "__main__":
    run(DB_PATH)
```

Run it:
```bash
python scripts/extract_patches.py
```

Check validation results:
```bash
sqlite3 data/corpus.db \
  "SELECT patch_validated, COUNT(*) FROM test_cases WHERE crash_reproducible = 1 GROUP BY patch_validated;"
```

Bugs where `patch_validated = 0` should be investigated manually. They may have an environment issue inside the container, or the BugsC++ ground truth may be stale. Do not include unvalidated cases in the final corpus.

### 3.6 Mark Final Corpus

Once all filters and extractions are complete, run a final query to mark which bugs make it into the corpus. A bug is included if and only if:

1. It built successfully
2. It crashes reproducibly with a catchable signal (all 3 runs)
3. Its frames were parsed successfully (user_frame_function is not NULL)
4. Its ground-truth patch was extracted and validated

```python
# scripts/finalize_corpus.py
"""
Sets included_in_corpus = 1 for all bugs that pass every filter.
Run this last, after all other scripts complete.
"""

import sqlite3

DB_PATH = "data/corpus.db"

def finalize(db_path):
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    cur.execute("""
        UPDATE test_cases
        SET included_in_corpus = 1
        WHERE crash_reproducible = 1
          AND user_frame_function IS NOT NULL
          AND patch_validated = 1
          AND bug_id IN (
              SELECT bug_id FROM build_log WHERE success = 1
          )
    """)

    n = cur.execute(
        "SELECT COUNT(*) FROM test_cases WHERE included_in_corpus = 1"
    ).fetchone()[0]

    con.commit()
    con.close()
    print(f"Final corpus: {n} cases marked included_in_corpus = 1")

if __name__ == "__main__":
    finalize(DB_PATH)
```

Run it:
```bash
python scripts/finalize_corpus.py
# Expected output: "Final corpus: ~120-160 cases marked included_in_corpus = 1"
```

---

## Part 4: Final Corpus Verification

Before committing the corpus, run a sanity check across all included cases:

```bash
# Full summary
sqlite3 data/corpus.db "
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN crash_signal = 'SIGSEGV' THEN 1 ELSE 0 END) as sigsegv,
    SUM(CASE WHEN crash_signal = 'SIGABRT' THEN 1 ELSE 0 END) as sigabrt,
    SUM(CASE WHEN crash_signal = 'SIGFPE'  THEN 1 ELSE 0 END) as sigfpe,
    SUM(CASE WHEN crash_signal = 'SIGBUS'  THEN 1 ELSE 0 END) as sigbus,
    SUM(CASE WHEN frame0_function != user_frame_function THEN 1 ELSE 0 END) as indirect_crashes
FROM test_cases WHERE included_in_corpus = 1;
"

# Verify every included case has a backtrace file on disk
sqlite3 data/corpus.db "SELECT backtrace_path FROM test_cases WHERE included_in_corpus = 1;" |
  while read p; do
    [ -f "data/$p" ] || echo "MISSING: data/$p"
  done

# Verify every included case has a patch file on disk
sqlite3 data/corpus.db "SELECT patch_path FROM test_cases WHERE included_in_corpus = 1;" |
  while read p; do
    [ -f "data/$p" ] || echo "MISSING: data/$p"
  done
```

If all checks pass, commit the corpus to the project repo:

```bash
git add data/corpus.db data/patches/ data/backtraces/
git commit -m "Add curated test case corpus (N crash-eligible bugs from BugsC++)"
```

Do not commit `data/filter_runs/` — those are raw debug logs and are large. Add them to `.gitignore`.

---

## Part 5: Directory and File Summary

```
data/
├── corpus.db               # SQLite — primary index and query interface
│                           # Tables: test_cases, filter_log, build_log
│
├── patches/                # Ground-truth developer patches
│   ├── coreutils-1.diff    # unified diff for each included bug
│   ├── libtiff-2.diff
│   └── ...
│
├── backtraces/             # Raw GDB backtrace text
│   ├── coreutils-1.txt
│   ├── libtiff-2.txt
│   └── ...
│
├── inputs/                 # Trigger input files (if any)
│   ├── libtiff-2/
│   │   └── input.tif
│   └── ...
│
└── filter_runs/            # Raw GDB output from crash filter (NOT committed)
    ├── coreutils-1_run1.txt
    ├── coreutils-1_run2.txt
    └── ...

scripts/
├── seed_db.py              # Step 1: insert all discovered candidates
├── build_filter.py         # Step 2: attempt builds, log results
├── crash_filter.py         # Step 3: run GDB 3x, check signals
├── extract_crash_location.py  # Step 4: parse frames, store backtrace files
├── extract_patches.py      # Step 5: pull and validate patches
└── finalize_corpus.py      # Step 6: set included_in_corpus flag

schema.sql                  # DB schema definition
```

---

## Part 6: Execution Order

Run the scripts in this exact order. Each step depends on the previous one completing successfully.

```bash
# 0. One-time environment setup (see Part 1)
source ~/chatdbg-eval-env/bin/activate
sqlite3 data/corpus.db < schema.sql

# 1. Seed
python scripts/seed_db.py

# 2. Build filter (~30-60 min, run in tmux)
python scripts/build_filter.py

# 3. Crash filter (~2-4 hours, run in tmux)
python scripts/crash_filter.py

# 4. Extract crash locations (~20-40 min)
python scripts/extract_crash_location.py

# 5. Extract and validate patches (~30-60 min)
python scripts/extract_patches.py

# 6. Finalize
python scripts/finalize_corpus.py

# 7. Verify and commit
# (run verification queries from Part 4, then git commit)
```

Total wall-clock time: approximately 4–7 hours on a single machine with a decent network connection. Steps 2 and 3 are the bottleneck and should be run in `tmux` to survive disconnections.
