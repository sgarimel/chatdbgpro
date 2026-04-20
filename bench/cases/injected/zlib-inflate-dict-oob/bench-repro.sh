#!/usr/bin/env bash
# Trigger the zlib inflate_table off-by-one. WORKDIR is the built zlib tree.
set -u
cd "${WORKDIR:?WORKDIR must be set by the orchestrator}"

# Produce a large enough input that the Huffman table is non-trivial,
# gzip it, then round-trip it through the sanitized minigzip.
head -c 65536 /dev/urandom > /tmp/zlib-in.bin
./minigzip /tmp/zlib-in.bin
./minigzip -d /tmp/zlib-in.bin.gz
