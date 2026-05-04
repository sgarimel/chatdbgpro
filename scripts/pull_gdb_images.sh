#!/usr/bin/env bash
# Pull chatdbgpro gdb images from GHCR and retag them to the local names
# the corpus database (data/corpus.db) and bench drivers expect.
#
# Usage:
#   scripts/pull_gdb_images.sh                # pull every image listed in corpus.db
#   scripts/pull_gdb_images.sh berry exiv2    # pull only the named projects
#   scripts/pull_gdb_images.sh --runtime apptainer berry   # SIF cache via apptainer
#
# Env:
#   REGISTRY  default: ghcr.io/sgarimel
#   RUNTIME   docker (default) | apptainer
set -euo pipefail

REGISTRY="${REGISTRY:-ghcr.io/anikamehrotra}"
RUNTIME="${RUNTIME:-docker}"

# Parse --runtime out of args, leave the rest as project names.
projects=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime) RUNTIME="$2"; shift 2 ;;
    --runtime=*) RUNTIME="${1#--runtime=}"; shift ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *) projects+=("$1"); shift ;;
  esac
done

# If no projects passed, derive the list from corpus.db so we pull exactly
# what the bench expects to find. Falls back to local images if the DB is missing.
if [[ ${#projects[@]} -eq 0 ]]; then
  if [[ -f data/corpus.db ]]; then
    mapfile -t projects < <(
      python - <<'PY'
import sqlite3, sys
db = sqlite3.connect("data/corpus.db")
seen = set()
for (image,) in db.execute(
    "select distinct gdb_image from bugs where gdb_image is not null"
):
    # gdb_image looks like 'chatdbgpro/gdb-<project>:latest'
    name = image.split("/")[-1].split(":")[0]
    if name.startswith("gdb-"):
        seen.add(name[len("gdb-"):])
for p in sorted(seen):
    print(p)
PY
    )
  fi
fi

if [[ ${#projects[@]} -eq 0 ]]; then
  echo "ERROR: no projects to pull. Pass project names or run from a checkout with data/corpus.db." >&2
  exit 1
fi

case "$RUNTIME" in
  docker)
    for p in "${projects[@]}"; do
      remote="$REGISTRY/chatdbgpro-gdb-$p:latest"
      local_tag="chatdbgpro/gdb-$p:latest"
      echo "=== $p ==="
      docker pull "$remote"
      docker tag "$remote" "$local_tag"
      echo "  retagged -> $local_tag"
    done
    ;;
  apptainer)
    : "${APPTAINER_CACHEDIR:=$HOME/.apptainer/cache}"
    mkdir -p "$APPTAINER_CACHEDIR"
    for p in "${projects[@]}"; do
      url="docker://$REGISTRY/chatdbgpro-gdb-$p:latest"
      echo "=== $p ==="
      APPTAINER_CACHEDIR="$APPTAINER_CACHEDIR" apptainer pull --force \
        "$APPTAINER_CACHEDIR/chatdbgpro-gdb-$p.sif" "$url"
    done
    ;;
  *)
    echo "ERROR: unknown --runtime '$RUNTIME' (expected docker or apptainer)" >&2
    exit 2
    ;;
esac

echo
echo "Done. Pulled ${#projects[@]} image(s) from $REGISTRY."
