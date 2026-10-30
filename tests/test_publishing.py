import io
import os
from contextlib import redirect_stdout
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml  # type: ignore

from scripts import build, update


class PublishingTests(unittest.TestCase):
    def test_failed_recipe_does_not_stop_remaining_targets(self):
        recipes = [Path('recipes/broken/recipe.yaml'), Path('recipes/healthy/recipe.yaml')]
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / 'summary'
            with patch('sys.argv', ['build.py', '--target-platforms', 'linux-64', 'win-64']), \
                 patch.object(build, 'find_recipes', return_value=recipes), \
                 patch.object(build, 'load_dotenv', return_value={}), \
                 patch.object(build, 'build_recipe', side_effect=[RuntimeError('broken'), None, None, None]) as cook, \
                 patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(summary)}), \
                 redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    build.main()
            self.assertEqual(result.exception.code, 1)
            self.assertEqual(cook.call_count, 4)
            self.assertIn('broken', summary.read_text())

    def test_successful_build_batch_exits_normally(self):
        with patch('sys.argv', ['build.py']), \
             patch.object(build, 'find_recipes', return_value=[Path('recipe.yaml')]), \
             patch.object(build, 'load_dotenv', return_value={}), \
             patch.object(build, 'build_recipe'):
            build.main()

    def test_missing_publish_credentials_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe = Path(tmp) / 'recipe.yaml'
            recipe.write_text('context: {version: "1.0"}\npackage: {name: example}\n')
            with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'required for publishing'):
                    build.build_recipe(recipe, 'linux-64', 'example', True, False, False)


class UpdaterTests(unittest.TestCase):
    def recipe(self, directory):
        path = Path(directory) / 'recipe.yaml'
        path.write_text('context: {version: "1.0"}\nabout: {repository: "https://github.com/example/tool"}\nsource:\n- url: "https://github.com/example/tool/releases/download/v${{ version }}/tool.tar.gz"\n  sha256: ' + 'a' * 64 + '\n')
        return path

    def release(self, version='1.0', digest=None):
        return {'tag_name': 'v' + version, 'assets': [{'name': 'tool.tar.gz', 'digest': digest or 'sha256:' + 'b' * 64}]}

    def test_same_version_skips_unless_explicit_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.recipe(tmp)
            original = path.read_bytes()
            with patch.object(update, 'get_latest_release', return_value=self.release()):
                update.update_single_recipe(str(path), None, None, {}, None, True, False)
                self.assertEqual(path.read_bytes(), original)
                update.update_single_recipe(str(path), None, None, {}, None, True, False, True)
            self.assertEqual(yaml.safe_load(path.read_text())['source'][0]['sha256'], 'b' * 64)

    def test_unresolved_assets_never_write_new_version_with_old_hash(self):
        for failure in ('missing', 'download', 'invalid'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                path = self.recipe(tmp)
                original = path.read_bytes()
                release = self.release('2.0', 'sha256:invalid' if failure == 'invalid' else None)
                if failure == 'missing':
                    release['assets'] = []
                with patch.object(update, 'get_latest_release', return_value=release):
                    if failure == 'download':
                        with patch.object(update, 'compute_sha_for_asset', side_effect=RuntimeError('offline')):
                            with self.assertRaises(RuntimeError):
                                update.update_single_recipe(str(path), None, None, {}, None, True, False)
                    else:
                        with self.assertRaises(RuntimeError):
                            update.update_single_recipe(str(path), None, None, {}, None, True, False)
                self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
