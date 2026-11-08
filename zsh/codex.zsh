# Shared Codex integration for Zsh. Credentials remain local to each command.
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"

_codex_load_credentials() {
  if [[ -z ${BEDROCK_API_KEY:-} && -r "$HOME/.secrets/bedrock" ]]; then
    BEDROCK_API_KEY=$(< "$HOME/.secrets/bedrock")
  fi
  if [[ -z ${FOUNDRY_KIMIK_KEY:-} && -r "$HOME/.secrets/kimik.foundry" ]]; then
    FOUNDRY_KIMIK_KEY=$(< "$HOME/.secrets/kimik.foundry")
  fi
  export BEDROCK_API_KEY FOUNDRY_KIMIK_KEY
}

# An existing alias must not prevent defining the function.
unalias codex 2>/dev/null || :
codex() {
  (
    local executable
    executable=$(whence -p codex) || { printf 'codex: executable not found in PATH\n' >&2; return 1; }
    _codex_load_credentials
    export EDITOR=micro
    "$executable" --profile granular "$@"
  )
}
