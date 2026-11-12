"""Verify add does not hide conflicts or partial Pixi changes."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cli'))
import longred_skills


class SkillsCLITests(unittest.TestCase):
    def test_sync_from_subdirectory_uses_workspace_and_default_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text('[workspace]\nname = "example"\n')
            subdir = root / 'src' / 'nested'
            subdir.mkdir(parents=True)
            skill = root / '.pixi/envs/default/share/agent-skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')
            with patch.object(Path, 'cwd', return_value=subdir), \
                    patch('sys.argv', ['longred-skills', 'sync']):
                longred_skills.main()
                longred_skills.main()
            link = root / '.agents/skills/example'
            self.assertTrue(link.is_symlink())
            self.assertTrue(link.samefile(skill))
            self.assertFalse((subdir / '.agents').exists())

    def test_pyproject_workspace_and_explicit_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pyproject.toml').write_text('[tool.pixi.workspace]\nname = "example"\n')
            subdir = root / 'src'
            subdir.mkdir()
            skill = root / '.pixi/envs/default/share/agent-skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')
            for agent in ('codex', 'claude'):
                with self.subTest(agent=agent), patch.object(Path, 'cwd', return_value=subdir), \
                        patch('sys.argv', ['longred-skills', 'sync', '--agent', agent]):
                    longred_skills.main()
                self.assertTrue((root / f'.{agent}/skills/example').samefile(skill))

    def test_add_from_subdirectory_runs_pixi_at_workspace_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text('[workspace]\nname = "example"\n')
            subdir = root / 'src'
            subdir.mkdir()
            def pixi(command, **kwargs):
                self.assertEqual(kwargs['cwd'], root)
                if command[1] == 'add':
                    skill = root / '.pixi/envs/default/share/agent-skills/example'
                    skill.mkdir(parents=True)
                    (skill / 'SKILL.md').write_text('skill')
            with patch.object(Path, 'cwd', return_value=subdir), \
                    patch('sys.argv', ['longred-skills', 'add', 'agent-skill-example']), \
                    patch.object(longred_skills.subprocess, 'run', side_effect=pixi):
                longred_skills.main()
            self.assertTrue((root / '.agents/skills/example').is_symlink())

    def test_global_targets_use_persistent_workspace_from_any_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            workspace = home / '.local/share/longred-skills/default'
            skill = workspace / '.pixi/envs/default/share/agent-skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')
            elsewhere = home / 'project'
            elsewhere.mkdir()
            for agent in ('agents', 'claude'):
                with self.subTest(agent=agent), patch.object(Path, 'home', return_value=home), \
                        patch.object(Path, 'cwd', return_value=elsewhere), \
                        patch('sys.argv', ['longred-skills', 'sync', '--global', '--agent', agent]):
                    longred_skills.main()
                    longred_skills.main()
                self.assertTrue((home / f'.{agent}/skills/example').samefile(skill))
            self.assertFalse((elsewhere / '.agents').exists())

    def test_global_conflict_fails_before_workspace_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / '.agents').write_text('existing')
            with patch.object(Path, 'home', return_value=home), \
                    patch('sys.argv', ['longred-skills', 'add', '--global', 'agent-skill-example']), \
                    patch.object(longred_skills.subprocess, 'run') as run:
                with self.assertRaises(FileExistsError):
                    longred_skills.main()
            run.assert_not_called()
            self.assertFalse((home / '.local').exists())

    def test_list_rejects_invalid_environment(self):
        with patch('sys.argv', ['longred-skills', 'list', '-e', '../outside']):
            with self.assertRaisesRegex(ValueError, 'Invalid environment'):
                longred_skills.main()

    def test_existing_skill_conflict_fails_before_pixi_mutates_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / '.pixi/envs/default/share/agent-skills/example'
            src.mkdir(parents=True)
            (src / 'SKILL.md').write_text('installed')
            user = root / '.agents/skills/example'
            user.mkdir(parents=True)
            (user / 'SKILL.md').write_text('user data')
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'add', 'agent-skill-example']), \
                    patch.object(longred_skills.subprocess, 'run') as run:
                with self.assertRaisesRegex(FileExistsError, 'Existing path conflicts'):
                    longred_skills.main()
            run.assert_not_called()
            self.assertEqual((user / 'SKILL.md').read_text(), 'user data')

    def test_newly_installed_skill_conflict_reports_pixi_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user = root / '.agents/skills/new-skill'
            user.mkdir(parents=True)
            (user / 'SKILL.md').write_text('user data')
            def pixi(*args, **kwargs):
                if args[0][1] == 'add':
                    src = root / '.pixi/envs/default/share/agent-skills/new-skill'
                    src.mkdir(parents=True)
                    (src / 'SKILL.md').write_text('package data')
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'add', 'agent-skill-example']), \
                    patch.object(longred_skills.subprocess, 'run', side_effect=pixi) as run:
                with self.assertRaisesRegex(RuntimeError, 'Pixi added .*manifest, lockfile, and environment may have changed'):
                    longred_skills.main()
            self.assertEqual(run.call_count, 2)
            self.assertEqual((user / 'SKILL.md').read_text(), 'user data')

    def test_pixi_failure_reports_possible_channel_change(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(Path, 'cwd', return_value=Path(tmp)), \
                patch('sys.argv', ['longred-skills', 'add', 'agent-skill-example']), \
                patch.object(longred_skills.subprocess, 'run', side_effect=[None, subprocess.CalledProcessError(1, 'pixi')]):
            with self.assertRaisesRegex(RuntimeError, 'project channel may already have changed'):
                longred_skills.main()

    def test_non_directory_agent_root_fails_before_pixi(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.agents').write_text('user data')
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'add', 'agent-skill-example']), \
                    patch.object(longred_skills.subprocess, 'run') as run:
                with self.assertRaisesRegex(FileExistsError, 'configuration directory conflicts'):
                    longred_skills.main()
            run.assert_not_called()
            self.assertEqual((root / '.agents').read_text(), 'user data')

    def test_multi_agent_all_links_all_registered_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text('[workspace]\nname = "test"\n')
            skill = root / '.pixi/envs/default/share/agent-skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'sync', '--agent', 'all']):
                longred_skills.main()
            for agent, path in longred_skills.AGENTS.items():
                link = root / path / 'example'
                self.assertTrue(link.is_symlink(), f"Expected symlink for {agent}")
                self.assertTrue(link.samefile(skill))

    def test_comma_separated_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text('[workspace]\nname = "test"\n')
            skill = root / '.pixi/envs/default/share/agent-skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'sync', '--agent', 'claude,cursor']):
                longred_skills.main()
            self.assertTrue((root / '.claude/skills/example').is_symlink())
            self.assertTrue((root / '.cursor/skills/example').is_symlink())
            self.assertFalse((root / '.agents/skills/example').exists())

    def test_remove_uninstalls_and_prunes_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text('[workspace]\nname = "test"\n')
            skill = root / '.pixi/envs/default/share/agent-skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')
            link = root / '.agents/skills/example'
            link.parent.mkdir(parents=True)
            link.symlink_to(os.path.relpath(skill, link.parent), target_is_directory=True)
            link_claude = root / '.claude/skills/example'
            link_claude.parent.mkdir(parents=True)
            link_claude.symlink_to(os.path.relpath(skill, link_claude.parent), target_is_directory=True)

            def pixi_remove(cmd, **kwargs):
                self.assertEqual(cmd, ['pixi', 'remove', '-e', 'default', 'agent-skill-example'])
                # simulate pixi deleting the package folder
                (skill / 'SKILL.md').unlink()
                skill.rmdir()

            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'remove', 'agent-skill-example']), \
                    patch.object(longred_skills.subprocess, 'run', side_effect=pixi_remove):
                longred_skills.main()

            self.assertFalse(link.exists())
            self.assertFalse(link.is_symlink())
            self.assertFalse(link_claude.exists())
            self.assertFalse(link_claude.is_symlink())

    def test_dangling_symlinks_pruned_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text('[workspace]\nname = "test"\n')
            source = root / '.pixi/envs/default/share/agent-skills'
            source.mkdir(parents=True)

            # Dangling link pointing to non-existent skill in .pixi
            target = root / '.agents/skills'
            target.mkdir(parents=True)
            dangling = target / 'stale-skill'
            dangling.symlink_to(os.path.relpath(source / 'stale-skill', dangling.parent), target_is_directory=True)

            # User-created external symlink pointing outside pixi
            external = root / 'my-local-skill'
            external.mkdir()
            (external / 'SKILL.md').write_text('local')
            user_link = target / 'my-local-skill'
            user_link.symlink_to(os.path.relpath(external, user_link.parent), target_is_directory=True)

            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'sync', '--prune']):
                # When source is empty, sync with allow_empty won't crash if prune is handled
                longred_skills.prune_dangling(root, root, 'default', ['agents'])

            self.assertFalse(dangling.is_symlink())
            self.assertTrue(user_link.is_symlink())
            self.assertTrue(user_link.exists())

    def test_friendly_name_resolution(self):
        fake_repodata = {
            'packages.conda': {
                'p1': {'name': 'agent-skill-vercel-labs-find-skills', 'version': '0.0.1'},
                'p2': {'name': 'agent-skill-tiangolo-library-skills', 'version': '0.0.1'},
            }
        }
        # Direct canonical name
        self.assertEqual(
            longred_skills.resolve_package_name('agent-skill-vercel-labs-find-skills', repodata=fake_repodata),
            'agent-skill-vercel-labs-find-skills'
        )
        # Suffix matching
        self.assertEqual(
            longred_skills.resolve_package_name('find-skills', repodata=fake_repodata),
            'agent-skill-vercel-labs-find-skills'
        )
        # Ambiguous matching
        with self.assertRaisesRegex(ValueError, 'Ambiguous skill name'):
            longred_skills.resolve_package_name('skills', repodata=fake_repodata)

    def test_info_installed_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / '.pixi/envs/default/share/agent-skills/demo'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('---\nname: Demo Skill\ndescription: A demo skill\n---\nPrompt body\n')
            link = root / '.agents/skills/demo'
            link.parent.mkdir(parents=True)
            link.symlink_to(os.path.relpath(skill, link.parent), target_is_directory=True)

            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'info', 'demo']), \
                    patch('builtins.print') as mock_print:
                longred_skills.main()
                printed = ' '.join(call.args[0] for call in mock_print.call_args_list if call.args)
                self.assertIn('Skill:        demo', printed)
                self.assertIn('Display Name: Demo Skill', printed)
                self.assertIn('Description:  A demo skill', printed)
                self.assertIn('Agents:       agents', printed)

    def test_list_verbose_shows_linked_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / '.pixi/envs/default/share/agent-skills/demo'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')
            link = root / '.agents/skills/demo'
            link.parent.mkdir(parents=True)
            link.symlink_to(os.path.relpath(skill, link.parent), target_is_directory=True)

            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'list', '-v']), \
                    patch('builtins.print') as mock_print:
                longred_skills.main()
                printed = [call.args[0] for call in mock_print.call_args_list if call.args]
                self.assertIn('demo (linked: agents)', printed)


if __name__ == '__main__':
    unittest.main()
