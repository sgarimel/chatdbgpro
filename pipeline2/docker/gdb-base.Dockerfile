# pipeline2/docker/gdb-base.Dockerfile
# Per-project gdb-enabled image. Built by ensure_image.py as
#   chatdbgpro/gdb-<project>:latest
#
# Two-stage build:
#   Stage 1 (gdb-builder) — shared across all projects. Builds Python 3.11
#   from source, gdb 14.2 linked against it, and a venv with ChatDBG's
#   runtime deps. Everything lives under /opt and is relocatable (RPATH).
#   Expensive (~30 min on first build) but Docker's layer cache reuses it
#   across every per-project build.
#
#   Stage 2 (final) — per-project. Starts from the bugscpp base image
#   (Ubuntu 20.04), COPYs /opt/python3.11 + /opt/gdb + /opt/chatdbg-venv
#   from stage 1. The base image's C/C++ build toolchain is untouched,
#   so existing data/workspaces/ remain valid.
#
# Why this design:
#   * ChatDBG requires Python 3.11+ (PEP 585 generics, no `from __future__`
#     shims). Ubuntu 20.04's system Python is 3.8. gdb's embedded Python
#     is locked to whatever libpython gdb was linked against, so the fix
#     has to rebuild gdb against 3.11.
#   * Deadsnakes' focal PPA was emptied on 2025-10-01 — its Packages
#     index is zero bytes for every arch. We build Python 3.11 from source.
#   * RPATH + `-L/opt/python3.11/lib` at gdb-configure time let gdb's
#     conftest link against libpython3.11 at a non-standard prefix and
#     run at build time. Without the explicit -L, gdb's internal
#     python-config.py emits only `-lpython3.11` (no search path),
#     `AC_TRY_LINK` fails, and configure reports "no usable python."

# PROJECT must be declared before the first FROM so it's visible in the
# stage-2 FROM line. Stage 1 ignores it.
ARG PROJECT

# ─── Stage 1: shared Python 3.11 + gdb + ChatDBG deps builder ────────────────
# Build on Ubuntu 18.04 (bionic, GLIBC 2.27). GLIBC is NOT forward-compatible:
# a binary built against 20.04's glibc 2.31 references symbols bionic lacks
# ("GLIBC_2.28 not found" at load). Building on bionic makes the resulting
# /opt/gdb + /opt/python3.11 binaries runnable on BOTH bionic and focal
# bugscpp base images. Bundled libs in /opt/gdb/lib cover the rest of the
# SONAME drift (libreadline 7→8, libncurses 5→6, libboost_regex, libicu*).
FROM ubuntu:18.04 AS gdb-builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl wget xz-utils \
        build-essential \
        libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
        libffi-dev liblzma-dev libncurses-dev libgdbm-dev uuid-dev \
        libexpat1-dev tk-dev \
        texinfo libmpfr-dev libgmp-dev libsource-highlight-dev \
 && rm -rf /var/lib/apt/lists/*

# Bionic's apt rustc is 1.41 (2020). tiktoken's Rust sources need ≥1.70 to
# parse their Cargo.toml (edition = "2021", resolver = "2"). litellm 1.55+
# transitively pulls tiktoken ≥0.7 with no bionic-compatible wheel, so we
# have to build it from source — install rustup to get a modern toolchain.
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --profile minimal --default-toolchain stable
ENV PATH=/root/.cargo/bin:${PATH}

# Build Python 3.11 from source into /opt/python3.11 as a shared-lib install.
# LDFLAGS=-Wl,-rpath=/opt/python3.11/lib embeds the runtime lib path into
# every ELF we build against this Python.
ARG PYTHON_VERSION=3.11.10
RUN cd /tmp \
 && wget -q https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz \
 && tar -xf Python-${PYTHON_VERSION}.tar.xz \
 && cd Python-${PYTHON_VERSION} \
 && ./configure \
        --prefix=/opt/python3.11 \
        --enable-shared \
        --with-ensurepip=install \
        --disable-test-modules \
        LDFLAGS='-Wl,-rpath=/opt/python3.11/lib' \
 && make -j"$(nproc)" \
 && make install \
 && cd /tmp && rm -rf Python-${PYTHON_VERSION} Python-${PYTHON_VERSION}.tar.xz \
 && ln -sf /opt/python3.11/bin/python3.11 /opt/python3.11/bin/python3 \
 && ln -sf /opt/python3.11/bin/python3.11 /opt/python3.11/bin/python

ENV PATH=/opt/python3.11/bin:${PATH}

RUN python3.11 -c 'import sys; assert sys.version_info[:2] == (3, 11); print(sys.version)'

# Build gdb 14.2 against /opt/python3.11.
#   --with-python=DIR      sets python_prog to DIR/bin/python (our symlink)
#   LDFLAGS -L + -rpath    lets gdb's AC_TRY_LINK conftest find libpython3.11
#                          at link time and find it again at runtime.
ARG GDB_VERSION=14.2
RUN cd /tmp \
 && wget -q https://ftp.gnu.org/gnu/gdb/gdb-${GDB_VERSION}.tar.xz \
 && tar -xf gdb-${GDB_VERSION}.tar.xz \
 && cd gdb-${GDB_VERSION} \
 && ./configure \
        --prefix=/opt/gdb \
        --with-python=/opt/python3.11 \
        --with-system-readline \
        --disable-nls \
        --disable-werror \
        --disable-gdbserver \
        LDFLAGS='-L/opt/python3.11/lib -Wl,-rpath=/opt/python3.11/lib' \
 && make -j"$(nproc)" \
 && make install-strip \
 && cd /tmp && rm -rf gdb-${GDB_VERSION} gdb-${GDB_VERSION}.tar.xz

# Bundle every non-core shared lib gdb transitively links against into
# /opt/gdb/lib so the image runs unchanged on both Ubuntu 20.04 (focal)
# and Ubuntu 18.04 (bionic) stage-2 bases. Focal ships libreadline.so.8,
# libncursesw.so.6, libtinfo.so.6, libboost_regex.so.1.71.0, libicu*.so.66;
# bionic only has the older SONAMEs (.so.7, .so.5, 1.65.1, .so.60). Without
# bundling, stage-2 on bionic hits "libreadline.so.8: cannot open ..." (and
# half a dozen similar errors after).
#
# We skip the core glibc/gcc/stdc++ runtime (libc.so, libm.so, libpthread,
# libdl, libutil, libgcc_s, libstdc++, ld-linux) — those must come from the
# base OS or we'd risk ABI mismatches with the debuggee. libpython3.11 is
# already shipped via the /opt/python3.11 copy, so also skip.
#
# patchelf --force-rpath on every bundled .so makes the dynamic linker
# resolve transitive deps out of /opt/gdb/lib instead of the system paths,
# regardless of whether the binary uses DT_RPATH or DT_RUNPATH semantics.
RUN apt-get update \
 && apt-get install -y --no-install-recommends patchelf \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /opt/gdb/lib \
 && CORE='libc\.so|libm\.so|libpthread\.so|libdl\.so|libutil\.so|libgcc_s\.so|libstdc\+\+\.so|ld-linux|linux-vdso|libpython3\.11' \
 && ldd /opt/gdb/bin/gdb | awk '/=> \//{print $3}' \
      | grep -Ev "$CORE" \
      | while read -r lib; do cp -aL "$lib" /opt/gdb/lib/; done \
 && for so in /opt/gdb/lib/*.so*; do \
        [ -f "$so" ] && [ ! -L "$so" ] && patchelf --force-rpath --set-rpath '$ORIGIN' "$so" || true; \
    done \
 && patchelf --force-rpath --set-rpath '$ORIGIN/../lib:/opt/python3.11/lib' /opt/gdb/bin/gdb

# Fail the build now if gdb's embedded interpreter isn't 3.11.
RUN /opt/gdb/bin/gdb -nx -batch -ex 'python import sys; print(sys.version)' \
 | grep -q '^3\.11'

# Install ChatDBG's runtime deps into a venv on top of /opt/python3.11.
# The venv's executables inherit the RPATH from /opt/python3.11, so they're
# portable to stage 2 as long as /opt/python3.11 is copied alongside.
RUN python3.11 -m venv /opt/chatdbg-venv \
 && /opt/chatdbg-venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/chatdbg-venv/bin/pip install --no-cache-dir \
        "llm-utils>=0.2.8" \
        "openai>=1.29.0" \
        "rich>=13.7.0" \
        "ansicolors>=1.1.8" \
        "traitlets>=5.14.1" \
        "ipdb>=0.13.13" \
        "ipython>=9.0.0" \
        "pygments>=2.0.0" \
        "litellm==1.55.9" \
        "PyYAML>=6.0.1" \
        "ipyflow>=0.0.130" \
        "numpy>=1.26.3"


# ─── Stage 2: per-project final image ────────────────────────────────────────
FROM hschoe/defects4cpp-ubuntu:${PROJECT} AS final

USER root
ENV DEBIAN_FRONTEND=noninteractive

# The hschoe base images have a stale apt.kitware.com entry in
# /etc/apt/sources.list whose GPG key has expired — strip it before apt
# update. libsource-highlight4v5 is the runtime lib gdb links against
# (source-highlight-dev in stage 1); libtool-bin is needed by build.py
# for libtool wrapper handling; `patch` is already in the base.
RUN sed -i '/kitware/d' /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null || true \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        libtool-bin patch libsource-highlight4v5 \
 && rm -rf /var/lib/apt/lists/*

# Drop in Python 3.11, gdb, and the ChatDBG venv from the builder.
# RPATH in these binaries makes them self-contained — no ldconfig, no
# LD_LIBRARY_PATH required at `docker run` time.
COPY --from=gdb-builder /opt/python3.11   /opt/python3.11
COPY --from=gdb-builder /opt/gdb          /opt/gdb
COPY --from=gdb-builder /opt/chatdbg-venv /opt/chatdbg-venv

# Our gdb wins on PATH. Python 3.11 is exposed too. The ChatDBG venv's
# site-packages is surfaced as an env var so docker_gdb.py can extend
# PYTHONPATH at `docker run` time without hard-coding the version.
ENV PATH=/opt/gdb/bin:/opt/python3.11/bin:${PATH} \
    CHATDBG_VENV_SITE=/opt/chatdbg-venv/lib/python3.11/site-packages

# Fail the image build now if any invariant breaks: custom gdb on PATH,
# gdb's embedded Python is 3.11, ChatDBG's deps import under that Python.
RUN test "$(command -v gdb)" = "/opt/gdb/bin/gdb" \
 && gdb -nx -batch -ex 'python import sys; assert sys.version_info[:2] == (3, 11), sys.version' \
 && gdb -nx -batch -ex "python import sys; sys.path.insert(0, '${CHATDBG_VENV_SITE}'); import litellm, openai, llm_utils, yaml, rich, ipdb, IPython, numpy"

# Workspace is bind-mounted at /work by `docker run -v <host>:/work`.
WORKDIR /work
