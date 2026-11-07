#!/usr/bin/env python3
"""Persistent integration tests using real fzf in a controlling pseudo-terminal."""
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import struct
import sys
import tempfile
import termios
import time
import tomllib
import unittest

ROOT = Path(__file__).resolve().parent.parent
ANSI = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


class Terminal:
    def __init__(self, command, env):
        self.output = b""
        self.status = None
        self.pid, self.fd = os.forkpty()
        if self.pid == 0:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 140, 0, 0))
            os.execvpe(command[0], command, env)
        os.set_blocking(self.fd, False)

    def read(self):
        if select.select([self.fd], [], [], 0.05)[0]:
            try:
                self.output += os.read(self.fd, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
        if self.status is None:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.status = os.waitstatus_to_exitcode(status)

    def wait_for(self, text):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.read()
            if text.encode() in ANSI.sub(b"", self.output):
                return
            if self.status is not None:
                break
        raise AssertionError(f"Screen did not show {text!r}; status={self.status}; output={ANSI.sub(b'', self.output)[-4000:]!r}")

    def send(self, keys):
        os.write(self.fd, keys)

    def finish(self):
        deadline = time.monotonic() + 10
        while self.status is None and time.monotonic() < deadline:
            self.read()
        if self.status is None:
            raise AssertionError(f"Launcher did not exit: {self.output!r}")
        return self.status

    def close(self):
        if self.status is None:
            os.kill(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        os.close(self.fd)


@unittest.skipUnless(shutil.which("fzf") and shutil.which("jq"), "requires real fzf and jq")
class ModelPickerTuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex-picker-tui-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.argv_file = self.work / "argv.json"
        catalog_data = json.loads((ROOT / "tests/fixtures/codex-model-picker.json").read_text())
        catalog_data["models"][2]["openrouter_region"] = "eu"
        self.catalog = self.work / "models.json"
        self.catalog.write_text(json.dumps(catalog_data))
        self.codex = self.work / "codex-stub"
        self.codex.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "with open(os.environ['TEST_ARGV_FILE'], 'w') as output:\n"
            "    json.dump(sys.argv[1:], output)\n"
        )
        self.codex.chmod(0o755)
        env = dict(os.environ, TERM="xterm-256color", TEST_ARGV_FILE=str(self.argv_file),
                   FZF_DEFAULT_OPTS="--filter=wrong --multi", FZF_DEFAULT_OPTS_FILE="/nonexistent")
        self.terminal = Terminal([
            str(ROOT / "scripts/pick-codex-model.sh"),
            "--catalog", str(self.catalog),
            "--codex-bin", str(self.codex),
        ], env)
        self.addCleanup(self.terminal.close)
        self.terminal.wait_for("Model >")

    def open_effort(self):
        self.terminal.send(b"Claude Test Batch")
        # Wait for a filtered result count before accepting, avoiding event races.
        self.terminal.wait_for("1/3")
        self.terminal.send(b"\r")
        self.terminal.wait_for("Effort for anthropic/claude-test:batch >")

    def test_display_name_search_and_default_effort(self):
        self.open_effort()
        self.terminal.send(b"\r")
        self.assertEqual(self.terminal.finish(), 0)
        argv = json.loads(self.argv_file.read_text())
        self.assertEqual(argv[:4], ["--model", "anthropic/claude-test:batch", "-c",
                                    'model_reasoning_effort="high"'])

    def test_effort_keyboard_navigation(self):
        self.open_effort()
        # Reverse layout puts default high first, then low, then max.
        self.terminal.send(b"\x1b[B\x1b[B\r")
        self.assertEqual(self.terminal.finish(), 0)
        self.assertEqual(json.loads(self.argv_file.read_text())[3], 'model_reasoning_effort="max"')

    def test_slug_search_skips_single_effort_screen(self):
        self.terminal.send(b"openai/no-reasoning-test")
        self.terminal.wait_for("1/3")
        self.terminal.send(b"\r")
        self.assertEqual(self.terminal.finish(), 0)
        argv = json.loads(self.argv_file.read_text())
        self.assertEqual(argv[1], "openai/no-reasoning-test")
        self.assertEqual(argv[3], 'model_reasoning_effort="none"')
        self.assertNotIn(b"Effort for", self.terminal.output)

    def test_eu_exception_routing(self):
        self.terminal.send(b"openai/quoted-name-test")
        self.terminal.wait_for("1/3")
        self.terminal.wait_for("[EU routing]")
        self.terminal.send(b"\r")
        self.assertEqual(self.terminal.finish(), 0)
        argv = json.loads(self.argv_file.read_text())
        self.assertEqual(argv[5], 'model_provider="open_router_eu_exception"')
        overrides = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "-c"]
        provider_override = next(x for x in overrides if x.startswith("model_providers."))
        provider = tomllib.loads(provider_override)["model_providers"]["open_router_eu_exception"]
        self.assertEqual(provider, {
            "name": "OpenRouter EU exception",
            "base_url": "https://eu.openrouter.ai/api/v1",
            "env_key": "OPEN_ROUTER_KEY",
            "wire_api": "responses",
        })
        self.assertIn(b"EU-only routing", self.terminal.output)

    def test_model_escape_cancels(self):
        self.terminal.send(b"\x1b")
        self.assertEqual(self.terminal.finish(), 130)
        self.assertFalse(self.argv_file.exists())

    def test_effort_ctrl_c_cancels(self):
        self.open_effort()
        self.terminal.send(b"\x03")
        self.assertEqual(self.terminal.finish(), 130)
        self.assertFalse(self.argv_file.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
