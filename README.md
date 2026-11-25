# Dotfiles

Shared Codex, Herdr, and Ghostty configuration for Linux and macOS, with Bash
and Zsh Codex model pickers. Clone the repository somewhere stable: installed
files are symlinks back to this checkout, so editing them edits the repository.

## Install

From the checkout, run either:

```sh
make linux
make macos
```

Both targets install the shared files. They need `make` and standard Unix
utilities; they do not install applications, fonts, or packages. Defaults work
for any user on either platform:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CODEX_HOME` | `$HOME/.codex` | Codex configs, rules, instructions, and scripts |
| `XDG_CONFIG_HOME` | `$HOME/.config` | Base directory for Ghostty and Herdr |
| `HERDR_CONFIG_PATH` | `$XDG_CONFIG_HOME/herdr/config.toml` | Herdr config override |

Ghostty is installed at `$XDG_CONFIG_HOME/ghostty/config`. Set overrides in
the environment before running Make and when starting the relevant programs:

```sh
CODEX_HOME="$HOME/my-codex" XDG_CONFIG_HOME="$HOME/my-config" make linux
HERDR_CONFIG_PATH="$HOME/my-herdr.toml" make macos
```

`XDG_CONFIG_HOME`, when set, must be a nonempty absolute path. An explicitly
empty `HERDR_CONFIG_PATH` is rejected; relative Codex and Herdr overrides are
resolved relative to the directory where Make runs. An unset or empty
`CODEX_HOME` uses its default. The installer rejects overlapping destinations
and destinations inside this repository.

Existing files and symlinks at install destinations are moved to numbered
`.dotfiles-backup.N` backups. Directories are not replaced. Repeated installs
leave correct symlinks and backups alone. Codex config and rules are **whole
files**, not merges: existing machine-local values, including project trust and
local rules, remain in backups but are no longer active. Review and manually
copy desired settings into an appropriate local configuration before relying on
them. Other Codex state, credentials, sessions, and Herdr state remain local.
Review `codex/rules/default.rules` before installing: it contains broad command
approvals. Changes to a symlinked config or rules file modify this checkout.

The installer does not edit shell startup files. To activate the shared shell
functions, add the appropriate line to your startup configuration:

```bash
# Bash (for example, in ~/.bashrc)
source "${CODEX_HOME:-$HOME/.codex}/scripts/codex-shell.bash"
```

```zsh
# Zsh (for example, in ${ZDOTDIR:-$HOME}/.zshrc)
source "${CODEX_HOME:-$HOME/.codex}/scripts/codex-shell.zsh"
```

Set a custom `CODEX_HOME` before the shell sources these files. Restart the
shell after changing startup configuration. Ghostty may also read other XDG or
macOS-specific config files which can affect the final settings; this installer
does not modify them. Install JetBrainsMono Nerd Font separately.

## Optional OpenRouter

Only on an approved machine, install the integration and refresh its catalog
on either Linux or macOS:

```sh
make openrouter
```

This target reads `OPEN_ROUTER_KEY` from the environment or
`~/.secrets/openrouter`, installs the optional files, and fetches OpenRouter
models. Edit `codex/openrouter-model-families.txt` to allowlist model ID
prefixes; only matching text-input/text-output models with a valid context
length are included, plus any exact EU exceptions configured in
`codex/openrouter-model-exceptions.json`. Every catalog entry has empty
`base_instructions`. The generated `$CODEX_HOME/models.json` replaces the
existing catalog atomically; its backup is also stripped of base instructions.
A failed refresh leaves the existing catalog intact, though installation may
already have updated symlinks. The target requires Bash, curl, jq, and stat.

To install the optional files without fetching models, use
`make linux OPENROUTER=1` or `make macos OPENROUTER=1` instead. The opt-in
config defaults to OpenRouter and the `z-ai/glm-5.2` model; it does not
change the standard config. Source the appropriate optional file **after**
the shared one, so ordinary `codex` commands can read the key file:

```bash
source "${CODEX_HOME:-$HOME/.codex}/scripts/codex-openrouter-shell.bash"
```

```zsh
source "${CODEX_HOME:-$HOME/.codex}/scripts/codex-openrouter-shell.zsh"
```

Run `codex-openrouter-models` to refresh the catalog and `codex pick
--openrouter` to choose a model. The EU exception models require suitable
OpenRouter account access. Credentials come from `OPEN_ROUTER_KEY` or
`~/.secrets/openrouter` and are not copied to this repository. The optional
wrapper loads the OpenRouter key for every `codex` invocation, including
commands that explicitly select a different provider; it does not leave a
file-loaded key in the parent shell.

Run the platform target again without `OPENROUTER=1` to switch back to the
standard config and remove optional symlinks that still point to this checkout.
Unmanaged optional files and generated catalogs are not removed. Remove or
change your optional shell source line manually, and restart your shell.
This opt-in controls what this repo installs, not access through other tools or
configurations. Follow your workplace's provider policies.

## Codex picker and catalog tools

`codex pick` queries the configured Codex provider's app server and uses `fzf`
to select a model and reasoning effort. For example:

```sh
codex pick -C /path/to/project "Review this project"
codex pick -- "--model is prompt text"
```

The generic picker needs Bash 3.2+, `jq`, `fzf`, Lua 5.4+, and a Codex CLI
with app-server `model/list` support. It does not switch providers; canceling
with Escape or Ctrl-C does not launch a session. Shell integration also reads
`BEDROCK_API_KEY` and `FOUNDRY_KIMIK_KEY` from the environment or their
corresponding files in `~/.secrets`.

The catalog sanitizer clears every model's `base_instructions` in a local
catalog, atomically and without making a backup:

```sh
"${CODEX_HOME:-$HOME/.codex}/scripts/strip-model-system-prompts.sh"
"${CODEX_HOME:-$HOME/.codex}/scripts/strip-model-system-prompts.sh" --target /path/to/models.json
```

The default target is `$CODEX_HOME/models.json`. It requires `jq` and `stat`;
the optional OpenRouter catalog refresh additionally requires `curl`.

## Migrating from the Lua installer

The former installer merged TOML and rules, created a managed-state file, and
edited shell startup files. The new installer does none of those things. It
backs up the old active files before linking the repository versions; review
the backups for settings that must be retained. The old
`.dotfiles-managed-config.json` and existing startup lines are left untouched.
Remove obsolete lines and the state file manually if desired. Existing startup
lines may still load integration files, including unmanaged OpenRouter files;
review them separately. The granular profile is now linked as-is and no longer
receives machine-specific additions from the old installer.

## Tests

`make test` runs the persistent Python and shell suites. They use temporary
homes, fixtures, and stub executables. The suites require Python 3.11+, Bash,
Lua 5.4+, `jq`, and `fzf`; Zsh tests run when Zsh is available. Set `TEST_ZSH`
to choose a Zsh executable, or `TEST_REAL_CODEX` for the optional real Codex
app-server smoke test. The latter may contact the configured provider.
