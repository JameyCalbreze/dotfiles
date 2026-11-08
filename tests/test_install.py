#!/usr/bin/env python3
"""Exercise installation against isolated homes, never the user's real configuration."""
import datetime
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
ZSH = os.environ.get('TEST_ZSH') or shutil.which('zsh')
ZSH_SOURCE = '[[ -f "${CODEX_HOME:-$HOME/.codex}/scripts/codex-shell.zsh" ]] && source "${CODEX_HOME:-$HOME/.codex}/scripts/codex-shell.zsh"'
ZSH_OPTIONAL = '[[ -f "${CODEX_HOME:-$HOME/.codex}/scripts/codex-openrouter-shell.zsh" ]] && source "${CODEX_HOME:-$HOME/.codex}/scripts/codex-openrouter-shell.zsh"'
ZSH_PROFILE_SOURCE = '[[ -f "${ZDOTDIR:-$HOME}/.zsh_profile" ]] && source "${ZDOTDIR:-$HOME}/.zsh_profile"'


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dotfiles test ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo with spaces'
        self.repo.mkdir()
        for name in ('install.lua', 'vendor', 'codex', 'bash', 'zsh', 'herdr', 'ghostty'):
            src, dest = ROOT / name, self.repo / name
            if src.is_dir():
                shutil.copytree(src, dest, ignore=shutil.ignore_patterns('__pycache__'))
            else:
                shutil.copy2(src, dest)
        self.home = self.base / 'home with spaces'
        self.home.mkdir()
        self.codex = self.home / 'custom codex'
        self.env = dict(os.environ, HOME=str(self.home), CODEX_HOME=str(self.codex))
        for key in ('OPENAI_BASE_URL', 'OPEN_ROUTER_KEY', 'BEDROCK_API_KEY', 'FOUNDRY_KIMIK_KEY', 'ZDOTDIR', 'XDG_CONFIG_HOME', 'HERDR_CONFIG_PATH'):
            self.env.pop(key, None)

    def install(self, success=True, include_openrouter=False):
        args = [os.environ.get('LUA', 'lua'), str(self.repo / 'install.lua')]
        if include_openrouter:
            args.append('--include-openrouter')
        result = subprocess.run(args, env=self.env, text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def load(self, name):
        with (self.codex / name).open('rb') as f:
            return tomllib.load(f)

    def test_fresh_and_repeat_install(self):
        self.install()
        self.assertEqual((self.codex / 'AGENTS.md').resolve(), self.repo / 'codex/AGENTS.md')
        self.assertTrue((self.codex / 'scripts/codex-shell.bash').is_symlink())
        self.assertTrue((self.codex / 'scripts/codex-shell.zsh').is_symlink())
        self.assertTrue((self.codex / 'scripts/pick-codex-model.sh').is_symlink())
        self.assertTrue((self.codex / 'scripts/strip-model-system-prompts.sh').is_symlink())
        for name in ('pick-openrouter-model.sh', 'refresh-openrouter-model-catalog.sh', 'codex-openrouter-shell.bash', 'codex-openrouter-shell.zsh'):
            self.assertFalse((self.codex / 'scripts' / name).exists())
        self.assertFalse((self.codex / 'openrouter-model-families.txt').exists())
        self.assertFalse((self.codex / 'openrouter-model-exceptions.json').exists())
        self.assertNotIn('openrouter', (self.home / '.bashrc_local').read_text())
        self.assertNotIn('openrouter', (self.home / '.zshrc').read_text())
        self.assertNotIn('openrouter', (self.home / '.zsh_profile').read_text())
        self.assertEqual((self.home / '.zshrc').read_text().count(ZSH_PROFILE_SOURCE), 1)
        self.assertEqual((self.home / '.zsh_profile').read_text().count(ZSH_SOURCE), 1)
        self.assertFalse((self.codex / 'models.json').exists())
        self.assertNotIn('model_catalog_json', self.load('config.toml'))
        profile = self.load('granular.config.toml')
        self.assertTrue(profile['permissions']['granular']['workspace_roots'][str(self.codex)])
        self.assertEqual(profile['permissions']['granular']['filesystem'][':workspace_roots']['.'], 'read')
        shell_before = (self.home / '.bashrc_local').read_text()
        zsh_before = (self.home / '.zshrc').read_text()
        zsh_profile_before = (self.home / '.zsh_profile').read_text()
        config_before = (self.codex / 'config.toml').read_text()
        self.install()
        self.assertEqual((self.home / '.bashrc_local').read_text(), shell_before)
        self.assertEqual((self.home / '.zshrc').read_text(), zsh_before)
        self.assertEqual((self.home / '.zsh_profile').read_text(), zsh_profile_before)
        self.assertEqual((self.codex / 'config.toml').read_text(), config_before)
        self.assertFalse(list(self.home.glob('*.dotfiles-backup.*')))
        self.assertFalse(list(self.codex.glob('*.dotfiles-backup.*')))

    def test_rules_additive_install_and_repeat(self):
        rules_dir = self.codex / 'rules'
        rules_dir.mkdir(parents=True)
        rules = rules_dir / 'default.rules'
        shared = (self.repo / 'codex/rules/default.rules').read_text().splitlines()
        self.assertTrue(shared)
        original = '# local comment\n' + shared[0] + '\n' + shared[1] + ' # local suffix\nlocal_rule()'
        rules.write_text(original)
        other = rules_dir / 'local.rules'
        other.write_text('other rules\n')
        self.install()
        self.assertFalse(rules.is_symlink())
        text = rules.read_text()
        self.assertTrue(text.startswith(original + '\n'))
        self.assertTrue(all(text.splitlines().count(line) == 1 for line in shared))
        self.assertEqual((rules_dir / 'default.rules.dotfiles-backup.1').read_text(), original)
        self.assertEqual(other.read_text(), 'other rules\n')
        self.install()
        self.assertEqual(rules.read_text(), text)
        self.assertFalse((rules_dir / 'default.rules.dotfiles-backup.2').exists())
        (self.repo / 'codex/rules/default.rules').write_text(shared[0] + '\nnew_rule()\n')
        self.install()
        self.assertEqual(rules.read_text(), text + 'new_rule()\n')
        self.assertIn(shared[-1], rules.read_text().splitlines())

    def test_rules_fresh_install_and_optional_mode(self):
        for optional in (False, True):
            with self.subTest(optional=optional):
                self.codex = self.home / ('optional' if optional else 'default')
                self.env['CODEX_HOME'] = str(self.codex)
                self.install(include_openrouter=optional)
                rules = self.codex / 'rules/default.rules'
                self.assertFalse(rules.is_symlink())
                self.assertEqual(rules.read_text(), (self.repo / 'codex/rules/default.rules').read_text())

    def test_rules_symlink_backup_does_not_modify_target(self):
        rules_dir = self.codex / 'rules'
        rules_dir.mkdir(parents=True)
        old = self.home / 'old rules'
        old.write_text('local_rule()\n')
        rules = rules_dir / 'default.rules'
        rules.symlink_to(old)
        self.install()
        self.assertFalse(rules.is_symlink())
        self.assertTrue(rules.read_text().startswith('local_rule()\n'))
        self.assertEqual(old.read_text(), 'local_rule()\n')
        backup = rules_dir / 'default.rules.dotfiles-backup.1'
        self.assertTrue(backup.is_symlink())
        self.assertEqual(backup.resolve(), old)

    def test_rules_preflight_failures_do_not_change_home(self):
        shared = self.repo / 'codex/rules/default.rules'
        text = shared.read_text()
        shared.unlink()
        result = self.install(False)
        self.assertIn('missing repository file', result.stderr)
        self.assertFalse(self.codex.exists())
        shared.write_text(text)
        (self.codex / 'rules/default.rules').mkdir(parents=True)
        self.install(False)
        self.assertTrue((self.codex / 'rules/default.rules').is_dir())
        self.assertFalse((self.codex / 'AGENTS.md').exists())
        self.assertFalse((self.home / '.bashrc_local').exists())

    def test_removed_azure_kimik_provider_is_removed_on_upgrade(self):
        shared_config = self.repo / 'codex/config.toml'
        current_config = shared_config.read_text()
        shared_config.write_text(current_config + '''
[model_providers.azure_kimik]
name = "azure/kimik"
base_url = "https://jameycalbreze-5520-resource.services.ai.azure.com/openai/v1"
env_key = "FOUNDRY_KIMIK_KEY"
wire_api = "responses"
''')
        self.install()
        self.assertIn('azure_kimik', self.load('config.toml')['model_providers'])

        shared_config.write_text(current_config)
        self.install()
        self.assertNotIn('azure_kimik', self.load('config.toml').get('model_providers', {}))
        self.assertTrue((self.codex / 'config.toml.dotfiles-backup.1').exists())
        self.install()
        self.assertFalse((self.codex / 'config.toml.dotfiles-backup.2').exists())

    def test_herdr_and_ghostty_default_paths_and_repeat_install(self):
        self.install()
        for app, filename in (('herdr', 'config.toml'), ('ghostty', 'config')):
            target = self.home / '.config' / app / filename
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), self.repo / app / filename)
        self.install()
        self.assertFalse(list((self.home / '.config').rglob('*.dotfiles-backup.*')))

    def test_shared_app_settings(self):
        herdr = tomllib.loads((self.repo / 'herdr/config.toml').read_text())
        self.assertFalse(herdr['onboarding'])
        self.assertEqual(herdr['keys']['next_workspace'], ['ctrl+tab', 'prefix+right'])
        self.assertEqual(herdr['keys']['previous_workspace'], ['ctrl+shift+tab', 'prefix+left'])
        self.assertEqual(herdr['keys']['switch_tab'], ['ctrl+1..9', 'prefix+1..9'])
        ghostty = (self.repo / 'ghostty/config').read_text().splitlines()
        for setting in ('keybind = ctrl+tab=unbind', 'keybind = ctrl+shift+tab=unbind',
                        'font-family = JetBrainsMono Nerd Font Mono', 'font-size = 16',
                        'theme = Adwaita Dark', 'keybind = f11=toggle_fullscreen'):
            self.assertIn(setting, ghostty)

    def test_custom_config_paths_and_backups(self):
        xdg = self.home / 'custom config'
        ghostty = xdg / 'ghostty/config'
        ghostty.parent.mkdir(parents=True)
        ghostty.write_text('font-size = 12\n')
        herdr = self.home / 'custom herdr/config.toml'
        herdr.parent.mkdir()
        old = self.home / 'old-herdr.toml'
        old.write_text('onboarding = true\n')
        herdr.symlink_to(old)
        self.env.update(XDG_CONFIG_HOME=str(xdg), HERDR_CONFIG_PATH=str(herdr))
        self.install()
        self.assertEqual(ghostty.resolve(), self.repo / 'ghostty/config')
        self.assertEqual((ghostty.parent / 'config.dotfiles-backup.1').read_text(), 'font-size = 12\n')
        self.assertEqual(herdr.resolve(), self.repo / 'herdr/config.toml')
        backup = herdr.parent / 'config.toml.dotfiles-backup.1'
        self.assertTrue(backup.is_symlink())
        self.assertEqual(backup.resolve(), old)
        self.assertEqual(old.read_text(), 'onboarding = true\n')
        self.install()
        self.assertFalse((ghostty.parent / 'config.dotfiles-backup.2').exists())
        self.assertFalse((herdr.parent / 'config.toml.dotfiles-backup.2').exists())

    def test_custom_xdg_without_herdr_override(self):
        xdg = self.home / 'custom config'
        self.env['XDG_CONFIG_HOME'] = str(xdg)
        self.install(include_openrouter=True)
        self.assertEqual((xdg / 'herdr/config.toml').resolve(), self.repo / 'herdr/config.toml')
        self.assertEqual((xdg / 'ghostty/config').resolve(), self.repo / 'ghostty/config')
        self.assertFalse((self.home / '.config/herdr/config.toml').exists())

    def test_invalid_app_paths_and_conflicts_fail_before_changes(self):
        for key, value, message in (
            ('XDG_CONFIG_HOME', '', 'XDG_CONFIG_HOME'),
            ('XDG_CONFIG_HOME', 'relative', 'XDG_CONFIG_HOME'),
            ('HERDR_CONFIG_PATH', '', 'HERDR_CONFIG_PATH'),
            ('HERDR_CONFIG_PATH', str(self.home / '.config/ghostty/config'), 'multiple managed files'),
            ('HERDR_CONFIG_PATH', str(self.codex / 'config.toml'), 'multiple managed files'),
            ('HERDR_CONFIG_PATH', str(self.home / '.bashrc_local'), 'multiple managed files'),
            ('HERDR_CONFIG_PATH', str(self.repo / 'herdr/config.toml'), 'refusing to replace repository file'),
            ('HERDR_CONFIG_PATH', str(self.repo / 'ghostty/config'), 'refusing to replace repository file'),
            ('HERDR_CONFIG_PATH', str(self.repo / 'herdr') + '/../herdr/config.toml', 'refusing to replace repository file'),
        ):
            with self.subTest(key=key, value=value):
                self.env[key] = value
                result = self.install(success=False)
                self.assertIn(message, result.stderr)
                self.assertFalse(self.codex.exists())
                self.assertFalse((self.home / '.config').exists())
                self.env.pop(key)
        (self.home / '.config/herdr/config.toml').mkdir(parents=True)
        result = self.install(success=False)
        self.assertIn('refusing to replace directory', result.stderr)
        self.assertFalse(self.codex.exists())
        self.assertFalse((self.home / '.config/ghostty').exists())

    def test_ghostty_other_configs_are_left_alone_and_reported(self):
        extra = self.home / '.config/ghostty/config.ghostty'
        mac = self.home / 'Library/Application Support/com.mitchellh.ghostty/config'
        for path in (extra, mac):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('font-size = 20\n')
        result = self.install()
        for path in (extra, mac):
            self.assertIn(str(path), result.stderr)
            self.assertEqual(path.read_text(), 'font-size = 20\n')

    def test_missing_app_config_fails_before_changes(self):
        (self.repo / 'ghostty/config').unlink()
        result = self.install(success=False)
        self.assertIn('missing repository file', result.stderr)
        self.assertFalse(self.codex.exists())
        self.assertFalse((self.home / '.config').exists())

    def test_granular_profile_is_restored_in_both_install_modes(self):
        shared = tomllib.loads((self.repo / 'codex/granular.config.toml').read_text())
        for include_openrouter in (False, True):
            with self.subTest(include_openrouter=include_openrouter):
                self.codex = self.home / ('with openrouter' if include_openrouter else 'without openrouter')
                self.env['CODEX_HOME'] = str(self.codex)
                expected = json.loads(json.dumps(shared))
                expected['permissions']['granular']['workspace_roots'] = {str(self.codex): True}

                self.install(include_openrouter=include_openrouter)
                self.assertEqual(self.load('granular.config.toml'), expected)
                profile = self.codex / 'granular.config.toml'
                profile.unlink()

                self.install(include_openrouter=include_openrouter)
                self.assertEqual(self.load('granular.config.toml'), expected)

                original = ('model = "local/model"\n'
                            '[hooks.state."local-hook"]\n'
                            'trusted_hash = "sha256:keep"\n')
                profile.write_text(original)
                self.install(include_openrouter=include_openrouter)
                merged = self.load('granular.config.toml')
                self.assertEqual(merged['model'], 'local/model')
                self.assertEqual(merged['hooks']['state']['local-hook']['trusted_hash'], 'sha256:keep')
                for key in ('default_permissions', 'model_reasoning_effort', 'approvals_reviewer', 'auto_review'):
                    self.assertEqual(merged[key], expected[key])
                self.assertEqual(merged['permissions'], expected['permissions'])
                self.assertEqual((self.codex / 'granular.config.toml.dotfiles-backup.1').read_text(), original)
                self.install(include_openrouter=include_openrouter)
                self.assertFalse((self.codex / 'granular.config.toml.dotfiles-backup.2').exists())

    def test_openrouter_named_codex_home_does_not_bypass_provider_guard(self):
        self.codex = self.home / 'openrouter-named codex home'
        self.env['CODEX_HOME'] = str(self.codex)
        self.codex.mkdir()
        profile = self.codex / 'granular.config.toml'
        original = 'model_provider = "open_router"\n'
        profile.write_text(original)

        result = self.install(success=False)
        self.assertIn('OpenRouter references remain', result.stderr)
        self.assertEqual(profile.read_text(), original)
        self.assertFalse((self.codex / 'config.toml').exists())
        self.assertFalse((self.codex / 'AGENTS.md').exists())

    @unittest.skipUnless(shutil.which('jq') and shutil.which('bash'), 'requires jq and Bash')
    def test_default_sanitizer_is_manual_and_provider_neutral(self):
        self.codex.mkdir()
        catalog = self.codex / 'models.json'
        original = {'models': [
            {'slug': 'work/model', 'base_instructions': 'first prompt', 'other': 1},
            {'slug': 'another', 'base_instructions': 'second prompt', 'other': 2},
        ], 'unrelated': True}
        catalog.write_text(json.dumps(original))
        self.install()
        self.assertEqual(json.loads(catalog.read_text()), original, 'installer must not sanitize automatically')
        sanitizer = self.codex / 'scripts/strip-model-system-prompts.sh'
        self.assertTrue(sanitizer.is_symlink())
        result = subprocess.run([str(sanitizer)], env=self.env, cwd=self.home,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        sanitized = json.loads(catalog.read_text())
        self.assertEqual([model['base_instructions'] for model in sanitized['models']], ['', ''])
        self.assertEqual([model['slug'] for model in sanitized['models']], ['work/model', 'another'])
        self.assertEqual([model['other'] for model in sanitized['models']], [1, 2])
        self.assertTrue(sanitized['unrelated'])
        self.assertFalse((self.codex / 'scripts/pick-openrouter-model.sh').exists())

    def test_default_shell_does_not_install_openrouter_functions_or_load_key(self):
        self.install()
        secrets = self.home / '.secrets'
        secrets.mkdir()
        (secrets / 'openrouter').write_text('not-for-default-install')
        bin_dir = self.base / 'default-bin'
        bin_dir.mkdir()
        launched = self.base / 'default-env'
        stub = bin_dir / 'codex'
        stub.write_text('#!/bin/sh\nprintf "%s" "${OPEN_ROUTER_KEY-unset}" > "$TEST_LAUNCH"\n')
        stub.chmod(0o755)
        env = dict(self.env, PATH=str(bin_dir) + os.pathsep + self.env['PATH'], TEST_LAUNCH=str(launched))
        command = 'source "$HOME/.bashrc_local"; ! type -t codex-openrouter-models; codex --help'
        result = subprocess.run(['bash', '-c', command], env=env, cwd=self.home, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(launched.read_text(), 'unset')
        self.assertNotIn('openrouter', (self.codex / 'scripts/codex-shell.bash').read_text().lower())

    def test_include_openrouter_installs_all_optional_files_and_config(self):
        self.install(include_openrouter=True)
        for name in ('pick-openrouter-model.sh', 'refresh-openrouter-model-catalog.sh',
                     'codex-openrouter-shell.bash', 'codex-openrouter-shell.zsh'):
            self.assertTrue((self.codex / 'scripts' / name).is_symlink(), name)
        for name in ('openrouter-model-families.txt', 'openrouter-model-exceptions.json'):
            self.assertTrue((self.codex / name).is_symlink(), name)
        base = self.load('config.toml')
        for key in ('model', 'model_provider', 'model_catalog_json'):
            self.assertNotIn(key, base)
        self.assertEqual(base['model_providers']['open_router']['base_url'], 'https://openrouter.ai/api/v1')
        self.assertEqual(base['profiles']['openrouter_glm']['model_provider'], 'open_router')
        self.assertNotIn('model', self.load('granular.config.toml'))
        shell = (self.home / '.bashrc_local').read_text()
        self.assertEqual(shell.count('source "${CODEX_HOME:-$HOME/.codex}/scripts/codex-openrouter-shell.bash"'), 1)
        zshrc = (self.home / '.zshrc').read_text()
        zsh_profile = (self.home / '.zsh_profile').read_text()
        self.assertEqual(zshrc.count(ZSH_PROFILE_SOURCE), 1)
        self.assertNotIn('codex-openrouter-shell.zsh', zshrc)
        self.assertEqual(zsh_profile.count(ZSH_OPTIONAL), 1)
        self.install(include_openrouter=True)
        self.assertEqual((self.home / '.bashrc_local').read_text(), shell)
        self.assertEqual((self.home / '.zshrc').read_text(), zshrc)
        self.assertEqual((self.home / '.zsh_profile').read_text(), zsh_profile)
        self.assertFalse((self.codex / 'config.toml.dotfiles-backup.1').exists())

    def test_default_after_opt_in_removes_only_managed_optional_installation(self):
        self.install(include_openrouter=True)
        catalog = self.codex / 'models.json'
        catalog.write_text('{"models": []}\n')
        self.install()
        for name in ('pick-openrouter-model.sh', 'refresh-openrouter-model-catalog.sh',
                     'codex-openrouter-shell.bash', 'codex-openrouter-shell.zsh'):
            self.assertFalse((self.codex / 'scripts' / name).exists(), name)
        for name in ('openrouter-model-families.txt', 'openrouter-model-exceptions.json'):
            self.assertFalse((self.codex / name).exists(), name)
        base = self.load('config.toml')
        self.assertFalse(any(key in base for key in ('model', 'model_provider', 'model_catalog_json')))
        self.assertNotIn('open_router', base.get('model_providers', {}))
        self.assertNotIn('openrouter_glm', base.get('profiles', {}))
        self.assertNotIn('model', self.load('granular.config.toml'))
        self.assertNotIn('codex-openrouter-shell.bash', (self.home / '.bashrc_local').read_text())
        self.assertNotIn('codex-openrouter-shell.zsh', (self.home / '.zshrc').read_text())
        self.assertNotIn('codex-openrouter-shell.zsh', (self.home / '.zsh_profile').read_text())
        self.assertEqual((self.home / '.zshrc').read_text().count(ZSH_PROFILE_SOURCE), 1)
        self.assertTrue(catalog.is_file(), 'generated local catalog must not be deleted')
        self.assertTrue((self.codex / 'scripts/strip-model-system-prompts.sh').is_symlink())
        self.assertTrue((self.codex / 'config.toml.dotfiles-backup.1').exists())
        self.install()
        self.assertFalse((self.codex / 'config.toml.dotfiles-backup.2').exists())
        self.install(include_openrouter=True)
        self.assertTrue((self.codex / 'scripts/pick-openrouter-model.sh').is_symlink())
        self.assertIn('open_router', self.load('config.toml')['model_providers'])

    def test_default_does_not_remove_unmanaged_optional_files(self):
        (self.codex / 'scripts').mkdir(parents=True)
        local_script = self.codex / 'scripts/pick-openrouter-model.sh'
        local_script.write_text('local script\n')
        local_families = self.codex / 'openrouter-model-families.txt'
        local_families.write_text('local families\n')
        result = self.install()
        self.assertIn('leaving unmanaged optional file', result.stderr)
        self.assertEqual(local_script.read_text(), 'local script\n')
        self.assertEqual(local_families.read_text(), 'local families\n')
        self.assertNotIn('codex-openrouter-shell.bash', (self.home / '.bashrc_local').read_text())

    def test_optional_files_are_not_required_for_default_install(self):
        (self.repo / 'bash/codex-openrouter.bash').unlink()
        (self.repo / 'codex/openrouter.config.toml').unlink()
        self.install()
        result = self.install(False, include_openrouter=True)
        self.assertIn('missing repository file', result.stderr)
        self.assertFalse((self.codex / 'scripts/pick-openrouter-model.sh').exists())
        self.assertTrue((self.codex / 'scripts/pick-codex-model.sh').is_symlink())

    def test_existing_openrouter_config_allowed_only_with_explicit_flag(self):
        self.codex.mkdir()
        (self.codex / 'config.toml').write_text('model_provider = "open_router"\n[local]\nkeep = true\n')
        self.install(False)
        self.install(include_openrouter=True)
        config = self.load('config.toml')
        self.assertEqual(config['model_provider'], 'open_router')
        self.assertTrue(config['local']['keep'])
        self.assertTrue((self.codex / 'scripts/pick-openrouter-model.sh').is_symlink())

    def test_invalid_install_options_do_not_write(self):
        for option, success in (('--help', True), ('--unknown', False)):
            result = subprocess.run([os.environ.get('LUA', 'lua'), str(self.repo / 'install.lua'), option],
                                    env=self.env, text=True, capture_output=True)
            self.assertEqual(result.returncode == 0, success)
            self.assertIn('--include-openrouter', result.stdout if success else result.stderr)
            self.assertFalse(self.codex.exists())
            self.assertFalse((self.home / '.bashrc_local').exists())

    def test_custom_zdotdir_and_private_zshrc_are_preserved(self):
        zdotdir = self.home / 'zsh config with spaces'
        zdotdir.mkdir()
        rc = zdotdir / '.zshrc'
        rc.write_text('alias n=nano\n')
        rc.chmod(0o600)
        self.env['ZDOTDIR'] = str(zdotdir)
        self.install()
        self.assertTrue(rc.read_text().startswith('alias n=nano\n'))
        profile = zdotdir / '.zsh_profile'
        self.assertIn(ZSH_PROFILE_SOURCE, rc.read_text())
        self.assertIn('codex-shell.zsh', profile.read_text())
        self.assertEqual(rc.stat().st_mode & 0o777, 0o600)
        self.assertEqual((zdotdir / '.zshrc.dotfiles-backup.1').read_text(), 'alias n=nano\n')
        self.assertFalse((self.home / '.zshrc').exists())
        if ZSH:
            result = subprocess.run([ZSH, '-i', '-c', 'whence -w codex'], env=self.env,
                                    cwd=self.home, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('codex: function', result.stdout)
        previous = rc.read_text()
        self.install()
        self.assertEqual(rc.read_text(), previous)
        self.assertFalse((zdotdir / '.zshrc.dotfiles-backup.2').exists())
        self.install(include_openrouter=True)
        self.assertIn('codex-openrouter-shell.zsh', profile.read_text())
        self.assertNotIn('codex-openrouter-shell.zsh', rc.read_text())
        if ZSH:
            result = subprocess.run([ZSH, '-i', '-c', 'whence -w codex-openrouter-models'], env=self.env,
                                    cwd=self.home, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('codex-openrouter-models: function', result.stdout)
        self.install()
        self.assertNotIn('codex-openrouter-shell.zsh', profile.read_text())
        self.assertEqual(rc.read_text().count(ZSH_PROFILE_SOURCE), 1)
        self.assertIn('alias n=nano', rc.read_text())
        self.assertEqual(rc.stat().st_mode & 0o777, 0o600)

    def test_legacy_direct_zsh_sources_are_migrated_and_deduplicated(self):
        rc = self.home / '.zshrc'
        previous_rc = 'alias n=nano\n' + ZSH_SOURCE + '\n' + ZSH_OPTIONAL + '\n' + ZSH_SOURCE + '\n'
        rc.write_text(previous_rc)
        profile = self.home / '.zsh_profile'
        profile.write_text('export PERSONAL_SETTING=keep\n')
        self.install(include_openrouter=True)
        self.assertEqual((self.home / '.zshrc.dotfiles-backup.1').read_text(), previous_rc)
        self.assertTrue(rc.read_text().startswith('alias n=nano\n'))
        self.assertNotIn(ZSH_SOURCE, rc.read_text())
        self.assertNotIn(ZSH_OPTIONAL, rc.read_text())
        self.assertEqual(rc.read_text().count(ZSH_PROFILE_SOURCE), 1)
        self.assertTrue(profile.read_text().startswith('export PERSONAL_SETTING=keep\n'))
        self.assertEqual(profile.read_text().count(ZSH_SOURCE), 1)
        self.assertEqual(profile.read_text().count(ZSH_OPTIONAL), 1)
        before_rc, before_profile = rc.read_text(), profile.read_text()
        self.install(include_openrouter=True)
        self.assertEqual(rc.read_text(), before_rc)
        self.assertEqual(profile.read_text(), before_profile)
        self.assertFalse((self.home / '.zshrc.dotfiles-backup.2').exists())
        self.install()
        self.assertEqual(rc.read_text().count(ZSH_PROFILE_SOURCE), 1)
        self.assertEqual(profile.read_text().count(ZSH_SOURCE), 1)
        self.assertNotIn(ZSH_OPTIONAL, profile.read_text())
        self.assertIn('export PERSONAL_SETTING=keep', profile.read_text())

    def test_common_existing_zsh_profile_imports_are_not_duplicated(self):
        imports = (
            'source ~/.zsh_profile',
            '. "$HOME/.zsh_profile"',
            'source "${HOME}/.zsh_profile" # keep user source',
            '[[ -f "$HOME/.zsh_profile" ]] && source "$HOME/.zsh_profile"',
            '[ -f "$HOME/.zsh_profile" ] && . "$HOME/.zsh_profile"',
            'source "${ZDOTDIR:-$HOME}/.zsh_profile"',
            'source "$HOME/.zsh_profile" 2>/dev/null',
            'source ~/.zsh_profile; export PERSONAL_SETTING=keep',
            'if [[ -f "$HOME/.zsh_profile" ]]; then source "$HOME/.zsh_profile"; fi',
        )
        for index, source_line in enumerate(imports):
            with self.subTest(source=source_line):
                home = self.base / f'existing-source-{index}'
                home.mkdir()
                self.home = home
                self.codex = home / '.codex'
                self.env['HOME'] = str(home)
                self.env['CODEX_HOME'] = str(self.codex)
                rc = home / '.zshrc'
                original = '# existing setup\n' + source_line + '\n'
                rc.write_text(original)
                profile = home / '.zsh_profile'
                profile.write_text('export TEST_PROFILE_LOADS=$(( ${TEST_PROFILE_LOADS:-0} + 1 ))\n')
                self.install()
                self.assertEqual(rc.read_text(), original)
                self.assertFalse((home / '.zshrc.dotfiles-backup.1').exists())
                self.assertEqual(profile.read_text().count(ZSH_SOURCE), 1)
                self.install()
                self.assertEqual(rc.read_text(), original)
                self.assertEqual(profile.read_text().count(ZSH_SOURCE), 1)
                if ZSH:
                    env = dict(self.env, ZDOTDIR=str(home))
                    env.pop('TEST_PROFILE_LOADS', None)
                    result = subprocess.run([ZSH, '-i', '-c', 'print -r -- "loads=$TEST_PROFILE_LOADS"'],
                                            env=env, cwd=home, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('loads=1', result.stdout)

    def test_existing_custom_zdotdir_profile_import_is_not_duplicated(self):
        zdotdir = self.home / 'custom zsh config'
        zdotdir.mkdir()
        self.env['ZDOTDIR'] = str(zdotdir)
        rc = zdotdir / '.zshrc'
        original = 'source "$ZDOTDIR/.zsh_profile"\n'
        rc.write_text(original)
        profile = zdotdir / '.zsh_profile'
        profile.write_text('export TEST_PROFILE_LOADS=$(( ${TEST_PROFILE_LOADS:-0} + 1 ))\n')
        self.install()
        self.install()
        self.assertEqual(rc.read_text(), original)
        self.assertEqual(profile.read_text().count(ZSH_SOURCE), 1)
        if ZSH:
            result = subprocess.run([ZSH, '-i', '-c', 'print -r -- "loads=$TEST_PROFILE_LOADS"'],
                                    env=self.env, cwd=self.home, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('loads=1', result.stdout)

    def test_duplicate_managed_profile_imports_collapse_to_one(self):
        rc = self.home / '.zshrc'
        rc.write_text('alias n=nano\n' + ZSH_PROFILE_SOURCE + '\n' + ZSH_PROFILE_SOURCE + '\n')
        self.install()
        self.assertEqual(rc.read_text().count(ZSH_PROFILE_SOURCE), 1)
        self.assertIn('alias n=nano', rc.read_text())
        self.install()
        self.assertEqual(rc.read_text().count(ZSH_PROFILE_SOURCE), 1)

    def test_existing_user_import_replaces_duplicate_managed_import(self):
        rc = self.home / '.zshrc'
        user_line = 'source "$HOME/.zsh_profile"'
        rc.write_text(user_line + '\n' + ZSH_PROFILE_SOURCE + '\n')
        (self.home / '.zsh_profile').write_text('export TEST_PROFILE_LOADS=$(( ${TEST_PROFILE_LOADS:-0} + 1 ))\n')
        self.install()
        self.assertEqual(rc.read_text(), user_line + '\n')
        self.install()
        self.assertEqual(rc.read_text(), user_line + '\n')
        if ZSH:
            env = dict(self.env, ZDOTDIR=str(self.home))
            env.pop('TEST_PROFILE_LOADS', None)
            result = subprocess.run([ZSH, '-i', '-c', 'print -r -- "loads=$TEST_PROFILE_LOADS"'],
                                    env=env, cwd=self.home, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('loads=1', result.stdout)

    def test_existing_managed_profile_source_stays_in_place_on_update(self):
        rc = self.home / '.zshrc'
        original = 'export BEFORE=1\n' + ZSH_PROFILE_SOURCE + '\nexport AFTER=1\n'
        rc.write_text(original)
        self.install()
        self.install()
        self.assertEqual(rc.read_text(), original)
        self.assertFalse((self.home / '.zshrc.dotfiles-backup.1').exists())

    def test_commented_import_does_not_disable_installation(self):
        rc = self.home / '.zshrc'
        original = '# source ~/.zsh_profile\n'
        rc.write_text(original)
        self.install()
        self.assertTrue(rc.read_text().startswith(original))
        self.assertEqual(rc.read_text().count(ZSH_PROFILE_SOURCE), 1)
        self.assertEqual((self.home / '.zsh_profile').read_text().count(ZSH_SOURCE), 1)

    def test_home_profile_import_is_distinct_with_custom_zdotdir(self):
        zdotdir = self.home / 'custom zsh config'
        zdotdir.mkdir()
        self.env['ZDOTDIR'] = str(zdotdir)
        rc = zdotdir / '.zshrc'
        original = 'source "$HOME/.zsh_profile"\n'
        rc.write_text(original)
        home_profile = self.home / '.zsh_profile'
        home_profile.write_text('export HOME_PROFILE_LOADED=1\n')
        self.install()
        self.assertEqual(home_profile.read_text(), 'export HOME_PROFILE_LOADED=1\n')
        self.assertTrue(rc.read_text().startswith(original))
        self.assertEqual(rc.read_text().count(ZSH_PROFILE_SOURCE), 1)
        self.assertEqual((zdotdir / '.zsh_profile').read_text().count(ZSH_SOURCE), 1)
        if ZSH:
            result = subprocess.run([ZSH, '-i', '-c', 'print -r -- "home=$HOME_PROFILE_LOADED"; whence -w codex'],
                                    env=self.env, cwd=self.home, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('home=1', result.stdout)
            self.assertIn('codex: function', result.stdout)

    def test_existing_profile_and_rc_symlinks_are_backed_up_without_touching_targets(self):
        rc_target = self.home / 'original-zshrc'
        profile_target = self.home / 'original-zsh-profile'
        rc_target.write_text('alias n=nano\n')
        profile_target.write_text('export PERSONAL_SETTING=keep\n')
        profile_target.chmod(0o600)
        (self.home / '.zshrc').symlink_to(rc_target)
        (self.home / '.zsh_profile').symlink_to(profile_target)
        self.install()
        self.assertEqual(rc_target.read_text(), 'alias n=nano\n')
        self.assertEqual(profile_target.read_text(), 'export PERSONAL_SETTING=keep\n')
        self.assertEqual((self.home / '.zshrc.dotfiles-backup.1').resolve(), rc_target)
        self.assertEqual((self.home / '.zsh_profile.dotfiles-backup.1').resolve(), profile_target)
        self.assertFalse((self.home / '.zshrc').is_symlink())
        self.assertFalse((self.home / '.zsh_profile').is_symlink())
        self.assertEqual((self.home / '.zsh_profile').stat().st_mode & 0o777, 0o600)

    def test_invalid_zsh_profile_fails_before_modifying_home(self):
        (self.home / '.zsh_profile').mkdir()
        result = self.install(False)
        self.assertIn('install:', result.stderr)
        self.assertFalse(self.codex.exists())
        self.assertFalse((self.home / '.bashrc_local').exists())
        self.assertFalse((self.home / '.zshrc').exists())

    def test_invalid_zdotdir_fails_before_modifying_home(self):
        self.env['ZDOTDIR'] = str(self.home / 'missing')
        result = self.install(False)
        self.assertIn('ZDOTDIR directory does not exist', result.stderr)
        self.assertFalse(self.codex.exists())
        self.assertFalse((self.home / '.bashrc_local').exists())
        self.assertFalse((self.home / '.zshrc').exists())

    def test_zshrc_symlink_is_backed_up_without_changing_its_target(self):
        original = self.home / 'original-zshrc'
        original.write_text('alias n=nano\n')
        original.chmod(0o600)
        (self.home / '.zshrc').symlink_to(original)
        self.install()
        self.assertEqual(original.read_text(), 'alias n=nano\n')
        self.assertTrue((self.home / '.zshrc.dotfiles-backup.1').is_symlink())
        self.assertEqual((self.home / '.zshrc.dotfiles-backup.1').resolve(), original)
        self.assertFalse((self.home / '.zshrc').is_symlink())
        self.assertEqual((self.home / '.zshrc').stat().st_mode & 0o777, 0o600)

    def test_existing_files_preserved_backed_up_and_merged(self):
        self.codex.mkdir()
        (self.codex / 'AGENTS.md').write_text('old instructions\n')
        (self.home / '.bashrc_local').write_text('alias n=nano\n')
        (self.home / '.bashrc_local').chmod(0o600)
        (self.codex / 'config.toml').write_text('''# keep this backup
model = "local old"
model_provider = "local old"
when = 2026-01-01T12:00:00Z
not_a_number = nan
[[my_tools]]
name = "one"
[projects."/local/project"]
trust_level = "trusted"
[tui]
fullscreen_transcript = true
[model_providers.local_work]
local_extra = "keep"
''')
        (self.codex / 'granular.config.toml').write_text('''[projects."/local/project"]
trust_level = "trusted"
[hooks.state."local-hook"]
trusted_hash = "sha256:keep"
[permissions.granular.workspace_roots]
"/local/extra" = true
''')
        self.install()
        base = self.load('config.toml')
        self.assertEqual(base['model'], 'local old')
        self.assertEqual(base['projects']['/local/project']['trust_level'], 'trusted')
        self.assertEqual(base['my_tools'], [{'name': 'one'}])
        self.assertTrue(base['tui']['fullscreen_transcript'])
        self.assertEqual(base['model_providers']['local_work']['local_extra'], 'keep')
        profile = self.load('granular.config.toml')
        self.assertEqual(profile['hooks']['state']['local-hook']['trusted_hash'], 'sha256:keep')
        self.assertTrue(profile['permissions']['granular']['workspace_roots']['/local/extra'])
        self.assertTrue(profile['permissions']['granular']['workspace_roots'][str(self.codex)])
        self.assertEqual((self.codex / 'AGENTS.md.dotfiles-backup.1').read_text(), 'old instructions\n')
        self.assertEqual((self.home / '.bashrc_local.dotfiles-backup.1').read_text(), 'alias n=nano\n')
        self.assertIn('# keep this backup', (self.codex / 'config.toml.dotfiles-backup.1').read_text())
        self.assertIn('alias n=nano', (self.home / '.bashrc_local').read_text())
        self.assertEqual((self.home / '.bashrc_local').stat().st_mode & 0o777, 0o600)
        self.install()
        self.assertFalse((self.codex / 'config.toml.dotfiles-backup.2').exists())
        self.assertFalse((self.home / '.bashrc_local.dotfiles-backup.2').exists())

    def test_preserves_toml_types_in_unmanaged_settings(self):
        self.codex.mkdir()
        (self.codex / 'config.toml').write_text('''model = "old"
empty_array = []
empty_inline = {}
nested = [[], {}, [1.0, "2026-01-02"]]
date_string = "2026-01-02"
local_date = 2026-01-02
local_time = 12:34:56.123
local_datetime = 2026-01-02T12:34:56
utc_datetime = 2026-01-02T12:34:56Z
big_integer = 9223372036854775807
float_value = 1.0
negzero = -0.0
inline = { "a.b" = [], nested = { empty = {} } }
[[example]]
name = "first"
[example.data]
values = []
[[example]]
name = "second"
''')
        self.install()
        data = self.load('config.toml')
        self.assertEqual(data['empty_array'], [])
        self.assertEqual(data['empty_inline'], {})
        self.assertEqual(data['nested'], [[], {}, [1.0, '2026-01-02']])
        self.assertIs(type(data['nested'][2][0]), float)
        self.assertEqual(data['date_string'], '2026-01-02')
        self.assertEqual(data['local_date'], datetime.date(2026, 1, 2))
        self.assertEqual(data['local_time'], datetime.time(12, 34, 56, 123000))
        self.assertEqual(data['local_datetime'], datetime.datetime(2026, 1, 2, 12, 34, 56))
        self.assertEqual(data['utc_datetime'], datetime.datetime(2026, 1, 2, 12, 34, 56, tzinfo=datetime.timezone.utc))
        self.assertEqual(data['big_integer'], 9223372036854775807)
        self.assertIs(type(data['float_value']), float)
        self.assertLess(math.copysign(1, data['negzero']), 0)
        self.assertEqual(data['inline'], {'a.b': [], 'nested': {'empty': {}}})
        self.assertEqual(data['example'], [{'name': 'first', 'data': {'values': []}}, {'name': 'second'}])
        self.install()
        self.assertFalse((self.codex / 'config.toml.dotfiles-backup.2').exists())

    def test_fresh_config_contains_no_openrouter_defaults(self):
        self.install()
        config = self.load('config.toml')
        profile = self.load('granular.config.toml')
        for key in ('model', 'model_provider', 'model_catalog_json'):
            self.assertNotIn(key, config)
        self.assertNotIn('model', profile)
        self.assertNotIn('open_router', config.get('model_providers', {}))
        self.assertNotIn('openrouter_glm', config.get('profiles', {}))

    def test_existing_unmanaged_openrouter_config_fails_without_changes(self):
        for name, content in (
            ('config.toml', 'model_provider = "open_router"\n'),
            ('granular.config.toml', '[model_providers.work]\nbase_url = "https://openrouter.ai/api/v1"\n'),
        ):
            with self.subTest(name=name):
                self.codex.mkdir(exist_ok=True)
                path = self.codex / name
                path.write_text(content)
                result = self.install(False)
                self.assertIn('OpenRouter references remain', result.stderr)
                self.assertEqual(path.read_text(), content)
                self.assertFalse((self.codex / 'AGENTS.md').exists())
                self.assertFalse((self.home / '.bashrc_local').exists())
                path.unlink()

    def test_previous_managed_openrouter_settings_are_removed(self):
        self.codex.mkdir()
        (self.codex / 'config.toml').write_text('''model = "openai/gpt-5.4"
model_provider = "open_router"
model_catalog_json = "old.json"
[model_providers.open_router]
base_url = "https://openrouter.ai/api/v1"
[profiles.openrouter_glm]
model_provider = "open_router"
[projects."/work"]
trust_level = "trusted"
''')
        (self.codex / 'granular.config.toml').write_text('model = "deepseek/deepseek-v4.1-flash"\n')
        (self.codex / '.dotfiles-managed-config.json').write_text(json.dumps({
            'config.toml': [['model'], ['model_provider'], ['model_catalog_json'],
                            ['model_providers', 'open_router', 'base_url'],
                            ['profiles', 'openrouter_glm', 'model_provider']],
            'granular.config.toml': [['model']],
        }))
        self.install()
        data = self.load('config.toml')
        self.assertFalse(any(k in data for k in ('model', 'model_provider', 'model_catalog_json')))
        self.assertNotIn('open_router', data.get('model_providers', {}))
        self.assertNotIn('openrouter_glm', data.get('profiles', {}))
        self.assertEqual(data['projects']['/work']['trust_level'], 'trusted')
        self.assertNotIn('model', self.load('granular.config.toml'))
        self.assertTrue((self.codex / 'config.toml.dotfiles-backup.1').exists())

    def test_previous_openrouter_opt_in_migrates_to_provider_neutral_defaults(self):
        self.codex.mkdir()
        (self.codex / 'config.toml').write_text('''model = "openai/gpt-5.4"
model_provider = "open_router"
model_catalog_json = "old.json"
[model_providers.open_router]
name = "Open Router"
base_url = "https://openrouter.ai/api/v1"
env_key = "OPEN_ROUTER_KEY"
wire_api = "responses"
[projects."/work"]
trust_level = "trusted"
''')
        (self.codex / 'granular.config.toml').write_text('model = "deepseek/deepseek-v4.1-flash"\n')
        (self.codex / '.dotfiles-managed-config.json').write_text(json.dumps({
            'config.toml': [['model'], ['model_provider'], ['model_catalog_json'],
                            *[['model_providers', 'open_router', key] for key in ('name', 'base_url', 'env_key', 'wire_api')]],
            'granular.config.toml': [['model']],
        }))
        self.install(include_openrouter=True)
        base = self.load('config.toml')
        self.assertFalse(any(key in base for key in ('model', 'model_provider', 'model_catalog_json')))
        self.assertIn('open_router', base['model_providers'])
        self.assertEqual(base['projects']['/work']['trust_level'], 'trusted')
        self.assertNotIn('model', self.load('granular.config.toml'))
        self.assertTrue((self.codex / 'config.toml.dotfiles-backup.1').exists())
        self.assertTrue((self.codex / 'scripts/pick-openrouter-model.sh').is_symlink())
        self.assertTrue((self.codex / 'scripts/pick-codex-model.sh').is_symlink())

    def test_previous_python_metadata_is_migrated(self):
        self.codex.mkdir()
        (self.codex / 'config.toml').write_text('obsolete = "old"\n[local]\nkeep = true\n')
        (self.codex / '.dotfiles-managed-config.json').write_text(json.dumps({
            'config.toml': [['obsolete']], 'granular.config.toml': []
        }))
        self.install()
        data = self.load('config.toml')
        self.assertNotIn('obsolete', data)
        self.assertTrue(data['local']['keep'])
        self.assertNotIn(['model_catalog_json'], json.loads((self.codex / '.dotfiles-managed-config.json').read_text())['config.toml'])

    def test_invalid_metadata_fails_before_modifying_any_files(self):
        for bad in ('[]', '{"config.toml": null}', '{"config.toml": {}}',
                    '{"config.toml": [["model", null]]}', '{"config.toml": [null]}'):
            with self.subTest(state=bad):
                self.codex.mkdir(exist_ok=True)
                state = self.codex / '.dotfiles-managed-config.json'
                state.write_text(bad)
                self.install(False)
                self.assertEqual(state.read_text(), bad)
                self.assertFalse((self.codex / 'AGENTS.md').exists())
                self.assertFalse((self.home / '.bashrc_local').exists())

    def test_shared_settings_update_and_removed_keys(self):
        self.install()
        config = self.repo / 'codex/config.toml'
        text = config.read_text().replace('approval_policy = "on-request"', 'approval_policy = "never"').replace('status_line_use_colors = true\n', '')
        config.write_text(text)
        self.install()
        data = self.load('config.toml')
        self.assertEqual(data['approval_policy'], 'never')
        self.assertNotIn('status_line_use_colors', data['tui'])
        self.assertTrue((self.codex / 'config.toml.dotfiles-backup.1').exists())

    def test_managed_number_type_change_triggers_update(self):
        self.install()
        config = self.repo / 'codex/config.toml'
        config.write_text(config.read_text().replace('model_context_window = 200000', 'model_context_window = 200000.0'))
        self.install()
        value = self.load('config.toml')['profiles']['bedrock_glm']['model_context_window']
        self.assertIs(type(value), float)
        self.assertEqual(value, 200000.0)

    def test_invalid_config_or_directory_conflict_does_not_mutate(self):
        self.codex.mkdir()
        (self.codex / 'config.toml').write_text('not valid = [\n')
        result = self.install(False)
        self.assertIn('install:', result.stderr)
        self.assertEqual((self.codex / 'config.toml').read_text(), 'not valid = [\n')
        self.assertFalse((self.home / '.bashrc_local').exists())
        (self.codex / 'config.toml').unlink()
        (self.codex / 'AGENTS.md').mkdir()
        self.install(False)
        self.assertTrue((self.codex / 'AGENTS.md').is_dir())
        self.assertFalse((self.home / '.bashrc_local').exists())

    def test_conflicting_symlink_is_backed_up_without_touching_target(self):
        self.codex.mkdir()
        old = self.home / 'old instructions'
        old.write_text('unchanged')
        (self.codex / 'AGENTS.md').symlink_to(old)
        self.install()
        self.assertEqual(old.read_text(), 'unchanged')
        self.assertEqual((self.codex / 'AGENTS.md.dotfiles-backup.1').resolve(), old)

    def test_default_codex_home_and_local_bash_source(self):
        del self.env['CODEX_HOME']
        self.codex = self.home / '.codex'
        self.install()
        result = subprocess.run(['bash', '-c', 'source "$HOME/.bashrc_local"; type -t codex; printf "%s" "$CODEX_HOME"'], env=self.env, text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout, f'function\n{self.codex}')

    @unittest.skipUnless(shutil.which('jq') and shutil.which('bash'), 'requires jq and Bash')
    def test_installed_picker_before_and_after_local_refresh(self):
        self.install(include_openrouter=True)
        bin_dir = self.base / 'bin'
        bin_dir.mkdir()
        fixture = self.repo / 'codex/tests/fixtures/openrouter-models.json'
        (bin_dir / 'curl').write_text('#!/usr/bin/env bash\ncat "' + str(fixture) + '"\n')
        (bin_dir / 'fzf').write_text('#!/usr/bin/env bash\nawk "NR==1"\n')
        (bin_dir / 'codex').write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$LAUNCH_ARGS"\n')
        (bin_dir / 'python3').write_text('#!/usr/bin/env bash\nexit 99\n')
        for entry in bin_dir.iterdir():
            entry.chmod(0o755)
        env = dict(self.env, PATH=str(bin_dir) + os.pathsep + self.env['PATH'],
                   OPEN_ROUTER_KEY='fake-key', LAUNCH_ARGS=str(self.base / 'launch args'))
        def shell(command):
            return subprocess.run(['bash', '-c', 'source "$HOME/.bashrc_local"; ' + command],
                                  env=env, text=True, capture_output=True)
        missing = shell('codex pick --openrouter')
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('catalogue not readable', missing.stderr)
        self.assertFalse((self.base / 'launch args').exists())
        refreshed = shell('codex-openrouter-models')
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        self.assertTrue((self.codex / 'models.json').is_file())
        launched = shell('codex pick --openrouter')
        self.assertEqual(launched.returncode, 0, launched.stderr)
        args = (self.base / 'launch args').read_text().splitlines()
        self.assertEqual(args[:2], ['--model', 'anthropic/claude-test'])
        self.assertIn('model_provider="open_router"', args)
        self.assertIn('--profile', args)
        self.assertIn('granular', args)
        self.assertFalse((self.repo / 'codex/models.json').exists())

    @unittest.skipUnless(ZSH, 'requires zsh (or TEST_ZSH)')
    def test_zsh_default_startup_routes_codex_and_keeps_credentials_local(self):
        rc = self.home / '.zshrc'
        rc.write_text("alias codex='echo wrong-alias'\n")
        secrets = self.home / '.secrets'
        secrets.mkdir()
        (secrets / 'bedrock').write_text('fake-bedrock')
        (secrets / 'kimik.foundry').write_text('fake-foundry')
        (secrets / 'openrouter').write_text('must-not-load')
        bin_dir = self.base / 'zsh bin'
        bin_dir.mkdir()
        codex = bin_dir / 'codex'
        codex.write_text('''#!/bin/sh
printf "%s\\n" "$@" > "$TEST_ARGV"
printf "%s|%s|%s|%s" "${EDITOR-}" "${BEDROCK_API_KEY-}" "${FOUNDRY_KIMIK_KEY-}" "${OPEN_ROUTER_KEY-}" > "$TEST_ENV"
exit "${TEST_CODEX_STATUS:-0}"
''')
        codex.chmod(0o755)
        self.install()
        env = dict(self.env, ZDOTDIR=str(self.home), PATH=str(bin_dir) + os.pathsep + self.env['PATH'],
                   TEST_ARGV=str(self.base / 'args'), TEST_ENV=str(self.base / 'env'))
        command = ('codex exec "a prompt with spaces"; '
                   'print -r -- "local:${BEDROCK_API_KEY-unset}:${FOUNDRY_KIMIK_KEY-unset}:${OPEN_ROUTER_KEY-unset}"; '
                   'case "$(whence -w codex-openrouter-models)" in *": function") exit 98;; esac; exit 0')
        result = subprocess.run([ZSH, '-i', '-c', command], env=env, cwd=self.home, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.base / 'args').read_text().splitlines(), ['--profile', 'granular', 'exec', 'a prompt with spaces'])
        self.assertEqual((self.base / 'env').read_text(), 'micro|fake-bedrock|fake-foundry|')
        self.assertIn('local:unset:unset:unset', result.stdout)
        env['BEDROCK_API_KEY'] = 'from-environment'
        result = subprocess.run([ZSH, '-i', '-c', 'codex --help'], env=env, cwd=self.home, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.base / 'env').read_text(), 'micro|from-environment|fake-foundry|')
        env['TEST_CODEX_STATUS'] = '37'
        result = subprocess.run([ZSH, '-i', '-c', 'codex --help'], env=env, cwd=self.home, text=True, capture_output=True)
        self.assertEqual(result.returncode, 37, result.stderr)
        env.pop('TEST_CODEX_STATUS')
        env.pop('BEDROCK_API_KEY')
        (secrets / 'bedrock').unlink()
        (secrets / 'kimik.foundry').unlink()
        result = subprocess.run([ZSH, '-i', '-c', 'codex --help'], env=env, cwd=self.home, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.base / 'env').read_text(), 'micro|||')

    @unittest.skipUnless(ZSH and shutil.which('jq') and shutil.which('bash'), 'requires zsh, jq and Bash')
    def test_zsh_openrouter_opt_in_picker_and_refresh_with_stubs(self):
        (self.home / '.zshrc').write_text("alias codex='echo wrong-alias'\nalias codex-openrouter-models='echo wrong-refresh'\n")
        secrets = self.home / '.secrets'
        secrets.mkdir()
        (secrets / 'openrouter').write_text('fake-router')
        (secrets / 'bedrock').write_text('fake-bedrock')
        (secrets / 'kimik.foundry').write_text('fake-foundry')
        bin_dir = self.base / 'zsh tools'
        bin_dir.mkdir()
        scripts = {
            'codex': '#!/bin/sh\nprintf "%s\\n" "$@" > "$TEST_ARGV"\nprintf "%s|%s|%s|%s" "${EDITOR-}" "${BEDROCK_API_KEY-}" "${FOUNDRY_KIMIK_KEY-}" "${OPEN_ROUTER_KEY-}" > "$TEST_ENV"\n',
            'curl': '#!/bin/sh\ncat "$TEST_FIXTURE"\n',
            'fzf': "#!/bin/sh\nawk 'NR==1 {print}'\n",
        }
        for name, content in scripts.items():
            path = bin_dir / name
            path.write_text(content)
            path.chmod(0o755)
        self.install(include_openrouter=True)
        env = dict(self.env, ZDOTDIR=str(self.home), PATH=str(bin_dir) + os.pathsep + self.env['PATH'],
                   TEST_ARGV=str(self.base / 'args'), TEST_ENV=str(self.base / 'env'),
                   TEST_FIXTURE=str(self.repo / 'codex/tests/fixtures/openrouter-models.json'),
                   TEST_PROJECT=str(self.home), TEST_PROMPT='prompt with spaces')
        result = subprocess.run([ZSH, '-i', '-c', 'codex-openrouter-models'], env=env, cwd=self.home, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.codex / 'models.json').is_file())
        command = 'codex pick --openrouter -C "$TEST_PROJECT" "$TEST_PROMPT"; print -r -- "local:${OPEN_ROUTER_KEY-unset}"'
        result = subprocess.run([ZSH, '-i', '-c', command], env=env, cwd=self.home, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.base / 'args').read_text().splitlines()
        self.assertEqual(args[:2], ['--model', 'anthropic/claude-test'])
        self.assertIn('model_provider="open_router"', args)
        self.assertEqual(args[-5:], ['--profile', 'granular', '-C', str(self.home), 'prompt with spaces'])
        self.assertEqual((self.base / 'env').read_text(), 'micro|fake-bedrock|fake-foundry|fake-router')
        self.assertIn('local:unset', result.stdout)
        env['OPEN_ROUTER_KEY'] = 'from-environment'
        result = subprocess.run([ZSH, '-i', '-c', 'codex --help'], env=env, cwd=self.home, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.base / 'env').read_text(), 'micro|fake-bedrock|fake-foundry|from-environment')
        self.install()
        self.assertFalse((self.codex / 'scripts/codex-openrouter-shell.zsh').exists())
        self.assertNotIn('codex-openrouter-shell.zsh', (self.home / '.zshrc').read_text())
        self.assertNotIn('codex-openrouter-shell.zsh', (self.home / '.zsh_profile').read_text())
        self.assertTrue((self.codex / 'models.json').is_file())

    @unittest.skipUnless(ZSH, 'requires zsh (or TEST_ZSH)')
    def test_zsh_missing_codex_executable_reports_error(self):
        self.install()
        empty_path = self.base / 'empty-path'
        empty_path.mkdir()
        env = dict(self.env, ZDOTDIR=str(self.home), PATH=str(empty_path))
        result = subprocess.run([ZSH, '-i', '-c', 'codex --help'], env=env, cwd=self.home, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('executable not found in PATH', result.stderr)

    def test_installer_does_not_invoke_python(self):
        bin_dir = self.base / 'no python bin'
        bin_dir.mkdir()
        for name in ('python', 'python3'):
            stub = bin_dir / name
            stub.write_text('#!/bin/sh\nexit 99\n')
            stub.chmod(0o755)
        self.env['PATH'] = str(bin_dir) + os.pathsep + self.env['PATH']
        self.install()
        self.assertTrue((self.codex / 'AGENTS.md').is_symlink())

    def test_paths_with_shell_metacharacters_are_not_executed(self):
        self.home = self.base / "home ' $() `echo test`"
        self.home.mkdir()
        self.codex = self.home / "codex ' $()"
        self.env = dict(self.env, HOME=str(self.home), CODEX_HOME=str(self.codex))
        self.install()
        self.assertTrue((self.codex / 'AGENTS.md').is_symlink())
        self.assertNotIn('model_catalog_json', self.load('config.toml'))
        self.install()
        self.assertFalse(list(self.codex.glob('*.dotfiles-backup.*')))

    def test_managed_state_is_local_and_metadata_does_not_include_secrets(self):
        self.install()
        state = json.loads((self.codex / '.dotfiles-managed-config.json').read_text())
        self.assertNotIn(['model_catalog_json'], state['config.toml'])
        self.assertFalse((self.repo / 'codex/models.json').exists())
        self.assertFalse((self.repo / '.secrets').exists())


if __name__ == '__main__':
    unittest.main()
