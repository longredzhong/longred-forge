#!/usr/bin/env python3
"""Update recipe versions from GitHub releases.

Usage: python scripts/update.py --recipe recipes/hatchet-cli/recipe.yaml --owner hatchet-dev --repo hatchet [--apply]
"""
import argparse
import hashlib
import os
import re
import sys
from typing import Any, Dict, List, Optional

import httpx
import yaml  # type: ignore

# Fix Windows encoding issue - ensure UTF-8 output
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# Network defaults: keep CI runs from hanging indefinitely.
DEFAULT_HTTP_TIMEOUT = 30.0
ASSET_DOWNLOAD_TIMEOUT = 120.0

# GCS bucket for claude-code native binaries
CLAUDE_CODE_GCS_BUCKET = "https://storage.googleapis.com/claude-code-dist-86c565f3-f756-42ad-8dfa-d59b1c096819/claude-code-releases"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--recipe", default=None, help="Path to a recipe file. If omitted, all recipes under 'recipes/' will be processed.")
    p.add_argument("--owner", default=None)
    p.add_argument("--repo", default=None)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def get_latest_release(owner: str, repo: str, token: Optional[str]) -> Dict[str, Any]:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"
    # GitHub API best-practice headers
    headers.setdefault("Accept", "application/vnd.github+json")
    headers.setdefault("X-GitHub-Api-Version", "2022-11-28")
    headers.setdefault("User-Agent", "longred-forge-recipe-updater")
    r = httpx.get(url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def sha256_hex_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_from_checksum_txt(filename: str, txt: str) -> Optional[str]:
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        # common formats: <hash> <filename>
        if line.endswith(filename):
            parts = line.split()
            if len(parts) >= 1:
                return parts[0]
    return None


def get_gcs_checksums(version: str) -> Dict[str, str]:
    """Fetch SHA-256 checksums from GCS manifest.json for a given claude-code version.

    Returns a dict mapping GCS platform names to sha256 hex strings, e.g.:
      {"linux-x64": "abc123...", "linux-arm64": "def456...", ...}
    """
    manifest_url = f"{CLAUDE_CODE_GCS_BUCKET}/{version}/manifest.json"
    r = httpx.get(manifest_url, timeout=DEFAULT_HTTP_TIMEOUT)
    r.raise_for_status()
    manifest = r.json()
    platforms = manifest.get("platforms", {})
    result: Dict[str, str] = {}
    for platform, info in platforms.items():
        if not isinstance(info, dict):
            continue
        checksum = info.get("checksum", "")
        if checksum:
            result[platform] = checksum
        else:
            print(f"Warning: missing checksum for platform {platform} in GCS manifest")
    return result


def gcs_platform_for_if_cond(if_cond: str) -> Optional[str]:
    """Map a recipe if-condition string to the corresponding GCS platform name."""
    if "linux" in if_cond and "x86_64" in if_cond:
        return "linux-x64"
    if "linux" in if_cond and "aarch64" in if_cond:
        return "linux-arm64"
    if "osx" in if_cond and "x86_64" in if_cond:
        return "darwin-x64"
    if "osx" in if_cond and "arm64" in if_cond:
        return "darwin-arm64"
    return None


def asset_name_for(if_cond: str, version_tag: str, repo: Optional[str] = None) -> Optional[str]:
    v = version_tag.lstrip("v")
    # Support multiple naming patterns for different tools

    if repo and repo.lower() == "hatchet":
        # Hatchet pattern: hatchet_<version>_<OS>_<ARCH>.tar.gz
        if "linux" in if_cond and "x86_64" in if_cond:
            return f"hatchet_{v}_Linux_x86_64.tar.gz"
        if "linux" in if_cond and "aarch64" in if_cond:
            return f"hatchet_{v}_Linux_arm64.tar.gz"
        if "osx" in if_cond and "x86_64" in if_cond:
            return f"hatchet_{v}_Darwin_x86_64.tar.gz"
        if "osx" in if_cond and "arm64" in if_cond:
            return f"hatchet_{v}_Darwin_arm64.tar.gz"

    if repo and repo.lower() == "copilot-cli":
        # Copilot-CLI pattern: copilot-<os>-<arch>.tar.gz
        if "linux" in if_cond and "x86_64" in if_cond:
            return f"copilot-linux-x64.tar.gz"
        if "linux" in if_cond and "aarch64" in if_cond:
            return f"copilot-linux-arm64.tar.gz"
        if "osx" in if_cond and "x86_64" in if_cond:
            return f"copilot-darwin-x64.tar.gz"
        if "osx" in if_cond and "arm64" in if_cond:
            return f"copilot-darwin-arm64.tar.gz"

    if repo and repo.lower() == "opencode":
        # OpenCode pattern: opencode-<os>-<arch>.tar.gz or .zip
        if "linux" in if_cond and "x86_64" in if_cond:
            return f"opencode-linux-x64.tar.gz"
        if "linux" in if_cond and "aarch64" in if_cond:
            return f"opencode-linux-arm64.tar.gz"
        if "osx" in if_cond and "x86_64" in if_cond:
            return f"opencode-darwin-x64.zip"
        if "osx" in if_cond and "arm64" in if_cond:
            return f"opencode-darwin-arm64.zip"

    if repo and repo.lower() == "radar":
        # Radar pattern: radar_v<version>_<os>_<arch>.tar.gz
        if "linux" in if_cond and "x86_64" in if_cond:
            return f"radar_v{v}_linux_amd64.tar.gz"
        if "linux" in if_cond and "aarch64" in if_cond:
            return f"radar_v{v}_linux_arm64.tar.gz"
        if "osx" in if_cond and "x86_64" in if_cond:
            return f"radar_v{v}_darwin_amd64.tar.gz"
        if "osx" in if_cond and "arm64" in if_cond:
            return f"radar_v{v}_darwin_arm64.tar.gz"

    if repo and repo.lower() == "garage-webui":
        # garage-webui pattern: garage-webui-v<version>-linux-<arch>
        if "linux" in if_cond and "x86_64" in if_cond:
            return f"garage-webui-v{v}-linux-amd64"
        if "linux" in if_cond and "arm64" in if_cond:
            return f"garage-webui-v{v}-linux-arm64"

    return None


def asset_name_from_recipe_pattern(recipe_url: Optional[str], if_cond: str, version: Optional[str]) -> Optional[str]:
    """Extract asset name pattern from recipe source URL, substituting the version placeholder."""
    if not recipe_url:
        return None
    # Extract pattern like copilot-linux-x64.tar.gz or radar_v${{ version }}_linux_amd64.tar.gz
    import re
    # Substitute version placeholder with provided version (if available)
    url_pattern = recipe_url.replace("${{ version }}", str(version) if version is not None else "")
    url_pattern = url_pattern.strip()
    if "{" in url_pattern:  # Skip if unresolved other variables remain
        return None
    # Extract just the filename
    m = re.search(r'/([^/]+\.(?:tar\.gz|zip))$', url_pattern)
    if m:
        return m.group(1)
    return None


def find_asset(assets: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    for a in assets:
        if a.get("name") == name:
            return a
    return None


def compute_sha_for_asset(asset: Dict[str, Any], headers: Dict[str, str]) -> str:
    # Use asset.digest if present
    digest = asset.get("digest")
    if digest:
        m = re.search(r"sha-?256:?(.*)", str(digest), re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # Look for checksum asset
    asset_name: Optional[str] = asset.get("name")
    if not asset_name:
        raise RuntimeError("asset has no name")
    # try common checksum suffixes
    possible_suffixes = [".sha256", ".sha256sum", ".sha256.txt", ".sha256sums"]
    release_assets: List[Dict[str, Any]] = asset.get("_release_assets_cache") or []
    for s in possible_suffixes:
        candidate = next((x for x in release_assets if x.get("name") == asset_name + s), None)
        if candidate:
            candidate_url: Optional[str] = candidate.get("browser_download_url")
            if candidate_url:
                txt = httpx.get(candidate_url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT).text
                got = digest_from_checksum_txt(asset_name, txt)
                if got:
                    return got

    # Try to find any checksum file in the release assets that contains the filename
    for cand in release_assets:
        cand_name: Optional[str] = cand.get("name")
        if cand_name and ("sha" in cand_name.lower() or "checksum" in cand_name.lower()):
            cand_url: Optional[str] = cand.get("browser_download_url")
            if cand_url:
                txt = httpx.get(cand_url, headers=headers, timeout=DEFAULT_HTTP_TIMEOUT).text
                got = digest_from_checksum_txt(asset_name, txt)
                if got:
                    return got

    # Last resort: download asset and compute
    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("asset has no download url")
    r = httpx.get(url, headers=headers, timeout=ASSET_DOWNLOAD_TIMEOUT)
    r.raise_for_status()
    return sha256_hex_bytes(r.content)


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


def update_single_recipe(recipe_path: str, owner: Optional[str], repo: Optional[str], headers: Dict[str, str], token: Optional[str], apply: bool, dry: bool) -> None:
    """Update a single recipe file in-place (or show preview if dry)."""
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
        owner = owner_from_recipe
        repo = repo_from_recipe

    if not owner or not repo:
        print("Owner/repo not set and not found in recipe. Skipping this recipe.")
        return

    release = get_latest_release(owner, repo, token)
    tag = release.get("tag_name")
    if not tag:
        print("No tag_name found in release; skipping")
        return
    version = tag.lstrip("v")
    print(f"Latest upstream release: {tag}")

    if doc.get("context", {}).get("version") == version:
        print(f"Recipe already at version {version}")
        return

    # update version
    doc.setdefault("context", {})
    doc["context"]["version"] = str(version)

    assets = release.get("assets", [])
    # attach release assets cache for checksum lookups
    for a in assets:
        a["_release_assets_cache"] = assets

    # Pre-fetch GCS checksums if any source URL references the claude-code GCS bucket
    gcs_checksums: Optional[Dict[str, str]] = None

    if isinstance(doc.get("source"), list):
        for src in doc["source"]:
            if not isinstance(src, dict):
                continue
            
            # Handle two types of source structures:
            # 1. Simple: source has url/sha256 directly
            # 2. Conditional: source has if/then structure
            
            items_to_process: List[Dict[str, Any]] = []
            if_cond = ""
            
            if "then" in src:
                # Conditional structure with if/then
                if_cond = src.get("if", "")
                then_list = src.get("then") or []
                items_to_process = then_list
            elif "url" in src:
                # Simple structure with url directly
                items_to_process = [src]
            
            for item in items_to_process:
                if not isinstance(item, dict):
                    continue
                if not item.get("url"):
                    continue
                
                # For simple single-file downloads (like gemini.js), extract filename from URL
                recipe_url: Optional[str] = item.get("url")
                if not recipe_url:
                    continue

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
                            print(f"Failed to fetch GCS checksums: {e}")
                            gcs_checksums = {}
                    gcs_platform = gcs_platform_for_if_cond(if_cond)
                    if gcs_platform and gcs_checksums.get(gcs_platform):
                        sha = gcs_checksums[gcs_platform]
                        print(f"Using GCS sha for {gcs_platform}: {sha}")
                        item["sha256"] = sha
                    else:
                        print(f"GCS checksum not found for platform: {gcs_platform}")
                    continue
                
                # Try hardcoded patterns first (for known repos like hatchet), then try URL-based pattern
                expected = asset_name_for(if_cond, tag, repo)
                if not expected:
                    # Try to infer from recipe URL pattern
                    expected = asset_name_from_recipe_pattern(recipe_url, if_cond, version)
                
                # For simple URLs, extract the filename directly
                if not expected and not if_cond:
                    import re
                    m = re.search(r'/([^/]+)$', recipe_url)
                    if m:
                        expected = m.group(1)
                
                if not expected:
                    print(f"Could not determine asset name for url: {recipe_url}")
                    continue
                
                asset = find_asset(assets, expected)
                if not asset:
                    print(f"No matching asset found for {expected}")
                    continue
                try:
                    sha = compute_sha_for_asset(asset, headers)
                except Exception as e:
                    print(f"Failed to compute sha for {expected}: {e}")
                    continue
                print(f"Using sha for {expected}: {sha}")
                item["sha256"] = sha

    out = "# yaml-language-server: $schema=https://raw.githubusercontent.com/prefix-dev/recipe-format/main/schema.json\n" + yaml.safe_dump(doc, sort_keys=False)

    if dry:
        print("--- Updated recipe preview ---")
        print(out)
        print("--- end preview ---")
        print("(dry-run) not writing changes for this recipe")
        return

    with open(recipe_path, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"Wrote updated recipe with version {version}")


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

    if recipe_path:
        # Single recipe
        print(f"Reading recipe: {os.path.abspath(recipe_path)}")
        update_single_recipe(recipe_path, owner, repo, headers, token, apply, dry)
        return

    # No recipe specified: update all recipes under recipes/*/recipe.yaml
    import glob

    pattern = os.path.join("recipes", "*", "recipe.yaml")
    files = glob.glob(pattern)
    if not files:
        print("No recipes found to process")
        return

    for fp in sorted(files):
        try:
            update_single_recipe(fp, owner, repo, headers, token, apply, dry)
        except Exception as e:
            print(f"Failed to update {fp}: {e}")


if __name__ == "__main__":
    main()
