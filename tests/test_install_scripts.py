"""Verify recipe install scripts make upstream binaries executable in the prefix."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RECIPES = Path(__file__).resolve().parents[1] / 'recipes'


def load_install_module(recipe):
    path = RECIPES / recipe / 'install.py'
    spec = importlib.util.spec_from_file_location(f'test_{recipe}_install', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    def test_deepseek_harness_installs_scoped_package_and_shims(self):
        module = load_install_module('deepseek-harness')
        for os_name, cpu in (('linux', 'x64'), ('win32', 'x64')):
            with self.subTest(os_name=os_name, cpu=cpu), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                src = root / 'src'
                prefix = root / 'prefix'
                (src / 'lib' / 'types').mkdir(parents=True)
                (src / 'lib' / 'bin.js').write_text('#!/usr/bin/env node\n', encoding='utf-8')
                (src / 'lib' / 'bin.js.map').write_text('{}', encoding='utf-8')
                (src / 'lib' / 'types' / 'bin.d.ts').write_text('export {};\n', encoding='utf-8')
                (src / 'package.json').write_text(json.dumps({
                    'name': '@deepseek-ai/dsh',
                    'bin': {'dsh': 'lib/bin.js'},
                }), encoding='utf-8')
                for scaffold in ('conda_build.sh', 'conda_build.bat', 'conda_build.log', 'build_env.sh', 'build_env.bat', '.source_info.json'):
                    (src / scaffold).write_text('scaffold', encoding='utf-8')

                def fake_npm_run(cmd, cwd=None, check=False):
                    self.assertIn(f'--os={os_name}', cmd)
                    self.assertIn(f'--cpu={cpu}', cmd)
                    self.assertIn('--ignore-scripts', cmd)
                    dep = Path(cwd) / 'node_modules' / 'dep'
                    dep.mkdir(parents=True)
                    (dep / 'index.js').write_text('export const ok = true;\n', encoding='utf-8')
                    (dep / 'index.js.map').write_text('{}', encoding='utf-8')
                    (dep / 'index.d.ts').write_text('export const ok: boolean;\n', encoding='utf-8')
                    (dep / 'index.d.cts').write_text('export const ok: boolean;\n', encoding='utf-8')
                    (dep / 'index.d.mts').write_text('export const ok: boolean;\n', encoding='utf-8')

                old_cwd = os.getcwd()
                try:
                    os.chdir(src)
                    with patch.dict(os.environ, {'PREFIX': str(prefix)}), \
                            patch.object(sys, 'argv', ['install.py', os_name, cpu]), \
                            patch.object(module.shutil, 'which', return_value='npm'), \
                            patch.object(module.subprocess, 'run', side_effect=fake_npm_run):
                        module.main()
                finally:
                    os.chdir(old_cwd)

                if os_name == 'win32':
                    pkg_dir = prefix / 'node_modules' / '@deepseek-ai' / 'dsh'
                    shim = prefix / 'Scripts' / 'dsh.cmd'
                    self.assertTrue(shim.is_file())
                    self.assertIn(r'%~dp0..\node_modules\@deepseek-ai\dsh\lib\bin.js', shim.read_text(encoding='ascii'))
                else:
                    pkg_dir = prefix / 'lib' / 'node_modules' / '@deepseek-ai' / 'dsh'
                    shim = prefix / 'bin' / 'dsh'
                    self.assertTrue(shim.is_file())
                    self.assertIn('../lib/node_modules/@deepseek-ai/dsh/lib/bin.js', shim.read_text(encoding='ascii'))
                    if sys.platform != 'win32':
                        self.assertNotEqual(os.stat(shim).st_mode & 0o111, 0)
                self.assertTrue((pkg_dir / 'node_modules' / 'dep' / 'index.js').is_file())
                for removed in (
                    pkg_dir / 'lib' / 'bin.js.map',
                    pkg_dir / 'lib' / 'types',
                    pkg_dir / 'node_modules' / 'dep' / 'index.js.map',
                    pkg_dir / 'node_modules' / 'dep' / 'index.d.ts',
                    pkg_dir / 'node_modules' / 'dep' / 'index.d.cts',
                    pkg_dir / 'node_modules' / 'dep' / 'index.d.mts',
                ):
                    self.assertFalse(removed.exists(), f'expected pruned path to be removed: {removed}')
                for scaffold in ('conda_build.sh', 'conda_build.bat', 'conda_build.log', 'build_env.sh', 'build_env.bat', '.source_info.json'):
                    self.assertFalse((pkg_dir / scaffold).exists())

    def test_deepseek_harness_rejects_escaping_bin_target(self):
        module = load_install_module('deepseek-harness')
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / 'prefix' / 'lib' / 'node_modules' / '@deepseek-ai' / 'dsh'
            target_dir.mkdir(parents=True)
            (Path(tmp) / 'outside.js').write_text('evil', encoding='utf-8')
            with self.assertRaises(SystemExit):
                module.write_bin_shim('linux', str(Path(tmp) / 'prefix'), ['@deepseek-ai', 'dsh'], 'dsh', 'lib/../../outside.js', str(target_dir))


if __name__ == '__main__':
    unittest.main()
