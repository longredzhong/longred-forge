"""Render real recipes for every supported target without building or publishing."""

import argparse
from pathlib import Path

if __package__:
    from .forge.planner import PLATFORMS, changed_recipes, render
else:
    from forge.planner import PLATFORMS, changed_recipes, render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe-path')
    parser.add_argument('--changed-since')
    args = parser.parse_args()
    recipes = [Path(args.recipe_path)] if args.recipe_path else sorted(Path('recipes').glob('*/recipe.yaml'))
    if args.changed_since and not args.recipe_path:
        recipes = changed_recipes(args.changed_since)
    failures = []
    for recipe in recipes:
        for target in PLATFORMS:
            try:
                artifacts = render(recipe, target)
                print(f'{recipe} {target}: {"valid" if artifacts else "unsupported"}')
            except Exception as exc:
                print(f'{recipe} {target}: {exc}')
                failures.append((recipe, target))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
