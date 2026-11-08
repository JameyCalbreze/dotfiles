#!/usr/bin/env bash
# Select models exposed by the configured Codex provider, not a specific vendor.
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
codex_bin=${CODEX_BIN:-$(type -P codex || true)}

usage() {
  cat <<'USAGE'
Usage: pick-codex-model.sh [--codex-bin PATH] [-- CODEX_ARGS...]

Query Codex's model/list for the current provider and account, choose a model
and its supported reasoning effort, and launch Codex. The configured provider
is not changed. The Codex app server may contact the configured provider.

Options:
  --codex-bin PATH  Codex executable (default: $CODEX_BIN or codex on PATH).
  -h, --help        Show this help text.

In Bash or Zsh, use: codex pick [-C DIRECTORY] [PROMPT]
Escape or Ctrl-C cancels. Model and reasoning-effort overrides in CODEX_ARGS
are rejected; other options are passed through.
USAGE
}

die() { printf 'codex pick: %s\n' "$*" >&2; exit 1; }
argument_error() { printf 'codex pick: %s\n' "$*" >&2; exit 2; }

while (($#)); do
  case "$1" in
    --codex-bin)
      (($# >= 2)) && [[ -n $2 ]] || argument_error '--codex-bin requires a path'
      codex_bin=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    *) argument_error "unknown launcher argument: $1 (put Codex arguments after --)" ;;
  esac
done

# Start the model-list server with the same profile, working directory, and
# provider-affecting overrides as the later Codex invocation.
server_args=()
selected_profile=''
profile_set=0
add_server_pair() {
  server_args[${#server_args[@]}]=$1
  server_args[${#server_args[@]}]=$2
}
check_assignment() {
  local key=${1%%=*}
  key=${key//[[:space:]]/}; key=${key//\"/}; key=${key//\'/}
  case "$key" in
    model|model_reasoning_effort) argument_error "configuration override conflicts with the picker: $key" ;;
  esac
}
check_codex_args() {
  local arg cluster flag value
  while (($#)); do
    arg=$1; shift
    case "$arg" in
      --) break ;;
      --model|--model=*) argument_error "option conflicts with the picker: $arg" ;;
      --openrouter) argument_error 'OpenRouter selection requires --include-openrouter on an approved machine' ;;
      --remote|--remote=*|--remote-auth-token-env|--remote-auth-token-env=*)
        argument_error "remote Codex connections are not supported by this picker: $arg" ;;
      --profile)
        (($#)) || argument_error "$arg requires a value"
        selected_profile=$1; profile_set=1; shift ;;
      --profile=*) selected_profile=${arg#--profile=}; profile_set=1 ;;
      --config|--cd|--enable|--disable|--local-provider)
        (($#)) || argument_error "$arg requires a value"
        [[ $arg != --config ]] || check_assignment "$1"
        add_server_pair "$arg" "$1"; shift ;;
      --config=*) check_assignment "${arg#--config=}"; add_server_pair --config "${arg#--config=}" ;;
      --cd=*|--enable=*|--disable=*|--local-provider=*)
        server_args[${#server_args[@]}]=$arg ;;
      --oss) server_args[${#server_args[@]}]=$arg ;;
      --sandbox|--ask-for-approval|--add-dir|--image)
        (($#)) || argument_error "$arg requires a value"
        shift ;;
      --*) ;;
      -?*)
        cluster=${arg#-}
        while [[ -n $cluster ]]; do
          flag=${cluster:0:1}; cluster=${cluster:1}
          case "$flag" in
            m) argument_error "option conflicts with the picker: $arg" ;;
            c|p|C|s|a|i)
              if [[ -n $cluster ]]; then value=${cluster#=}
              else (($#)) || argument_error "-$flag requires a value"; value=$1; shift
              fi
              case "$flag" in
                c) check_assignment "$value"; add_server_pair -c "$value" ;;
                p) selected_profile=$value; profile_set=1 ;;
                C) add_server_pair "-$flag" "$value" ;;
              esac
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

work=$(mktemp -d "${TMPDIR:-/tmp}/codex-model-picker.XXXXXX") || die 'could not create temporary directory'
server_pid=''
watchdog_pid=''
cleanup() {
  if [[ -n $watchdog_pid ]]; then
    kill "$watchdog_pid" 2>/dev/null || :
    wait "$watchdog_pid" 2>/dev/null || :
  fi
  if [[ -n $server_pid ]]; then
    kill "$server_pid" 2>/dev/null || :
    wait "$server_pid" 2>/dev/null || :
  fi
  exec 3>&- 4>&- || :
  rm -rf -- "$work"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if ((profile_set)); then
  [[ -n $selected_profile && $selected_profile != *'/'* && $selected_profile != *'..'* ]] || argument_error 'invalid profile name'
  profile_file="${CODEX_HOME:-${HOME:-}/.codex}/$selected_profile.config.toml"
  [[ -r $profile_file ]] || die "Codex profile is not readable: $profile_file"
  command -v lua >/dev/null || die 'lua is required to load a Codex profile'
  profile_helper="$SCRIPT_DIR/codex-profile-config.lua"
  toml_parser="$SCRIPT_DIR/codex-toml.lua"
  [[ -f $toml_parser ]] || toml_parser="$SCRIPT_DIR/../../vendor/tinytoml.lua"
  [[ -r $profile_helper && -r $toml_parser ]] || die 'profile parser files are missing; rerun the dotfiles installer'
  lua "$profile_helper" "$profile_file" "$toml_parser" >"$work/profile-args" || die 'could not load the selected Codex profile'
  profile_args=()
  while IFS= read -r assignment || [[ -n ${assignment:-} ]]; do
    profile_args[${#profile_args[@]}]=-c
    profile_args[${#profile_args[@]}]=$assignment
  done <"$work/profile-args"
  for ((index = 0; index < ${#server_args[@]}; index++)); do
    profile_args[${#profile_args[@]}]=${server_args[$index]}
  done
  if ((${#profile_args[@]})); then server_args=("${profile_args[@]}"); fi
fi
mkfifo "$work/input" "$work/output" || die 'could not create app-server pipes'
# Keep the input FIFO open while starting the server. The output is opened
# read-only after starting it, so a crashed server produces EOF immediately.
exec 3<>"$work/input"
start_server() {
  if ((${#server_args[@]})); then
    exec "$codex_bin" "${server_args[@]}" app-server
  else
    exec "$codex_bin" app-server
  fi
}
start_server <&3 >"$work/output" 2>"$work/server.stderr" &
server_pid=$!
# Bash 3.2 discards partial data on timed reads. A watchdog bounds discovery
# while ordinary reads preserve complete JSON lines on macOS's system Bash.
(
  timer_pid=''
  trap 'if [[ -n $timer_pid ]]; then kill "$timer_pid" 2>/dev/null || :; wait "$timer_pid" 2>/dev/null || :; fi; exit 0' TERM INT
  sleep 30 &
  timer_pid=$!
  wait "$timer_pid" || exit 0
  : >"$work/timed-out"
  kill "$server_pid" 2>/dev/null || :
) &
watchdog_pid=$!
exec 4<"$work/output"

receive_response() {
  local id=$1 line count=0 message
  while IFS= read -r line <&4; do
    count=$((count + 1))
    ((count <= 1000)) || die 'too many app-server messages before the response'
    if printf '%s\n' "$line" | jq -e --argjson id "$id" 'type == "object" and .id == $id' >/dev/null 2>&1; then
      if printf '%s\n' "$line" | jq -e 'has("error")' >/dev/null; then
        message=$(printf '%s\n' "$line" | jq -r '.error.message // "unknown error"')
        die "Codex app server rejected model discovery: $message"
      fi
      printf '%s\n' "$line"
      return 0
    fi
  done
  if [[ -e $work/timed-out ]]; then
    die 'Codex app server timed out while listing models'
  fi
  die 'Codex app server exited before replying; verify your Codex version and configuration'
}

printf '%s\n' '{"id":1,"method":"initialize","params":{"clientInfo":{"name":"dotfiles_codex_picker","title":"Dotfiles Codex Picker","version":"1.0.0"}}}' >&3
receive_response 1 >/dev/null
printf '%s\n' '{"method":"initialized","params":{}}' >&3
cursor=''
: >"$work/cursors"
page=0
while :; do
  page=$((page + 1))
  ((page <= 100)) || die 'model list exceeded 100 pages'
  params=$(jq -nc --arg cursor "$cursor" '{limit:100,includeHidden:false} + (if $cursor == "" then {} else {cursor:$cursor} end)')
  request=$(jq -nc --argjson id "$((page + 1))" --argjson params "$params" '{id:$id,method:"model/list",params:$params}')
  printf '%s\n' "$request" >&3
  response=$(receive_response "$((page + 1))")
  printf '%s\n' "$response" | jq -e '.result.data | type == "array"' >/dev/null || die 'invalid model/list response'
  page_file=$(printf '%s/page.%03d.json' "$work" "$page")
  printf '%s\n' "$response" | jq -c '.result.data' >"$page_file"
  cursor=$(printf '%s\n' "$response" | jq -er 'if .result.nextCursor == null then "" elif (.result.nextCursor | type) == "string" and (.result.nextCursor | test("[\\x00-\\x1f\\x7f]") | not) then .result.nextCursor else error("invalid cursor") end') || die 'invalid model-list cursor'
  [[ -n $cursor ]] || break
  if grep -Fqx -- "$cursor" "$work/cursors"; then die 'model-list cursor repeated'; fi
  printf '%s\n' "$cursor" >>"$work/cursors"
done

# Convert app-server models to a small, validated snapshot for the UI.
if ! catalog_json=$(jq -sce '
  def nonempty: type == "string" and length > 0;
  [ .[][] | select(.hidden != true) |
    {slug:(.model // .id), display_name:(.displayName // .model // .id),
     supported_reasoning_levels: [(.supportedReasoningEfforts // [])[] | {effort:.reasoningEffort}],
     default_reasoning_level:.defaultReasoningEffort}
    | if .default_reasoning_level == null and (.supported_reasoning_levels | length) > 0
      then .default_reasoning_level = .supported_reasoning_levels[0].effort else . end ]
  | if length == 0 then error("no visible models")
    elif any(.[ ]; (.slug | nonempty | not) or (.slug | test("[\\x00-\\x1f\\x7f]")) or
      ((.display_name | type) != "string") or
      any(.supported_reasoning_levels[]; (.effort | type) != "string" or (.effort | test("^[a-z][a-z0-9_-]*$") | not)) or
      (([.supported_reasoning_levels[].effort] | length) != ([.supported_reasoning_levels[].effort] | unique | length)) or
      (if (.supported_reasoning_levels | length) > 0 then .default_reasoning_level as $default | ([.supported_reasoning_levels[].effort] | index($default)) == null else false end))
      then error("invalid model or reasoning-effort metadata")
    elif ([.[].slug] | length) != ([.[].slug] | unique | length) then error("duplicate model IDs")
    else {models:.} end
' "$work"/page.*.json); then
  die 'Codex returned an invalid or empty model list'
fi
cleanup
server_pid=''
watchdog_pid=''
trap - EXIT INT TERM

choose_row() {
  local rows=$1 selected row status
  shift
  if selected=$(FZF_DEFAULT_OPTS='' FZF_DEFAULT_OPTS_FILE='' fzf \
    --no-multi --layout=reverse --border --delimiter=$'\t' --with-nth=2.. \
    --header='Type to search | arrows to navigate | Enter to select | Esc/Ctrl-C to cancel' \
    "$@" <<< "$rows"); then
    while IFS= read -r row; do
      if [[ $row == "$selected" ]]; then printf '%s' "${row%%$'\t'*}"; return 0; fi
    done <<< "$rows"
    die 'picker returned an invalid selection'
  else
    status=$?
    case "$status" in
      130) ;;
      1) printf 'codex pick: no selection\n' >&2 ;;
      *) printf 'codex pick: fzf failed (exit %s)\n' "$status" >&2 ;;
    esac
    return "$status"
  fi
}

model_rows=$(jq -r '.models | to_entries[] | [.key,.value.slug,(.value.display_name | gsub("[\\x00-\\x1f\\x7f]"; " "))] | @tsv' <<< "$catalog_json")
model_index=$(choose_row "$model_rows" --prompt='Model > ')
model_json=$(jq -c --argjson index "$model_index" '.models[$index]' <<< "$catalog_json")
slug=$(jq -r '.slug' <<< "$model_json")
efforts_json=$(jq -c '.default_reasoning_level as $default | .supported_reasoning_levels | [ .[] | select(.effort == $default) ] + [ .[] | select(.effort != $default) ]' <<< "$model_json")
effort_count=$(jq 'length' <<< "$efforts_json")
if [[ $effort_count == 0 ]]; then
  exec "$codex_bin" --model "$slug" "$@"
elif [[ $effort_count == 1 ]]; then
  effort_index=0
else
  effort_rows=$(jq -r --arg default "$(jq -r '.default_reasoning_level' <<< "$model_json")" 'to_entries[] | [.key,.value.effort,(if .value.effort == $default then "(default)" else "" end)] | @tsv' <<< "$efforts_json")
  effort_index=$(choose_row "$effort_rows" --prompt="Effort for $slug > " --no-sort)
fi
effort=$(jq -r --argjson index "$effort_index" '.[$index].effort' <<< "$efforts_json")
effort_value=$(jq -Rn --arg value "$effort" '$value')
exec "$codex_bin" --model "$slug" -c "model_reasoning_effort=$effort_value" "$@"
