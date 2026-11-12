#!/usr/bin/env python3
"""Check committed skill recipes against the catalog lock without network access."""
from pathlib import Path
import sys

import yaml


def verify(lock, recipes_dir):
    errors = []
    skills = lock['skills']
    recipes = {p.parent.name: p for p in recipes_dir.glob('*/recipe.yaml')}
    for name in sorted(set(skills) | set(recipes)):
        if name not in skills or name not in recipes:
            errors.append(f'{name}: missing lock entry or recipe')
            continue
        entry = skills[name]
        recipe = yaml.safe_load(recipes[name].read_text())
        package, source = recipe.get('package', {}), recipe.get('source', {})
        if package.get('name') != name or str(package.get('version')) != entry['version']:
            errors.append(f'{name}: package name or version differs from lock')
        commit = entry['commit']
        if source.get('rev') != commit and not source.get('url', '').endswith(f'/{commit}.tar.gz'):
            errors.append(f'{name}: source commit differs from lock')
    return errors


def main():
    lock = yaml.safe_load(Path('skill-lock.yaml').read_text())
    errors = verify(lock, Path('skill-recipes'))
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'Validated {len(lock["skills"])} skill recipes against lock')
    return 0


if __name__ == '__main__':
    sys.exit(main())
