#!/usr/bin/env bash

# Read "<RFC3339-created>\t<repository>:<tag>" records from stdin and print
# expired 12-hex deployment tags. Only tags matching /^[0-9a-f]{12}$/ are ever
# candidates; the current tag, :latest, <none> (dangling), and any other
# non-12-hex tag are always protected. KEEP counts the current tag, so KEEP-1
# other tags are retained (the newest by creation time, tag as tie-break).
select_images_to_delete() {
  local current_ref=${1-}
  local keep=${2-}
  local retain tab

  case "$keep" in
    ''|*[!0-9]*)
      echo "KEEP must be a non-negative integer" >&2
      return 2
      ;;
  esac

  if ((keep > 0)); then
    retain=$((keep - 1))
  else
    retain=0
  fi
  tab=$(printf '\t')

  awk -F '\t' -v current_ref="$current_ref" '
    NF >= 2 {
      created = $1
      ref = $2
      tag = ref
      sub(/^.*:/, "", tag)

      if (ref == current_ref || tag == "latest" || tag == "<none>") {
        next
      }
      if (tag !~ /^[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]$/) {
        next
      }

      print created "\t" ref
    }
  ' \
    | LC_ALL=C sort -t "$tab" -k1,1r -k2,2r \
    | awk -F '\t' -v retain="$retain" 'NR > retain { print $2 }'
}
