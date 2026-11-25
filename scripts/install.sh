#!/bin/sh
# Install whole-file symlinks, preserving existing files in numbered backups.
set -eu
set -f

fail() { printf 'install: %s\n' "$*" >&2; exit 1; }
[ "$#" -eq 1 ] || fail 'expected OPENROUTER=0 or OPENROUTER=1'
case $1 in 0|1) openrouter=$1 ;; *) fail 'OPENROUTER must be 0 or 1' ;; esac
[ -n "${HOME:-}" ] || fail 'HOME must be set'
root=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)
cwd=$(pwd -P)

# Normalize a path through existing parent symlinks, without creating anything.
# The final component is deliberately not resolved: it is the link to replace.
canonical_entry() {
    path=$1
    case $path in /*) ;; *) path=$cwd/$path ;; esac
    leaf=${path##*/}
    [ -n "$leaf" ] && [ "$leaf" != . ] && [ "$leaf" != .. ] || fail "invalid file path: $path"
    rest=${path%/*}
    current=/
    old_ifs=$IFS
    IFS=/
    for part in $rest; do
        case $part in
            ''|.) continue ;;
            ..) current=${current%/*}; [ -n "$current" ] || current=/ ;;
            *)
                if [ "$current" = / ]; then candidate=/$part; else candidate=$current/$part; fi
                if [ -d "$candidate" ]; then
                    current=$(CDPATH= cd "$candidate" && pwd -P) || fail "cannot resolve $candidate"
                elif [ -e "$candidate" ] || [ -L "$candidate" ]; then
                    fail "parent is not a directory: $candidate"
                else
                    current=$candidate
                fi ;;
        esac
    done
    IFS=$old_ifs
    if [ "$current" = / ]; then printf '/%s\n' "$leaf"; else printf '%s/%s\n' "$current" "$leaf"; fi
}

codex_home=${CODEX_HOME:-$HOME/.codex}
if [ "${XDG_CONFIG_HOME+x}" ]; then
    case $XDG_CONFIG_HOME in /*) xdg=$XDG_CONFIG_HOME ;; *) fail 'XDG_CONFIG_HOME must be a non-empty absolute path' ;; esac
else
    xdg=$HOME/.config
fi
if [ "${HERDR_CONFIG_PATH+x}" ]; then
    [ -n "$HERDR_CONFIG_PATH" ] || fail 'HERDR_CONFIG_PATH must not be empty'
    herdr=$HERDR_CONFIG_PATH
else
    herdr=$xdg/herdr/config.toml
fi
# Keep paths absolute so utilities do not mistake leading dashes for options.
case $codex_home in /*) ;; *) codex_home=$cwd/$codex_home ;; esac
case $xdg in /*) ;; *) xdg=$cwd/$xdg ;; esac
case $herdr in /*) ;; *) herdr=$cwd/$herdr ;; esac
# Newlines would make the preflight destination list ambiguous.
newline='
'
case $HOME$codex_home$xdg$herdr$root in *"$newline"*) fail 'paths containing newlines are not supported' ;; esac

destinations=
mode=check
link() {
    source=$1
    target=$2
    kind=${3:-common}
    if [ "$mode" = check ]; then
        [ -f "$source" ] || fail "missing repository file: $source"
        dest=$(canonical_entry "$target") || exit 1
        case $dest in "$root"|"$root"/*) fail "destination is inside the repository: $target" ;; esac
        old_ifs=$IFS
        IFS=$newline
        for previous in $destinations; do
            case $dest in "$previous"|"$previous"/*) fail "overlapping destinations: $target and $previous" ;; esac
            case $previous in "$dest"/*) fail "overlapping destinations: $target and $previous" ;; esac
        done
        IFS=$old_ifs
        destinations=${destinations}${destinations:+"$newline"}$dest
        if [ "$kind" != optional ] || [ "$openrouter" = 1 ]; then
            if [ -d "$target" ] && [ ! -L "$target" ]; then fail "refusing to replace directory: $target"; fi
        fi
        return
    fi
    if [ "$kind" = optional ] && [ "$openrouter" = 0 ]; then
        if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
            rm "$target"
            printf 'Removed %s\n' "$target"
        fi
        return
    fi
    if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then return; fi
    mkdir -p "$(dirname "$target")"
    if [ -e "$target" ] || [ -L "$target" ]; then
        n=1
        backup=$target.dotfiles-backup.$n
        while [ -e "$backup" ] || [ -L "$backup" ]; do
            n=$((n + 1))
            backup=$target.dotfiles-backup.$n
        done
        mv "$target" "$backup"
        printf 'Backed up %s to %s\n' "$target" "$backup"
    fi
    ln -s "$source" "$target"
    printf 'Linked %s -> %s\n' "$target" "$source"
}

links() {
    link "$root/herdr/config.toml" "$herdr"
    link "$root/ghostty/config" "$xdg/ghostty/config"
    link "$root/codex/AGENTS.md" "$codex_home/AGENTS.md"
    if [ "$openrouter" = 1 ]; then config=$root/codex/openrouter.config.toml; else config=$root/codex/config.toml; fi
    link "$config" "$codex_home/config.toml"
    link "$root/codex/granular.config.toml" "$codex_home/granular.config.toml"
    link "$root/codex/rules/default.rules" "$codex_home/rules/default.rules"
    link "$root/bash/codex.bash" "$codex_home/scripts/codex-shell.bash"
    link "$root/zsh/codex.zsh" "$codex_home/scripts/codex-shell.zsh"
    link "$root/codex/scripts/pick-codex-model.sh" "$codex_home/scripts/pick-codex-model.sh"
    link "$root/codex/scripts/strip-model-system-prompts.sh" "$codex_home/scripts/strip-model-system-prompts.sh"
    link "$root/codex/scripts/codex-profile-config.lua" "$codex_home/scripts/codex-profile-config.lua"
    link "$root/vendor/tinytoml.lua" "$codex_home/scripts/codex-toml.lua"
    link "$root/bash/codex-openrouter.bash" "$codex_home/scripts/codex-openrouter-shell.bash" optional
    link "$root/zsh/codex-openrouter.zsh" "$codex_home/scripts/codex-openrouter-shell.zsh" optional
    link "$root/codex/openrouter-model-families.txt" "$codex_home/openrouter-model-families.txt" optional
    link "$root/codex/openrouter-model-exceptions.json" "$codex_home/openrouter-model-exceptions.json" optional
    link "$root/codex/scripts/pick-openrouter-model.sh" "$codex_home/scripts/pick-openrouter-model.sh" optional
    link "$root/codex/scripts/refresh-openrouter-model-catalog.sh" "$codex_home/scripts/refresh-openrouter-model-catalog.sh" optional
}

links
mode=install
links
printf '%s\n' 'Done. Source the shell integration as described in README.md.'
