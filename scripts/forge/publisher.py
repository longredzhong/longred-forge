"""Publish exact planned artifacts and verify channel indexing."""

import hashlib
import os
import subprocess
import time
from pathlib import Path

import httpx

from .http import HTTPClient
from .planner import Artifact


def indexed(artifact: Artifact, channel: str, sha256: str | None = None) -> bool:
    try:
        url = f'https://repo.prefix.dev/{channel}/{artifact.platform}/repodata.json'
        if sha256:
            # Ordinary channel metadata is cached for 30 minutes; verify uploads against a fresh URL.
            url += f'?verify={time.time_ns()}'
        repodata = HTTPClient().json(url)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return False
        raise
    metadata = repodata.get('packages.conda', {}).get(artifact.filename)
    if metadata is None:
        return False
    if sha256 and metadata.get('sha256') != sha256:
        raise RuntimeError(f'Channel checksum differs for {artifact.filename}; increment build.number')
    return True


def publish(artifact: Artifact, path: Path, channel: str) -> str:
    token = os.environ.get('PREFIX_API_KEY') or os.environ.get('PREFIX_TOKEN')
    if not token:
        raise RuntimeError('PREFIX_API_KEY/PREFIX_TOKEN is required for publishing; use --no-upload for local builds')
    with path.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    if indexed(artifact, channel, digest):
        return 'already_exists'
    env = dict(os.environ, PREFIX_API_KEY=token)
    for attempt in range(3):
        result = subprocess.run(
            ['rattler-build', 'upload', 'prefix', '-c', channel, '--skip-existing', str(path)], env=env,
        )
        if result.returncode == 0:
            break
        if attempt == 2:
            raise RuntimeError(f'Upload failed: {artifact.filename}')
        time.sleep(2 ** attempt)
    for attempt in range(24):
        if indexed(artifact, channel, digest):
            return 'published'
        time.sleep(15)
    raise RuntimeError(f'Uploaded artifact not indexed yet: {artifact.filename}')
