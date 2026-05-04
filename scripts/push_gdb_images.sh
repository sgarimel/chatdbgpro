#!/usr/bin/env bash
# Push locally-built chatdbgpro/gdb-<project>:latest images to GHCR.
#
# Usage:
#   scripts/push_gdb_images.sh                # push every local chatdbgpro/gdb-*
#   scripts/push_gdb_images.sh berry exiv2    # push only the named projects
#   DRY_RUN=1 scripts/push_gdb_images.sh      # print what would happen
#
# Env:
#   REGISTRY        default: ghcr.io/sgarimel
#   GHCR_USER       default: $(gh api user --jq .login)
#   GHCR_TOKEN      default: $(gh auth token); must have write:packages scope
#                   (run: gh auth refresh -h github.com -s write:packages,read:packages)
#
# Note on visibility:
#   GitHub's REST + GraphQL APIs do not expose a visibility flip for
#   *user-owned* container packages — only org-owned. After this script
#   finishes, it prints the package settings URLs; flip them to "Public"
#   manually (one click each, "Change visibility" at the bottom of the page).
#   Org-owned namespaces can be flipped automatically; if you point this
#   script at one (REGISTRY=ghcr.io/<org>), set PUBLIC=1.
set -euo pipefail

REGISTRY="${REGISTRY:-ghcr.io/anikamehrotra}"
DRY_RUN="${DRY_RUN:-0}"
PUBLIC="${PUBLIC:-0}"  # off by default; only meaningful for org namespaces

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '  [dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

# ghcr.io/<namespace>/repo  ->  <namespace> (used by the GitHub packages API)
namespace="${REGISTRY#ghcr.io/}"
namespace="${namespace%%/*}"
if [[ -z "$namespace" || "$namespace" == "$REGISTRY" ]]; then
  echo "ERROR: REGISTRY must look like ghcr.io/<namespace> (got: $REGISTRY)" >&2
  exit 2
fi

# Resolve credentials. Token must carry write:packages.
GHCR_USER="${GHCR_USER:-$(gh api user --jq .login 2>/dev/null || true)}"
GHCR_TOKEN="${GHCR_TOKEN:-$(gh auth token 2>/dev/null || true)}"
if [[ -z "$GHCR_USER" || -z "$GHCR_TOKEN" ]]; then
  echo "ERROR: could not resolve GHCR_USER / GHCR_TOKEN. Run 'gh auth login' first." >&2
  exit 2
fi

scopes=$(gh auth status -t 2>&1 | awk -F"'" '/Token scopes:/ {for(i=2;i<NF;i+=2) print $i}')
if ! grep -qx 'write:packages' <<<"$scopes"; then
  cat >&2 <<EOF
ERROR: gh token is missing the 'write:packages' scope (current: $(echo $scopes | tr '\n' ' ')).
Run:  gh auth refresh -h github.com -s write:packages,read:packages
Then re-run this script.
EOF
  exit 2
fi

# Pick the set of local images to push.
mapfile -t local_images < <(
  docker images 'chatdbgpro/gdb-*' --format '{{.Repository}}:{{.Tag}}' \
    | grep ':latest$' | sort -u
)
if [[ ${#local_images[@]} -eq 0 ]]; then
  echo "ERROR: no local images match chatdbgpro/gdb-*:latest. Build first via pipeline2/ensure_image.py." >&2
  exit 1
fi

declare -a selected
if [[ $# -gt 0 ]]; then
  for project in "$@"; do
    tag="chatdbgpro/gdb-${project}:latest"
    if ! printf '%s\n' "${local_images[@]}" | grep -qx "$tag"; then
      echo "ERROR: requested project '$project' has no local image ($tag)." >&2
      exit 1
    fi
    selected+=("$tag")
  done
else
  selected=("${local_images[@]}")
fi

echo "Will push ${#selected[@]} image(s) to $REGISTRY:"
for img in "${selected[@]}"; do
  project="${img#chatdbgpro/gdb-}"; project="${project%:latest}"
  echo "  $img  ->  $REGISTRY/chatdbgpro-gdb-${project}:latest"
done

# Login (idempotent — docker overwrites the credential store entry).
echo
echo "Logging in to ghcr.io as $GHCR_USER ..."
run bash -c "echo \"$GHCR_TOKEN\" | docker login ghcr.io -u \"$GHCR_USER\" --password-stdin"

# Detect whether the namespace is an org (visibility flip API works) or a user
# (no API — we'll print UI URLs at the end).
ns_kind="user"
if gh api "orgs/$namespace" >/dev/null 2>&1; then
  ns_kind="org"
fi

declare -a pushed_projects
for img in "${selected[@]}"; do
  project="${img#chatdbgpro/gdb-}"; project="${project%:latest}"
  remote="$REGISTRY/chatdbgpro-gdb-${project}:latest"
  pkg="chatdbgpro-gdb-${project}"

  echo
  echo "=== $project ==="
  run docker tag "$img" "$remote"
  run docker push "$remote"
  pushed_projects+=("$project")

  if [[ "$PUBLIC" == "1" && "$ns_kind" == "org" ]]; then
    if [[ "$DRY_RUN" == "1" ]]; then
      echo "  [dry-run] flip $pkg to public"
    elif gh api -X PATCH "orgs/$namespace/packages/container/$pkg" \
            -f visibility=public >/dev/null 2>&1; then
      echo "  visibility=public"
    else
      echo "  WARN: could not set visibility=public via API; flip it in the GitHub UI." >&2
    fi
  fi
done

echo
echo "Done. Pushed ${#pushed_projects[@]} image(s) to $REGISTRY."

if [[ "$ns_kind" == "user" && "$DRY_RUN" != "1" ]]; then
  echo
  echo "Visibility: GitHub does not expose an API to flip user-owned container"
  echo "packages to public. Open each URL below and click 'Change visibility'"
  echo "-> 'Public' at the bottom of the settings page:"
  for project in "${pushed_projects[@]}"; do
    pkg="chatdbgpro-gdb-${project}"
    echo "  https://github.com/users/$namespace/packages/container/$pkg/settings"
  done
fi
