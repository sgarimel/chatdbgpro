"""
scripts/ensure_gdb_image.py
Idempotently build chatdbgpro/gdb-<project>:latest from the parameterized
docker/gdb-base.Dockerfile template.

A no-op when the image already exists locally. Otherwise runs
  docker build -f docker/gdb-base.Dockerfile \
      --build-arg BASE_IMAGE=hschoe/defects4cpp-ubuntu:<project> \
      -t chatdbgpro/gdb-<project>:latest docker/

Usage:
    python scripts/ensure_gdb_image.py libtiff
    python scripts/ensure_gdb_image.py --all
    python scripts/ensure_gdb_image.py --all --force   # rebuild even if present
"""

import argparse
import subprocess
import sys
from pathlib import Path

from utils import BUGSCPP_TAXONOMY_DIR, PROJECT_ROOT, SKIP_PROJECTS

DOCKERFILE = PROJECT_ROOT / "docker" / "gdb-base.Dockerfile"
BUILD_CONTEXT = PROJECT_ROOT / "docker"
BASE_IMAGE_FMT = "hschoe/defects4cpp-ubuntu:{project}"
TAG_FMT = "chatdbgpro/gdb-{project}:latest"


def image_exists(tag: str) -> bool:
    r = subprocess.run(
        ["docker", "image", "inspect", tag],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def build_image(project: str) -> tuple[bool, str]:
    base = BASE_IMAGE_FMT.format(project=project)
    tag = TAG_FMT.format(project=project)
    cmd = [
        "docker", "build",
        "-f", str(DOCKERFILE),
        "--build-arg", f"BASE_IMAGE={base}",
        "-t", tag,
        str(BUILD_CONTEXT),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-5:]
        return False, "\n    ".join(tail)
    return True, tag


def ensure(project: str, force: bool = False) -> bool:
    tag = TAG_FMT.format(project=project)
    if not force and image_exists(tag):
        print(f"[ensure_gdb_image] {tag} already present, skipping")
        return True
    print(f"[ensure_gdb_image] building {tag} ...")
    ok, info = build_image(project)
    if ok:
        print(f"[ensure_gdb_image] OK  {info}")
    else:
        print(f"[ensure_gdb_image] FAIL {project}\n    {info}")
    return ok


def discover_projects() -> list[str]:
    if not BUGSCPP_TAXONOMY_DIR.exists():
        print(f"[ensure_gdb_image] taxonomy dir missing: {BUGSCPP_TAXONOMY_DIR}",
              file=sys.stderr)
        sys.exit(2)
    projects = []
    for d in sorted(BUGSCPP_TAXONOMY_DIR.iterdir()):
        if d.is_dir() and d.name not in SKIP_PROJECTS and (d / "meta.json").exists():
            projects.append(d.name)
    return projects


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project", nargs="?",
                        help="project name (e.g. libtiff); omit with --all")
    parser.add_argument("--all", action="store_true",
                        help="build images for every BugsC++ taxonomy project")
    parser.add_argument("--force", action="store_true",
                        help="rebuild even if the image already exists")
    args = parser.parse_args()

    if args.all:
        projects = discover_projects()
        print(f"[ensure_gdb_image] building for {len(projects)} project(s): "
              f"{', '.join(projects)}")
    elif args.project:
        projects = [args.project]
    else:
        parser.error("pass a project name or --all")

    failures = [p for p in projects if not ensure(p, force=args.force)]
    if failures:
        print(f"\n[ensure_gdb_image] {len(failures)} failure(s): {', '.join(failures)}",
              file=sys.stderr)
        sys.exit(1)
    print(f"\n[ensure_gdb_image] all {len(projects)} image(s) ready")


if __name__ == "__main__":
    main()
