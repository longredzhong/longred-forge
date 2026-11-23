#!/usr/bin/env python3
"""Upload a batch of locally receipted skills after pre-upload checksum checks."""
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import httpx

if __package__:
    from .build import load_dotenv
    from .forge.builder import existing_receipt_digest, recipe_fingerprint, receipt_path
    from .forge.http import HTTPClient
    from .forge.planner import render
else:
    from build import load_dotenv
    from forge.builder import existing_receipt_digest, recipe_fingerprint, receipt_path
    from forge.http import HTTPClient
    from forge.planner import render

CHANNEL = 'longredzhong/longred-skills-forge'


def channel_records(fresh=False):
    url = f'https://repo.prefix.dev/{CHANNEL}/noarch/repodata.json'
    if fresh:
        url += f'?verify={time.time_ns()}'
    try:
        return HTTPClient().json(url).get('packages.conda', {})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {}
        raise


def main():
    for key, value in load_dotenv(Path('.env')).items():
        os.environ.setdefault(key, value)
    token = os.environ.get('PREFIX_API_KEY') or os.environ.get('PREFIX_TOKEN')
    if not token:
        raise RuntimeError('PREFIX_API_KEY/PREFIX_TOKEN is required')
    pending = []
    records = channel_records()
    recipes = sorted(Path('skill-recipes').glob('*/recipe.yaml'))
    for recipe in recipes:
        for artifact in render(recipe, 'linux-64'):
            if artifact.filename in records:
                receipt = receipt_path(artifact, Path('output'))
                digest = existing_receipt_digest(recipe, artifact, artifact.path(Path('output')), receipt)
                if not digest:
                    raise RuntimeError(f'Build receipt missing for published package: {artifact.filename}; rebuild or adopt receipts deliberately')
                if records[artifact.filename].get('sha256') != digest:
                    raise RuntimeError(f'Channel checksum differs for {artifact.filename}; increment build.number')
                print(f'already indexed: {artifact.filename}', flush=True)
                continue
            path = artifact.path(Path('output'))
            receipt = receipt_path(artifact, Path('output'))
            if not path.is_file() or not receipt.is_file():
                raise RuntimeError(f'Missing package or receipt: {receipt}')
            with path.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            expected = {'filename': artifact.filename, 'sha256': digest, 'recipe_sha256': recipe_fingerprint(recipe)}
            if json.loads(receipt.read_text(encoding='utf-8')) != expected:
                raise RuntimeError(f'Build receipt mismatch: {path}')
            pending.append((artifact, path, digest))
    if not pending:
        print('No packages to publish')
        return
    env = dict(os.environ, PREFIX_API_KEY=token)
    cmd = ['rattler-build', 'upload', 'prefix', '--channel', CHANNEL, '--skip-existing'] + [str(path) for _, path, _ in pending]
    for attempt in range(3):
        if subprocess.run(cmd, env=env).returncode == 0:
            print(f'Uploaded {len(pending)} package(s)')
            return
        if attempt == 2:
            raise RuntimeError('Batch upload failed')
        time.sleep(2 ** attempt)


if __name__ == '__main__':
    main()
