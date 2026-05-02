# Tier-2 runner image: Ubuntu + clang + gdb + mini-swe-agent.
#
# Why this exists: gdb on macOS arm64 (Homebrew gdb 17.x) cannot run
# native binaries — `target=native` is unavailable for darwin-aarch64,
# so every `run` / `step` / `continue` returns "Don't know how to
# run". Tier 2's persistent-gdb-session value is degraded to
# symbol-loading on macOS. This image gives us a Linux/amd64
# environment where gdb has full native support, so when running
# Tier 2 sweeps from a macOS host we shell into a container and the
# debugger actually works.
#
# Build:  docker build -t chatdbg-tier2-runner \
#                      -f bench/drivers/tier2_runner.Dockerfile .
#
# IMPORTANT: do NOT pin --platform=linux/amd64 on Apple Silicon hosts.
# Rosetta translation breaks gdb's ptrace probes
# ("linux_ptrace_test_ret_to_nx: Cannot PTRACE_GETREGS: Input/output
# error"), making `run` / `bt` etc. unusable. linux/arm64 runs natively
# under Hypervisor.framework on Apple Silicon, where ptrace works.
# The image build picks up the host's native arch by default.
# Used by: bench/drivers/tier2_minisweagent.py (auto-detected when
#           platform.system() == "Darwin"); pass `--tier2-linux=never`
#           to the orchestrator to opt out and use native gdb instead.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        # toolchain — clang for ASan/UBSan rebuilds; libclang-rt-*-dev
        # ships the sanitizer runtime archives (without it, asan/msan
        # links fail on x86_64). gdb is the whole point of this image.
        clang gdb \
        libclang-rt-18-dev \
        # gcc + make + autotools for injected_repo cases that build
        # via plain `make` or `./configure && make` (cjson, lua, ...)
        gcc g++ make cmake autoconf libtool pkg-config \
        # git for prepare_injected_workspace's `git clone` + checkout
        git \
        # python + pip for mini-swe-agent. python3.12 is Ubuntu
        # 24.04's default; mini supports >=3.10.
        python3 python3-pip python3-venv \
        # ca-certificates so litellm/openai HTTPS calls work
        # rsync for moving artefacts back to the bind-mounted run dir
        ca-certificates rsync \
    && rm -rf /var/lib/apt/lists/*

# Install mini-swe-agent and our analysis deps. Pin a known-good
# version so this image is reproducible across hosts. v2.2.8 is the
# version we validated in PR #6 / PR #7 / PR #8.
RUN pip install --break-system-packages --no-cache-dir \
        "mini-swe-agent>=2.2.8,<2.4" \
        "pyyaml" \
    && python3 -c "import minisweagent; print('mini', minisweagent.__file__)"

# tier2_runner.py is bind-mounted from the host repo at /work, not
# baked in — so the runner can iterate without rebuilding the image.
WORKDIR /work
