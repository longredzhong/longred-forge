import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.forge import planner, publisher


class PlanningTests(unittest.TestCase):
    def test_resource_change_selects_parent_recipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe = Path(tmp) / 'recipe.yaml'
            with patch.object(planner.subprocess, 'run', return_value=Mock(stdout='recipes/mihomo/install.py\n')), patch.object(Path, 'is_file', return_value=True):
                self.assertEqual(planner.changed_recipes('base'), [Path('recipes/mihomo/recipe.yaml')])

    def test_core_change_selects_all_recipes(self):
        with patch.object(planner.subprocess, 'run', return_value=Mock(stdout='scripts/forge/builder.py\n')):
            self.assertEqual(planner.changed_recipes('base'), sorted(Path('recipes').glob('*/recipe.yaml')))

    def test_cli_change_selects_manager_recipe(self):
        with patch.object(planner.subprocess, 'run', return_value=Mock(stdout='cli/longred_skills/__init__.py\n')):
            self.assertEqual(planner.changed_recipes('base'), [Path('recipes/longred-skills/recipe.yaml')])

    def test_docs_only_change_is_empty(self):
        with patch.object(planner.subprocess, 'run', return_value=Mock(stdout='README.md\n')):
            self.assertEqual(planner.changed_recipes('base'), [])

    def test_supported_platforms_exclude_osx64(self):
        self.assertEqual(planner.PLATFORMS, ('linux-64', 'linux-aarch64', 'osx-arm64', 'win-64'))
        self.assertNotIn('osx-64', planner.PLATFORMS)

    def test_upload_retries_without_post_upload_polling(self):
        artifact = planner.Artifact('tool', '1', 'h_0', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / artifact.filename
            path.write_bytes(b'package')
            with patch.dict('os.environ', {'PREFIX_TOKEN': 'test-token'}), patch.object(publisher, 'indexed', return_value=False) as indexed, patch.object(publisher.subprocess, 'run', side_effect=[Mock(returncode=1), Mock(returncode=0)]) as run, patch.object(publisher.time, 'sleep'):
                self.assertEqual(publisher.publish(artifact, path, 'example'), 'published')
                self.assertEqual(run.call_count, 2)
                self.assertEqual(indexed.call_count, 1)
                self.assertEqual(len(indexed.call_args.args[2]), 64)

    def test_upload_fails_after_retry_exhaustion(self):
        artifact = planner.Artifact('tool', '1', 'h_0', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / artifact.filename
            path.write_bytes(b'package')
            with patch.dict('os.environ', {'PREFIX_TOKEN': 'test-token'}), patch.object(publisher, 'indexed', return_value=False), patch.object(publisher.subprocess, 'run', return_value=Mock(returncode=1)) as run, patch.object(publisher.time, 'sleep'):
                with self.assertRaisesRegex(RuntimeError, 'Upload failed'):
                    publisher.publish(artifact, path, 'example')
                self.assertEqual(run.call_count, 3)


if __name__ == '__main__':
    unittest.main()
