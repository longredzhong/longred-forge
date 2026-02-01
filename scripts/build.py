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
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import yaml  # type: ignore

# Fix Windows encoding issue - ensure UTF-8 output
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


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


def package_exists_locally(target_platform: str, name: str, version: str) -> bool:
    """Check if package file already exists locally in output directory."""
    pattern = f"output/{target_platform}/{name}-{version}-*_*.conda"
    files = list(Path(".").glob(pattern))
    if files:
        print(f"✓ {files[0].name} already built locally")
        return True
    return False


def build_recipe(
    recipe_yaml_path: Path,
    target_platform: str,
    channel: str,
    upload_flag: bool,
    build_flag: bool,
    skip_existing: bool,
):
    recipe_dir = recipe_yaml_path.parent
    recipe_name = recipe_dir.name
    print(f"::group::{recipe_name}-{target_platform}")
    try:
        recipe_content = yaml.safe_load(recipe_yaml_path.read_text())
        version = str(recipe_content.get("context", {}).get("version"))
        package_name = str(recipe_content.get("package", {}).get("name") or recipe_name)
        generated_recipe_dir = recipe_dir / f"generated/{target_platform}"
        # clear dir
        if generated_recipe_dir.exists():
            shutil.rmtree(generated_recipe_dir)
        generated_recipe_dir.mkdir(parents=True, exist_ok=True)

        recipe_yaml_out = generated_recipe_dir / "recipe.yaml"
        # write with schema header
        header = "# yaml-language-server: $schema=https://raw.githubusercontent.com/prefix-dev/recipe-format/main/schema.json\n"
        out_text = header + yaml.safe_dump(recipe_content, sort_keys=False)
        recipe_yaml_out.write_text(out_text)
        print(f"Written {recipe_yaml_out}")

        if build_flag:
            # Check local cache first before invoking rattler-build
            if skip_existing and package_exists_locally(target_platform, package_name, version):
                print(f"✓ {package_name} {version} already exists locally; skipping build")
                print("::endgroup::")
                return

            # Build the channel URL for prefix.dev
            channel_url = f"https://repo.prefix.dev/{channel}"

            # Run rattler-build with --skip-existing all to check remote channel
            # Add the target channel for remote existence check
            cmd = [
                "rattler-build",
                "build",
                "-r",
                str(recipe_yaml_out),
                "--target-platform",
                target_platform,
                "--test",
                "native",
                "-c",
                channel_url,  # Add target channel first for skip-existing check
                "-c",
                "conda-forge",
                "--skip-existing",
                "all" if skip_existing else "none",
            ]
            run(cmd)
            print(f"✓ Built for {target_platform}")

            if upload_flag:
                prefix_token = os.environ.get("PREFIX_API_KEY") or os.environ.get("PREFIX_TOKEN")
                if not prefix_token:
                    print("⚠️  PREFIX_API_KEY/PREFIX_TOKEN not found in environment; skipping upload")
                    print("::endgroup::")
                    return

                # find artifact - match any build number
                pattern = f"output/{target_platform}/{package_name}-{version}-*_*.conda"
                files = list(Path(".").glob(pattern))
                if not files:
                    # Package might have been skipped due to --skip-existing all
                    print(f"✓ No new artifacts to upload (package may already exist in {channel})")
                    print("::endgroup::")
                    return
                artifact = str(files[0])

                env = os.environ.copy()
                env["PREFIX_API_KEY"] = prefix_token

                print(f"✓ API key found: {prefix_token[:5]}...")

                upload_cmd = ["rattler-build", "upload", "prefix", "-c", channel, "--skip-existing", artifact]
                run(upload_cmd, env=env)
                print(f"✓ Uploaded {Path(artifact).name}")

                gha_summary = os.environ.get("GITHUB_STEP_SUMMARY")
                if gha_summary:
                    with open(gha_summary, "a") as f:
                        f.write(f"- :rocket: `{target_platform}/{Path(artifact).name}`: **published**\n")

    except Exception as e:
        print(f"::error title={recipe_yaml_path}::recipe failed to cook")
        print(e)
        print("::endgroup::")
        raise
    print("::endgroup::")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe-path", dest="recipe_path", help="Specific recipe to build")
    parser.add_argument("--channel", default="longred-forge")
    parser.add_argument("--target-platforms", nargs="*", default=None)
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
    os.environ.update(env_vars)

    platforms = args.target_platforms or (["linux-64"])

    recipes = find_recipes(args.recipe_path)
    for recipe in recipes:
        for target in platforms:
            build_recipe(
                recipe,
                target,
                args.channel,
                not args.no_upload,
                not args.no_build,
                args.skip_existing,
            )


if __name__ == "__main__":
    main()
