FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    gcc-riscv64-linux-gnu \
    binutils-riscv64-linux-gnu \
    qemu-system-misc \
    gdb-multiarch \
    python3 python3-pip python3-venv \
    bc \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install ChatDBG runtime deps
RUN pip3 install --break-system-packages litellm openai pyyaml

ENV TOOLPREFIX=riscv64-linux-gnu-

WORKDIR /xv6
