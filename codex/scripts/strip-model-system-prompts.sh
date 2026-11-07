#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
CODEX_HOME=${CODEX_HOME:-$(cd -- "$SCRIPT_DIR/.." && pwd)}
target="$CODEX_HOME/models.json"

# GNU and BSD stat expose modes differently; preserve them without Python.
copy_mode() {
  local mode
  mode=$(stat -L -c '%a' "$1" 2>/dev/null) || mode=$(stat -L -f '%Lp' "$1") || return
  chmod "$mode" "$2"
}

usage() {
  cat <<'EOF'
Usage: strip-model-system-prompts.sh [--target PATH]

Sets every Codex catalog model's base_instructions value to an empty string.
The base_instructions key must already exist and contain a string for every
model; this script never drops or adds that key.
EOF
}

while (($#)); do
  case "$1" in
    --target)
      [[ $# -ge 2 ]] || { echo "--target requires a path" >&2; exit 2; }
      target=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for dependency in jq stat; do
  command -v "$dependency" >/dev/null || { echo "$dependency is required" >&2; exit 1; }
done
[[ -f "$target" ]] || { echo "catalog not found: $target" >&2; exit 1; }

target_dir=$(dirname -- "$target")
tmp=$(mktemp "$target_dir/.models.json.sanitized.XXXXXX")
trap 'rm -f -- "$tmp"' EXIT

jq -e '
  if (.models | type) != "array" then
    error("catalog.models must be an array")
  elif any(.models[];
    if type != "object" then
      true
    else
      ((has("base_instructions") | not) or (.base_instructions | type) != "string")
    end
  ) then
    error("every model must have a string base_instructions field")
  else
    .models |= map(.base_instructions = "")
  end
' "$target" >"$tmp"

copy_mode "$target" "$tmp"
mv -f -- "$tmp" "$target"
trap - EXIT

printf 'Cleared base_instructions for %s model(s) in %s\n' \
  "$(jq '.models | length' "$target")" "$target"
