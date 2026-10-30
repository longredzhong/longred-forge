"""Execute builds using original recipe resources and exact rendered outputs."""

import hashlib
import json
import subprocess
from pathlib import Path

from .planner import render
from .publisher import indexed, publish


def build_recipe(recipe_yaml_path: Path, target_platform: str, channel: str,
                 upload_flag: bool, build_flag: bool, skip_existing: bool,
                 output: Path = Path('output')) -> dict:
    label = str(recipe_yaml_path)
    print(f'::group::{recipe_yaml_path.parent.name}-{target_platform}', flush=True)
    try:
        artifacts = render(recipe_yaml_path, target_platform)
        artifacts = [a for a in artifacts if a.platform != 'noarch' or target_platform == 'linux-64']
        if not artifacts:
            return {'recipe': label, 'platform': target_platform, 'status': 'unsupported', 'artifacts': []}
        outcomes = []
        for artifact in artifacts:
            if skip_existing and indexed(artifact, channel):
                outcomes.append({'path': str(artifact.path(output)), 'status': 'already_exists'})
                continue
            path = artifact.path(output)
            if build_flag:
                # Never trust a pre-existing artifact with the same identity but different recipe contents.
                if path.exists():
                    path.unlink()
                subprocess.run([
                    'rattler-build', 'build', '-r', str(recipe_yaml_path),
                    '--target-platform', target_platform, '--test', 'native',
                    '--output-dir', str(output), '-c', f'https://repo.prefix.dev/{channel}',
                    '-c', 'conda-forge', '--skip-existing', 'none',
                ], check=True)
            if not path.is_file():
                raise RuntimeError(f'Expected artifact missing: {path}')
            receipt = path.with_suffix('.receipt.json')
            with path.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            if build_flag:
                receipt.write_text(json.dumps({'filename': artifact.filename, 'sha256': digest}) + '\n', encoding='utf-8')
            elif not receipt.is_file() or json.loads(receipt.read_text(encoding='utf-8')) != {'filename': artifact.filename, 'sha256': digest}:
                raise RuntimeError(f'Build receipt missing or mismatched: {path}; rebuild before publishing')
            status = publish(artifact, path, channel) if upload_flag else 'built'
            print(f'{status}: {path}', flush=True)
            outcomes.append({'path': str(path), 'status': status})
        status = 'already_exists' if all(x['status'] == 'already_exists' for x in outcomes) else ('published' if upload_flag else 'built')
        return {'recipe': label, 'platform': target_platform, 'status': status, 'artifacts': outcomes}
    finally:
        print('::endgroup::', flush=True)
