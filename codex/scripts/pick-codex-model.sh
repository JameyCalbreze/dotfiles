#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
catalog="${CODEX_HOME:-$SCRIPT_DIR/..}/models.json"
codex_bin=${CODEX_BIN:-$(type -P codex || true)}

usage() {
  cat <<'EOF'
Usage: pick-codex-model.sh [--catalog PATH] [--codex-bin PATH] [-- CODEX_ARGS...]

Search the local OpenRouter catalogue, choose a supported reasoning effort,
and launch Codex. No catalogue refresh or configuration writes are performed.

Options:
  --catalog PATH    Catalogue to read (default: $CODEX_HOME/models.json,
                    or models.json beside this script's parent directory).
  --codex-bin PATH  Codex executable (default: $CODEX_BIN or codex on PATH).
  -h, --help        Show this help text.

In Bash or Zsh, use: codex pick [-C DIRECTORY] [PROMPT]
Typing searches; arrows navigate; Enter selects; Escape/Ctrl-C cancels.
Only supported efforts are shown, with the default selected first. Models
with one supported effort skip the effort screen. Model, effort, provider,
and catalogue overrides cannot be supplied in CODEX_ARGS. EU exception models
use the EU API domain (requires OpenRouter Business/Enterprise), keeping the
account privacy settings and refusing global-domain fallback.
EOF
}

die() { printf 'codex pick: %s\n' "$*" >&2; exit 1; }
argument_error() { printf 'codex pick: %s\n' "$*" >&2; exit 2; }

while (($#)); do
  case "$1" in
    --catalog|--codex-bin)
      (($# >= 2)) && [[ -n $2 ]] || argument_error "$1 requires a path"
      case "$1" in
        --catalog) catalog=$2 ;;
        --codex-bin) codex_bin=$2 ;;
      esac
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    *) argument_error "unknown launcher argument: $1 (put Codex arguments after --)" ;;
  esac
done

check_assignment() {
  local key=${1%%=*}
  # Ignore whitespace and quoted key spelling when identifying protected keys.
  key=${key//[[:space:]]/}
  key=${key//\"/}
  key=${key//\'/}
  case "$key" in
    model|model_reasoning_effort|model_provider|model_catalog_json|model_providers|model_providers.*|openai_base_url)
      argument_error "configuration override conflicts with the picker: $key" ;;
  esac
}

# Inspect only option tokens, skipping values consumed by ordinary Codex flags.
# Short option clusters are walked as well (e.g. -sm or -cmodel=...).
check_codex_args() {
  local arg cluster flag assignment
  while (($#)); do
    arg=$1
    shift
    case "$arg" in
      --) break ;;
      --model|--model=*|--oss|--local-provider|--local-provider=*|--remote|--remote=*)
        argument_error "option conflicts with the picker: $arg" ;;
      --config)
        (($#)) || argument_error '--config requires an assignment'
        check_assignment "$1"; shift ;;
      --config=*) check_assignment "${arg#--config=}" ;;
      --profile|--cd|--sandbox|--ask-for-approval|--add-dir|--enable|--disable|--image|--remote-auth-token-env)
        (($#)) || argument_error "$arg requires a value"
        shift ;;
      --*) ;; # Other long switches, including --option=value, pass through.
      -?*)
        cluster=${arg#-}
        while [[ -n $cluster ]]; do
          flag=${cluster:0:1}
          cluster=${cluster:1}
          case "$flag" in
            m) argument_error "option conflicts with the picker: $arg" ;;
            c)
              if [[ -n $cluster ]]; then
                assignment=$cluster
              else
                (($#)) || argument_error '-c requires an assignment'
                assignment=$1; shift
              fi
              check_assignment "$assignment"
              break ;;
            p|C|s|a|i)
              if [[ -z $cluster ]]; then
                (($#)) || argument_error "-$flag requires a value"
                shift
              fi
              break ;;
          esac
        done ;;
    esac
  done
}
check_codex_args "$@"

for dependency in jq fzf; do
  command -v "$dependency" >/dev/null || die "$dependency is required; install it and retry"
done
[[ -n $codex_bin && -f $codex_bin && -x $codex_bin ]] || die "Codex executable not found: ${codex_bin:-codex} (use --codex-bin PATH)"
[[ -f $catalog && -r $catalog ]] || die "catalogue not readable: $catalog; run refresh-openrouter-model-catalog.sh first"
# Resolve a relative catalogue path without changing the launch working directory.
catalog=$(cd -- "$(dirname -- "$catalog")" && printf '%s/%s' "$PWD" "$(basename -- "$catalog")")

# Snapshot once: subsequent refreshes cannot change the model/effort pairing.
if ! catalog_json=$(jq -ces '
  def nonempty_string: if type == "string" then length > 0 else false end;
  def model_valid:
    if type != "object" then false
    elif (.slug | nonempty_string | not) then false
    elif (.slug | test("[\\x00-\\x1f\\x7f]")) then false
    elif (has("openrouter_region") and .openrouter_region != "eu") then false
    elif (.display_name != null and (.display_name | type) != "string") then false
    elif (.supported_reasoning_levels | type) != "array" then false
    elif (.supported_reasoning_levels | length) == 0 then false
    elif any(.supported_reasoning_levels[];
      if type != "object" then true
      elif (.effort | type) != "string" then true
      else (.effort | test("^[a-z][a-z0-9_-]*$") | not) end
    ) then false
    elif ([.supported_reasoning_levels[].effort] | length) !=
         ([.supported_reasoning_levels[].effort] | unique | length) then false
    else .default_reasoning_level as $default
      | ([.supported_reasoning_levels[].effort] | index($default)) != null
    end;
  if length != 1 then error("expected one JSON catalogue")
  else .[0]
    | if type != "object" then error("catalogue must be an object")
      elif (.models | type) != "array" then error("catalogue.models must be an array")
      elif (.models | length) == 0 then error("catalogue contains no models")
      elif any(.models[]; model_valid | not) then
        error("models require valid slugs, unique supported efforts, and a supported default")
      elif ([.models[].slug] | length) != ([.models[].slug] | unique | length) then
        error("catalogue contains duplicate model slugs")
      else . end
  end
' "$catalog"); then
  die "invalid catalogue: $catalog; refresh or repair it before retrying"
fi

choose_row() {
  local rows=$1 selected row status
  shift
  # --with-nth hides the index; fzf searches all displayed fields by default.
  # Adding --nth=2.. here would search only the name after transformation.
  if selected=$(FZF_DEFAULT_OPTS='' FZF_DEFAULT_OPTS_FILE='' fzf \
    --no-multi --layout=reverse --border --delimiter=$'\t' \
    --with-nth=2.. --header='Type to search | arrows to navigate | Enter to select | Esc/Ctrl-C to cancel' \
    "$@" <<< "$rows"); then
    # Return the hidden numeric index only if fzf returned an actual input row.
    while IFS= read -r row; do
      if [[ $row == "$selected" ]]; then
        printf '%s' "${row%%$'\t'*}"
        return 0
      fi
    done <<< "$rows"
    die 'picker returned an invalid selection'
  else
    status=$?
    case "$status" in
      130) ;; # User cancellation: no launch and no error message.
      1) printf 'codex pick: no selection\n' >&2 ;;
      *) printf 'codex pick: fzf failed (exit %s)\n' "$status" >&2 ;;
    esac
    return "$status"
  fi
}

model_rows=$(jq -r '
  .models | to_entries[]
  | [.key, .value.slug, (((.value.display_name // .value.slug) + (if .value.openrouter_region == "eu" then " [EU routing]" else "" end)) | gsub("[\\x00-\\x1f\\x7f]"; " "))]
  | @tsv
' <<< "$catalog_json")
model_index=$(choose_row "$model_rows" --prompt='Model > ')
model_json=$(jq -c --argjson index "$model_index" '.models[$index]' <<< "$catalog_json")
slug=$(jq -r '.slug' <<< "$model_json")

# Keep the original relative order of non-default efforts.
efforts_json=$(jq -c '
  .default_reasoning_level as $default
  | .supported_reasoning_levels
  | [ .[] | select(.effort == $default) ] + [ .[] | select(.effort != $default) ]
' <<< "$model_json")
if [[ $(jq 'length' <<< "$efforts_json") == 1 ]]; then
  effort_index=0
else
  effort_rows=$(jq -r --arg default "$(jq -r '.default_reasoning_level' <<< "$model_json")" '
    to_entries[] | [.key, .value.effort,
      (if .value.effort == $default then "(default)" else "" end)] | @tsv
  ' <<< "$efforts_json")
  effort_index=$(choose_row "$effort_rows" --prompt="Effort for $slug > " --no-sort)
fi
effort=$(jq -r --argjson index "$effort_index" '.[$index].effort' <<< "$efforts_json")

# JSON string quoting is also valid for these TOML string values.
effort_value=$(jq -Rn --arg value "$effort" '$value')
catalog_value=$(jq -Rn --arg value "$catalog" '$value')
provider=open_router
# Do not install a provider globally: bind it only to this opted-in launch.
routing_args=(-c 'model_providers.open_router={name="OpenRouter",base_url="https://openrouter.ai/api/v1",env_key="OPEN_ROUTER_KEY",wire_api="responses"}')
if [[ $(jq -r '.openrouter_region // ""' <<< "$model_json") == eu ]]; then
  provider=open_router_eu_exception
  # Replace the entire provider table: inherited global-domain settings cannot
  # alter the fixed destination, authentication source, or wire protocol.
  routing_args=(-c 'model_providers.open_router_eu_exception={name="OpenRouter EU exception",base_url="https://eu.openrouter.ai/api/v1",env_key="OPEN_ROUTER_KEY",wire_api="responses"}')
  printf 'codex pick: EU-only routing for %s (OpenRouter Business/Enterprise required)\n' "$slug" >&2
fi
exec "$codex_bin" --model "$slug" \
  -c "model_reasoning_effort=$effort_value" \
  -c "model_provider=\"$provider\"" \
  -c "model_catalog_json=$catalog_value" \
  "${routing_args[@]}" "$@"
