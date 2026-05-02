FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        clang lldb gdb \
        libclang-rt-18-dev \
        python3 python3-pip python3-venv \
        ca-certificates rsync \
    && rm -rf /var/lib/apt/lists/*

# ChatDBG runtime deps that the embedded Python in lldb / the orchestrator
# both import. Match the host venv's set.
RUN pip install --break-system-packages --no-cache-dir \
        "litellm>=1.40" pyyaml openai "llm_utils>=0.2.8" \
        "ipython<9" rich ipywidgets ipykernel

# The orchestrator + driver are bind-mounted at /work; nothing to copy.
WORKDIR /work
