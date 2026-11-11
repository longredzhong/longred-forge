import base64
import copy
import hashlib
import io
import json
import os
import tempfile
import tarfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import longred_skills, skills_publish, skills_update
from scripts.forge import builder
from scripts.forge.planner import Artifact

DEMO_SKILL = b'---\nname: demo\ndescription: A useful skill\n---\nbody\n'


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.tree_sha = 'b' * 40
        self.commit = 'a' * 40
        self.license_sha = 'c' * 40
        self.truncated = False
        self.extra = []

    def json(self, url, headers):
        self.calls.append(url)
        if '/git/ref/' in url:
            return {'object': {'sha': self.commit}}
        if '/git/commits/' in url:
            return {'tree': {'sha': 'e' * 40}}
        if '/git/trees/' in url:
            return {'sha': 'e' * 40, 'truncated': self.truncated, 'tree': [
                {'path': 'LICENSE', 'type': 'blob', 'sha': self.license_sha},
                {'path': 'skills/demo', 'type': 'tree', 'sha': self.tree_sha},
                {'path': 'skills/demo/SKILL.md', 'type': 'blob', 'sha': 'd' * 40}, *self.extra]}
        if '/git/blobs/' in url:
            data = DEMO_SKILL
            return {'encoding': 'base64', 'size': len(data), 'content': base64.b64encode(data).decode()}
        raise AssertionError(url)

    def sha256(self, url):
        self.calls.append(url)
        return 'f' * 64

    def read(self, url, consume, headers=None, timeout=None):
        import httpx
        self.calls.append(url)
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as tar:
            info = tarfile.TarInfo('skills-commit/skills/demo/SKILL.md')
            info.size = len(DEMO_SKILL)
            tar.addfile(info, io.BytesIO(DEMO_SKILL))
        return consume(httpx.Response(200, content=output.getvalue()))


class SkillsForgeTests(unittest.TestCase):
    def setUp(self):
        self.config = {'version': 1, 'repositories': [{'repository': 'example/skills', 'branch': 'main',
            'license': 'MIT', 'license_file': 'LICENSE', 'skills': [
                {'path': 'skills/demo', 'name': 'demo', 'package': 'agent-skill-example-demo'}]}]}
        self.client = FakeGitHub()

    def check(self, lock=None):
        return skills_update.check(self.config, lock or {'version': 1, 'skills': {}}, self.client, {})

    def test_commit_only_change_does_not_rebuild_but_tree_change_does(self):
        lock, recipes = self.check()
        self.assertEqual(len(recipes), 1)
        self.assertEqual(lock['skills']['agent-skill-example-demo']['version'], '0.0.1')
        self.client.commit = 'e' * 40
        same, recipes = self.check(lock)
        self.assertEqual(recipes, {})
        self.assertEqual(same, lock)
        self.client.tree_sha = 'f' * 40
        newer, recipes = self.check(lock)
        self.assertEqual(newer['skills']['agent-skill-example-demo']['version'], '0.0.2')
        self.assertEqual(recipes['agent-skill-example-demo']['source']['rev'], 'e' * 40)

    def test_repository_cache_avoids_tree_lookup_and_respects_lock_changes(self):
        cache = {}
        lock, _ = skills_update.check(self.config, {'version': 1, 'skills': {}}, self.client, {}, cache=cache)
        self.client.calls.clear()
        same, recipes = skills_update.check(self.config, lock, self.client, {}, cache=cache)
        self.assertEqual((same, recipes), (lock, {}))
        self.assertEqual(len(self.client.calls), 1)
        self.client.calls.clear()
        altered = copy.deepcopy(lock)
        altered['skills']['agent-skill-example-demo']['tree'] = 'f' * 40
        skills_update.check(self.config, altered, self.client, {}, cache=cache)
        self.assertGreaterEqual(len(self.client.calls), 2)

    def test_repository_cache_expires_after_one_day(self):
        cache = {}
        with patch.object(skills_update.time, 'time', return_value=100000):
            lock, _ = skills_update.check(self.config, {'version': 1, 'skills': {}}, self.client, {}, cache=cache)
        self.client.calls.clear()
        with patch.object(skills_update.time, 'time', return_value=100000 + 86400):
            skills_update.check(self.config, lock, self.client, {}, cache=cache)
        self.assertEqual(len(self.client.calls), 2)

    def test_incomplete_tree_and_symlinks_are_rejected(self):
        self.client.truncated = True
        with self.assertRaisesRegex(RuntimeError, 'truncated'):
            self.check()
        self.client.truncated = False
        self.client.extra = [{'path': 'skills/demo/escape', 'mode': '120000'}]
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.check()

    def test_root_skill_requires_archive_and_checks_complete_tree(self):
        repo = self.config['repositories'][0]
        repo['skills'][0]['path'] = '.'
        with self.assertRaisesRegex(ValueError, 'Root skills require'):
            self.check()
        repo['archive'] = True
        self.client.extra = [{'path': 'SKILL.md', 'type': 'blob', 'sha': 'd' * 40}]
        lock, recipes = self.check()
        self.assertEqual(lock['skills']['agent-skill-example-demo']['tree'], 'e' * 40)
        self.assertIn('$SRC_DIR/./.', recipes['agent-skill-example-demo']['build']['script'])
        self.client.extra.append({'path': 'escape', 'mode': '120000'})
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.check(lock)

    def test_license_change_requires_review(self):
        lock, _ = self.check()
        self.client.license_sha = 'f' * 40
        with self.assertRaisesRegex(ValueError, 'License changed'):
            self.check(lock)
        newer, recipes = skills_update.check(self.config, lock, self.client, {}, True)
        self.assertEqual(newer['skills']['agent-skill-example-demo']['version'], '0.0.2')
        self.assertTrue(recipes)

    def test_unlicensed_skill_without_license_file(self):
        repository = self.config['repositories'][0]
        repository['license'] = 'UNLICENSED'
        del repository['license_file']
        lock, recipes = self.check()
        recipe = recipes['agent-skill-example-demo']
        self.assertIsNone(lock['skills']['agent-skill-example-demo']['license_blob'])
        self.assertNotIn('license_file', recipe['about'])
        self.assertNotIn('share/licenses', recipe['build']['script'])
        repository['license'] = 'MIT'
        with self.assertRaisesRegex(ValueError, 'License file required'):
            self.check()

    def test_additional_license_changes_bump_version_and_invalidate_cache_and_receipt(self):
        item = self.config['repositories'][0]['skills'][0]
        item['additional_license_files'] = ['THIRD-PARTY-NOTICES.txt']
        with tempfile.TemporaryDirectory() as tmp:
            recipe_dir = Path(tmp) / item['package']
            recipe_dir.mkdir()
            notice = recipe_dir / 'THIRD-PARTY-NOTICES.txt'
            notice.write_text('original notice', encoding='utf-8')
            with patch.object(skills_update, 'SKILL_RECIPES_DIR', Path(tmp)):
                cache = {}
                lock, recipes = skills_update.check(self.config, {'version': 1, 'skills': {}}, self.client, {}, cache=cache)
                recipe = recipes[item['package']]
                self.assertIn('"$RECIPE_DIR/THIRD-PARTY-NOTICES.txt"', recipe['build']['script'])
                self.assertIn(f'share/licenses/{item["package"]}/THIRD-PARTY-NOTICES.txt', recipe['tests'][0]['package_contents']['files'])
                recipe_path = recipe_dir / 'recipe.yaml'
                recipe_path.write_text('source: {}\n', encoding='utf-8')
                receipt = builder.recipe_fingerprint(recipe_path)
                notice.write_text('corrected notice', encoding='utf-8')
                self.assertNotEqual(builder.recipe_fingerprint(recipe_path), receipt)
                newer, recipes = skills_update.check(self.config, lock, self.client, {}, cache=cache)
                self.assertEqual(newer['skills'][item['package']]['version'], '0.0.2')
                self.assertIn(item['package'], recipes)

    def test_additional_license_rejects_unsafe_or_missing_file(self):
        item = self.config['repositories'][0]['skills'][0]
        with tempfile.TemporaryDirectory() as tmp, patch.object(skills_update, 'SKILL_RECIPES_DIR', Path(tmp)):
            for names in (['../escape'], ['LICENSE'], ['MISSING.txt'], [''], 'not-a-list'):
                with self.subTest(names=names), self.assertRaises(ValueError):
                    item['additional_license_files'] = names
                    self.check()

    def test_archive_mode_pins_commit_and_checksum(self):
        self.config['repositories'][0]['archive'] = True
        lock, recipes = self.check()
        recipe = recipes['agent-skill-example-demo']
        self.assertEqual(recipe['source']['sha256'], 'f' * 64)
        self.assertIn(lock['skills']['agent-skill-example-demo']['commit'], recipe['source']['url'])

    def test_bundle_validates_and_packages_each_child(self):
        item = self.config['repositories'][0]['skills'][0]
        item.update({'path': 'skills', 'name': 'bundle', 'bundle': True})
        original = self.client.json
        def response(url, headers):
            data = original(url, headers)
            if '/git/trees/' in url:
                data['tree'].append({'path': 'skills', 'type': 'tree', 'sha': 'e' * 40})
            return data
        self.client.json = response
        lock, recipes = self.check()
        recipe = recipes['agent-skill-example-demo']
        self.assertEqual(lock['skills']['agent-skill-example-demo']['identity'][-1], 'bundle')
        self.assertEqual(recipe['tests'][0]['package_contents']['files'], ['share/agent-skills/demo/SKILL.md'])
        self.assertIn('"$SRC_DIR/skills/." "$PREFIX/share/agent-skills/"', recipe['build']['script'])

    def test_pinned_commit_does_not_follow_branch(self):
        self.config['repositories'][0]['commit'] = 'e' * 40
        lock, _ = self.check()
        self.assertEqual(lock['skills']['agent-skill-example-demo']['commit'], 'e' * 40)
        self.assertTrue(all('/git/ref/' not in url for url in self.client.calls))

    def test_locked_source_tree_change_cannot_reuse_old_content_hash(self):
        self.config['repositories'][0]['skills'][0]['lock_hash'] = hashlib.sha256(b'SKILL.md' + DEMO_SKILL).hexdigest()
        lock, _ = self.check()
        self.client.tree_sha = 'f' * 40
        with self.assertRaisesRegex(ValueError, 'verify and update the lock hash'):
            self.check(lock)

    def test_first_import_rejects_wrong_lock_hash_without_mutating_cache(self):
        self.config['repositories'][0]['skills'][0]['lock_hash'] = '0' * 64
        cache = {'existing': {'value': 'unchanged'}}
        with self.assertRaisesRegex(ValueError, 'Source lock hash mismatch'):
            skills_update.check(self.config, {'version': 1, 'skills': {}}, self.client, {}, cache=cache)
        self.assertEqual(cache, {'existing': {'value': 'unchanged'}})

    def test_npx_hash_uses_node_localecompare_not_byte_sort(self):
        files = {'B.md': b'B', 'a.md': b'a', 'A.md': b'A', 'b.md': b'b'}
        expected = hashlib.sha256(b'a.mdaA.mdAb.mdbB.mdB').hexdigest()
        with patch.dict(os.environ, {'LC_ALL': 'C.UTF-8'}):
            self.assertEqual(skills_update.npx_skill_hash(files), expected)

    def test_one_archive_download_verifies_multiple_locked_skills(self):
        item = self.config['repositories'][0]['skills'][0]
        item['lock_hash'] = hashlib.sha256(b'SKILL.md' + DEMO_SKILL).hexdigest()
        self.config['repositories'][0]['skills'].append({**item, 'package': 'agent-skill-example-other'})
        lock, recipes = self.check()
        self.assertEqual(len(recipes), 2)
        self.assertEqual(len([url for url in self.client.calls if '/archive/' in url]), 1)
        self.assertEqual(lock['skills']['agent-skill-example-other']['source_lock_verified'], item['lock_hash'])

    def test_locked_archive_rejects_traversal_links_and_size_overflow(self):
        import httpx
        def make_archive(name, link=False):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode='w:gz') as tar:
                item = tarfile.TarInfo(name)
                if link:
                    item.type = tarfile.SYMTYPE
                    item.linkname = '../../outside'
                    tar.addfile(item)
                else:
                    item.size = 1
                    tar.addfile(item, io.BytesIO(b'x'))
            return output.getvalue()
        class ArchiveClient:
            def __init__(self, content):
                self.content = content
            def read(self, url, consume, **kwargs):
                return consume(httpx.Response(200, content=self.content))
        for content in (make_archive('root/../outside'), make_archive('root/skills/demo/link', True)):
            with self.subTest(content=content), self.assertRaises(ValueError):
                skills_update.download_locked_archive(ArchiveClient(content), 'https://example.com', {'skills/demo'})
        with patch.object(skills_update, 'MAX_ARCHIVE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'compressed size'):
                skills_update.download_locked_archive(ArchiveClient(make_archive('root/skills/demo/file')), 'https://example.com', {'skills/demo'})

    def test_existing_unverified_lock_rechecks_without_bumping_version(self):
        item = self.config['repositories'][0]['skills'][0]
        item['lock_hash'] = hashlib.sha256(b'SKILL.md' + DEMO_SKILL).hexdigest()
        lock, _ = self.check()
        self.assertEqual(lock['skills'][item['package']]['source_lock_verified'], item['lock_hash'])
        del lock['skills'][item['package']]['source_lock_verified']
        cache = {'example/skills': {'commit': self.client.commit, 'checked_at': 1}}
        updated, recipes = skills_update.check(self.config, lock, self.client, {}, cache=cache)
        self.assertEqual(recipes, {})
        self.assertEqual(updated['skills'][item['package']]['version'], '0.0.1')
        self.assertEqual(updated['skills'][item['package']]['source_lock_verified'], item['lock_hash'])

    def test_dependency_change_releases_new_package_with_runtime_dependencies(self):
        lock, _ = self.check()
        self.config['repositories'][0]['skills'][0]['dependencies'] = ['agent-skill-example-other ==0.0.1']
        self.config['repositories'][0]['skills'].append({'path': 'skills/demo', 'name': 'demo', 'package': 'agent-skill-example-other'})
        newer, recipes = self.check(lock)
        self.assertEqual(newer['skills']['agent-skill-example-demo']['version'], '0.0.2')
        self.assertEqual(recipes['agent-skill-example-demo']['requirements']['run'], ['agent-skill-example-other ==0.0.1'])

    def test_shell_metacharacters_and_removed_packages_are_rejected(self):
        bad = copy.deepcopy(self.config)
        bad['repositories'][0]['skills'][0]['path'] = 'skills/$(touch-bad)'
        with self.assertRaises(ValueError):
            skills_update.check(bad, {'version': 1, 'skills': {}}, self.client, {})
        with self.assertRaisesRegex(ValueError, 'Removed packages'):
            self.check({'version': 1, 'skills': {'agent-skill-removed': {}}})

    def test_project_sync_preserves_existing_user_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / '.pixi/envs/default/share/agent-skills/demo'
            source.mkdir(parents=True)
            (source / 'SKILL.md').write_text('skill')
            longred_skills.sync(root, 'default', 'codex')
            linked = root / '.codex/skills/demo'
            self.assertTrue(linked.is_symlink())
            self.assertEqual((linked / 'SKILL.md').read_text(), 'skill')
            longred_skills.sync(root, 'default', 'codex')
            linked.unlink()
            linked.mkdir()
            (linked / 'SKILL.md').write_text('user data')
            with self.assertRaises(FileExistsError):
                longred_skills.sync(root, 'default', 'codex')
            self.assertEqual((linked / 'SKILL.md').read_text(), 'user data')

    def test_local_recipe_source_changes_invalidate_build_receipt_fingerprint(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            recipe_dir = root / 'recipe'
            recipe_dir.mkdir()
            source = root / 'source'
            source.mkdir()
            (source / 'code.py').write_text('first')
            recipe = recipe_dir / 'recipe.yaml'
            recipe.write_text('source:\n  path: ../source\n')
            original = builder.recipe_fingerprint(recipe)
            (source / 'code.py').write_text('second')
            self.assertNotEqual(builder.recipe_fingerprint(recipe), original)

    def test_batch_publish_uploads_only_receipted_artifacts_and_checks_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = Path.cwd()
            try:
                os.chdir(tmp)
                recipes = [Path('skill-recipes/first/recipe.yaml'), Path('skill-recipes/second/recipe.yaml')]
                artifacts = [Artifact('first', '1', 'h_0', 'noarch'), Artifact('second', '1', 'h_0', 'noarch')]
                for recipe, artifact in zip(recipes, artifacts):
                    recipe.parent.mkdir(parents=True)
                    recipe.write_text('source: {}\n')
                    path = artifact.path(Path('output'))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(artifact.name.encode())
                    receipt = {'filename': artifact.filename, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                               'recipe_sha256': 'valid'}
                    path.with_suffix('.receipt.json').write_text(json.dumps(receipt))
                with patch.dict(os.environ, {'PREFIX_API_KEY': 'test'}), \
                        patch.object(skills_publish, 'load_dotenv', return_value={}), \
                        patch.object(skills_publish, 'render', side_effect=[[artifacts[0]], [artifacts[1]]]), \
                        patch.object(skills_publish, 'recipe_fingerprint', return_value='valid'), \
                        patch.object(skills_publish, 'channel_records', side_effect=[{}, {
                            a.filename: {'sha256': hashlib.sha256(a.name.encode()).hexdigest()} for a in artifacts}]) as index, \
                        patch.object(skills_publish.subprocess, 'run', return_value=Mock(returncode=0)) as upload:
                    skills_publish.main()
                self.assertEqual(upload.call_count, 1)
                self.assertEqual(upload.call_args.args[0][-2:], [str(a.path(Path('output'))) for a in artifacts])
                self.assertEqual(index.call_count, 2)
            finally:
                os.chdir(old_cwd)

    def test_pixi_index_confirmation_requires_channel_filename_and_sha(self):
        artifact = Artifact('example', '1', 'h_0', 'noarch')
        digest = 'a' * 64
        url = 'https://prefix.dev/longredzhong/longred-skills-forge/noarch/' + artifact.filename
        entry = {'fn': artifact.filename, 'url': url, 'sha256': digest}
        pending = [(artifact, Path('package.conda'), digest)]
        with patch.object(skills_publish.subprocess, 'run', return_value=Mock(returncode=0, stdout=json.dumps({'noarch': [entry]}))):
            self.assertEqual(skills_publish.pixi_indexed(pending), {artifact.filename})
        entry['url'] = 'https://example.org/other.conda'
        with patch.object(skills_publish.subprocess, 'run', return_value=Mock(returncode=0, stdout=json.dumps({'noarch': [entry]}))):
            self.assertEqual(skills_publish.pixi_indexed(pending), set())
        entry['url'], entry['sha256'] = url, 'b' * 64
        with patch.object(skills_publish.subprocess, 'run', return_value=Mock(returncode=0, stdout=json.dumps({'noarch': [entry]}))):
            with self.assertRaisesRegex(RuntimeError, 'checksum differs'):
                skills_publish.pixi_indexed(pending)


if __name__ == '__main__':
    unittest.main()
