#!/usr/bin/env bash
# Trigger the mg_http_parse uninit-read bug through a tiny MSan harness
# (test/msan_http_parse.c) that the build step compiled. WORKDIR is the
# Mongoose source tree.
set -u
cd "${WORKDIR:?WORKDIR must be set by the orchestrator}"

# A short request that exercises the header loop but leaves most of the
# optional fields of struct mg_http_message unset. The harness calls
# mg_http_parse on this payload and then touches an optional field.
./msan_http_parse $'GET / HTTP/1.0\r\nHost: x\r\n\r\n'
