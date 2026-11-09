import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import skills_publish
from scripts.forge import builder
from scripts.forge.planner import Artifact


class ExistingReceiptTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = Path.cwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.chdir, self.previous_cwd)
        self.recipe = Path('skill-recipes/demo/recipe.yaml')
        self.recipe.parent.mkdir(parents=True)
        self.recipe.write_text('source: {}\n', encoding='utf-8')
        self.artifact = Artifact('agent-skill-demo', '0.0.1', 'h_0', 'noarch')
        self.path = self.artifact.path(Path('output'))
        self.path.parent.mkdir(parents=True)
        self.digest = hashlib.sha256(b'local').hexdigest()

    def write_receipt(self, *, with_artifact=True):
        self.path.with_suffix('.receipt.json').write_text(json.dumps({
            'filename': self.artifact.filename,
            'sha256': self.digest,
            'recipe_sha256': builder.recipe_fingerprint(self.recipe),
        }), encoding='utf-8')
        if with_artifact:
            self.path.write_bytes(b'local')

    def publish(self, remote_sha):
        records = {self.artifact.filename: {'sha256': remote_sha}}
        with patch.dict(os.environ, {'PREFIX_TOKEN': 'test'}, clear=True), \
             patch.object(skills_publish, 'load_dotenv', return_value={}), \
             patch.object(skills_publish, 'channel_records', return_value=records), \
             patch.object(skills_publish, 'render', return_value=[self.artifact]), \
             patch.object(skills_publish.subprocess, 'run') as upload:
            skills_publish.main()
            upload.assert_not_called()

    def test_publisher_compares_existing_remote_checksum_to_receipt(self):
        self.write_receipt()
        self.publish(self.digest)
        with self.assertRaisesRegex(RuntimeError, 'Channel checksum differs'):
            self.publish('0' * 64)

    def test_publisher_compares_receipt_without_local_artifact(self):
        self.write_receipt(with_artifact=False)
        with self.assertRaisesRegex(RuntimeError, 'Channel checksum differs'):
            self.publish('0' * 64)

    def test_publisher_skips_existing_package_without_receipt(self):
        self.publish('0' * 64)

    def test_publisher_rejects_recipe_or_artifact_mismatched_with_receipt(self):
        self.write_receipt()
        self.path.write_bytes(b'tampered')
        with self.assertRaisesRegex(RuntimeError, 'receipt mismatch'):
            self.publish(self.digest)
        self.path.write_bytes(b'local')
        self.recipe.write_text('source: {}\n# changed\n', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'receipt mismatch'):
            self.publish(self.digest)

    def test_builder_checks_remote_checksum_when_receipt_exists(self):
        self.write_receipt()
        def indexed(artifact, channel, sha256=None):
            if sha256 and sha256 != '0' * 64:
                raise RuntimeError('Channel checksum differs')
            return True
        with patch.object(builder, 'render', return_value=[self.artifact]), \
             patch.object(builder, 'indexed', side_effect=indexed), \
             patch.object(builder.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Channel checksum differs'):
                builder.build_recipe(self.recipe, 'linux-64', 'example', False, True, True)
            run.assert_not_called()

    def test_builder_skips_after_matching_receipt_checksum(self):
        self.write_receipt(with_artifact=False)
        with patch.object(builder, 'render', return_value=[self.artifact]), \
             patch.object(builder, 'indexed', return_value=True) as indexed, \
             patch.object(builder.subprocess, 'run') as run:
            result = builder.build_recipe(self.recipe, 'linux-64', 'example', False, True, True)
            self.assertEqual(result['status'], 'already_exists')
            self.assertEqual(indexed.call_count, 2)
            indexed.assert_called_with(self.artifact, 'example', self.digest)
            run.assert_not_called()

    def test_builder_skips_existing_package_without_receipt(self):
        with patch.object(builder, 'render', return_value=[self.artifact]), \
             patch.object(builder, 'indexed', return_value=True) as indexed, \
             patch.object(builder.subprocess, 'run') as run:
            result = builder.build_recipe(self.recipe, 'linux-64', 'example', False, True, True)
            self.assertEqual(result['status'], 'already_exists')
            indexed.assert_called_once_with(self.artifact, 'example')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
