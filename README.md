# Dotfiles

Portable Codex configuration, with an optional OpenRouter model selector.
Other Bash customizations can be added later.

## Install

Prerequisites: Lua 5.4 or newer, Bash 4 or newer, Codex CLI on `PATH`, and
standard Unix utilities. The installer bundles its Lua libraries and does not
require Python or LuaRocks. Clone this repository somewhere stable and run:

```bash
lua install.lua
```

**The default installation does not install OpenRouter configuration, Bash
functions, scripts, or catalog inputs.** The checkout still contains those
optional files; they are not linked or merged into your home directory.
Configure an appropriate provider for your environment separately. Do not use
OpenRouter at work if your workplace prohibits it.

The installer uses `$CODEX_HOME` if set, otherwise `~/.codex`. It links the
shared global `AGENTS.md` and Bash integration there. Existing Bash content is
preserved and a guarded source line is added to `~/.bashrc_local`. Ensure
`~/.bashrc` sources that file, then start a new shell or source it. For a
custom `CODEX_HOME`, set it before sourcing the file and running the installer.

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

## Optional OpenRouter installation

Only on an approved machine, explicitly include OpenRouter:

```bash
lua install.lua --include-openrouter
```

This adds the OpenRouter provider, models and catalog path to the generated
Codex configs; links the picker, catalog refresh and sanitization scripts, and
catalog inputs; and sources an additional Bash integration. **Ordinary `codex`
invocations then use the configured OpenRouter provider and granular model,**
not just `codex pick`. The option is an installation-time opt-in: no additional
per-command environment flag is needed. `jq`, `fzf`, `curl`, and `stat` are
needed for the picker and catalog tools.

After opting in, create the local catalog and use the picker:

```bash
codex-openrouter-models
codex pick
codex pick -C /path/to/project "Review this project"
```

The picker selects a model and supported reasoning effort with `fzf`; Escape or
Ctrl-C cancels. It passes the selected model, effort, provider, and catalog to
Codex and rejects conflicting overrides. Use `codex pick -- "--model is prompt
text"` for a prompt beginning with a dash. Family filters and optional EU
exceptions are in `codex/openrouter-model-families.txt` and
`codex/openrouter-model-exceptions.json`. EU exceptions use the EU endpoint
when launched via the picker and require appropriate OpenRouter account access.

The functions use existing `BEDROCK_API_KEY` and `FOUNDRY_KIMIK_KEY` values,
or matching files under `~/.secrets` when present. The optional integration
similarly uses `OPEN_ROUTER_KEY` or `~/.secrets/openrouter`. Keys are never
copied into this repository; file-loaded secrets stay in the invoked process.
Catalogs, backups, sessions, databases, logs, machine trust, approval rules,
and Herdr-managed hooks are not synchronized.

## Returning to the default installation

Re-run `lua install.lua` **without** `--include-openrouter`. It removes settings
that this installer previously managed, removes optional symlinks that still
point to this checkout, and removes its optional Bash source line. It does not
delete a generated local catalog or unmanaged files. Start a new shell so any
previously loaded OpenRouter functions are no longer active. Re-running the
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
dependencies. Set `LUA` to an interpreter path if it is not named `lua`.

```bash
python3 -m unittest discover -s tests -v
bash codex/tests/test-codex-model-picker.sh
bash codex/tests/test-model-catalog.sh
python3 codex/tests/test-codex-model-picker-tui.py
```

Tests use temporary directories, fixture data, and stub executables; the TUI
suite uses a real `fzf` in a pseudo-terminal. No real credentials are needed.
