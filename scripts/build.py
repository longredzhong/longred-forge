#!/usr/bin/env python3
"""Build recipes using rattler-build.

Usage examples:
  python scripts/build.py --target-platforms linux-64
  python scripts/build.py --recipe-path recipes/hatchet-cli/recipe.yaml --target-platforms linux-64 --no-upload

The script uses rattler-build's --skip-existing option to avoid rebuilding packages
that already exist in the target channel.
"""

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

if __package__:
    from .forge.builder import build_recipe
    from .forge.planner import PLATFORMS, changed_recipes
    from .forge.reporting import write_report
else:
    from forge.builder import build_recipe
    from forge.planner import PLATFORMS, changed_recipes
    from forge.reporting import write_report

# Fix Windows encoding issue - ensure UTF-8 output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def load_dotenv(path: Path):
    if not path.exists():
        return {}
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def run(cmd: List[str], env=None, cwd: Optional[Path] = None, check=True):
    print("$ ", " ".join(shlex.quote(c) for c in cmd))
    res = subprocess.run(cmd, env=env, cwd=cwd)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)} (exit {res.returncode})")
    return res.returncode


def find_recipes(recipe_path: Optional[str]) -> List[Path]:
    """Find recipe.yaml files in the recipes directory.
    
    Only looks for recipe.yaml files directly inside recipe folders (recipes/*/recipe.yaml),
    excluding generated subdirectories to avoid duplicate builds.
    """
    if recipe_path:
        return [Path(recipe_path)]
    # Only match recipes/<recipe-name>/recipe.yaml, not generated subdirectories
    recipes = list(Path("recipes").glob("*/recipe.yaml"))
    return sorted(recipes)



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe-path", dest="recipe_path", help="Specific recipe to build")
    parser.add_argument("--channel", default="longred-forge")
    parser.add_argument("--target-platforms", nargs="*", choices=PLATFORMS, default=None)
    parser.add_argument("--changed-since", help="Build only recipes affected since this git ref")
    parser.add_argument("--report", help="Write machine-readable results")
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--no-build", dest="no_build", action="store_true")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=os.environ.get("SKIP_EXISTING", "0") == "1",
        help="Skip build if package version already exists on prefix.dev",
    )
    args = parser.parse_args()

    # load .env if present
    env_vars = load_dotenv(Path(".env"))
    for key, value in env_vars.items():
        os.environ.setdefault(key, value)

    platforms = args.target_platforms or (["linux-64"])

    recipes = find_recipes(args.recipe_path)
    if args.changed_since and not args.recipe_path:
        recipes = changed_recipes(args.changed_since)
    failures = []
    results = []
    for recipe in recipes:
        for target in platforms:
            try:
                result = build_recipe(
                    recipe,
                    target,
                    args.channel,
                    not args.no_upload,
                    not args.no_build,
                    args.skip_existing,
                )
                if isinstance(result, dict):
                    results.append(result)
            except Exception as exc:
                print(f"::error title={recipe}::{exc}")
                failures.append((recipe, target, str(exc)))
                results.append({'recipe': str(recipe), 'platform': target, 'status': 'failed', 'error': str(exc)})

    write_report(args.report, results)
    if failures:
        summary = "\n".join(f"- `{recipe}` ({target}): **failed**" for recipe, target, _ in failures)
        print(f"Failed builds ({len(failures)}):\n{summary}")
        gha_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if gha_summary:
            with open(gha_summary, "a", encoding="utf-8") as f:
                f.write(f"\n### Failed builds\n{summary}\n")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
