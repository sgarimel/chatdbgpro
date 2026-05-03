"""Build per-project gdb-enabled images on demand.

Two runtime backends, selected at the call site:

  runtime="docker" (default)
    Local docker build of chatdbgpro/gdb-<project>:latest from
    pipeline2/docker/gdb-base.Dockerfile. Cached locally; rebuilds
    only when missing or force=True. Returns the local docker tag.

  runtime="apptainer"
    Returns a docker:// URL pointing at the pre-published registry
    image. Apptainer pulls + caches the SIF on first use; subsequent
    `apptainer instance start` calls hit the local cache (~/.apptainer/
    cache/). For HPC hosts (adroit, della, ...) that lack docker.

Registry mapping:
  Default registry: ghcr.io/diodide/chatdbgpro-gdb-<project>:latest.
  Override via $BENCH_APPTAINER_REGISTRY (env), e.g.
  ghcr.io/<your-namespace>/chatdbgpro-gdb-<project>:latest.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "pipeline2" / "docker" / "gdb-base.Dockerfile"

DEFAULT_APPTAINER_REGISTRY = "ghcr.io/diodide"


def gdb_image_tag(project: str) -> str:
    return f"chatdbgpro/gdb-{project}:latest"


def gdb_image_apptainer_url(project: str) -> str:
    """docker:// URL apptainer can pull. Honors $BENCH_APPTAINER_REGISTRY
    so a researcher running on a different namespace doesn't need a
    code change."""
    registry = os.environ.get("BENCH_APPTAINER_REGISTRY", DEFAULT_APPTAINER_REGISTRY)
    return f"docker://{registry}/chatdbgpro-gdb-{project}:latest"


def _image_exists(tag: str) -> bool:
    r = subprocess.run(
        ["docker", "image", "inspect", tag],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def ensure_gdb_image(project: str, *, force: bool = False,
                     runtime: str = "docker") -> str:
    """Return an image reference the caller's container runtime can use.

    runtime="apptainer": no local build required — returns a docker://
    registry URL apptainer pulls + caches on first use. Local docker
    daemon is not needed.
    runtime="docker": ensures a local build of chatdbgpro/gdb-<project>:
    latest, then returns the tag.
    """
    if runtime == "apptainer":
        return gdb_image_apptainer_url(project)
    if runtime != "docker":
        raise ValueError(f"Unknown runtime: {runtime!r}")
    tag = gdb_image_tag(project)
    if not force and _image_exists(tag):
        return tag
    # hschoe/defects4cpp-ubuntu:<project> ships amd64 only. On arm64 Macs the
    # build (and `docker run` later) must explicitly pin linux/amd64 — without
    # this Docker fails to pull stage-2 FROM with "no matching manifest". The
    # build still runs natively for stage 1 and via Rosetta/QEMU for stage 2.
    cmd = [
        "docker", "build",
        "--platform", "linux/amd64",
        "-t", tag,
        "--build-arg", f"PROJECT={project}",
        "-f", str(DOCKERFILE),
        str(REPO_ROOT),
    ]
    # Stage 1 (Python 3.11 + gdb 14.2 from source) takes ~35 min on x86 and
    # significantly longer under emulation on Apple Silicon. Bumping timeout
    # to 2h for the first build; stage-2-only builds finish in a few minutes.
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if r.returncode != 0:
        raise RuntimeError(
            f"docker build failed for {project}:\n{r.stderr[-2000:]}"
        )
    return tag


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(f"[ensure_image] {p} -> {ensure_gdb_image(p)}")
