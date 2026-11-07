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


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dotfiles test ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo with spaces'
        self.repo.mkdir()
        for name in ('install.lua', 'vendor', 'codex', 'bash'):
            src, dest = ROOT / name, self.repo / name
            if src.is_dir():
                shutil.copytree(src, dest, ignore=shutil.ignore_patterns('__pycache__'))
            else:
                shutil.copy2(src, dest)
        self.home = self.base / 'home with spaces'
        self.home.mkdir()
        self.codex = self.home / 'custom codex'
        self.env = dict(os.environ, HOME=str(self.home), CODEX_HOME=str(self.codex))

    def install(self, success=True):
        result = subprocess.run([os.environ.get('LUA', 'lua'), str(self.repo / 'install.lua')], env=self.env, text=True, capture_output=True)
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
        for name in ('pick-codex-model.sh', 'refresh-openrouter-model-catalog.sh', 'strip-model-system-prompts.sh', 'codex-shell.bash'):
            self.assertTrue((self.codex / 'scripts' / name).is_symlink())
        self.assertTrue((self.codex / 'openrouter-model-families.txt').is_symlink())
        self.assertFalse((self.codex / 'models.json').exists())
        self.assertEqual(self.load('config.toml')['model_catalog_json'], str(self.codex / 'models.json'))
        profile = self.load('granular.config.toml')
        self.assertTrue(profile['permissions']['granular']['workspace_roots'][str(self.codex)])
        self.assertEqual(profile['permissions']['granular']['filesystem'][':workspace_roots']['.'], 'read')
        shell_before = (self.home / '.bashrc_local').read_text()
        config_before = (self.codex / 'config.toml').read_text()
        self.install()
        self.assertEqual((self.home / '.bashrc_local').read_text(), shell_before)
        self.assertEqual((self.codex / 'config.toml').read_text(), config_before)
        self.assertFalse(list(self.home.glob('*.dotfiles-backup.*')))
        self.assertFalse(list(self.codex.glob('*.dotfiles-backup.*')))

    def test_existing_files_preserved_backed_up_and_merged(self):
        self.codex.mkdir()
        (self.codex / 'AGENTS.md').write_text('old instructions\n')
        (self.home / '.bashrc_local').write_text('alias n=nano\n')
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
[model_providers.open_router]
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
        self.assertEqual(base['model'], 'openai/gpt-5.4')
        self.assertEqual(base['projects']['/local/project']['trust_level'], 'trusted')
        self.assertEqual(base['my_tools'], [{'name': 'one'}])
        self.assertTrue(base['tui']['fullscreen_transcript'])
        self.assertEqual(base['model_providers']['open_router']['local_extra'], 'keep')
        profile = self.load('granular.config.toml')
        self.assertEqual(profile['hooks']['state']['local-hook']['trusted_hash'], 'sha256:keep')
        self.assertTrue(profile['permissions']['granular']['workspace_roots']['/local/extra'])
        self.assertTrue(profile['permissions']['granular']['workspace_roots'][str(self.codex)])
        self.assertEqual((self.codex / 'AGENTS.md.dotfiles-backup.1').read_text(), 'old instructions\n')
        self.assertEqual((self.home / '.bashrc_local.dotfiles-backup.1').read_text(), 'alias n=nano\n')
        self.assertIn('# keep this backup', (self.codex / 'config.toml.dotfiles-backup.1').read_text())
        self.assertIn('alias n=nano', (self.home / '.bashrc_local').read_text())
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
        self.assertIn(['model_catalog_json'], json.loads((self.codex / '.dotfiles-managed-config.json').read_text())['config.toml'])

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
        text = config.read_text().replace('model = "openai/gpt-5.4"', 'model = "openai/changed"').replace('status_line_use_colors = true\n', '')
        config.write_text(text)
        self.install()
        data = self.load('config.toml')
        self.assertEqual(data['model'], 'openai/changed')
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
        self.install()
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
        missing = shell('codex pick')
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('catalogue not readable', missing.stderr)
        self.assertFalse((self.base / 'launch args').exists())
        refreshed = shell('codex-openrouter-models')
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        self.assertTrue((self.codex / 'models.json').is_file())
        launched = shell('codex pick')
        self.assertEqual(launched.returncode, 0, launched.stderr)
        args = (self.base / 'launch args').read_text().splitlines()
        self.assertEqual(args[:2], ['--model', 'anthropic/claude-test'])
        self.assertIn('model_provider="open_router"', args)
        self.assertIn('--profile', args)
        self.assertIn('granular', args)
        self.assertFalse((self.repo / 'codex/models.json').exists())

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
        self.assertEqual(self.load('config.toml')['model_catalog_json'], str(self.codex / 'models.json'))
        self.install()
        self.assertFalse(list(self.codex.glob('*.dotfiles-backup.*')))

    def test_managed_state_is_local_and_metadata_does_not_include_secrets(self):
        self.install()
        state = json.loads((self.codex / '.dotfiles-managed-config.json').read_text())
        self.assertIn(['model_catalog_json'], state['config.toml'])
        self.assertFalse((self.repo / 'codex/models.json').exists())
        self.assertFalse((self.repo / '.secrets').exists())


if __name__ == '__main__':
    unittest.main()
