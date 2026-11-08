# Shared Codex integration. Credentials remain in the environment or ~/.secrets.
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"

_codex_load_credentials() {
  local name file
  for name in BEDROCK_API_KEY FOUNDRY_KIMIK_KEY; do
    case "$name" in
      BEDROCK_API_KEY) file="$HOME/.secrets/bedrock" ;;
      FOUNDRY_KIMIK_KEY) file="$HOME/.secrets/kimik.foundry" ;;
    esac
    if [[ -z ${!name:-} && -r $file ]]; then
      printf -v "$name" '%s' "$(< "$file")"
    fi
    export "$name"
  done
}

codex() (
  local executable
  executable=$(type -P codex) || { printf 'codex: executable not found in PATH\n' >&2; return 1; }
  _codex_load_credentials
  export EDITOR=micro
  if [[ ${1:-} == pick ]]; then
    shift
    "$CODEX_HOME/scripts/pick-codex-model.sh" --codex-bin "$executable" -- --profile granular "$@"
  else
    "$executable" --profile granular "$@"
  fi
)
