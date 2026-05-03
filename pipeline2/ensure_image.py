"""Build per-project gdb-enabled docker images on demand.

Tag scheme: chatdbgpro/gdb-<project>:latest, built from
pipeline2/docker/gdb-base.Dockerfile with --build-arg PROJECT=<project>.
Skips the build if the tag is already present locally.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "pipeline2" / "docker" / "gdb-base.Dockerfile"


def gdb_image_tag(project: str) -> str:
    return f"chatdbgpro/gdb-{project}:latest"


def _image_exists(tag: str) -> bool:
    r = subprocess.run(
        ["docker", "image", "inspect", tag],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def ensure_gdb_image(project: str, *, force: bool = False) -> str:
    """Build chatdbgpro/gdb-<project>:latest if missing. Return the tag."""
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
