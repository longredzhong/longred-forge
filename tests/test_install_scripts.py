"""Verify recipe install scripts make upstream binaries executable in the prefix."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RECIPES = Path(__file__).resolve().parents[1] / 'recipes'


class InstallScriptTests(unittest.TestCase):
    def assert_installed_executable(self, recipe, unix_names):
        is_windows = sys.platform == 'win32'
        binaries = [f'{name}.exe' if is_windows else name for name in unix_names]
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / 'prefix'
            src = Path(tmp) / 'src'
            src.mkdir()
            for binary in binaries:
                # Simulate an upstream archive member that lacks the exec bit.
                (src / binary).write_bytes(b'#!/bin/sh\nexit 0\n')
                (src / binary).chmod(0o644)
            env = dict(os.environ, PREFIX=str(prefix))
            result = subprocess.run(
                [sys.executable, str(RECIPES / recipe / 'install.py')],
                cwd=src, env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            bin_dir = prefix / ('Scripts' if is_windows else 'bin')
            for binary in binaries:
                installed = bin_dir / binary
                self.assertTrue(installed.is_file(), f'missing {installed}')
                if sys.platform != 'win32':
                    self.assertNotEqual(
                        os.stat(installed).st_mode & 0o111, 0,
                        f'no exec bit on {installed}; upstream archives may lack it',
                    )

    def test_obscura_installs_both_binaries_executable(self):
        self.assert_installed_executable('obscura', ['obscura', 'obscura-worker'])

    def test_opencode_installs_binary_executable(self):
        self.assert_installed_executable('opencode', ['opencode'])


if __name__ == '__main__':
    unittest.main()
