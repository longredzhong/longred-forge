#!/usr/bin/env python3
"""Build recipes using rattler-build (Python replacement for .tasks/build.ts).

Usage examples:
  python scripts/build.py --target-platforms linux-64
  python scripts/build.py --recipe-path recipes/hatchet-cli/recipe.yaml --target-platforms linux-64 --no-upload
"""
import argparse
import glob
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import httpx  # type: ignore
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
    if recipe_path:
        return [Path(recipe_path)]
    recipes = list(Path("recipes").rglob("recipe.yaml"))
    return recipes


def write_generated_recipe(recipe_path: Path, generated_dir: Path):
    txt = recipe_path.read_text()
    data = yaml.safe_load(txt)
    generated_dir.mkdir(parents=True, exist_ok=True)
    out_path = generated_dir / "recipe.yaml"
    header = "# yaml-language-server: $schema=https://raw.githubusercontent.com/prefix-dev/recipe-format/main/schema.json\n"
    out_text = header + yaml.safe_dump(data, sort_keys=False)
    out_path.write_text(out_text)
    print(f"Written {out_path}")
    return data


def package_exists_in_channel(channel: str, target_platform: str, name: str, version: str) -> bool:
    if not channel or not target_platform or not name or not version:
        return False

    base_url = os.environ.get("PREFIX_DEV_REPO_BASE", "https://prefix.dev").rstrip("/")
    repodata_url = f"{base_url}/channels/{channel}/{target_platform}/repodata.json"

    try:
        resp = httpx.get(repodata_url, timeout=15.0)
        if resp.status_code != 200:
            print(f"⚠️  Could not fetch repodata ({resp.status_code}): {repodata_url}")
            return False

        data = resp.json()
        for section in ("packages", "packages.conda"):
            entries = data.get(section, {})
            if not isinstance(entries, dict):
                continue
            for record in entries.values():
                if not isinstance(record, dict):
                    continue
                if record.get("name") == name and str(record.get("version")) == version:
                    return True
    except Exception as e:
        print(f"⚠️  Failed to check prefix.dev repodata: {e}")

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

        if build_flag and skip_existing:
            if package_exists_in_channel(channel, target_platform, recipe_name, version):
                print(
                    f"✓ {recipe_name} {version} already exists on {channel}/{target_platform}; skipping build"
                )
                return

        if build_flag:
            # run rattler-build
            cmd = ["rattler-build", "build", "-r", str(recipe_yaml_out), "--target-platform", target_platform, "--test", "native", "-c", "conda-forge"]
            run(cmd)
            print(f"✓ Built for {target_platform}")

            if upload_flag:
                prefix_token = os.environ.get("PREFIX_API_KEY") or os.environ.get("PREFIX_TOKEN")
                if not prefix_token:
                    print("⚠️  PREFIX_API_KEY/PREFIX_TOKEN not found in environment; skipping upload")
                    return

                # find artifact
                pattern = f"output/{target_platform}/{recipe_name}-{version}-*_0.conda"
                files = list(Path(".").glob(pattern))
                if not files:
                    print("No artifacts found to upload")
                    return
                artifact = str(files[0])

                env = os.environ.copy()
                env["PREFIX_API_KEY"] = prefix_token

                print(f"✓ API key found: {prefix_token[:5]}...")

                upload_cmd = ["rattler-build", "upload", "prefix", "-c", channel, artifact]
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
