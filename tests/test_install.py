#!/usr/bin/env python3
"""Exercise Make targets against isolated homes and repository copies."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dotfiles test ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo with spaces'
        self.repo.mkdir()
        for name in ('Makefile', 'scripts', 'vendor', 'codex', 'bash', 'zsh', 'herdr', 'ghostty'):
            src, dst = ROOT / name, self.repo / name
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__'))
            else:
                shutil.copy2(src, dst)
        self.home = self.base / 'home with spaces'
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home))
        for name in ('CODEX_HOME', 'XDG_CONFIG_HOME', 'HERDR_CONFIG_PATH', 'OPENROUTER',
                     'OPEN_ROUTER_KEY', 'OPENROUTER_MODELS_URL'):
            self.env.pop(name, None)

    def install(self, platform='linux', optional=False, success=True):
        args = ['make', '-C', str(self.repo), platform, f'OPENROUTER={int(optional)}']
        result = subprocess.run(args, env=self.env, capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def expected(self, codex, xdg, herdr, optional=False):
        repo = self.repo
        links = {
            herdr: repo / 'herdr/config.toml',
            xdg / 'ghostty/config': repo / 'ghostty/config',
            codex / 'AGENTS.md': repo / 'codex/AGENTS.md',
            codex / 'config.toml': repo / ('codex/openrouter.config.toml' if optional else 'codex/config.toml'),
            codex / 'granular.config.toml': repo / 'codex/granular.config.toml',
            codex / 'rules/default.rules': repo / 'codex/rules/default.rules',
            codex / 'scripts/codex-shell.bash': repo / 'bash/codex.bash',
            codex / 'scripts/codex-shell.zsh': repo / 'zsh/codex.zsh',
            codex / 'scripts/pick-codex-model.sh': repo / 'codex/scripts/pick-codex-model.sh',
            codex / 'scripts/strip-model-system-prompts.sh': repo / 'codex/scripts/strip-model-system-prompts.sh',
            codex / 'scripts/codex-profile-config.lua': repo / 'codex/scripts/codex-profile-config.lua',
            codex / 'scripts/codex-toml.lua': repo / 'vendor/tinytoml.lua',
        }
        if optional:
            links.update({
                codex / 'scripts/codex-openrouter-shell.bash': repo / 'bash/codex-openrouter.bash',
                codex / 'scripts/codex-openrouter-shell.zsh': repo / 'zsh/codex-openrouter.zsh',
                codex / 'openrouter-model-families.txt': repo / 'codex/openrouter-model-families.txt',
                codex / 'openrouter-model-exceptions.json': repo / 'codex/openrouter-model-exceptions.json',
                codex / 'scripts/pick-openrouter-model.sh': repo / 'codex/scripts/pick-openrouter-model.sh',
                codex / 'scripts/refresh-openrouter-model-catalog.sh': repo / 'codex/scripts/refresh-openrouter-model-catalog.sh',
            })
        return links

    def assert_links(self, links):
        for destination, source in links.items():
            with self.subTest(destination=destination):
                self.assertTrue(destination.is_symlink(), str(destination))
                self.assertEqual(os.readlink(destination), str(source))

    def test_defaults_and_repeated_install_for_both_platforms(self):
        for platform in ('linux', 'macos'):
            with self.subTest(platform=platform):
                # Reuse the same home to also check switching targets is harmless.
                self.install(platform)
                codex, xdg = self.home / '.codex', self.home / '.config'
                self.assert_links(self.expected(codex, xdg, xdg / 'herdr/config.toml'))
                self.assertFalse((codex / 'scripts/pick-openrouter-model.sh').exists())
                self.assertFalse((self.home / '.bashrc_local').exists())
                self.assertFalse((self.home / '.zshrc').exists())
                self.assertFalse((self.home / '.zsh_profile').exists())
                self.install(platform)
                self.assertFalse(list(self.home.rglob('*.dotfiles-backup.*')))

    def test_overrides_and_relative_herdr_path(self):
        codex, xdg = self.base / 'custom codex', self.base / 'custom xdg'
        herdr = self.base / 'custom herdr' / 'config.toml'
        self.env.update(CODEX_HOME=str(codex), XDG_CONFIG_HOME=str(xdg),
                        HERDR_CONFIG_PATH='../custom herdr/config.toml')
        self.install('macos')
        self.assert_links(self.expected(codex, xdg, herdr))
        self.assertFalse((self.home / '.codex').exists())

    def test_empty_codex_home_uses_default_and_invalid_overrides_fail(self):
        self.env['CODEX_HOME'] = ''
        self.install()
        self.assertTrue((self.home / '.codex/config.toml').is_symlink())
        for name, value in (('XDG_CONFIG_HOME', ''), ('XDG_CONFIG_HOME', 'relative'),
                            ('HERDR_CONFIG_PATH', '')):
            with self.subTest(name=name, value=value):
                self.env[name] = value
                self.assertIn(name, self.install(success=False).stderr)
                del self.env[name]

    def test_conflicts_are_backed_up_and_broken_links_preserved(self):
        codex = self.home / '.codex'
        codex.mkdir()
        config = codex / 'config.toml'
        config.write_text('local config')
        (codex / 'config.toml.dotfiles-backup.1').write_text('older backup')
        agents = codex / 'AGENTS.md'
        agents.symlink_to('/missing/original')
        self.install()
        self.assertEqual((codex / 'config.toml.dotfiles-backup.1').read_text(), 'older backup')
        self.assertEqual((codex / 'config.toml.dotfiles-backup.2').read_text(), 'local config')
        self.assertEqual(os.readlink(codex / 'AGENTS.md.dotfiles-backup.1'), '/missing/original')
        self.assertTrue(config.is_symlink())
        self.install()
        self.assertFalse((codex / 'config.toml.dotfiles-backup.3').exists())

    def test_migration_preserves_startup_state_and_old_rules_in_backup(self):
        codex = self.home / '.codex'
        (codex / 'rules').mkdir(parents=True)
        old_rules = codex / 'rules/default.rules'
        old_rules.write_text('local rules\n')
        state = codex / '.dotfiles-managed-config.json'
        state.write_text('old state\n')
        startup = self.home / '.bashrc_local'
        startup.write_text('source existing integration\n')
        zshrc = self.home / '.zshrc'
        zshrc.write_text('existing zsh config\n')
        self.install()
        self.assertTrue(old_rules.is_symlink())
        self.assertEqual((codex / 'rules/default.rules.dotfiles-backup.1').read_text(), 'local rules\n')
        self.assertEqual(state.read_text(), 'old state\n')
        self.assertEqual(startup.read_text(), 'source existing integration\n')
        self.assertEqual(zshrc.read_text(), 'existing zsh config\n')

    def test_symlink_to_directory_is_backed_up_without_modifying_target(self):
        external = self.base / 'existing directory'
        external.mkdir()
        (external / 'keep').write_text('untouched')
        destination = self.home / '.config/ghostty/config'
        destination.parent.mkdir(parents=True)
        destination.symlink_to(external, target_is_directory=True)
        self.install()
        self.assertTrue(destination.is_symlink())
        self.assertEqual(os.readlink(destination.with_name('config.dotfiles-backup.1')), str(external))
        self.assertEqual((external / 'keep').read_text(), 'untouched')

    def test_conflicting_directories_are_rejected_before_changes(self):
        bad = self.home / '.codex/rules/default.rules'
        bad.mkdir(parents=True)
        result = self.install(success=False)
        self.assertIn('refusing to replace directory', result.stderr)
        self.assertTrue(bad.is_dir())
        self.assertFalse((self.home / '.config').exists())
        self.assertFalse((self.home / '.codex/config.toml').exists())

    def test_collisions_and_repository_destinations_fail_before_changes(self):
        for path in (self.home / '.codex/config.toml', self.repo / 'codex/config.toml',
                     self.home / '.codex/scripts'):
            with self.subTest(path=path):
                self.env['HERDR_CONFIG_PATH'] = str(path)
                self.install(success=False)
                self.assertFalse((self.home / '.config').exists())
                self.assertFalse((self.home / '.codex').exists())
        self.assertTrue((self.repo / 'codex/config.toml').is_file())

    def test_symlinked_parent_into_repository_is_rejected(self):
        alias = self.base / 'repo alias'
        alias.symlink_to(self.repo, target_is_directory=True)
        self.env['HERDR_CONFIG_PATH'] = str(alias / 'herdr/config.toml')
        self.assertIn('inside the repository', self.install(success=False).stderr)
        self.assertFalse((self.home / '.config').exists())

    def test_missing_source_is_detected_before_changes(self):
        (self.repo / 'codex/scripts/pick-codex-model.sh').unlink()
        self.assertIn('missing repository file', self.install(success=False).stderr)
        self.assertFalse((self.home / '.config').exists())
        self.assertFalse((self.home / '.codex').exists())

    def test_opt_in_then_default_removes_only_managed_optional_links(self):
        codex, xdg = self.home / '.codex', self.home / '.config'
        self.install(optional=True)
        self.assert_links(self.expected(codex, xdg, xdg / 'herdr/config.toml', optional=True))
        optional = codex / 'openrouter-model-families.txt'
        optional.unlink()
        optional.write_text('unmanaged')
        catalog = codex / 'models.json'
        catalog.write_text('local catalog')
        self.install()
        self.assert_links(self.expected(codex, xdg, xdg / 'herdr/config.toml'))
        self.assertEqual(optional.read_text(), 'unmanaged')
        self.assertEqual(catalog.read_text(), 'local catalog')
        for name in ('codex-openrouter-shell.bash', 'codex-openrouter-shell.zsh',
                     'pick-openrouter-model.sh', 'refresh-openrouter-model-catalog.sh'):
            self.assertFalse((codex / 'scripts' / name).is_symlink())
        self.assertFalse((codex / 'openrouter-model-exceptions.json').is_symlink())
        self.assertEqual(os.readlink(codex / 'config.toml.dotfiles-backup.1'),
                         str(self.repo / 'codex/openrouter.config.toml'))
        self.install(optional=True)
        self.assertTrue(optional.is_symlink())
        self.assertEqual((codex / 'openrouter-model-families.txt.dotfiles-backup.1').read_text(), 'unmanaged')

    def test_default_leaves_unmanaged_optional_directory(self):
        directory = self.home / '.codex/scripts/pick-openrouter-model.sh'
        directory.mkdir(parents=True)
        self.install()
        self.assertTrue(directory.is_dir())
        self.install(optional=True, success=False)
        self.assertTrue(directory.is_dir())

    def test_openrouter_config_contains_standard_config(self):
        with (self.repo / 'codex/config.toml').open('rb') as f:
            standard = tomllib.load(f)
        with (self.repo / 'codex/openrouter.config.toml').open('rb') as f:
            optional = tomllib.load(f)
        for key, value in standard.items():
            if isinstance(value, dict):
                for nested_key, nested_value in value.items():
                    self.assertEqual(optional[key][nested_key], nested_value)
            else:
                self.assertEqual(optional[key], value)
        self.assertEqual(optional['model_provider'], 'open_router')
        self.assertEqual(optional['model'], 'z-ai/glm-5.2')
        self.assertNotIn('model_provider', standard)
        self.assertNotIn('bedrock_glm', standard.get('profiles', {}))
        self.assertNotIn('bedrock_glm', optional.get('profiles', {}))
        self.assertIn('open_router', optional['model_providers'])
        self.assertNotIn('openrouter_glm', optional.get('profiles', {}))

    def test_openrouter_target_installs_allowlisted_prompt_free_catalog(self):
        bindir = self.base / 'stub bin'
        bindir.mkdir()
        curl = bindir / 'curl'
        curl.write_text('''#!/bin/sh
case "$*" in
  *"Authorization: Bearer $EXPECTED_KEY"*) ;;
  *) exit 91 ;;
esac
if [ "${BAD_CATALOG:-}" = 1 ]; then
  printf '%s\\n' '{"data":{}}'
else
  cat "$MODEL_FIXTURE"
fi
''')
        curl.chmod(0o755)
        (self.repo / 'codex/openrouter-model-families.txt').write_text('openai/\n')
        secrets = self.home / '.secrets'
        secrets.mkdir()
        (secrets / 'openrouter').write_text('file-key\n')
        codex, xdg = self.base / 'custom codex', self.home / '.config'
        self.env.update(CODEX_HOME=str(codex), PATH=str(bindir) + os.pathsep + self.env['PATH'],
                        EXPECTED_KEY='file-key', MODEL_FIXTURE=str(self.repo / 'codex/tests/fixtures/openrouter-models.json'))
        result = self.install('openrouter')
        self.assertNotIn('file-key', result.stdout + result.stderr)
        self.assert_links(self.expected(codex, xdg, xdg / 'herdr/config.toml', optional=True))
        catalog = codex / 'models.json'
        data = json.loads(catalog.read_text())
        self.assertEqual([model['slug'] for model in data['models']], ['openai/gpt-test'])
        self.assertTrue(all(model['base_instructions'] == '' for model in data['models']))
        self.assertEqual(catalog.stat().st_mode & 0o777, 0o600)

        # A supplied environment key takes precedence, and failed refreshes leave
        # the previously installed catalog unchanged.
        self.env.update(OPEN_ROUTER_KEY='env-key', EXPECTED_KEY='env-key', BAD_CATALOG='1')
        before = catalog.read_bytes()
        result = self.install('openrouter', success=False)
        self.assertNotIn('env-key', result.stdout + result.stderr)
        self.assertEqual(catalog.read_bytes(), before)
        self.assertFalse(list(codex.glob('models.json.*.bak')))
        del self.env['BAD_CATALOG']
        data['models'][0]['base_instructions'] = 'old system prompt'
        catalog.write_text(json.dumps(data))
        self.install('openrouter')
        backups = list(codex.glob('models.json.*.bak'))
        self.assertEqual(len(backups), 1)
        self.assertTrue(all(model['base_instructions'] == ''
                            for model in json.loads(backups[0].read_text())['models']))

    def test_openrouter_target_requires_credentials_before_installing(self):
        result = self.install('openrouter', success=False)
        self.assertIn('OPEN_ROUTER_KEY', result.stderr)
        self.assertFalse((self.home / '.codex').exists())
        self.assertFalse((self.home / '.config').exists())

    def test_invalid_optional_value_fails_without_changes(self):
        result = subprocess.run(['make', '-C', str(self.repo), 'linux', 'OPENROUTER=yes'],
                                env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('OPENROUTER must be 0 or 1', result.stderr)
        self.assertFalse((self.home / '.config').exists())


if __name__ == '__main__':
    unittest.main()
