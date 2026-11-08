#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
CODEX_HOME=${CODEX_HOME:-$(cd -- "$SCRIPT_DIR/.." && pwd)}
families_file="$CODEX_HOME/openrouter-model-families.txt"
target="$CODEX_HOME/models.json"

# GNU and BSD stat expose modes differently; preserve them without Python.
copy_mode() {
  local mode
  mode=$(stat -L -c '%a' "$1" 2>/dev/null) || mode=$(stat -L -f '%Lp' "$1") || return
  chmod "$mode" "$2"
}
exceptions_file="$CODEX_HOME/openrouter-model-exceptions.json"
exceptions_endpoint=https://openrouter.ai/api/v1/models?region=eu
endpoint=${OPENROUTER_MODELS_URL:-https://openrouter.ai/api/v1/models}
sanitizer="$SCRIPT_DIR/strip-model-system-prompts.sh"

usage() {
  cat <<'EOF'
Usage: refresh-openrouter-model-catalog.sh [OPTIONS]

Fetches OpenRouter's model list, filters it by configured text-chat model
families, and atomically replaces Codex's models.json catalog.

Options:
  --families PATH  Read model-ID prefixes from PATH.
  --target PATH    Write the generated catalog to PATH.
  --exceptions PATH Read explicit EU exceptions from PATH (missing default: none).
  --exceptions-endpoint URL Override the public EU catalog endpoint for tests.
  --endpoint URL   Override the OpenRouter models endpoint (primarily for tests).
  -h, --help       Show this help text.

OPEN_ROUTER_KEY must be set in the environment. The key is never written to disk.
EU exception metadata is fetched without credentials. Use codex pick --openrouter to apply
the generated routing metadata; ordinary model selection does not enforce it.
EOF
}

while (($#)); do
  case "$1" in
    --families)
      [[ $# -ge 2 ]] || { echo "--families requires a path" >&2; exit 2; }
      families_file=$2
      shift 2
      ;;
    --target)
      [[ $# -ge 2 ]] || { echo "--target requires a path" >&2; exit 2; }
      target=$2
      shift 2
      ;;
    --exceptions|--exceptions-endpoint)
      [[ $# -ge 2 ]] || { echo "$1 requires a value" >&2; exit 2; }
      if [[ $1 == --exceptions ]]; then
        exceptions_file=$2
        [[ -f "$exceptions_file" ]] || { echo "exceptions configuration not found: $exceptions_file" >&2; exit 1; }
      else
        exceptions_endpoint=$2
      fi
      shift 2
      ;;
    --endpoint)
      [[ $# -ge 2 ]] || { echo "--endpoint requires a URL" >&2; exit 2; }
      endpoint=$2
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

for dependency in curl jq stat; do
  command -v "$dependency" >/dev/null || { echo "$dependency is required" >&2; exit 1; }
done
[[ -x "$sanitizer" ]] || { echo "sanitizer is not executable: $sanitizer" >&2; exit 1; }
[[ -n ${OPEN_ROUTER_KEY:-} ]] || { echo "OPEN_ROUTER_KEY must be set" >&2; exit 1; }
[[ -f "$families_file" ]] || { echo "family configuration not found: $families_file" >&2; exit 1; }

families=()
while IFS= read -r family || [[ -n ${family:-} ]]; do
  families[${#families[@]}]=$family
done < <(sed -E 's/[[:space:]]*#.*$//; /^[[:space:]]*$/d; s/^[[:space:]]+//; s/[[:space:]]+$//' "$families_file")
((${#families[@]})) || { echo "family configuration is empty: $families_file" >&2; exit 1; }

exceptions_json='{"exceptions":[]}'
if [[ -f "$exceptions_file" ]]; then
  exceptions_json=$(jq -ces '
    def valid_exception:
      if type != "object" then false
      elif (.id | type) != "string" then false
      else (.id | test("^[a-z0-9_-]+/[A-Za-z0-9._:/-]+$")) and .region == "eu" end;
    if length != 1 then error("expected one exceptions configuration")
    else .[0]
      | if type != "object" then error("exceptions configuration must be an object")
        elif (.exceptions | type) != "array" then error("exceptions must be an array")
        elif any(.exceptions[]; valid_exception | not) then error("exceptions require a model id and region eu")
        elif ([.exceptions[].id] | length) != ([.exceptions[].id] | unique | length) then error("duplicate exception model id")
        else . end
    end
  ' "$exceptions_file")
fi

target_dir=$(dirname -- "$target")
[[ -d "$target_dir" ]] || { echo "target directory not found: $target_dir" >&2; exit 1; }
raw=$(mktemp "$target_dir/.openrouter-models.raw.XXXXXX")
generated=$(mktemp "$target_dir/.models.json.generated.XXXXXX")
exception_raw=$(mktemp "$target_dir/.openrouter-models.eu.XXXXXX")
backup_tmp=''
trap 'rm -f -- "$raw" "$generated" "$exception_raw" "$backup_tmp"' EXIT

curl --fail --silent --show-error --location --retry 2 \
  --header "Authorization: Bearer $OPEN_ROUTER_KEY" \
  "$endpoint" >"$raw"

jq -e '.data | type == "array"' "$raw" >/dev/null || {
  echo "OpenRouter response does not contain a data array" >&2
  exit 1
}

printf '%s\n' '{"data":[]}' >"$exception_raw"
if [[ $(jq '.exceptions | length' <<< "$exceptions_json") -gt 0 ]]; then
  # Public metadata only: never send the account key to the exception endpoint.
  curl --fail --silent --show-error --location --retry 2 \
    "$exceptions_endpoint" >"$exception_raw"
  jq -e --argjson config "$exceptions_json" '
    if (.data | type) != "array" then error("EU catalog must contain a data array")
    else .data as $models
      | all($config.exceptions[]; .id as $id
        | ([$models[] | select(.id == $id)
            | select((.context_length | type) == "number" and .context_length > 0)
            | select(((.architecture.input_modalities // []) | index("text")) != null)
            | select(((.architecture.output_modalities // []) | index("text")) != null)] | length) == 1)
    end
  ' "$exception_raw" >/dev/null || {
    echo "configured exception is missing or invalid in the EU text-chat catalog; catalog unchanged" >&2
    exit 1
  }
fi

families_json=$(printf '%s\n' "${families[@]}" | jq -R . | jq -s .)
jq --argjson families "$families_json" --argjson exceptions "$exceptions_json" --slurpfile eu "$exception_raw" '
  def has_text_input:
    ((.architecture.input_modalities? // []) | index("text")) != null;
  def has_text_output:
    ((.architecture.output_modalities? // []) | index("text")) != null;
  def selected_family:
    .id as $id | any($families[]; . as $prefix | $id | startswith($prefix));
  def reasoning_levels:
    if ((.reasoning.supported_efforts? // []) | length) > 0 then
      .reasoning.supported_efforts | map({description: ., effort: .})
    elif (.reasoning.mandatory? == true) then
      [{description: "medium", effort: "medium"}]
    else
      [{description: "none", effort: "none"}]
    end;
  def default_reasoning($levels):
    (.reasoning.default_effort? // null) as $default
    | if ($levels | map(.effort) | index($default)) != null then
      $default
    else
      $levels[0].effort
    end;
  {
    models: [
      (.data[] | del(.openrouter_region) | select(.id as $id | any($exceptions.exceptions[]; .id == $id) | not)),
      ($eu[0].data[] | .id as $id
        | select(any($exceptions.exceptions[]; .id == $id))
        | . + {openrouter_region: "eu"})
      | select((.id | type) == "string")
      | select((.context_length | type) == "number" and .context_length > 0)
      | select(has_text_input and has_text_output and (selected_family or .openrouter_region == "eu"))
      | reasoning_levels as $levels
      | {
          base_instructions: "",
          context_window: .context_length,
          default_reasoning_level: default_reasoning($levels),
          default_verbosity: "low",
          display_name: (.name // .id),
          experimental_supported_tools: [],
          priority: 1,
          shell_type: "shell_command",
          slug: .id,
          support_verbosity: false,
          supported_in_api: true,
          supported_reasoning_levels: $levels,
          supports_parallel_tool_calls: false,
          supports_reasoning_summaries: false,
          truncation_policy: {limit: 10000, mode: "tokens"},
          visibility: "list"
        } + (if .openrouter_region == "eu" then {openrouter_region: "eu"} else {} end)
    ] | sort_by(.slug)
  }
' "$raw" >"$generated"

generated_count=$(jq '.models | length' "$generated")
((generated_count > 0)) || {
  echo "no text-chat models matched the configured families" >&2
  exit 1
}

"$sanitizer" --target "$generated" >/dev/null

if [[ -f "$target" ]]; then
  timestamp=$(date -u +%Y%m%dT%H%M%SZ)
  backup="$target.$timestamp.bak"
  backup_tmp=$(mktemp "$target_dir/.models.json.backup.XXXXXX")
  cp -- "$target" "$backup_tmp"
  copy_mode "$target" "$backup_tmp"
  "$sanitizer" --target "$backup_tmp" >/dev/null
  mv -f -- "$backup_tmp" "$backup"
  backup_tmp=''
fi

if [[ -f "$target" ]]; then
  copy_mode "$target" "$generated"
else
  chmod 600 "$generated"
fi
mv -f -- "$generated" "$target"
trap - EXIT
rm -f -- "$raw" "$exception_raw"

printf 'Wrote %s OpenRouter model(s) to %s\n' "$generated_count" "$target"
exception_count=$(jq '[.models[] | select(.openrouter_region == "eu")] | length' "$target")
if ((exception_count > 0)); then
  printf 'Included %s EU routing exception(s); launch them with codex pick --openrouter (Business/Enterprise required)\n' "$exception_count"
fi
