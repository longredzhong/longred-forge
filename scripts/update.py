#!/usr/bin/env python3
"""Update recipe versions from GitHub releases.

Usage: python scripts/update.py --recipe recipes/hatchet-cli/recipe.yaml [--apply]

Default/dry-run previews are validated with rattler-build for all five targets.
--apply replaces each recipe atomically only after every source and render succeeds.
--refresh-checksums explicitly revalidates unchanged versions. --report PATH writes
JSON per-recipe statuses; any failure makes the batch exit nonzero after continuing.
"""
import argparse
import glob
import json
import stat
import subprocess
import tempfile
from pathlib import Path
import os
import re
import sys
from typing import Any, Dict, List, Optional

import yaml  # type: ignore

# Fix Windows encoding issue - ensure UTF-8 output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


# Re-export provider helpers to preserve the scripts.update API and patch points.
if __package__:
    from .forge.upstream import (
        ASSET_DOWNLOAD_TIMEOUT, DEFAULT_HTTP_TIMEOUT, CLAUDE_CODE_GCS_BUCKET,
        VALID_ASSET_BASENAME_PATTERN, asset_name_for, asset_name_from_recipe_pattern,
        compute_sha_for_asset, digest_from_checksum_txt, find_asset, get_gcs_checksums,
        get_latest_release, get_release_for_major, gcs_platform_for_if_cond, sha256_hex_bytes, validate_sha256,
    )
else:
    from forge.upstream import (
        ASSET_DOWNLOAD_TIMEOUT, DEFAULT_HTTP_TIMEOUT, CLAUDE_CODE_GCS_BUCKET,
        VALID_ASSET_BASENAME_PATTERN, asset_name_for, asset_name_from_recipe_pattern,
        compute_sha_for_asset, digest_from_checksum_txt, find_asset, get_gcs_checksums,
        get_latest_release, get_release_for_major, gcs_platform_for_if_cond, sha256_hex_bytes, validate_sha256,
    )

TARGET_PLATFORMS = ("linux-64", "linux-aarch64", "osx-64", "osx-arm64", "win-64")


def validate_and_write(recipe_path: str, out: str, write: bool) -> None:
    """Render all five targets beside the recipe, then atomically replace it.

    A sibling candidate preserves relative scripts, patches, and other resources.
    Dry runs perform the same validation but never replace the original.
    """
    path = Path(recipe_path)
    candidate = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".yaml",
                                         prefix=".update-", dir=path.parent, delete=False) as handle:
            candidate = Path(handle.name)
            handle.write(out)
            handle.flush()
            os.fsync(handle.fileno())
        candidate.chmod(stat.S_IMODE(path.stat().st_mode))
        for platform in TARGET_PLATFORMS:
            subprocess.run(["rattler-build", "build", "--recipe", str(candidate),
                            "--target-platform", platform, "--render-only"],
                           check=True, capture_output=True, text=True, timeout=120)
        if write:
            os.replace(candidate, path)
    finally:
        if candidate is not None:
            candidate.unlink(missing_ok=True)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--recipe", default=None, help="Path to a recipe file. If omitted, all recipes under 'recipes/' will be processed.")
    p.add_argument("--owner", default=None)
    p.add_argument("--repo", default=None)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--refresh-checksums", action="store_true", help="Explicitly revalidate assets even when the version is unchanged")
    p.add_argument("--report", help="Write structured per-recipe JSON results")
    return p.parse_args()


def parse_owner_repo_from_url(url: str):
    """Parse owner/repo from common repository URL forms."""
    if not url:
        return None
    url = url.strip()
    m = re.match(r"git@github.com:(?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?", url)
    if m:
        return m.group("owner"), m.group("repo")
    m = re.match(r"https?://github.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)(?:\.git)?", url)
    if m:
        return m.group("owner"), m.group("repo")
    try:
        from urllib.parse import urlparse

        p = urlparse(url)
        parts = [seg for seg in p.path.split("/") if seg]
        if len(parts) >= 2:
            repo_name = parts[1]
            if repo_name.endswith(".git"):
                repo_name = repo_name[:-4]
            return parts[0], repo_name
    except Exception:
        pass
    return None


def checked_source_items(source):
    """Validate every source before changing checksums, preserving YAML structure.

    Local path resources need no upstream checksum. Unknown providers, URL lists,
    nested conditionals and else branches fail closed rather than retaining hashes.
    """
    sources = source if isinstance(source, list) else [source]
    if not sources:
        raise RuntimeError("Recipe has no sources")
    result = []
    for entry in sources:
        if not isinstance(entry, dict):
            raise RuntimeError("Unsupported recipe source type")
        condition = ""
        if "then" in entry or "if" in entry:
            if (set(entry) - {"if", "then"} or not isinstance(entry.get("if"), str)
                    or not entry["if"] or "then" not in entry):
                raise RuntimeError("Unsupported conditional source")
            condition = entry["if"]
            children = entry["then"]
            children = children if isinstance(children, list) else [children]
            if not children:
                raise RuntimeError("Empty conditional source")
        else:
            children = [entry]
        for child in children:
            if not isinstance(child, dict) or any(key in child for key in ("if", "then", "else", "git")):
                raise RuntimeError("Unsupported recipe source")
            if "url" in child:
                if not isinstance(child["url"], str) or not child["url"].strip() or "path" in child:
                    raise RuntimeError("Unsupported recipe URL source")
                result.append((child, condition))
            elif (not isinstance(child.get("path"), str) or not child["path"].strip()
                  or any(key in child for key in ("sha256", "md5", "sha1"))):
                raise RuntimeError("Unsupported recipe source without URL")
    return result


def update_single_recipe(recipe_path: str, owner: Optional[str], repo: Optional[str], headers: Dict[str, str], token: Optional[str], apply: bool, dry: bool, refresh_checksums: bool = False) -> str:
    """Resolve every source and validate before replacing; return a report status."""
    print(f"Processing recipe: {recipe_path}")
    with open(recipe_path, "r", encoding="utf-8") as f:
        raw = f.read()
    doc = yaml.safe_load(raw)

    # Determine owner/repo from recipe if not provided
    repo_url = None
    about = doc.get("about") or {}
    if isinstance(about, dict):
        repo_url = about.get("repository")
    parsed = parse_owner_repo_from_url(repo_url) if repo_url else None
    if parsed:
        owner_from_recipe, repo_from_recipe = parsed
        print(f"Detected owner/repo from recipe: {owner_from_recipe}/{repo_from_recipe}")
        owner = owner or owner_from_recipe
        repo = repo or repo_from_recipe

    if not owner or not repo:
        raise RuntimeError("Owner/repo not set and not found in recipe")

    extra = doc.get("extra") or {}
    update_config = (extra.get("update") or {}) if isinstance(extra, dict) else {}
    major = None
    if isinstance(update_config, dict) and "major" in update_config:
        major = update_config["major"]
        if type(major) is not int or major <= 0:
            raise ValueError("extra.update.major must be a positive integer")

    release = (get_latest_release(owner, repo, token) if major is None
               else get_release_for_major(owner, repo, token, major))
    tag = release.get("tag_name")
    if not tag:
        raise RuntimeError("No tag_name found in release")
    version = tag.lstrip("v")
    print(f"Latest upstream release: {tag}")

    if major is not None:
        current = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(doc.get("context", {}).get("version")))
        selected = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag)
        if not current or not selected:
            raise ValueError("Configured release lines require numeric version triples")
        if tuple(map(int, selected.groups())) < tuple(map(int, current.groups())):
            raise RuntimeError(f"Refusing downgrade from {current[0]} to {tag}")

    if str(doc.get("context", {}).get("version")) == version and not refresh_checksums:
        print(f"Recipe already at version {version}")
        return "unchanged"

    source_items = checked_source_items(doc.get("source"))

    # update version
    doc.setdefault("context", {})
    doc["context"]["version"] = str(version)

    assets = release.get("assets", [])
    # attach release assets cache for checksum lookups
    for a in assets:
        a["_release_assets_cache"] = assets

    # Pre-fetch GCS checksums if any source URL references the claude-code GCS bucket
    gcs_checksums: Optional[Dict[str, str]] = None
    resolved_sources = 0

    for item, if_cond in source_items:
        recipe_url = item["url"]

        # GCS-based source (claude-code): fetch checksums from manifest
        # The URL may use a ${{ gcs_base }} context variable or the literal GCS URL
        ctx_gcs_base = (doc.get("context") or {}).get("gcs_base", "")
        is_gcs_source = (
            CLAUDE_CODE_GCS_BUCKET in recipe_url
            or (ctx_gcs_base and ctx_gcs_base == CLAUDE_CODE_GCS_BUCKET)
        )
        if is_gcs_source:
            if gcs_checksums is None:
                try:
                    gcs_checksums = get_gcs_checksums(version)
                    print(f"Fetched GCS checksums for version {version}")
                except Exception as e:
                    raise RuntimeError("Failed to fetch GCS checksums") from None
            gcs_platform = gcs_platform_for_if_cond(if_cond)
            if gcs_platform and gcs_checksums.get(gcs_platform):
                sha = validate_sha256(gcs_checksums[gcs_platform])
                print(f"Using GCS sha for {gcs_platform}: {sha}")
                item["sha256"] = sha
                resolved_sources += 1
            else:
                raise RuntimeError(f"GCS checksum not found for platform: {gcs_platform}")
            continue

        expected = asset_name_from_recipe_pattern(recipe_url, if_cond, version)

        if not expected:
            raise RuntimeError("Could not determine asset name from recipe URL")

        asset = find_asset(assets, expected)
        if not asset:
            raise RuntimeError(f"No matching asset found for {expected}")
        try:
            sha = compute_sha_for_asset(asset, headers)
        except Exception as e:
            raise RuntimeError("Failed to compute asset checksum") from None
        try:
            sha = validate_sha256(sha)
        except ValueError as exc:
            raise RuntimeError(f"Invalid SHA256 for {expected}") from exc
        print(f"Using sha for {expected}: {sha}")
        item["sha256"] = sha
        resolved_sources += 1

    if not resolved_sources:
        raise RuntimeError("Recipe has no updatable URL sources")

    out = "# yaml-language-server: $schema=https://raw.githubusercontent.com/prefix-dev/recipe-format/main/schema.json\n" + yaml.safe_dump(doc, sort_keys=False)

    validate_and_write(recipe_path, out, apply and not dry)

    if dry or not apply:
        print("--- Updated recipe preview ---")
        print(out)
        print("--- end preview ---")
        print("(dry-run) not writing changes for this recipe")
        return "dry-run"

    print(f"Wrote updated recipe with version {version}")
    return "updated"


def main():
    args = parse_args()
    apply = args.apply
    dry = args.dry_run or not apply

    recipe_path = args.recipe
    owner = args.owner
    repo = args.repo

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_API_TOKEN")
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"

    files = [recipe_path] if recipe_path else sorted(glob.glob(os.path.join("recipes", "*", "recipe.yaml")))
    results = []
    for fp in files:
        try:
            status = update_single_recipe(fp, owner, repo, headers, token, apply, dry, args.refresh_checksums)
            results.append({"recipe": fp, "status": status})
        except Exception as exc:
            # Network exception strings can contain URLs with credentials. Do not log them.
            error = type(exc).__name__
            print(f"Failed to update {fp}: {error}")
            results.append({"recipe": fp, "status": "failed", "error": error})
    failed = sum(result["status"] == "failed" for result in results)
    if args.report:
        report = Path(args.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"recipes": results, "failed": failed}, indent=2) + "\n", encoding="utf-8")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
