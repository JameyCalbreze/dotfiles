# Dotfiles

Portable Codex configuration and a provider-neutral model picker for Bash and
Zsh, with optional OpenRouter support. Other shell customizations can be added
later.

## Install

Prerequisites: Lua 5.4 or newer, Bash 3.2 or newer, Codex CLI on `PATH`, and
standard Unix utilities. The picker also needs `jq`, `fzf`, and a Codex version
with app-server `model/list` support. Zsh is needed for the Zsh integration. The
installer bundles its Lua libraries and does not require Python or LuaRocks.
Clone this repository somewhere stable and run:

```bash
lua install.lua
```

**The default installation does not install OpenRouter configuration, shell
functions, scripts, or catalog inputs.** The checkout still contains those
optional files; they are not linked or merged into your home directory.
Configure an appropriate provider for your environment separately. Do not use
OpenRouter at work if your workplace prohibits it.

The installer uses `$CODEX_HOME` if set, otherwise `~/.codex`. It links the
global `AGENTS.md`, the generic picker, and both Bash and Zsh integration files
there. Existing
startup content is preserved:

- Bash: a guarded source line is added to `~/.bashrc_local`. Ensure `~/.bashrc`
  sources that file.
- Zsh: a guarded source line is added directly to `${ZDOTDIR:-$HOME}/.zshrc`.
  The installer uses `ZDOTDIR` from its environment, or `HOME` when unset; the
  chosen directory must already exist. If `.zshenv` sets an unexported
  `ZDOTDIR`, pass the same value to the installer explicitly.

Start a new shell after installing. Set a custom `CODEX_HOME` before running
the installer and before the shell loads its startup file. Ensure your Codex
executable is on `PATH` in each shell.

The shared TOML files are templates, not symlinks. The installer merges their
settings into local `config.toml` and `granular.config.toml`, preserving
unmanaged values such as project trust, additional providers, and hook state.
The default templates do not choose a model, provider, or model catalog.
Managed settings removed from the templates are removed on the next install;
metadata recording managed keys stays in `CODEX_HOME`.

Conflicting files and changed configs are backed up alongside the originals
with a `.dotfiles-backup.N` suffix. Directories are never replaced. TOML values
are preserved, but formatting and comments may change. If a config or shell
file is a symlink, the link is backed up and replaced by a local file without
changing its target. The installer does not edit `~/.bashrc` or install
packages. On the original machine, `~/.codex` is itself a Git checkout, so
installing there will appear as changes in that separate checkout.

## Generic Codex picker

`codex pick` is installed by default in both Bash and Zsh:

```bash
codex pick
codex pick -C /path/to/project "Review this project"
```

The picker asks the local Codex app server for models available to the
configured provider and account, then uses `fzf` to select a model and supported
reasoning effort. It passes through the selected model and effort without
switching providers or adding an OpenRouter endpoint. The app server may
contact the configured provider when discovering models. Profile, working
directory, and model/provider-related profile and configuration overrides are
used for discovery and forwarded to Codex. For safety, profile-scoped provider
settings with inline headers, credentials, or unsupported fields are rejected;
move those provider definitions to `config.toml` instead. Escape or Ctrl-C
cancels; no session is launched. Remote
Codex connections are not supported by this picker. Use `codex pick --
"--model is prompt text"` for a prompt beginning with a dash. If your existing
Codex configuration selects OpenRouter, the generic picker uses that configured
provider; the installer does not override unmanaged settings.

## Sanitize a local model catalog

The default installation also makes the catalog sanitizer available:

```bash
"${CODEX_HOME:-$HOME/.codex}/scripts/strip-model-system-prompts.sh"
"${CODEX_HOME:-$HOME/.codex}/scripts/strip-model-system-prompts.sh" --target /path/to/models.json
```

It clears the `base_instructions` string on every model in the specified local
catalog; without `--target`, it uses `$CODEX_HOME/models.json` (or
`~/.codex/models.json`). The file is replaced atomically and its permissions
are preserved, but **no backup is created**. It fails without changing the file
if any model lacks a string `base_instructions`. It requires `jq` and `stat`.

The installer and generic picker do not run the sanitizer automatically. It
changes only the local file, not the provider's models or server-side prompts;
Codex must be configured to use that catalog for it to affect a session.

## Optional OpenRouter installation

Only on an approved machine, explicitly include OpenRouter:

```bash
lua install.lua --include-openrouter
```

This adds the OpenRouter provider and profile, plus the optional OpenRouter
picker, catalog refresh script, and catalog inputs. The refresh uses the shared
sanitizer automatically. It does
**not** change the default provider or model: ordinary `codex` and `codex pick`
continue to use the configured provider. Existing unmanaged settings are
preserved, so review them separately. Reinstalling after an earlier version of
this repo removes its previously managed OpenRouter defaults, with backups.
`curl` and `stat` are also needed for the optional catalog tools.

After opting in, refresh the local catalog and explicitly choose OpenRouter:

```bash
codex-openrouter-models
codex pick --openrouter
codex pick --openrouter -C /path/to/project "Review this project"
```

The OpenRouter picker uses the local catalog and passes an OpenRouter provider
only for that launch. Family filters and optional EU exceptions are in
`codex/openrouter-model-families.txt` and `codex/openrouter-model-exceptions.json`.
EU exceptions use the EU endpoint when launched via this picker and require
appropriate OpenRouter account access. The generic picker does not apply this
regional metadata; use `codex pick --openrouter` for OpenRouter EU exceptions.

The functions use existing `BEDROCK_API_KEY` and `FOUNDRY_KIMIK_KEY` values,
or matching files under `~/.secrets` when present. The optional integration
uses `OPEN_ROUTER_KEY` or `~/.secrets/openrouter` for the OpenRouter picker and
catalog refresh. Keys are never copied into this repository; file-loaded
secrets stay in the invoked process.
Catalogs, backups, sessions, databases, logs, machine trust, approval rules,
and Herdr-managed hooks are not synchronized.

## Returning to the default installation

Re-run `lua install.lua` **without** `--include-openrouter`. It removes settings
that this installer previously managed, removes optional symlinks that still
point to this checkout, and removes its optional Bash and Zsh source lines. It
does not delete a generated local catalog or unmanaged files. Start a new shell
so any previously loaded OpenRouter functions are no longer active. Re-running the
installer with the flag restores the optional integration.

If existing local configs contain unmanaged OpenRouter references, default
installation stops before modifying anything; review those references manually
or use the flag only on an approved machine. The installer leaves unmanaged
optional files and existing custom Bash definitions untouched, and warns about
unmanaged optional files it finds. In particular, the original machine's
independent `~/.codex` and `.bashrc_local` may already use OpenRouter.

This opt-in controls **what this repo installs**, not network access. Existing
local or project configuration, old shell functions, other tools, or direct
Codex invocation can still use OpenRouter. Verify your effective configuration
and workplace policy; use employer-managed network and credential restrictions
where available. This repo does not certify any provider for work use.

## Tests

The persistent suites require Python 3.11 or newer in addition to the runtime
dependencies. Zsh integration tests run when `zsh` is available; set `TEST_ZSH`
to a Zsh executable to use another runtime. Set `LUA` to an interpreter path if
it is not named `lua`. The shell suites can also be run with Bash 3.2 by putting
its `bash` executable first on `PATH`. Setting `TEST_REAL_CODEX` to a Codex
executable enables a credential-free app-server smoke test that cancels before
launch; the app server may contact its configured provider.

```bash
python3 -m unittest discover -s tests -v
bash codex/tests/test-codex-model-picker.sh
bash codex/tests/test-model-catalog.sh
python3 codex/tests/test-codex-model-picker-tui.py
```

Tests use temporary directories, fixture data, and stub executables; the TUI
suite uses a real `fzf` in a pseudo-terminal. No real credentials are needed.
