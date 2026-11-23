import io
import os
from contextlib import redirect_stdout
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml  # type: ignore

from scripts import build, update
from scripts.forge import publisher
from scripts.forge.planner import Artifact


class PublishingTests(unittest.TestCase):
    def test_index_delay_and_timeout_remain_failure_without_matching_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Artifact('example', '1.0', 'h0_0', 'linux-64')
            path = Path(tmp) / artifact.filename
            path.write_bytes(b'package')
            with patch.dict(os.environ, {'PREFIX_TOKEN': 'test'}), \
                 patch.object(publisher, 'INDEX_POLL_ATTEMPTS', 2), \
                 patch.object(publisher.time, 'sleep') as sleep, \
                 patch.object(publisher.subprocess, 'run') as upload, \
                 patch.object(publisher, 'indexed', side_effect=[False, False, False, True]) as indexed:
                upload.return_value.returncode = 0
                self.assertEqual(publisher.publish(artifact, path, 'example'), 'published')
                self.assertEqual(sleep.call_count, 2)
                self.assertTrue(all(call.args[2] for call in indexed.call_args_list))
            with patch.dict(os.environ, {'PREFIX_TOKEN': 'test'}), \
                 patch.object(publisher, 'INDEX_POLL_ATTEMPTS', 2), \
                 patch.object(publisher.time, 'sleep'), \
                 patch.object(publisher.subprocess, 'run') as upload, \
                 patch.object(publisher, 'indexed', return_value=False):
                upload.return_value.returncode = 0
                with self.assertRaisesRegex(RuntimeError, 'not indexed'):
                    publisher.publish(artifact, path, 'example')

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

    def test_batch_wait_for_index_polls_all_pending_together(self):
        first = Artifact('first', '1.0', 'h0_0', 'linux-64')
        second = Artifact('second', '1.0', 'h1_0', 'win-64')
        calls = []

        def fake_indexed(artifact, channel, sha256):
            calls.append((artifact.filename, sha256))
            # First becomes visible on attempt 0; second becomes visible on attempt 1.
            if artifact.filename == first.filename:
                return True
            return sum(1 for name, _ in calls if name == second.filename) >= 2

        with patch.object(publisher, 'INDEX_POLL_ATTEMPTS', 2), \
             patch.object(publisher.time, 'sleep') as sleep, \
             patch.object(publisher, 'indexed', side_effect=fake_indexed):
            publisher.wait_for_index([(first, 'a' * 64), (second, 'b' * 64)], 'example')
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual([name for name, _ in calls], [first.filename, second.filename, second.filename])

    def test_no_build_publish_batches_uploads_before_verifying_index(self):
        recipes = [Path('recipes/a/recipe.yaml'), Path('recipes/b/recipe.yaml')]
        events = []

        def fake_build_recipe(recipe, target, channel, upload, build_flag, skip, adopt_existing=False, pending_uploads=None):
            self.assertTrue(upload)
            self.assertFalse(build_flag)
            self.assertIsNotNone(pending_uploads)
            artifact = Artifact(recipe.parent.name, '1.0', 'h0_0', target)
            events.append(('upload', target, artifact.filename))
            outcome = {'path': f'output/{target}/{artifact.filename}', 'status': 'uploaded'}
            pending_uploads.append((artifact, 'c' * 64, outcome))
            return {'recipe': str(recipe), 'platform': target, 'status': 'uploaded', 'artifacts': [outcome]}

        def fake_wait(pending, channel):
            events.append(('verify', [a.filename for a, _ in pending], channel))

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / 'publish-results.json'
            with patch('sys.argv', ['build.py', '--no-build', '--skip-existing', '--report', str(report), '--target-platforms', 'linux-64', 'win-64']), \
                 patch.object(build, 'find_recipes', return_value=recipes), \
                 patch.object(build, 'load_dotenv', return_value={}), \
                 patch.object(build, 'build_recipe', side_effect=fake_build_recipe), \
                 patch.object(build, 'wait_for_index', side_effect=fake_wait), \
                 redirect_stdout(io.StringIO()):
                build.main()
            import json
            saved = json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual(len(events), 5)
        self.assertEqual(events[-1][0], 'verify')
        self.assertEqual(len(events[-1][1]), 4)
        self.assertTrue(all(item['status'] == 'published' for item in saved))
        self.assertTrue(all(art['status'] == 'published' for item in saved for art in item['artifacts']))

    def test_missing_publish_credentials_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe = Path(tmp) / 'recipe.yaml'
            recipe.write_text('context: {version: "1.0"}\npackage: {name: example}\n')
            with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'required for publishing'):
                    publisher.publish(Artifact('example', '1.0', 'h0_0', 'linux-64'), recipe, 'example')


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
                with patch.object(update.subprocess, 'run'):
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
