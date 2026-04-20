#!/usr/bin/env bash
# Trigger the injected cJSON bug. WORKDIR env is set by the orchestrator
# to the root of the cloned+patched+built cJSON tree.
set -u
cd "${WORKDIR:?WORKDIR must be set by the orchestrator}"

# Feed parse_with_opts an unterminated JSON string. The scan loop in
# parse_string will walk past the heap allocation, ASan catches.
printf '"abc' | ./parse_with_opts
