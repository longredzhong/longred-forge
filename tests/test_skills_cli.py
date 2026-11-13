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
    def test_install_in_git_worktree_uses_its_own_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            worktree = Path(tmp) / 'worktree'
            root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'pixi.toml').write_text(
                '[workspace]\nname = "example"\n'
                '[tool.longred-skills]\nagents = ["agents", "claude"]\nenvironment = "dev"\n'
            )
            subprocess.run(['git', '-C', str(root), 'add', 'pixi.toml'], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test',
                            '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'init'], check=True)
            subprocess.run(['git', '-C', str(root), 'worktree', 'add', '-qb', 'test-worktree', str(worktree)], check=True)
            nested = worktree / 'src'
            nested.mkdir()
            skill = worktree / '.pixi/envs/dev/share/agent-skills/example'

            def pixi(command, **kwargs):
                self.assertEqual(command, ['pixi', 'install', '--environment', 'dev', '--locked'])
                self.assertEqual(kwargs['cwd'], worktree)
                skill.mkdir(parents=True, exist_ok=True)
                (skill / 'SKILL.md').write_text('skill')

            with patch.object(Path, 'cwd', return_value=nested), \
                    patch('sys.argv', ['pixi-longred-skills', 'install', '--locked']), \
                    patch.object(longred_skills.subprocess, 'run', side_effect=pixi):
                longred_skills.main()
                longred_skills.main()
            for agent in ('agents', 'claude'):
                link = worktree / f'.{agent}/skills/example'
                self.assertTrue(link.is_symlink())
                self.assertTrue(link.samefile(skill))
                self.assertFalse(os.path.isabs(os.readlink(link)))
            self.assertFalse((root / '.agents').exists())

    def test_install_finds_pixi_workspace_above_unrelated_pyproject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text('[workspace]\nname = "example"\n')
            nested = root / 'nested'
            nested.mkdir()
            (nested / 'pyproject.toml').write_text('[tool.longred-skills]\nagents = ["claude"]\n')
            skill = root / '.pixi/envs/default/share/agent-skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')
            with patch.object(Path, 'cwd', return_value=nested), \
                    patch('sys.argv', ['longred-skills', 'install']), \
                    patch.object(longred_skills.subprocess, 'run') as run:
                longred_skills.main()
            self.assertEqual(run.call_args.kwargs['cwd'], root)
            self.assertTrue((root / '.agents/skills/example').samefile(skill))
            self.assertFalse((nested / '.claude').exists())

    def test_prune_preserves_custom_alias_into_skill_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / '.pixi/envs/default/share/agent-skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')
            alias = root / '.agents/skills/my-alias'
            alias.parent.mkdir(parents=True)
            alias.symlink_to(os.path.relpath(skill, alias.parent))
            longred_skills.sync(root, 'default', 'agents')
            self.assertTrue(alias.samefile(skill))

    def test_install_failure_does_not_sync_or_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text('[workspace]\nname = "example"\n')
            target = root / '.agents/skills/stale'
            target.parent.mkdir(parents=True)
            target.symlink_to('../../.pixi/envs/default/share/agent-skills/stale')
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'install']), \
                    patch.object(longred_skills.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'pixi')):
                with self.assertRaises(subprocess.CalledProcessError):
                    longred_skills.main()
            self.assertTrue(target.is_symlink())

    def test_sync_checks_all_agents_before_creating_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / '.pixi/envs/default/share/agent-skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')
            conflict = root / '.claude/skills/example'
            conflict.mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                longred_skills.sync(root, 'default', 'agents,claude')
            self.assertFalse((root / '.agents/skills/example').exists())

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

            # Claude has its own distinct directory
            with patch.object(Path, 'cwd', return_value=subdir), \
                    patch('sys.argv', ['longred-skills', 'sync', '--agent', 'claude']):
                longred_skills.main()
            self.assertTrue((root / '.claude/skills/example').samefile(skill))

            # Codex conforms to .agents/skills specification and aliases to agents
            with patch.object(Path, 'cwd', return_value=subdir), \
                    patch('sys.argv', ['longred-skills', 'sync', '--agent', 'codex']):
                longred_skills.main()
            self.assertTrue((root / '.agents/skills/example').samefile(skill))
            self.assertFalse((root / '.codex').exists())

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

    def test_multi_agent_all_links_all_canonical_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text('[workspace]\nname = "test"\n')
            skill = root / '.pixi/envs/default/share/agent-skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'sync', '--agent', 'all']):
                longred_skills.main()
            for agent, path in longred_skills.CANONICAL_AGENTS.items():
                link = root / path.local / 'example'
                self.assertTrue(link.is_symlink(), f"Expected symlink for {agent}")
                self.assertTrue(link.samefile(skill))
            # Verify no redundant alias directories were created
            self.assertFalse((root / '.codex').exists())
            self.assertFalse((root / '.cline').exists())

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

    def test_alias_resolution_and_deduplication(self):
        self.assertEqual(longred_skills.resolve_agents('codex'), ['agents'])
        self.assertEqual(longred_skills.resolve_agents('cline'), ['agents'])
        self.assertEqual(longred_skills.resolve_agents('gemini'), ['agents'])
        self.assertEqual(longred_skills.resolve_agents('opencode'), ['agents'])
        # Deduplication
        self.assertEqual(longred_skills.resolve_agents('agents,codex,cline'), ['agents'])
        # All returns canonical agents only
        self.assertEqual(
            longred_skills.resolve_agents('all'),
            list(longred_skills.CANONICAL_AGENTS.keys())
        )

    def test_scope_aware_paths(self):
        root = Path('/mock/workspace')
        home = Path('/mock/home')
        # Local paths
        self.assertEqual(longred_skills.get_agent_dir(root, 'windsurf', is_global=False), root / '.windsurf/skills')
        self.assertEqual(longred_skills.get_agent_dir(root, 'copilot', is_global=False), root / '.github/skills')
        self.assertEqual(longred_skills.get_agent_dir(root, 'agents', is_global=False), root / '.agents/skills')
        # Global paths
        self.assertEqual(longred_skills.get_agent_dir(home, 'windsurf', is_global=True), home / '.codeium/windsurf/skills')
        self.assertEqual(longred_skills.get_agent_dir(home, 'copilot', is_global=True), home / '.github/skills')
        self.assertEqual(longred_skills.get_agent_dir(home, 'claude', is_global=True), home / '.claude/skills')

    def test_pixi_toml_config_reading_and_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text(
                '[workspace]\nname = "test"\n'
                '[tool.longred-skills]\n'
                'agents = ["claude", "cursor"]\n'
                'environment = "testenv"\n'
            )
            cfg = longred_skills.read_config(root)
            self.assertEqual(cfg.get('agents'), ['claude', 'cursor'])
            self.assertEqual(cfg.get('environment'), 'testenv')

            skill = root / '.pixi/envs/testenv/share/agent-skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')

            # When -a and -e are omitted, uses config defaults
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'sync']):
                longred_skills.main()
            self.assertTrue((root / '.claude/skills/example').is_symlink())
            self.assertTrue((root / '.cursor/skills/example').is_symlink())
            self.assertFalse((root / '.agents/skills/example').exists())

            # CLI argument overrides config
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'sync', '-a', 'copilot']):
                longred_skills.main()
            self.assertTrue((root / '.github/skills/example').is_symlink())

    def test_clean_managed_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text('[workspace]\nname = "test"\n')
            source = root / '.pixi/envs/default/share/agent-skills/example'
            source.mkdir(parents=True)
            (source / 'SKILL.md').write_text('skill')

            target = root / '.agents/skills'
            target.mkdir(parents=True)
            managed_link = target / 'example'
            managed_link.symlink_to(os.path.relpath(source, managed_link.parent), target_is_directory=True)

            # User external skill
            external = root / 'custom-skill'
            external.mkdir()
            user_link = target / 'custom-skill'
            user_link.symlink_to(os.path.relpath(external, user_link.parent), target_is_directory=True)

            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'clean']):
                longred_skills.main()

            self.assertFalse(managed_link.exists())
            self.assertTrue(user_link.is_symlink())
            self.assertTrue(user_link.exists())

    def test_switch_environments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text('[workspace]\nname = "test"\n')
            env1_skill = root / '.pixi/envs/env1/share/agent-skills/skill1'
            env1_skill.mkdir(parents=True)
            (env1_skill / 'SKILL.md').write_text('skill1')

            env2_skill = root / '.pixi/envs/env2/share/agent-skills/skill2'
            env2_skill.mkdir(parents=True)
            (env2_skill / 'SKILL.md').write_text('skill2')

            # Initial sync from env1
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'sync', '-e', 'env1']):
                longred_skills.main()
            self.assertTrue((root / '.agents/skills/skill1').is_symlink())

            # Switch to env2
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'switch', 'env2']):
                longred_skills.main()

            self.assertFalse((root / '.agents/skills/skill1').exists())
            self.assertTrue((root / '.agents/skills/skill2').is_symlink())

    def test_hook_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text('[workspace]\nname = "test"\n')
            # Empty environment - hook install should quietly exit 0
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'hook', 'install']):
                longred_skills.main()
            self.assertFalse((root / '.agents').exists())

            # With skills present
            skill = root / '.pixi/envs/default/share/agent-skills/example'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('skill')

            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'hook', 'install']):
                longred_skills.main()
            self.assertTrue((root / '.agents/skills/example').is_symlink())

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

            target = root / '.agents/skills'
            target.mkdir(parents=True)
            dangling = target / 'stale-skill'
            dangling.symlink_to(os.path.relpath(source / 'stale-skill', dangling.parent), target_is_directory=True)

            external = root / 'my-local-skill'
            external.mkdir()
            (external / 'SKILL.md').write_text('local')
            user_link = target / 'my-local-skill'
            user_link.symlink_to(os.path.relpath(external, user_link.parent), target_is_directory=True)

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
        self.assertEqual(
            longred_skills.resolve_package_name('agent-skill-vercel-labs-find-skills', repodata=fake_repodata),
            'agent-skill-vercel-labs-find-skills'
        )
        self.assertEqual(
            longred_skills.resolve_package_name('find-skills', repodata=fake_repodata),
            'agent-skill-vercel-labs-find-skills'
        )
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

    def test_pyproject_workspace_root_and_metadata_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pyproject.toml').write_text(
                '[project]\nname = "test"\nversion = "0.1.0"\n'
                '[tool.pixi.workspace]\nchannels = ["conda-forge"]\n'
                '[tool.pixi.workspace.metadata.longred-skills]\n'
                'agents = ["claude", "cursor"]\n'
                'environment = "myenv"\n'
            )
            # project_root correctly finds root from a subdirectory
            subdir = root / 'src' / 'module'
            subdir.mkdir(parents=True)
            self.assertEqual(longred_skills.project_root(subdir), root)

            # read_config reads from tool.pixi.workspace.metadata.longred-skills
            cfg = longred_skills.read_config(root)
            self.assertEqual(cfg.get('agents'), ['claude', 'cursor'])
            self.assertEqual(cfg.get('environment'), 'myenv')

            # Test manifest path detection
            self.assertEqual(longred_skills.get_manifest_path(root), root / 'pyproject.toml')

    def test_init_pyproject_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pyproject.toml').write_text(
                '[project]\nname = "test"\nversion = "0.1.0"\n'
                '[tool.pixi.workspace]\nchannels = ["conda-forge"]\n'
                '[tool.pixi.tasks]\n'
            )
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'init']):
                longred_skills.main()

            content = (root / 'pyproject.toml').read_text()
            self.assertIn('[tool.longred-skills]', content)
            self.assertIn('setup = "pixi install --locked && longred-skills hook install"', content)
            self.assertIn('skills-sync = "longred-skills sync"', content)
            self.assertIn('skills-clean = "longred-skills clean"', content)
            self.assertIn('skills-manage = "longred-skills manage"', content)

            gitignore = (root / '.gitignore').read_text()
            self.assertIn('.agents/skills/', gitignore)
            self.assertIn('.claude/skills/', gitignore)
            self.assertIn('.cursor/skills/', gitignore)

    def test_init_pixi_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pixi.toml').write_text(
                '[workspace]\nname = "test"\nchannels = ["conda-forge"]\n'
                '[tasks]\n'
            )
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'init']):
                longred_skills.main()

            content = (root / 'pixi.toml').read_text()
            self.assertIn('[tool.longred-skills]', content)
            self.assertIn('setup = "pixi install --locked && longred-skills hook install"', content)
            self.assertIn('skills-sync = "longred-skills sync"', content)

    def test_pyproject_add_and_remove_uses_manifest_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pyproject.toml').write_text(
                '[project]\nname = "test"\nversion = "0.1.0"\n'
                '[tool.pixi.workspace]\nchannels = ["conda-forge"]\n'
            )
            manifest = root / 'pyproject.toml'
            subdir = root / 'src'
            subdir.mkdir()

            executed_cmds = []

            def fake_run(cmd, **kwargs):
                executed_cmds.append(cmd)
                if cmd[1] == 'add':
                    skill = root / '.pixi/envs/default/share/agent-skills/example'
                    skill.mkdir(parents=True)
                    (skill / 'SKILL.md').write_text('skill')

            with patch.object(Path, 'cwd', return_value=subdir), \
                    patch('sys.argv', ['longred-skills', 'add', 'agent-skill-example']), \
                    patch.object(longred_skills.subprocess, 'run', side_effect=fake_run):
                longred_skills.main()

            # Verify --manifest-path was passed pointing to pyproject.toml
            add_cmd = next(c for c in executed_cmds if c[1] == 'add')
            self.assertIn('--manifest-path', add_cmd)
            self.assertEqual(add_cmd[add_cmd.index('--manifest-path') + 1], str(manifest))
            self.assertTrue((root / '.agents/skills/example').is_symlink())


if __name__ == '__main__':
    unittest.main()
