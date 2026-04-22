# pipeline2/docker/gdb-base.Dockerfile
# Per-project gdb-enabled image. Built by ensure_image.py as
#   chatdbgpro/gdb-<project>:latest
# from `hschoe/defects4cpp-ubuntu:<project>` plus gdb + libtool + patch.

ARG PROJECT
FROM hschoe/defects4cpp-ubuntu:${PROJECT}

USER root
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        gdb libtool-bin patch \
 && rm -rf /var/lib/apt/lists/*

# Workspace is bind-mounted at /work by `docker run -v <host>:/work`.
WORKDIR /work
