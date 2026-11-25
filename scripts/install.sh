#!/bin/sh
# Install symlinks and a machine-specific profile, preserving previous files.
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

# The sandboxed instructions helper re-executes Codex; allow only the actual
# executable, not its containing directory. CODEX_EXECUTABLE is useful when the
# PATH entry is a launcher rather than the helper executable itself.
codex_executable=${CODEX_EXECUTABLE:-$(command -v codex || :)}
[ -n "$codex_executable" ] || fail 'codex executable not found; install Codex or set CODEX_EXECUTABLE to its path'
case $codex_executable in /*) ;; *) codex_executable=$cwd/$codex_executable ;; esac
validate_executable_path() {
    case $1 in *"$newline"*) fail 'codex executable path contains a newline' ;; esac
    if printf '%s' "$1" | LC_ALL=C grep '[[:cntrl:]]' >/dev/null; then
        fail 'codex executable path contains a control character'
    fi
}
validate_executable_path "$codex_executable"
[ -f "$codex_executable" ] && [ -x "$codex_executable" ] || fail "codex executable is not an executable file: $codex_executable"
# Resolve file symlinks portably, accounting for relative targets and symlinked
# parent directories. Include both the invocation path and final physical path.
codex_resolved=$codex_executable
hops=0
while :; do
    codex_parent=$(CDPATH= cd "$(dirname "$codex_resolved")" && pwd -P) || fail 'cannot resolve codex executable parent'
    codex_resolved=$codex_parent/${codex_resolved##*/}
    validate_executable_path "$codex_resolved"
    [ -L "$codex_resolved" ] || break
    hops=$((hops + 1))
    [ "$hops" -le 40 ] || fail 'too many codex executable symlinks'
    codex_link=$(readlink "$codex_resolved") || fail 'cannot read codex executable symlink'
    validate_executable_path "$codex_link"
    case $codex_link in /*) codex_resolved=$codex_link ;; *) codex_resolved=$codex_parent/$codex_link ;; esac
done
[ -f "$codex_resolved" ] && [ -x "$codex_resolved" ] || fail "resolved codex executable is not executable: $codex_resolved"

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
    if [ "$kind" = generated ]; then
        generate_profile "$source" "$target"
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
    backup_target "$target"
    ln -s "$source" "$target"
    printf 'Linked %s -> %s\n' "$target" "$source"
}

backup_target() {
    target_to_backup=$1
    if [ -e "$target_to_backup" ] || [ -L "$target_to_backup" ]; then
        n=1
        backup=$target_to_backup.dotfiles-backup.$n
        while [ -e "$backup" ] || [ -L "$backup" ]; do
            n=$((n + 1))
            backup=$target_to_backup.dotfiles-backup.$n
        done
        mv "$target_to_backup" "$backup"
        printf 'Backed up %s to %s\n' "$target_to_backup" "$backup"
    fi
}

generate_profile() {
    profile_source=$1
    profile_target=$2
    mkdir -p "$(dirname "$profile_target")"
    profile_tmp=$(mktemp "$(dirname "$profile_target")/.granular.config.toml.XXXXXX")
    trap 'rm -f -- "$profile_tmp"' EXIT HUP INT TERM
    cat "$profile_source" >"$profile_tmp"
    printf '\n[permissions.granular.filesystem]\n' >>"$profile_tmp"
    # Escape backslashes and double quotes for TOML basic-string keys.
    escaped=$(printf '%s' "$codex_executable" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '"%s" = "read"\n' "$escaped" >>"$profile_tmp"
    if [ "$codex_resolved" != "$codex_executable" ]; then
        escaped=$(printf '%s' "$codex_resolved" | sed 's/\\/\\\\/g; s/"/\\"/g')
        printf '"%s" = "read"\n' "$escaped" >>"$profile_tmp"
    fi
    if [ ! -L "$profile_target" ] && [ -f "$profile_target" ] && cmp -s "$profile_tmp" "$profile_target"; then
        rm -f -- "$profile_tmp"
    else
        backup_target "$profile_target"
        mv "$profile_tmp" "$profile_target"
        printf 'Generated %s with Codex executable read access\n' "$profile_target"
    fi
    trap - EXIT HUP INT TERM
}

links() {
    link "$root/herdr/config.toml" "$herdr"
    link "$root/ghostty/config" "$xdg/ghostty/config"
    link "$root/codex/AGENTS.md" "$codex_home/AGENTS.md"
    if [ "$openrouter" = 1 ]; then config=$root/codex/openrouter.config.toml; else config=$root/codex/config.toml; fi
    link "$config" "$codex_home/config.toml"
    link "$root/codex/granular.config.toml" "$codex_home/granular.config.toml" generated
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
