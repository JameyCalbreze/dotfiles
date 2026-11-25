#!/bin/sh
# Install the optional integration and refresh its catalog with local credentials.
set -eu
[ -n "${HOME:-}" ] || { echo 'openrouter: HOME must be set' >&2; exit 1; }
if [ -z "${OPEN_ROUTER_KEY:-}" ] && [ -r "$HOME/.secrets/openrouter" ]; then
    OPEN_ROUTER_KEY=$(cat "$HOME/.secrets/openrouter")
fi
[ -n "${OPEN_ROUTER_KEY:-}" ] || { echo 'openrouter: set OPEN_ROUTER_KEY or provide ~/.secrets/openrouter' >&2; exit 1; }
for dependency in bash curl jq stat; do
    command -v "$dependency" >/dev/null || { echo "openrouter: $dependency is required" >&2; exit 1; }
done
export OPEN_ROUTER_KEY
CODEX_HOME=${CODEX_HOME:-$HOME/.codex}
export CODEX_HOME
root=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)
sh "$root/scripts/install.sh" 1
bash "$CODEX_HOME/scripts/refresh-openrouter-model-catalog.sh"
