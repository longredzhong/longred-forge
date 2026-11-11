#!/usr/bin/env python3
"""Resolve pinned skill sources, comparing one Git tree per upstream repository."""
import argparse
import base64
import hashlib
import io
import json
import os
import re
import sys
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath

import yaml

if __package__:
    from .forge.http import ASSET_DOWNLOAD_TIMEOUT, HTTPClient
else:
    from forge.http import ASSET_DOWNLOAD_TIMEOUT, HTTPClient

REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA = re.compile(r"[a-f0-9]{40}\Z")
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_CONTENT_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100000
SKILL_RECIPES_DIR = Path('skill-recipes')


def download_locked_archive(client, url, skill_paths):
    """Read a bounded commit archive once, without extracting or executing files."""
    def collect(response):
        data = bytearray()
        digest = hashlib.sha256()
        for chunk in response.iter_bytes():
            if len(data) + len(chunk) > MAX_ARCHIVE_BYTES:
                raise ValueError('Source archive exceeds compressed size limit')
            data.extend(chunk)
            digest.update(chunk)
        return bytes(data), digest.hexdigest()
    content, digest = client.read(url, collect, timeout=ASSET_DOWNLOAD_TIMEOUT)
    files = {path: {} for path in skill_paths}
    total = 0
    root = None
    with tarfile.open(fileobj=io.BytesIO(content), mode='r:gz') as archive:
        for count, member in enumerate(archive, 1):
            if count > MAX_ARCHIVE_MEMBERS:
                raise ValueError('Source archive exceeds file count limit')
            parts = PurePosixPath(member.name).parts
            if not parts or member.name.startswith('/') or any(p in ('.', '..') for p in parts):
                raise ValueError('Unsafe source archive path')
            if root is None:
                root = parts[0]
            if parts[0] != root:
                raise ValueError('Source archive has multiple roots')
            total += max(member.size, 0)
            if total > MAX_ARCHIVE_CONTENT_BYTES:
                raise ValueError('Source archive exceeds uncompressed size limit')
            relative = '/'.join(parts[1:])
            for path in skill_paths:
                prefix = path + '/'
                if not relative.startswith(prefix):
                    continue
                name = relative[len(prefix):]
                if any(part in ('.git', 'node_modules') for part in PurePosixPath(name).parts):
                    continue
                if member.issym() or member.islnk() or '\\' in name:
                    raise ValueError('Unsupported link or filename in locked skill')
                if not member.isfile():
                    continue
                if name in files[path]:
                    raise ValueError('Duplicate file in locked skill archive')
                handle = archive.extractfile(member)
                if handle is None:
                    raise ValueError('Cannot read locked skill file')
                files[path][name] = handle.read()
    return digest, files


def npx_skill_hash(files):
    """Match skills CLI path.localeCompare ordering and SHA-256 input exactly."""
    if not files:
        raise ValueError('Locked skill archive contains no files')
    order = subprocess.run(
        ['node', '-e', 'const fs=require("fs");const a=JSON.parse(fs.readFileSync(0,"utf8"));a.sort((x,y)=>x.localeCompare(y));process.stdout.write(JSON.stringify(a));'],
        input=json.dumps(list(files)), capture_output=True, text=True, check=True, timeout=30,
    )
    digest = hashlib.sha256()
    for name in json.loads(order.stdout):
        digest.update(name.encode('utf-8'))
        digest.update(files[name])
    return digest.hexdigest()


def safe_path(value):
    if not isinstance(value, str) or not value or value.startswith('/') or '\\' in value:
        raise ValueError('Invalid source path')
    path = PurePosixPath(value)
    if any(part in ('..', '.') or not re.fullmatch(r'[A-Za-z0-9_.-]+', part) for part in value.split('/')) or str(path) != value:
        raise ValueError('Invalid source path')
    return value


def additional_licenses(item):
    """Validate local notices and include their contents in the release identity."""
    names = item.get('additional_license_files', [])
    if not isinstance(names, list) or len(names) > 32:
        raise ValueError('Invalid additional license files')
    package = item['package']
    if not isinstance(package, str) or not NAME.fullmatch(package) or not package.startswith('agent-skill-'):
        raise ValueError('Invalid skill or package name')
    hashes = {}
    for name in names:
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name) or name == 'LICENSE' or name in hashes:
            raise ValueError('Invalid additional license file name')
        path = SKILL_RECIPES_DIR / package / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Additional license file missing or invalid: {path}')
        contents = path.read_bytes()
        if not contents or len(contents) > 1024 * 1024:
            raise ValueError(f'Additional license file empty or oversized: {path}')
        hashes[name] = hashlib.sha256(contents).hexdigest()
    return hashes


def render_recipe(repository, item, commit, version, archive_sha=None, bundled_names=None):
    path, name, package = item['path'], item['name'], item['package']
    # All interpolated values are validated before reaching a shell or URL.
    target = '$PREFIX/share/agent-skills' if bundled_names is not None else f'$PREFIX/share/agent-skills/{name}'
    script = (f'mkdir -p "{target}"\n'
              f'cp -R "$SRC_DIR/{path}/." "{target}/"')
    if repository.get('license_file'):
        script += (f'\nmkdir -p "$PREFIX/share/licenses/{package}"'
                   f'\ncp "$SRC_DIR/{repository["license_file"]}" "$PREFIX/share/licenses/{package}/LICENSE"')
    license_files = item.get('additional_license_files', [])
    if license_files and not repository.get('license_file'):
        script += f'\nmkdir -p "$PREFIX/share/licenses/{package}"'
    for filename in license_files:
        script += f'\ncp "$RECIPE_DIR/{filename}" "$PREFIX/share/licenses/{package}/{filename}"'
    source = ({'url': f'https://github.com/{repository["repository"]}/archive/{commit}.tar.gz', 'sha256': archive_sha}
              if archive_sha else {'git': 'https://github.com/' + repository['repository'] + '.git', 'rev': commit})
    recipe = {'package': {'name': package, 'version': version},
              'source': source,
              'build': {'number': 0, 'noarch': 'generic', 'script': script},
              'tests': [{'package_contents': {'files': [f'share/agent-skills/{n}/SKILL.md' for n in (bundled_names if bundled_names is not None else [name])] + [f'share/licenses/{package}/{filename}' for filename in license_files]}}],
              'about': {'summary': f'Agent skill {name}', 'license': 'LicenseRef-Unlicensed' if repository['license'] == 'UNLICENSED' else repository['license'],
                        'repository': 'https://github.com/' + repository['repository']}}
    if repository.get('license_file'):
        recipe['about']['license_file'] = repository['license_file']
    if item.get('dependencies'):
        recipe['requirements'] = {'run': item['dependencies']}
    return recipe


def check(config, previous, client, headers, accept_license_change=False, cache=None):
    if config.get('version') != 1 or previous.get('version') != 1:
        raise ValueError('Unsupported source or lock version')
    result = dict(previous.get('skills', {}))
    recipes = {}
    seen = set()
    repositories = set()
    pending_cache = {}
    for repository in config['repositories']:
        repo, branch = repository['repository'], repository['branch']
        if not REPO.fullmatch(repo) or any(x in ('.', '..') for x in repo.split('/')):
            raise ValueError('Invalid GitHub repository')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', branch) or branch in ('.', '..'):
            raise ValueError('Invalid branch')
        if repo in repositories:
            raise ValueError(f'Duplicate repository configuration: {repo}')
        repositories.add(repo)
        license_file = repository.get('license_file')
        if license_file:
            safe_path(license_file)
        elif repository['license'] != 'UNLICENSED':
            raise ValueError('License file required unless UNLICENSED')
        if not re.fullmatch(r'[A-Za-z0-9.+-]+', repository['license']):
            raise ValueError('Invalid license')
        base = f'https://api.github.com/repos/{repo}'
        pinned = repository.get('commit')
        if pinned is not None:
            if not isinstance(pinned, str) or not SHA.fullmatch(pinned):
                raise ValueError('Invalid pinned commit SHA')
            commit = pinned
        else:
            ref = client.json(f'{base}/git/ref/heads/{branch}', headers)
            commit = ref['object']['sha']
        if not SHA.fullmatch(commit):
            raise ValueError('Invalid commit SHA')
        packages = [item['package'] for item in repository['skills']]
        local_licenses = {item['package']: additional_licenses(item) for item in repository['skills']}
        def signature(items):
            data = {'repository': repository, 'locked': {key: items.get(key) for key in packages}}
            if any(local_licenses.values()):
                data['additional_licenses'] = local_licenses
            return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        cached = (cache or {}).get(repo, {})
        if not isinstance(cached, dict):
            cached = {}
        checked_at = cached.get('checked_at')
        fresh = type(checked_at) in (int, float) and 0 <= time.time() - checked_at < 86400
        if (fresh and cached.get('commit') == commit and cached.get('signature') == signature(result)
                and all(key in result for key in packages) and len(set(packages)) == len(packages)
                and all(not item.get('lock_hash') or result[item['package']].get('source_lock_verified') == item['lock_hash']
                        for item in repository['skills'])
                and not (set(packages) & seen)):
            seen.update(packages)
            pending_cache[repo] = cached
            print(f'unchanged repository: {repo}')
            continue
        tree = client.json(f'{base}/git/trees/{commit}?recursive=1', headers)
        if tree.get('truncated'):
            raise RuntimeError(f'Git tree truncated for {repo}; refusing partial update')
        entries = {entry['path']: entry for entry in tree['tree']}
        license_entry = entries.get(license_file, {}) if license_file else {'sha': None}
        if license_file and (license_entry.get('type') != 'blob' or license_entry.get('mode') == '120000'):
            raise ValueError(f'License file missing in {repo}')
        archive_sha = None
        locked_files = None
        if type(repository.get('archive', False)) is not bool:
            raise ValueError('Invalid archive setting')
        for item in repository['skills']:
            path = safe_path(item['path'])
            name, package = item['name'], item['package']
            bundle = item.get('bundle', False)
            if type(bundle) is not bool:
                raise ValueError('Invalid bundle setting')
            source_lock_hash = item.get('lock_hash')
            if source_lock_hash is not None and (not isinstance(source_lock_hash, str) or not re.fullmatch(r'[a-f0-9]{64}', source_lock_hash)):
                raise ValueError('Invalid source lock hash')
            dependencies = item.get('dependencies', [])
            if not isinstance(dependencies, list) or any(not isinstance(dep, str) or not re.fullmatch(r'agent-skill-[a-z0-9]+(?:-[a-z0-9]+)* ==[0-9]+\.[0-9]+\.[0-9]+', dep) for dep in dependencies):
                raise ValueError('Invalid skill dependencies')
            if not NAME.fullmatch(name) or len(name) > 64 or not NAME.fullmatch(package) or not package.startswith('agent-skill-'):
                raise ValueError('Invalid skill or package name')
            if package in seen:
                raise ValueError(f'Duplicate package: {package}')
            seen.add(package)
            skill = entries.get(path, {})
            if skill.get('type') != 'tree' or not SHA.fullmatch(skill.get('sha', '')):
                raise ValueError(f'Skill directory or SKILL.md missing: {repo}/{path}')
            if bundle:
                prefix = path + '/'
                names = sorted(key[len(prefix):-len('/SKILL.md')] for key in entries
                               if key.startswith(prefix) and key.endswith('/SKILL.md')
                               and '/' not in key[len(prefix):-len('/SKILL.md')])
                if not names or any(not NAME.fullmatch(n) or len(n) > 64 for n in names):
                    raise ValueError(f'Invalid or empty skill bundle: {repo}/{path}')
            else:
                names = [name]
            markers = [(n, entries.get(f'{path}/{n}/SKILL.md' if bundle else path + '/SKILL.md', {})) for n in names]
            if any(marker.get('type') != 'blob' for _, marker in markers):
                raise ValueError(f'Skill directory or SKILL.md missing: {repo}/{path}')
            for key, entry in entries.items():
                if key.startswith(path + '/') and entry.get('mode') in ('120000', '160000'):
                    raise ValueError(f'Symlink or submodule is not supported: {repo}/{key}')
            old = result.get(package, {})
            if (source_lock_hash and old.get('source_lock_hash') == source_lock_hash
                    and old.get('tree') and old['tree'] != skill['sha']):
                raise ValueError(f'Source tree changed for locked skill {package}; verify and update the lock hash')
            if old.get('license_blob') and old['license_blob'] != license_entry['sha'] and not accept_license_change:
                raise ValueError(f'License changed for {repo}; review before updating {package}')
            identity = [repo, branch, path, name, repository['license'], license_file]
            if repository.get('archive', False):
                identity.append('archive')
            if bundle:
                identity.append('bundle')
            if source_lock_hash:
                identity.append('lock_hash:' + source_lock_hash)
            if dependencies:
                identity.append('dependencies:' + json.dumps(sorted(dependencies)))
            if local_licenses[package]:
                identity.append('additional_license_files:' + json.dumps(local_licenses[package], sort_keys=True))
            unchanged = old.get('identity') == identity and old.get('tree') == skill['sha'] and old.get('license_blob') == license_entry['sha']
            verified = (not source_lock_hash or
                        (old.get('source_lock_verified') == source_lock_hash and old.get('tree') == skill['sha']))
            if unchanged and verified:
                print(f'unchanged: {package}')
                continue
            if source_lock_hash and not verified:
                if locked_files is None:
                    paths = {safe_path(entry['path']) for entry in repository['skills'] if entry.get('lock_hash')}
                    archive_sha, locked_files = download_locked_archive(
                        client, f'https://github.com/{repo}/archive/{commit}.tar.gz', paths)
                if npx_skill_hash(locked_files[path]) != source_lock_hash:
                    raise ValueError(f'Source lock hash mismatch: {package}')
                if unchanged:
                    result[package] = dict(old, source_lock_verified=source_lock_hash)
                    print(f'verified: {package}')
                    continue
            for skill_name, marker in markers:
                blob = client.json(f'{base}/git/blobs/{marker["sha"]}', headers)
                if blob.get('encoding') != 'base64' or blob.get('size', 0) > 1024 * 1024:
                    raise ValueError(f'Invalid or oversized SKILL.md: {repo}/{path}/{skill_name}')
                text = base64.b64decode(blob['content'], validate=False).decode('utf-8')
                parts = text.split('---', 2)
                if len(parts) < 3 or parts[0].strip():
                    raise ValueError(f'Invalid skill frontmatter: {repo}/{path}/{skill_name}')
                meta = yaml.safe_load(parts[1])
                if not isinstance(meta, dict) or meta.get('name') != skill_name or not isinstance(meta.get('description'), str) or not 1 <= len(meta['description'].strip()) <= 1024:
                    raise ValueError(f'Invalid skill name or description: {repo}/{path}/{skill_name}')
            if repository.get('archive', False) and archive_sha is None:
                archive_sha = client.sha256(f'https://github.com/{repo}/archive/{commit}.tar.gz')
            version = f"0.0.{int(old.get('revision', 0)) + 1}"
            result[package] = {'identity': identity, 'commit': commit, 'tree': skill['sha'],
                               'license_blob': license_entry['sha'], 'revision': int(old.get('revision', 0)) + 1,
                               'version': version}
            if source_lock_hash:
                result[package]['source_lock_hash'] = source_lock_hash
                result[package]['source_lock_verified'] = source_lock_hash
            recipes[package] = render_recipe(repository, item, commit, version,
                                              archive_sha if repository.get('archive', False) else None,
                                              names if bundle else None)
            print(f'updated: {package} {version} {commit}')
        pending_cache[repo] = {'commit': commit, 'signature': signature(result), 'checked_at': time.time()}
    removed = set(result) - seen
    if removed:
        raise ValueError(f'Removed packages require an explicit migration: {sorted(removed)}')
    for repository in config['repositories']:
        for item in repository['skills']:
            for dependency in item.get('dependencies', []):
                dep_name, dep_version = dependency.split(' ==', 1)
                if dep_name == item['package'] or dep_name not in seen or result.get(dep_name, {}).get('version') != dep_version:
                    raise ValueError(f'Unresolved skill dependency for {item["package"]}: {dependency}')
    if cache is not None:
        cache.clear()
        cache.update(pending_cache)
    return {'version': 1, 'skills': result}, recipes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Write lock and recipe changes')
    parser.add_argument('--accept-license-change', action='store_true', help='Accept reviewed license changes')
    args = parser.parse_args()
    config = yaml.safe_load(Path('skill-sources.yaml').read_text())
    previous = yaml.safe_load(Path('skill-lock.yaml').read_text())
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'longred-skills-forge'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    cache_path = Path(os.environ['SKILLS_CACHE_DIR']) / 'repositories.json' if os.environ.get('SKILLS_CACHE_DIR') else None
    cache = {}
    if cache_path:
        try:
            cache = json.loads(cache_path.read_text(encoding='utf-8'))
            if not isinstance(cache, dict):
                cache = {}
        except (OSError, ValueError):
            pass
    lock, recipes = check(config, previous, HTTPClient(), headers, args.accept_license_change, cache)
    if args.apply:
        for package, recipe in recipes.items():
            dest = SKILL_RECIPES_DIR / package / 'recipe.yaml'
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(yaml.safe_dump(recipe, sort_keys=False), encoding='utf-8')
        Path('skill-lock.yaml').write_text(yaml.safe_dump(lock, sort_keys=False), encoding='utf-8')
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, sort_keys=True), encoding='utf-8')
    print(json.dumps({'changed': sorted(recipes), 'applied': args.apply}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'skill update failed: {type(exc).__name__}', file=sys.stderr)
        raise SystemExit(1) from None
