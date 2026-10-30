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

    def test_docs_only_change_is_empty(self):
        with patch.object(planner.subprocess, 'run', return_value=Mock(stdout='README.md\n')):
            self.assertEqual(planner.changed_recipes('base'), [])

    def test_upload_retries_then_verifies_digest(self):
        artifact = planner.Artifact('tool', '1', 'h_0', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / artifact.filename
            path.write_bytes(b'package')
            with patch.dict('os.environ', {'PREFIX_TOKEN': 'test-token'}), patch.object(publisher, 'indexed', side_effect=[False, False, True]) as indexed, patch.object(publisher.subprocess, 'run', side_effect=[Mock(returncode=1), Mock(returncode=0)]) as run, patch.object(publisher.time, 'sleep'):
                self.assertEqual(publisher.publish(artifact, path, 'example'), 'published')
                self.assertEqual(run.call_count, 2)
                self.assertEqual(len(indexed.call_args.args[2]), 64)

    def test_upload_never_succeeds_without_index_confirmation(self):
        artifact = planner.Artifact('tool', '1', 'h_0', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / artifact.filename
            path.write_bytes(b'package')
            with patch.dict('os.environ', {'PREFIX_TOKEN': 'test-token'}), patch.object(publisher, 'indexed', return_value=False), patch.object(publisher.subprocess, 'run', return_value=Mock(returncode=0)), patch.object(publisher.time, 'sleep'):
                with self.assertRaisesRegex(RuntimeError, 'not indexed'):
                    publisher.publish(artifact, path, 'example')


if __name__ == '__main__':
    unittest.main()
