ARG BASE_IMAGE
FROM ${BASE_IMAGE}
RUN sed -i '/kitware/d' /etc/apt/sources.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends gdb libtool \
 && rm -rf /var/lib/apt/lists/*
