#!/usr/bin/env bash
# Trigger the sqlite3 shell .read NULL fopen bug. WORKDIR is the built sqlite tree.
set -u
cd "${WORKDIR:?WORKDIR must be set by the orchestrator}"

# .read on a path that cannot possibly exist -> fopen returns NULL ->
# missing null check means fgets() is handed NULL.
./sqlite3 :memory: ".read /does/not/exist/chatdbgpro-bench-missing-file.sql"
