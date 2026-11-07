# Dotfiles

Portable Codex configuration and the `codex pick` model selector, bootstrapped
from this machine. Other Bash customizations can be added incrementally.

## Install and update

Prerequisites: Lua 5.4 or newer, Bash 4 or newer, Codex CLI on `PATH`, `jq`, `fzf`,
and `curl` for catalog refreshes, plus standard Unix utilities (including `stat`).
The installer bundles its Lua libraries and does not require Python or LuaRocks. Clone this repository somewhere stable and
run:

```bash
lua install.lua
```

The installer uses `$CODEX_HOME` if set, otherwise `~/.codex`. It links the
shared scripts, catalog filters, and global `AGENTS.md` into that directory.
Existing conflicting files are backed up alongside the originals with a
`.dotfiles-backup.N` suffix; directories are never replaced. Existing Bash
content is preserved and a guarded source line is added to `~/.bashrc_local`.
The source line follows any old Codex function definitions and overrides them.
Ensure your `~/.bashrc` sources `~/.bashrc_local`, then start a new shell or
source that file. On machines using a custom `CODEX_HOME`, set it **before**
sourcing the file and before running the installer.

The two repository TOML files are templates, not symlinks. The installer merges
shared settings into local `config.toml` and `granular.config.toml`, preserving
unmanaged values such as project trust, additional providers, and hook state.
It sets the local catalog path and granular workspace root for `CODEX_HOME`.
Re-run the installer after pulling changes to refresh these managed settings.
Managed settings are authoritative: removing one from a template removes it on
the next install. Metadata recording managed keys stays in `CODEX_HOME`.
When a merge changes a configuration file, its TOML values are preserved, but
formatting and comments may change; the original is backed up. If a config or
shell file is a symlink, the link is backed up and replaced by a local file,
without changing its original target. Review backups before deleting them.
Installation does not automatically edit your `~/.bashrc` or install packages.

On the original machine, `~/.codex` is itself a Git checkout. Linking files and
generating configs there will appear as changes in that separate checkout; the
installer does not modify its Git history.

## Credentials and catalog

Nothing copies credentials into the repository. The shell functions use existing
`OPEN_ROUTER_KEY`, `BEDROCK_API_KEY`, and `FOUNDRY_KIMIK_KEY` environment
variables if nonempty. Otherwise, they read the corresponding local files
`~/.secrets/openrouter`, `~/.secrets/bedrock`, and `~/.secrets/kimik.foundry`
when present. Missing credentials are left for the selected provider to report.
Secrets loaded from files are exported only to the invoked process, not the
calling shell.

Create or refresh the **local, generated** catalog with:

```bash
codex-openrouter-models
codex pick
codex pick -C /path/to/project "Review this project"
```

The picker searches the catalog using `fzf`, then prompts for a supported
reasoning effort. Escape or Ctrl-C cancels. It passes the selected model,
effort, provider, and catalog to Codex and rejects conflicting overrides.
Use `codex pick -- "--model is prompt text"` for a prompt beginning with a dash.
Ordinary `codex` commands continue to use the `granular` profile. The wrapper
uses the first executable `codex` on `PATH` and sets `EDITOR=micro`.

Edit `codex/openrouter-model-families.txt` to select model families. Optional
exact-ID EU exceptions live in `codex/openrouter-model-exceptions.json`; the
picker routes these only through the EU endpoint, which requires appropriate
OpenRouter account access. Direct model selection does not enforce the picker’s
EU routing. Run `codex-openrouter-models` after changing these inputs. The
refresh uses the key from the environment, replaces the local catalog atomically,
and sanitizes the prior catalog backup. The standalone scripts support `--help`.

Secrets, generated catalogs and backups, sessions, databases, logs, machine
trust, approval rules, and Herdr-managed hooks are not synchronized. Existing
local files are not deleted.

## Tests

The persistent test suites require Python 3.11 or newer in addition to the
runtime dependencies. Set `LUA` to an interpreter path if it is not named `lua`.

```bash
python3 -m unittest discover -s tests -v
bash codex/tests/test-codex-model-picker.sh
bash codex/tests/test-model-catalog.sh
python3 codex/tests/test-codex-model-picker-tui.py
```

Tests use temporary directories, fixture data, and stub executables; the TUI
suite uses a real `fzf` in a pseudo-terminal. No real credentials are needed.
