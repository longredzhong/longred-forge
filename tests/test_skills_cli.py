"""Verify add does not hide conflicts or partial Pixi changes."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cli'))
import longred_skills


class SkillsCLITests(unittest.TestCase):
    def test_existing_skill_conflict_fails_before_pixi_mutates_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / '.pixi/envs/default/share/agent-skills/example'
            src.mkdir(parents=True)
            (src / 'SKILL.md').write_text('installed')
            user = root / '.codex/skills/example'
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
            user = root / '.codex/skills/new-skill'
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
            (root / '.codex').write_text('user data')
            with patch.object(Path, 'cwd', return_value=root), \
                    patch('sys.argv', ['longred-skills', 'add', 'agent-skill-example']), \
                    patch.object(longred_skills.subprocess, 'run') as run:
                with self.assertRaisesRegex(FileExistsError, 'configuration directory conflicts'):
                    longred_skills.main()
            run.assert_not_called()
            self.assertEqual((root / '.codex').read_text(), 'user data')


if __name__ == '__main__':
    unittest.main()
