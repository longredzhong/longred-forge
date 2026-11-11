#!/usr/bin/env python3
"""Install published skill packages with Pixi and expose them to project agents."""
import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import httpx

CHANNEL = 'https://prefix.dev/longredzhong/longred-skills-forge'
AGENTS = {'agents': '.agents/skills', 'codex': '.codex/skills', 'claude': '.claude/skills'}
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')


def project_root(start):
    """Find the nearest Pixi workspace, including workspaces in pyproject.toml."""
    for directory in (start, *start.parents):
        if (directory / 'pixi.toml').is_file():
            return directory
        manifest = directory / 'pyproject.toml'
        if manifest.is_file():
            with manifest.open('rb') as f:
                data = tomllib.load(f)
            if 'pixi' in data.get('tool', {}):
                return directory
    return start


def plan_sync(root, environment, agent, selected=None, allow_empty=False, target_root=None):
    """Check all destinations before any filesystem or Pixi changes."""
    if not NAME.fullmatch(environment):
        raise ValueError('Invalid environment name')
    target = (target_root or root) / AGENTS[agent]
    if (target.parent.exists() or target.parent.is_symlink()) and not target.parent.is_dir():
        raise FileExistsError(f'Agent configuration directory conflicts: {target.parent}')
    if (target.exists() or target.is_symlink()) and not target.is_dir():
        raise FileExistsError(f'Agent skill directory conflicts: {target}')
    source = root / '.pixi' / 'envs' / environment / 'share' / 'agent-skills'
    if not source.is_dir():
        if allow_empty:
            return [], []
        raise ValueError(f'No installed skills found in {source}')
    skills = sorted(p for p in source.iterdir() if p.is_dir() and (p / 'SKILL.md').is_file())
    if selected:
        skills = [p for p in skills if p.name == selected]
        if not skills:
            raise ValueError(f'Skill not found in environment: {selected}')
    if not skills:
        if allow_empty:
            return [], []
        raise ValueError('No installed skills found')
    actions = []
    for skill in skills:
        if not NAME.fullmatch(skill.name):
            raise ValueError(f'Invalid skill name: {skill.name}')
        dest = target / skill.name
        if dest.is_symlink():
            if dest.resolve() != skill.resolve():
                raise FileExistsError(f'Existing symlink conflicts: {dest}')
        elif dest.exists():
            raise FileExistsError(f'Existing path conflicts: {dest}')
        else:
            actions.append((skill, dest))
    return skills, actions


def sync(root, environment, agent, selected=None, target_root=None):
    skills, actions = plan_sync(root, environment, agent, selected, target_root=target_root)
    target = (target_root or root) / AGENTS[agent]
    target.mkdir(parents=True, exist_ok=True)
    for skill, dest in actions:
        dest.symlink_to(os.path.relpath(skill, dest.parent), target_is_directory=True)
        print(f'linked: {dest} -> {skill}')
    print(f'{len(skills)} skill(s) available for {agent}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    find = sub.add_parser('find', help='Search published skill package names')
    find.add_argument('query', nargs='?', default='')
    for command in ('add', 'sync', 'list'):
        p = sub.add_parser(command)
        if command == 'add':
            p.add_argument('package')
        if command == 'sync':
            p.add_argument('--skill')
        p.add_argument('-e', '--environment', default='default')
        p.add_argument('-g', '--global', dest='global_scope', action='store_true',
                       help='Use the persistent global skill workspace and home directory')
        if command != 'list':
            p.add_argument('-a', '--agent', choices=AGENTS, default='agents')
    args = parser.parse_args()
    if args.command != 'find' and not NAME.fullmatch(args.environment):
        raise ValueError('Invalid environment name')
    root = project_root(Path.cwd()) if args.command != 'find' and not args.global_scope else Path.cwd()
    target_root = None
    if args.command != 'find' and args.global_scope:
        target_root = Path.home()
        root = target_root / '.local' / 'share' / 'longred-skills' / args.environment
        # Each named global workspace has a separate default Pixi environment.
        args.environment = 'default'
    if args.command == 'find':
        with httpx.Client(trust_env=False, follow_redirects=True, timeout=30) as client:
            response = client.get(CHANNEL + '/noarch/repodata.json')
            response.raise_for_status()
            data = response.json()
        packages = data.get('packages.conda', {}) | data.get('packages', {})
        names = sorted({p['name'] for p in packages.values() if p['name'].startswith('agent-skill-') and args.query.lower() in p['name'].lower()})
        print('\n'.join(names) if names else 'No matching skills')
    elif args.command == 'add':
        if not NAME.fullmatch(args.package) or not args.package.startswith('agent-skill-'):
            raise ValueError('Expected an agent-skill-* package name')
        # Existing skills can be checked before Pixi changes the project; newly
        # installed skill names are known only after the solver installs them.
        plan_sync(root, args.environment, args.agent, allow_empty=True, target_root=target_root)
        if target_root is not None:
            root.mkdir(parents=True, exist_ok=True)
            manifest = root / 'pixi.toml'
            if not manifest.exists():
                subprocess.run(['pixi', 'init', '--format', 'pixi', '--channel',
                                'https://prefix.dev/conda-forge'], check=True, cwd=root)
        try:
            subprocess.run(['pixi', 'workspace', 'channel', 'add', '-e', args.environment, CHANNEL], check=True, cwd=root)
            subprocess.run(['pixi', 'add', '-e', args.environment, '--pinning-strategy', 'latest-up',
                            f'{CHANNEL}::{args.package}'], check=True, cwd=root)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('Pixi could not add the package; the project channel may already have changed. '
                               'Inspect pixi.toml and pixi.lock before retrying.') from exc
        try:
            sync(root, args.environment, args.agent, target_root=target_root)
        except (ValueError, OSError) as exc:
            raise RuntimeError(f'Pixi added {args.package}, but agent synchronization failed: {exc}. '
                               'The manifest, lockfile, and environment may have changed; resolve the conflict '
                               'and run longred-skills sync.') from exc
    elif args.command == 'sync':
        sync(root, args.environment, args.agent, args.skill, target_root=target_root)
    else:
        source = root / '.pixi' / 'envs' / args.environment / 'share' / 'agent-skills'
        if source.is_dir():
            for skill in sorted(source.iterdir()):
                if skill.is_dir() and (skill / 'SKILL.md').is_file():
                    print(skill.name)


def run():
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError, httpx.HTTPError) as exc:
        print(f'longred-skills: {exc}', file=sys.stderr)
        raise SystemExit(1) from None
