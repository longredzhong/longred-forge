import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.forge import builder, planner, publisher


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.fingerprint = patch.object(builder, 'recipe_fingerprint', return_value='recipe-hash')
        self.fingerprint.start()
        self.addCleanup(self.fingerprint.stop)

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
            output = Path(tmp) / 'output'
            (output / 'linux-64').mkdir(parents=True)
            (output / 'linux-64/tool-1-h_1.conda').touch()
            with patch.object(builder, 'render', return_value=[artifact]), patch.object(builder, 'publish') as publish:
                with self.assertRaisesRegex(RuntimeError, 'Expected artifact missing'):
                    builder.build_recipe(Path('recipe.yaml'), 'linux-64', 'example', True, False, False, output)
                publish.assert_not_called()

    def test_rebuild_removes_stale_same_identity(self):
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            path = artifact.path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('stale')
            def rebuild(*args, **kwargs):
                self.assertFalse(path.exists())
                path.write_text('fresh')
            with patch.object(builder, 'render', return_value=[artifact]), patch.object(builder.subprocess, 'run', side_effect=rebuild):
                result = builder.build_recipe(Path('recipe.yaml'), 'linux-64', 'example', False, True, False, output)
            self.assertEqual(result['status'], 'built')
            self.assertEqual(path.read_text(), 'fresh')

    def test_receipted_remote_package_skips_build(self):
        import hashlib
        import json
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            path = artifact.path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'artifact')
            digest = hashlib.sha256(b'artifact').hexdigest()
            receipt = builder.receipt_path(artifact, output)
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps(
                {'filename': artifact.filename, 'sha256': digest, 'recipe_sha256': 'recipe-hash'}))
            with patch.object(builder, 'render', return_value=[artifact]), \
                    patch.object(builder, 'indexed', return_value=True), \
                    patch.object(builder.subprocess, 'run') as run:
                self.assertEqual(builder.build_recipe(Path('recipe.yaml'), 'linux-64', 'example', False, True, True, output)['status'], 'already_exists')
            run.assert_not_called()

    def test_adopt_existing_receipt_records_channel_digest(self):
        import json
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output' / 'output'
            with patch.object(builder, 'render', return_value=[artifact]), \
                    patch.object(builder, 'indexed', return_value=True), \
                    patch.object(builder, 'remote_digest', return_value='f' * 64) as remote, \
                    patch.object(builder.subprocess, 'run') as run:
                result = builder.build_recipe(Path('recipe.yaml'), 'linux-64', 'example', False, True, True, output, adopt_existing=True)
            self.assertEqual(result['status'], 'already_exists')
            run.assert_not_called()
            remote.assert_called_once_with(artifact, 'example')
            receipt = builder.receipt_path(artifact, output)
            data = json.loads(receipt.read_text(encoding='utf-8'))
            self.assertEqual(data, {'filename': artifact.filename, 'sha256': 'f' * 64, 'recipe_sha256': 'recipe-hash'})

    def test_receiptless_remote_package_is_rebuilt_and_verified(self):
        import json
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            path = artifact.path(output)
            path.parent.mkdir(parents=True, exist_ok=True)

            def rebuild(*args, **kwargs):
                path.write_bytes(b'fresh')

            with patch.object(builder, 'render', return_value=[artifact]), \
                    patch.object(builder, 'indexed', return_value=True) as indexed, \
                    patch.object(builder.subprocess, 'run', side_effect=rebuild) as run, \
                    patch.object(builder, 'publish', return_value='already_exists') as publish:
                result = builder.build_recipe(Path('recipe.yaml'), 'linux-64', 'example', True, True, True, output)
            self.assertEqual(result['status'], 'already_exists')
            run.assert_called_once()
            publish.assert_called_once()
            # The identity check plus the post-build digest verification both hit the index.
            self.assertGreaterEqual(indexed.call_count, 2)
            # The fresh build leaves a receipt at the committed location.
            data = json.loads(builder.receipt_path(artifact, output).read_text(encoding='utf-8'))
            import hashlib
            self.assertEqual(data['sha256'], hashlib.sha256(b'fresh').hexdigest())
            self.assertEqual(data['recipe_sha256'], 'recipe-hash')

    def test_receiptless_rebuild_with_digest_mismatch_fails_loudly(self):
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            path = artifact.path(output)
            path.parent.mkdir(parents=True, exist_ok=True)

            def rebuild(*args, **kwargs):
                path.write_bytes(b'different-recipe')

            def indexed_check(artifact_arg, channel, sha256=None):
                if sha256 is None:
                    return True
                raise RuntimeError(f'Channel checksum differs for {artifact_arg.filename}; increment build.number')

            with patch.object(builder, 'render', return_value=[artifact]), \
                    patch.object(builder, 'indexed', side_effect=indexed_check), \
                    patch.object(builder.subprocess, 'run', side_effect=rebuild) as run, \
                    patch.object(builder, 'publish') as publish:
                with self.assertRaisesRegex(RuntimeError, 'increment build.number'):
                    builder.build_recipe(Path('recipe.yaml'), 'linux-64', 'example', True, True, True, output)
            run.assert_called_once()
            publish.assert_not_called()

    def test_upload_only_rejects_unreceipted_artifact(self):
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            path = artifact.path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'unverified')
            with patch.object(builder, 'render', return_value=[artifact]), patch.object(builder, 'publish') as publish:
                with self.assertRaisesRegex(RuntimeError, 'Build receipt missing'):
                    builder.build_recipe(Path('recipe.yaml'), 'linux-64', 'example', True, False, False, output)
                publish.assert_not_called()

    def test_recipe_change_invalidates_upload_receipt(self):
        import hashlib
        import json
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            path = artifact.path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'old-build')
            receipt = builder.receipt_path(artifact, output)
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps({'filename': artifact.filename, 'sha256': hashlib.sha256(b'old-build').hexdigest(), 'recipe_sha256': 'different-recipe'}))
            with patch.object(builder, 'render', return_value=[artifact]), patch.object(builder, 'publish') as publish:
                with self.assertRaisesRegex(RuntimeError, 'receipt missing or mismatched'):
                    builder.build_recipe(Path('recipe.yaml'), 'linux-64', 'example', True, False, False, output)
                publish.assert_not_called()

    def test_index_checksum_collision_is_not_success(self):
        artifact = planner.Artifact('tool', '1', 'h_2', 'linux-64')
        response = Mock(status_code=200)
        response.json.return_value = {'packages.conda': {artifact.filename: {'sha256': 'wrong'}}}
        with patch.object(publisher.HTTPClient, 'json', return_value=response.json.return_value) as request:
            with self.assertRaisesRegex(RuntimeError, 'increment build.number'):
                publisher.indexed(artifact, 'example', 'expected')
            self.assertIn('?verify=', request.call_args.args[0])


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_ignores_checkout_line_endings(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe_dir = Path(tmp) / 'tool'
            recipe_dir.mkdir()
            recipe = recipe_dir / 'recipe.yaml'
            recipe.write_bytes(b'package:\n  name: tool\n  version: 1\n')
            (recipe_dir / 'install.py').write_bytes(b'print("hello")\n')
            expected = builder.recipe_fingerprint(recipe)
            for path in recipe_dir.iterdir():
                path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
            self.assertEqual(builder.recipe_fingerprint(recipe), expected)


if __name__ == '__main__':
    unittest.main()
