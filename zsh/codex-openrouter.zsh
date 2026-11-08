# Optional OpenRouter integration; sourced only with --include-openrouter.
_codex_load_openrouter_key() {
  if [[ -z ${OPEN_ROUTER_KEY:-} && -r "$HOME/.secrets/openrouter" ]]; then
    OPEN_ROUTER_KEY=$(< "$HOME/.secrets/openrouter")
  fi
  export OPEN_ROUTER_KEY
}

unalias codex 2>/dev/null || :
codex() {
  (
    local executable
    executable=$(whence -p codex) || { printf 'codex: executable not found in PATH\n' >&2; return 1; }
    _codex_load_credentials
    export EDITOR=micro
    if [[ ${1:-} == pick ]]; then
      shift
      if [[ ${1:-} == --openrouter ]]; then
        shift
        _codex_load_openrouter_key
        "$CODEX_HOME/scripts/pick-openrouter-model.sh" --codex-bin "$executable" -- --profile granular "$@"
      else
        "$CODEX_HOME/scripts/pick-codex-model.sh" --codex-bin "$executable" -- --profile granular "$@"
      fi
    else
      "$executable" --profile granular "$@"
    fi
  )
}

unalias codex-openrouter-models 2>/dev/null || :
codex-openrouter-models() {
  (
    _codex_load_openrouter_key
    "$CODEX_HOME/scripts/refresh-openrouter-model-catalog.sh" "$@"
  )
}
