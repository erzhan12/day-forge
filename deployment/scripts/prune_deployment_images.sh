#!/usr/bin/env bash
set -euo pipefail

# Keep the deployed image and two recent SHA-tagged rollback images for this app.
current_ref=${1:?current image reference required}
image_repo=${current_ref%:*}
current_tag=${current_ref##*:}
if [[ ! $current_tag =~ ^[0-9a-f]{12}$ ]]; then
  echo "Refusing cleanup: current image tag is not a 12-character SHA" >&2
  exit 2
fi
docker image inspect "$current_ref" >/dev/null

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib/select_images_to_delete.sh
source "$script_dir/lib/select_images_to_delete.sh"

refs=$(docker image ls --format '{{.Repository}}:{{.Tag}}' \
  --filter "reference=$image_repo:*")
inventory=''
while IFS= read -r ref; do
  [[ $ref == "$image_repo":* ]] || continue
  created=$(docker image inspect --format '{{.Created}}' "$ref")
  inventory+=$(printf '%s\t%s\n' "$created" "$ref")$'\n'
done <<< "$refs"

expired=$(printf '%s' "$inventory" | select_images_to_delete "$current_ref" 3)
while IFS= read -r ref; do
  [[ -n $ref ]] || continue
  docker image rm "$ref" || echo "Could not remove $ref (possibly used by a container)" >&2
done <<< "$expired"
