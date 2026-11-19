"""Execute builds using original recipe resources and exact rendered outputs."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

import yaml

from .planner import render
from .publisher import indexed, publish, remote_digest


def receipt_path(artifact, output: Path) -> Path:
    """Receipts live outside the gitignored output dir so CI can commit them."""
    return output.parent / 'receipts' / artifact.platform / f'{artifact.filename}.json'


def _fingerprint_bytes(resource: Path) -> bytes:
    """Normalize newlines so a Windows CRLF checkout has the same fingerprint."""
    return resource.read_bytes().replace(b'\r\n', b'\n')


def recipe_fingerprint(recipe: Path) -> str:
    digest = hashlib.sha256()
    for resource in sorted(recipe.parent.rglob('*')):
        relative = resource.relative_to(recipe.parent)
        if not resource.is_file() or any(part in ('generated', '__pycache__') for part in relative.parts) or resource.name.startswith('.update-'):
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b'\0')
        digest.update(_fingerprint_bytes(resource))
        digest.update(b'\0')
    doc = yaml.safe_load(recipe.read_text(encoding='utf-8')) or {}
    sources = doc.get('source', [])
    if isinstance(sources, dict):
        sources = [sources]
    if not isinstance(sources, list):
        sources = []
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get('path'), str):
            continue
        local = (recipe.parent / source['path']).resolve()
        if not local.is_relative_to(Path.cwd().resolve()):
            raise ValueError('Local recipe source must be inside the workspace')
        files = [local] if local.is_file() else sorted(local.rglob('*'))
        if not local.exists():
            raise ValueError(f'Local recipe source not found: {local}')
        for resource in files:
            if resource.is_symlink():
                raise ValueError(f'Symlink in local recipe source: {resource}')
            if not resource.is_file() or any(part in ('.git', '.pixi', '__pycache__') for part in resource.relative_to(local if local.is_dir() else local.parent).parts):
                continue
            digest.update(str(resource.relative_to(Path.cwd().resolve())).encode())
            digest.update(b'\0')
            digest.update(_fingerprint_bytes(resource))
            digest.update(b'\0')
    return digest.hexdigest()


def existing_receipt_digest(recipe: Path, artifact, path: Path, receipt: Path) -> str | None:
    """Validate a local receipt when available; published packages need no local build."""
    if not receipt.exists():
        return None
    try:
        data = json.loads(receipt.read_text(encoding='utf-8'))
        digest = data['sha256']
        if (not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)
                or data != {'filename': artifact.filename, 'sha256': digest,
                            'recipe_sha256': recipe_fingerprint(recipe)}):
            raise ValueError('receipt fields differ')
        if path is not None and path.is_file():
            with path.open('rb') as handle:
                if hashlib.file_digest(handle, 'sha256').hexdigest() != digest:
                    raise ValueError('artifact checksum differs')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f'Build receipt mismatch: {receipt}; rebuild and use a new version if already published') from exc
    return digest


def build_recipe(recipe_yaml_path: Path, target_platform: str, channel: str,
                 upload_flag: bool, build_flag: bool, skip_existing: bool,
                 output: Path = Path('output'), adopt_existing: bool = False) -> dict:
    label = str(recipe_yaml_path)
    print(f'::group::{recipe_yaml_path.parent.name}-{target_platform}', flush=True)
    try:
        artifacts = render(recipe_yaml_path, target_platform)
        artifacts = [a for a in artifacts if a.platform != 'noarch' or target_platform == 'linux-64']
        if not artifacts:
            return {'recipe': label, 'platform': target_platform, 'status': 'unsupported', 'artifacts': []}
        outcomes = []
        for artifact in artifacts:
            # A same-identity skip is only trustworthy with a matching local receipt
            # (receipts/ is committed alongside the channel state). When a receipt is
            # genuinely missing, rebuild and verify against the channel digest so a
            # recipe edit that forgot to bump build.number fails loudly instead of
            # silently keeping the old package.
            remote_identity = skip_existing and indexed(artifact, channel)
            receipt = receipt_path(artifact, output)
            if remote_identity:
                path = artifact.path(output)
                digest = existing_receipt_digest(recipe_yaml_path, artifact, path, receipt)
                if digest:
                    if not indexed(artifact, channel, digest):
                        raise RuntimeError(f'Cannot verify indexed package: {artifact.filename}')
                    outcomes.append({'path': str(path), 'status': 'already_exists'})
                    continue
                if adopt_existing:
                    # One-time bootstrap or deliberate recovery: adopt the channel's
                    # digest for the current recipe fingerprint instead of rebuilding.
                    remote = remote_digest(artifact, channel)
                    if remote:
                        receipt.parent.mkdir(parents=True, exist_ok=True)
                        receipt.write_text(json.dumps(
                            {'filename': artifact.filename, 'sha256': remote,
                             'recipe_sha256': recipe_fingerprint(recipe_yaml_path)}) + '\n',
                            encoding='utf-8')
                        print(f'adopted: {artifact.filename}', flush=True)
                        outcomes.append({'path': str(path), 'status': 'adopted'})
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
            with path.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            if remote_identity:
                # Rebuilt a receiptless same-identity package: fail loudly when the
                # digest differs from the published one instead of overwriting it.
                indexed(artifact, channel, digest)
            expected_receipt = {'filename': artifact.filename, 'sha256': digest, 'recipe_sha256': recipe_fingerprint(recipe_yaml_path)}
            if build_flag:
                receipt.parent.mkdir(parents=True, exist_ok=True)
                receipt.write_text(json.dumps(expected_receipt) + '\n', encoding='utf-8')
            elif not receipt.is_file() or json.loads(receipt.read_text(encoding='utf-8')) != expected_receipt:
                raise RuntimeError(f'Build receipt missing or mismatched: {receipt}; rebuild before publishing')
            status = publish(artifact, path, channel) if upload_flag else 'built'
            print(f'{status}: {path}', flush=True)
            outcomes.append({'path': str(path), 'status': status})
        status = ('already_exists' if all(x['status'] in ('already_exists', 'adopted') for x in outcomes)
                  else ('published' if upload_flag else 'built'))
        return {'recipe': label, 'platform': target_platform, 'status': status, 'artifacts': outcomes}
    finally:
        print('::endgroup::', flush=True)
