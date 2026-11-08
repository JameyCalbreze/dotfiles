#!/usr/bin/env python3
"""Provider-neutral picker tests; all Codex, model and fzf calls are stubbed."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
PICKER = ROOT / 'codex/scripts/pick-codex-model.sh'
ZSH = os.environ.get('TEST_ZSH') or shutil.which('zsh')


@unittest.skipUnless(shutil.which('jq') and shutil.which('bash'), 'requires jq and Bash')
class GenericPickerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='generic picker ')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.bin = self.work / 'bin with spaces'
        self.bin.mkdir()
        self.codex = self.bin / 'codex'
        self.codex.write_text(f'''#!{sys.executable}
import json, os, sys
from pathlib import Path
work = Path(os.environ['TEST_WORK'])
args = sys.argv[1:]
if 'app-server' not in args:
    (work / 'launch.json').write_text(json.dumps({{'args': args, 'cwd': os.getcwd(), 'key': os.environ.get('OPEN_ROUTER_KEY')}}))
    raise SystemExit(int(os.environ.get('STUB_EXIT', '0')))
(work / 'server-args.json').write_text(json.dumps(args))
(work / 'server-pid').write_text(str(os.getpid()))
if os.environ.get('STUB_BEHAVIOR') == 'crash':
    raise SystemExit(9)
if os.environ.get('STUB_BEHAVIOR') == 'hang':
    import time
    time.sleep(30)
for line in sys.stdin:
    request = json.loads(line)
    with (work / 'requests.jsonl').open('a') as output:
        output.write(json.dumps(request) + '\\n')
    method = request.get('method')
    if method == 'initialize':
        response = {{'id': request['id'], 'result': {{'userAgent': 'stub'}}}}
    elif method == 'model/list':
        behavior = os.environ.get('STUB_BEHAVIOR')
        if behavior == 'error':
            response = {{'id': request['id'], 'error': {{'code': -32600, 'message': 'provider unavailable'}}}}
        elif behavior == 'bad-data':
            response = {{'id': request['id'], 'result': {{'data': 'wrong'}}}}
        else:
            cursor = request['params'].get('cursor')
            if cursor is None:
                data = [
                    {{'id':'provider/alpha', 'model':'provider/alpha', 'displayName':'Alpha Model', 'hidden':False,
                      'defaultReasoningEffort':'high', 'supportedReasoningEfforts':[{{'reasoningEffort':'low'}},{{'reasoningEffort':'high'}}]}},
                    {{'id':'no-effort', 'model':'no-effort', 'displayName':'No Effort', 'supportedReasoningEfforts':[]}},
                    {{'id':'hidden', 'model':'hidden', 'hidden':True, 'supportedReasoningEfforts':[]}},
                ]
                response = {{'id': request['id'], 'result': {{'data':data, 'nextCursor':'second-page'}}}}
            else:
                data = [{{'id':'provider/beta','model':'provider/beta','displayName':'Beta Model',
                          'defaultReasoningEffort':'medium','supportedReasoningEfforts':[{{'reasoningEffort':'medium'}}]}}]
                if behavior == 'duplicate': data[0]['model'] = 'provider/alpha'
                response = {{'id': request['id'], 'result': {{'data':data, 'nextCursor': 'second-page' if behavior == 'cursor-loop' else None}}}}
    else:
        continue
    if os.environ.get('STUB_BEHAVIOR') == 'slow-response' and method == 'model/list':
        import time
        encoded = json.dumps(response)
        print(encoded[:15], end='', flush=True)
        time.sleep(1.2)
        print(encoded[15:], flush=True)
    else:
        print(json.dumps(response), flush=True)
''')
        self.codex.chmod(0o755)
        fzf = self.bin / 'fzf'
        fzf.write_text(f'''#!{sys.executable}
import json, os, sys
from pathlib import Path
work = Path(os.environ['TEST_WORK'])
countfile = work / 'fzf-count'
count = int(countfile.read_text()) + 1 if countfile.exists() else 1
countfile.write_text(str(count))
rows = sys.stdin.read().splitlines()
(work / f'rows-{{count}}').write_text('\\n'.join(rows))
(work / f'fzf-env-{{count}}').write_text(os.environ.get('FZF_DEFAULT_OPTS', 'missing') + '|' + os.environ.get('FZF_DEFAULT_OPTS_FILE', 'missing'))
if os.environ.get('CANCEL_STAGE') == str(count): raise SystemExit(130)
wanted = os.environ.get('STUB_MODEL' if count == 1 else 'STUB_EFFORT')
for row in rows:
    fields = row.split('\\t')
    if not wanted or (len(fields)>1 and fields[1] == wanted):
        print(row)
        raise SystemExit(0)
raise SystemExit(1)
''')
        fzf.chmod(0o755)
        self.home = self.work / 'isolated-home'
        self.home.mkdir()
        codex_home = self.home / '.codex'
        codex_home.mkdir()
        (codex_home / 'granular.config.toml').write_text('model_provider = "profile_provider"\n')
        self.env = dict(os.environ, TEST_WORK=str(self.work), HOME=str(self.home), CODEX_HOME=str(codex_home),
                        PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        FZF_DEFAULT_OPTS='--filter=wrong', FZF_DEFAULT_OPTS_FILE='/not-real', TMPDIR=str(self.work))
        for key in ('OPEN_ROUTER_KEY', 'CODEX_BIN', 'OPENAI_API_KEY', 'BEDROCK_API_KEY', 'FOUNDRY_KIMIK_KEY', 'ZDOTDIR'):
            self.env.pop(key, None)

    def run_picker(self, *args, env=None):
        return subprocess.run([str(PICKER), '--codex-bin', str(self.codex), *args], env=dict(self.env, **(env or {})),
                              cwd=self.work, capture_output=True, text=True, timeout=15)

    def launch(self):
        return json.loads((self.work / 'launch.json').read_text())

    def test_provider_neutral_list_pagination_efforts_and_arguments(self):
        project = self.work / 'project space'
        project.mkdir()
        result = self.run_picker('--', '--profile', 'granular', '-C', str(project),
                                 '-c', 'model_provider="company"', 'prompt with spaces')
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.launch()
        self.assertEqual(call['args'], ['--model', 'provider/alpha', '-c', 'model_reasoning_effort="high"',
                                        '--profile', 'granular', '-C', str(project), '-c', 'model_provider="company"', 'prompt with spaces'])
        self.assertEqual(call['cwd'], str(self.work))
        self.assertIsNone(call['key'])
        self.assertFalse(any('open_router' in item or 'openrouter.ai' in item for item in call['args']))
        self.assertEqual(json.loads((self.work / 'server-args.json').read_text()),
                         ['-c', '"model_provider"="profile_provider"', '-C', str(project), '-c', 'model_provider="company"', 'app-server'])
        requests = [json.loads(line) for line in (self.work / 'requests.jsonl').read_text().splitlines()]
        self.assertEqual([req['method'] for req in requests], ['initialize', 'initialized', 'model/list', 'model/list'])
        self.assertEqual(requests[-1]['params']['cursor'], 'second-page')
        self.assertIn('provider/beta', (self.work / 'rows-1').read_text())
        self.assertNotIn('hidden', (self.work / 'rows-1').read_text())
        self.assertTrue((self.work / 'rows-2').read_text().startswith('0\thigh\t(default)'))
        self.assertEqual((self.work / 'fzf-env-1').read_text(), '|')
        self.assertEqual(result.stdout, '')
        self.assertFalse(list(self.work.glob('codex-model-picker.*')))

    @unittest.skipUnless(shutil.which('fzf'), 'requires real fzf')
    def test_generic_picker_with_real_fzf_terminal(self):
        (self.bin / 'fzf').unlink()
        spec = importlib.util.spec_from_file_location('picker_tui_test', ROOT / 'codex/tests/test-codex-model-picker-tui.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        terminal = module.Terminal([str(PICKER), '--codex-bin', str(self.codex)], self.env)
        self.addCleanup(terminal.close)
        terminal.wait_for('Model >')
        terminal.send(b'Beta Model')
        terminal.wait_for('1/3')
        terminal.send(b'\r')
        self.assertEqual(terminal.finish(), 0)
        self.assertEqual(self.launch()['args'], ['--model', 'provider/beta', '-c', 'model_reasoning_effort="medium"'])

    def test_signal_stops_app_server_and_cleans_temporary_files(self):
        env = dict(self.env, STUB_BEHAVIOR='hang')
        process = subprocess.Popen([str(PICKER), '--codex-bin', str(self.codex)], env=env, cwd=self.work,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 5
        pidfile = self.work / 'server-pid'
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(pidfile.exists(), 'server did not start')
        server_pid = int(pidfile.read_text())
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, 143)
        with self.assertRaises(ProcessLookupError):
            os.kill(server_pid, 0)
        self.assertFalse(list(self.work.glob('codex-model-picker.*')))
        self.assertFalse((self.work / 'launch.json').exists())

    def test_single_no_effort_and_other_effort(self):
        result = self.run_picker(env={'STUB_MODEL':'no-effort'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launch()['args'], ['--model', 'no-effort'])
        self.assertEqual((self.work / 'fzf-count').read_text(), '1')
        (self.work / 'fzf-count').unlink()
        result = self.run_picker('--', '-C', str(self.work), env={'STUB_MODEL':'provider/beta'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launch()['args'], ['--model', 'provider/beta', '-c', 'model_reasoning_effort="medium"', '-C', str(self.work)])
        (self.work / 'fzf-count').unlink()
        result = self.run_picker(env={'STUB_EFFORT':'low'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launch()['args'][3], 'model_reasoning_effort="low"')

    def test_profile_is_layered_before_explicit_provider_overrides(self):
        profile = Path(self.env['CODEX_HOME']) / 'work.config.toml'
        profile.write_text('''model_provider = "corporate"
[model_providers.corporate]
base_url = "https://example.invalid/api"
env_key = "CORPORATE_KEY"
[model_providers.corporate.env_http_headers]
"X-API-Key" = "CORPORATE_KEY"
[permissions.granular.workspace_roots]
"/workspace with spaces" = true
[tui]
status_line = []
''')
        result = self.run_picker('--', '--profile', 'work', '-c', 'model_provider="override"')
        self.assertEqual(result.returncode, 0, result.stderr)
        server_args = json.loads((self.work / 'server-args.json').read_text())
        self.assertNotIn('--profile', server_args)
        overrides = [server_args[i + 1] for i, value in enumerate(server_args[:-1]) if value == '-c']
        parsed = [tomllib.loads(value) for value in overrides]
        self.assertIn({'model_provider': 'corporate'}, parsed)
        self.assertIn({'model_providers': {'corporate': {'base_url': 'https://example.invalid/api'}}}, parsed)
        self.assertIn({'model_providers': {'corporate': {'env_http_headers': {'X-API-Key': 'CORPORATE_KEY'}}}}, parsed)
        self.assertFalse(any('permissions' in value or 'tui' in value for value in parsed))
        self.assertEqual(overrides[-1], 'model_provider="override"')
        self.assertEqual(self.launch()['args'][-4:], ['--profile', 'work', '-c', 'model_provider="override"'])

    def test_profile_inline_credentials_are_not_exposed_to_app_server(self):
        profile = Path(self.env['CODEX_HOME']) / 'sensitive.config.toml'
        profile.write_text('''model_provider = "company"
[model_providers.company]
base_url = "https://example.invalid"
http_headers = { Authorization = "Bearer fake-secret" }
''')
        result = self.run_picker('--', '--profile', 'sensitive')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('potentially sensitive', result.stderr)
        self.assertNotIn('fake-secret', result.stderr)
        self.assertFalse((self.work / 'server-args.json').exists())
        self.assertFalse((self.work / 'launch.json').exists())

    def test_short_equals_flags_and_prompt_separator(self):
        (Path(self.env['CODEX_HOME']) / 'work.config.toml').write_text('model_provider = "profile_provider"\n')
        project = self.work / 'project with spaces'
        project.mkdir()
        result = self.run_picker('--', '-p=work', '-C=' + str(project), '-c=model_provider="custom"', '--', '--model is prompt')
        self.assertEqual(result.returncode, 0, result.stderr)
        server_args = json.loads((self.work / 'server-args.json').read_text())
        self.assertEqual(server_args, ['-c', '"model_provider"="profile_provider"', '-C', str(project),
                                       '-c', 'model_provider="custom"', 'app-server'])
        self.assertEqual(self.launch()['args'][-5:], ['-p=work', '-C=' + str(project),
                                                      '-c=model_provider="custom"', '--', '--model is prompt'])

    def test_missing_or_invalid_profile_fails_before_app_server(self):
        for profile in ('missing', '../outside', ''):
            with self.subTest(profile=profile):
                result = self.run_picker('--', '--profile', profile)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.work / 'server-args.json').exists())
                self.assertFalse((self.work / 'launch.json').exists())

    def test_conflicts_and_remote_fail_before_starting_server(self):
        for args in (('--', '--model=x'), ('--', '-mx'), ('--', '-c', 'model_reasoning_effort="high"'), ('--', '--remote=ws://example.invalid')):
            with self.subTest(args=args):
                result = self.run_picker(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse((self.work / 'server-args.json').exists())
                self.assertFalse((self.work / 'launch.json').exists())

    def test_slow_partial_json_response_is_reassembled(self):
        result = self.run_picker(env={'STUB_BEHAVIOR': 'slow-response'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launch()['args'][1], 'provider/alpha')

    def test_server_failures_never_show_picker_or_launch(self):
        for behavior in ('error', 'bad-data', 'duplicate', 'cursor-loop', 'crash'):
            with self.subTest(behavior=behavior):
                result = self.run_picker(env={'STUB_BEHAVIOR': behavior})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.work / 'fzf-count').exists())
                self.assertFalse((self.work / 'launch.json').exists())

    def install_default(self, include_openrouter=False):
        lua = os.environ.get('LUA', 'lua')
        if not shutil.which(lua):
            self.skipTest('requires Lua 5.4+')
        home = self.work / 'home with spaces'
        home.mkdir()
        secrets = home / '.secrets'
        secrets.mkdir()
        (secrets / 'openrouter').write_text('do-not-use')
        env = dict(self.env, HOME=str(home), CODEX_HOME=str(home / '.codex'), ZDOTDIR=str(home))
        args = [lua, str(ROOT / 'install.lua')]
        if include_openrouter:
            args.append('--include-openrouter')
        result = subprocess.run(args, env=env, cwd=home, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((home / '.codex/scripts/pick-codex-model.sh').is_symlink())
        self.assertEqual((home / '.codex/scripts/pick-openrouter-model.sh').is_symlink(), include_openrouter)
        return home, env

    def test_default_install_routes_bash_pick_without_openrouter(self):
        home, env = self.install_default()
        result = subprocess.run(['bash', '-c', 'source "$HOME/.bashrc_local"; codex pick -C "$HOME" "work prompt"'],
                                env=env, cwd=home, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.launch()
        self.assertEqual(call['args'][-5:], ['--profile', 'granular', '-C', str(home), 'work prompt'])
        self.assertIsNone(call['key'])
        self.assertFalse(any('open_router' in item or 'openrouter.ai' in item for item in call['args']))
        server_args = json.loads((self.work / 'server-args.json').read_text())
        self.assertNotIn('--profile', server_args)
        self.assertIn('"model_reasoning_effort"="high"', server_args)
        self.assertEqual(server_args[-3:], ['-C', str(home), 'app-server'])

    @unittest.skipUnless(ZSH, 'requires zsh (or TEST_ZSH)')
    def test_default_install_routes_zsh_pick_without_openrouter(self):
        home, env = self.install_default()
        result = subprocess.run([ZSH, '-i', '-c', 'codex pick -C "$HOME" "work prompt"'],
                                env=env, cwd=home, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.launch()
        self.assertEqual(call['args'][-5:], ['--profile', 'granular', '-C', str(home), 'work prompt'])
        self.assertIsNone(call['key'])
        self.assertFalse(any('open_router' in item or 'openrouter.ai' in item for item in call['args']))

    def test_optional_openrouter_does_not_change_generic_picker_or_load_key(self):
        home, env = self.install_default(include_openrouter=True)
        self.assertFalse((home / '.codex/models.json').exists())
        result = subprocess.run(['bash', '-c', 'source "$HOME/.bashrc_local"; codex pick'],
                                env=env, cwd=home, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launch()['args'][1], 'provider/alpha')
        self.assertIsNone(self.launch()['key'])
        self.assertFalse(any('open_router' in item or 'openrouter.ai' in item for item in self.launch()['args']))

    @unittest.skipUnless(ZSH, 'requires zsh (or TEST_ZSH)')
    def test_optional_openrouter_keeps_zsh_generic_picker_available(self):
        home, env = self.install_default(include_openrouter=True)
        result = subprocess.run([ZSH, '-i', '-c', 'codex pick'], env=env, cwd=home,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launch()['args'][1], 'provider/alpha')
        self.assertIsNone(self.launch()['key'])

    def test_openrouter_mode_refused_when_not_installed(self):
        home, env = self.install_default()
        result = subprocess.run(['bash', '-c', 'source "$HOME/.bashrc_local"; codex pick --openrouter'],
                                env=env, cwd=home, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('requires --include-openrouter', result.stderr)
        self.assertFalse((self.work / 'server-args.json').exists())
        self.assertFalse((self.work / 'launch.json').exists())

    @unittest.skipUnless(os.environ.get('TEST_REAL_CODEX'), 'set TEST_REAL_CODEX for a credential-free real app-server smoke test')
    def test_real_codex_app_server_with_installed_granular_profile(self):
        home, env = self.install_default()
        fzf = self.bin / 'fzf'
        fzf.write_text('#!/bin/sh\ncat >/dev/null\nexit 130\n')
        fzf.chmod(0o755)
        for name in list(env):
            if any(key in name.upper() for key in ('API_KEY', 'OPENROUTER', 'OPEN_ROUTER', 'OPENAI')):
                env.pop(name)
        result = subprocess.run([str(home / '.codex/scripts/pick-codex-model.sh'), '--codex-bin',
                                 os.environ['TEST_REAL_CODEX'], '--', '--profile', 'granular', '-C', str(home)],
                                env=env, cwd=home, capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 130, result.stderr)
        self.assertFalse((self.work / 'launch.json').exists())

    def test_cancel_or_codex_exit_is_propagated(self):
        for stage in ('1', '2'):
            with self.subTest(stage=stage):
                for name in ('fzf-count', 'launch.json'):
                    (self.work / name).unlink(missing_ok=True)
                result = self.run_picker(env={'CANCEL_STAGE': stage})
                self.assertEqual(result.returncode, 130, result.stderr)
                self.assertFalse((self.work / 'launch.json').exists())
        (self.work / 'fzf-count').unlink(missing_ok=True)
        result = self.run_picker(env={'STUB_EXIT':'37'})
        self.assertEqual(result.returncode, 37, result.stderr)


if __name__ == '__main__':
    unittest.main()
