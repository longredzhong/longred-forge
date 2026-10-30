import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.forge import builder, planner, publisher


class BuilderTests(unittest.TestCase):
    def test_exact_rendered_identity_includes_build_number(self):
        item = {'recipe': {'package': {'name': 'tool', 'version': '1'}, 'build': {'string': 'habc_2'}}, 'build_configuration': {'target_platform': 'linux-64'}}
        import json
        with patch.object(planner.subprocess, 'run', return_value=Mock(stdout=json.dumps([item]))):
            result = planner.render(Path('recipe.yaml'), 'linux-64')
        self.assertEqual(result[0].filename, 'tool-1-habc_2.conda')

    def test_unsupported_and_noarch_do_not_publish(self):
        for artifacts in ([], [planner.Artifact('tool', '1', 'h_0', 'noarch')]):
            with patch.object(builder, 'render', return_value=artifacts), patch.object(builder, 'publish') as publish:
                result = builder.build_recipe(Path('recipe.yaml'), 'win-64', 'example', True, True, True)
                self.assertEqual(result['status'], 'unsupported')
                publish.assert_not_called()

    def test_old_build_number_cannot_be_uploaded(self):
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / 'linux-64').mkdir()
            (output / 'linux-64/tool-1-h_1.conda').touch()
            with patch.object(builder, 'render', return_value=[artifact]), patch.object(builder, 'publish') as publish:
                with self.assertRaisesRegex(RuntimeError, 'Expected artifact missing'):
                    builder.build_recipe(Path('recipe.yaml'), 'linux-64', 'example', True, False, False, output)
                publish.assert_not_called()

    def test_rebuild_removes_stale_same_identity(self):
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            path = artifact.path(output)
            path.parent.mkdir()
            path.write_text('stale')
            def rebuild(*args, **kwargs):
                self.assertFalse(path.exists())
                path.write_text('fresh')
            with patch.object(builder, 'render', return_value=[artifact]), patch.object(builder.subprocess, 'run', side_effect=rebuild):
                result = builder.build_recipe(Path('recipe.yaml'), 'linux-64', 'example', False, True, False, output)
            self.assertEqual(result['status'], 'built')
            self.assertEqual(path.read_text(), 'fresh')

    def test_exact_remote_package_skips_build(self):
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        with patch.object(builder, 'render', return_value=[artifact]), patch.object(builder, 'indexed', return_value=True), patch.object(builder.subprocess, 'run') as run:
            self.assertEqual(builder.build_recipe(Path('recipe.yaml'), 'linux-64', 'example', False, True, True)['status'], 'already_exists')
            run.assert_not_called()

    def test_upload_only_rejects_unreceipted_artifact(self):
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            path = artifact.path(output)
            path.parent.mkdir()
            path.write_bytes(b'unverified')
            with patch.object(builder, 'render', return_value=[artifact]), patch.object(builder, 'publish') as publish:
                with self.assertRaisesRegex(RuntimeError, 'Build receipt missing'):
                    builder.build_recipe(Path('recipe.yaml'), 'linux-64', 'example', True, False, False, output)
                publish.assert_not_called()

    def test_index_checksum_collision_is_not_success(self):
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        response = Mock(status_code=200)
        response.json.return_value = {'packages.conda': {artifact.filename: {'sha256': 'wrong'}}}
        with patch.object(publisher.httpx, 'get', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'increment build.number'):
                publisher.indexed(artifact, 'example', 'expected')


if __name__ == '__main__':
    unittest.main()
