#!/usr/bin/env python3
"""Upload a batch of locally receipted skills and verify their channel indexes."""
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

if __package__:
    from .build import load_dotenv
    from .forge.builder import existing_receipt_digest, recipe_fingerprint
    from .forge.http import HTTPClient
    from .forge.planner import render
    from .forge.publisher import INDEX_POLL_ATTEMPTS, INDEX_POLL_INTERVAL
else:
    from build import load_dotenv
    from forge.builder import existing_receipt_digest, recipe_fingerprint
    from forge.http import HTTPClient
    from forge.planner import render
    from forge.publisher import INDEX_POLL_ATTEMPTS, INDEX_POLL_INTERVAL

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


def pixi_indexed(pending):
    """Confirm exact identities with a fresh Pixi index when HTTP metadata is stale."""
    with tempfile.TemporaryDirectory(prefix='skills-index-') as cache:
        env = dict(os.environ, PIXI_CACHE_DIR=cache, RATTLER_CACHE_DIR=cache)
        try:
            result = subprocess.run(
                ['pixi', 'search', '--json', '--channel', f'https://prefix.dev/{CHANNEL}',
                 '--platform', 'linux-64', '*'], env=env, capture_output=True, text=True, timeout=60,
            )
            if result.returncode:
                return set()
            groups = json.loads(result.stdout)
            entries = groups.get('noarch', [])
            by_filename = {entry.get('fn'): entry for entry in entries}
        except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError, TypeError):
            return set()
    confirmed = set()
    base = f'https://prefix.dev/{CHANNEL}/noarch/'
    for artifact, _, digest in pending:
        entry = by_filename.get(artifact.filename)
        if not entry or entry.get('url') != base + artifact.filename:
            continue
        if entry.get('sha256') != digest:
            raise RuntimeError(f'Channel checksum differs for {artifact.filename}; increment build.number')
        confirmed.add(artifact.filename)
    return confirmed


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
                digest = existing_receipt_digest(recipe, artifact, artifact.path(Path('output')))
                if digest and records[artifact.filename].get('sha256') != digest:
                    raise RuntimeError(f'Channel checksum differs for {artifact.filename}; increment build.number')
                print(f'already indexed: {artifact.filename}', flush=True)
                continue
            path = artifact.path(Path('output'))
            receipt = path.with_suffix('.receipt.json')
            if not path.is_file() or not receipt.is_file():
                raise RuntimeError(f'Missing package or receipt: {path}')
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
            break
        if attempt == 2:
            raise RuntimeError('Batch upload failed')
        time.sleep(2 ** attempt)
    for attempt in range(INDEX_POLL_ATTEMPTS + 1):
        records = channel_records(fresh=True)
        remaining = []
        for artifact, path, digest in pending:
            entry = records.get(artifact.filename)
            if entry is None:
                remaining.append((artifact, path, digest))
            elif entry.get('sha256') != digest:
                raise RuntimeError(f'Channel checksum differs for {artifact.filename}; increment build.number')
        pending = remaining
        if not pending:
            print('All uploaded packages indexed with matching SHA-256')
            return
        if attempt % 4 == 0:
            confirmed = pixi_indexed(pending)
            pending = [(a, p, digest) for a, p, digest in pending if a.filename not in confirmed]
            if not pending:
                print('All uploaded packages resolved by Pixi with matching SHA-256')
                return
        if attempt < INDEX_POLL_ATTEMPTS:
            if attempt % 20 == 0:
                print(f'Waiting for index: {len(pending)} package(s)', flush=True)
            time.sleep(INDEX_POLL_INTERVAL)
    raise RuntimeError('Not indexed: ' + ', '.join(a.filename for a, _, _ in pending))


if __name__ == '__main__':
    main()
