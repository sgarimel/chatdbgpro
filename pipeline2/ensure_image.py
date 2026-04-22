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
    cmd = [
        "docker", "build",
        "-t", tag,
        "--build-arg", f"PROJECT={project}",
        "-f", str(DOCKERFILE),
        str(REPO_ROOT),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(
            f"docker build failed for {project}:\n{r.stderr[-2000:]}"
        )
    return tag


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(f"[ensure_image] {p} -> {ensure_gdb_image(p)}")
