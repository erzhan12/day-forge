#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT
mkdir -p "$tmp_dir/bin"

cat >"$tmp_dir/bin/docker" <<'DOCKER_STUB'
#!/usr/bin/env bash
set -euo pipefail
repo=ghcr.io/erzhan12/day-forge
case "${1-} ${2-}" in
  "image inspect")
    [[ "${FAIL_INSPECT-}" != 1 ]] || exit 4
    ref=${@: -1}
    if [[ ${3-} == --format ]]; then
      case "$ref" in
        *:aaaaaaaaaaaa|*:latest) echo 2026-10-03T12:00:00Z ;;
        *:bbbbbbbbbbbb) echo 2026-10-02T12:00:00Z ;;
        *:cccccccccccc) echo 2026-10-01T12:00:00Z ;;
        *:dddddddddddd) echo 2026-09-30T12:00:00Z ;;
        *:manual) echo 2026-09-29T12:00:00Z ;;
        *) exit 4 ;;
      esac
    else
      [[ "$ref" == "$repo:aaaaaaaaaaaa" ]] || exit 4
    fi
    ;;
  "image ls")
    [[ "${FAIL_LIST-}" != 1 ]] || exit 4
    printf '%s\n' \
      "$repo:dddddddddddd" "$repo:bbbbbbbbbbbb" \
      "$repo:latest" "$repo:aaaaaaaaaaaa" \
      "$repo:cccccccccccc" "$repo:manual" \
      ghcr.io/erzhan12/lexi:eeeeeeeeeeee
    ;;
  "image rm")
    printf '%s\n' "$3" >>"$DOCKER_LOG"
    ;;
  *)
    printf 'unexpected docker call: %s\n' "$*" >&2
    exit 2
    ;;
esac
DOCKER_STUB
chmod +x "$tmp_dir/bin/docker"

current=ghcr.io/erzhan12/day-forge:aaaaaaaaaaaa
export PATH="$tmp_dir/bin:$PATH" DOCKER_LOG="$tmp_dir/deleted.log"
: >"$DOCKER_LOG"
bash "$repo_root/deployment/scripts/prune_deployment_images.sh" "$current"
[[ $(cat "$DOCKER_LOG") == ghcr.io/erzhan12/day-forge:dddddddddddd ]] || {
  echo 'retention must delete only the oldest Day Forge SHA tag' >&2
  exit 1
}

: >"$DOCKER_LOG"
if bash "$repo_root/deployment/scripts/prune_deployment_images.sh" \
  ghcr.io/erzhan12/day-forge:manual 2>/dev/null; then
  echo 'non-SHA current tag must be rejected' >&2
  exit 1
fi
[[ ! -s "$DOCKER_LOG" ]]

if FAIL_INSPECT=1 bash "$repo_root/deployment/scripts/prune_deployment_images.sh" \
  "$current" 2>/dev/null; then
  echo 'missing current image must stop cleanup' >&2
  exit 1
fi
[[ ! -s "$DOCKER_LOG" ]]

if FAIL_LIST=1 bash "$repo_root/deployment/scripts/prune_deployment_images.sh" \
  "$current" 2>/dev/null; then
  echo 'inventory failure must stop cleanup' >&2
  exit 1
fi
[[ ! -s "$DOCKER_LOG" ]]

echo 'image retention tests: PASS'
