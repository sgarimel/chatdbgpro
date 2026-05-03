# bench/drivers/synthetic_runner.Dockerfile
# A minimal Linux runner image for synthetic single-file C/C++ cases.
# Used by Tier3Driver in containerize=True mode (the GDB-everywhere
# default).
#
# Built as: chatdbgpro/synthetic-runner:latest
#
# Why this exists:
#   - Pre-migration, T3 synthetic ran lldb on macOS, gdb on Linux. That
#     made "T3 macOS vs T3 Linux" a confounding axis in cross-tier
#     comparisons.
#   - The BugsCPP T3 path runs gdb in chatdbgpro/gdb-<project> images.
#     Mirroring that for synthetic gives one debugger interface across
#     every host and every case kind.
#
# Platform selection:
#   - This Dockerfile builds for the host's native architecture by
#     default. On Apple Silicon (linux/arm64), gdb's ptrace works
#     natively. On linux/amd64, ptrace also works natively. On
#     Apple Silicon emulating linux/amd64 via Rosetta, gdb's ptrace
#     is broken (Rosetta does not implement PTRACE_GETREGS) — so the
#     synthetic-runner is intentionally built for the host's native
#     arch, not pinned to amd64 like the BugsCPP gdb-* images.
#   - BugsCPP T3 cannot avoid amd64 (hschoe/defects4cpp-ubuntu:* is
#     amd64-only); on Apple Silicon a working BugsCPP T3 path requires
#     disabling Rosetta in Docker Desktop > Settings > General >
#     "Use Rosetta for x86/amd64 emulation" (falls back to QEMU,
#     which implements PTRACE_GETREGS correctly).
#
# Build:
#   docker build -t chatdbgpro/synthetic-runner:latest \
#       -f bench/drivers/synthetic_runner.Dockerfile bench/drivers/
#   (Pass --platform if you need to override the native arch.)

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Toolchain + gdb. Ubuntu 24.04 ships gdb 15.1 with Python 3.12 embedded;
# that's plenty for ChatDBG's PEP 585 generics. clang covers C and C++.
# python3-venv lets us isolate ChatDBG's runtime deps from the system
# Python so future apt updates don't break us.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        build-essential clang \
        libclang-rt-18-dev \
        gdb gdbserver \
        python3 python3-venv python3-pip \
        libsource-highlight4v5 \
 && rm -rf /var/lib/apt/lists/*

# Build a venv with ChatDBG's runtime deps. Same set as
# pipeline2/docker/gdb-base.Dockerfile so behavior matches the BugsCPP
# T3 path.
RUN python3 -m venv /opt/chatdbg-venv \
 && /opt/chatdbg-venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/chatdbg-venv/bin/pip install --no-cache-dir \
        "llm-utils>=0.2.8" \
        "openai>=1.29.0" \
        "rich>=13.7.0" \
        "ansicolors>=1.1.8" \
        "traitlets>=5.14.1" \
        "ipdb>=0.13.13" \
        "ipython>=8.14.0,<9" \
        "pygments>=2.0.0" \
        "litellm==1.55.9" \
        "PyYAML>=6.0.1" \
        "ipyflow>=0.0.130" \
        "numpy>=1.26.3"

# CHATDBG_VENV_SITE: Tier3Driver appends this to PYTHONPATH at run time
# so gdb's embedded Python finds litellm/openai/llm_utils/...
ENV CHATDBG_VENV_SITE=/opt/chatdbg-venv/lib/python3.12/site-packages

# Sanity: gdb's Python imports the venv's deps when site-packages is
# pushed to sys.path.
RUN gdb -nx -batch -ex "python import sys; sys.path.insert(0, '${CHATDBG_VENV_SITE}'); import litellm, openai, llm_utils, yaml, rich" \
 && clang --version

WORKDIR /work
