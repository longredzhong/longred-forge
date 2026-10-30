"""Release providers, exact asset lookup, and strict SHA-256 resolution."""
import hashlib
import re
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlsplit

from .http import ASSET_DOWNLOAD_TIMEOUT, DEFAULT_HTTP_TIMEOUT, HTTPClient

CLAUDE_CODE_GCS_BUCKET = "https://storage.googleapis.com/claude-code-dist-86c565f3-f756-42ad-8dfa-d59b1c096819/claude-code-releases"
VALID_ASSET_BASENAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_+.-]*[A-Za-z0-9_+-])?$")


def validate_sha256(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("Invalid SHA256 (expected exactly 64 hexadecimal characters)")
    return value.lower()


def download_headers(url: str, headers: Dict[str, str]) -> Dict[str, str]:
    # Tokens supplied for the API must not be sent to asset/CDN/GCS hosts.
    if urlsplit(url).hostname == "api.github.com" and urlsplit(url).scheme == "https":
        return headers
    return {k: v for k, v in headers.items() if k.lower() in {"accept", "user-agent"}}


def get_latest_release(owner: str, repo: str, token: Optional[str]) -> Dict[str, Any]:
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in (owner, repo)):
        raise ValueError("Invalid GitHub owner/repository")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "longred-forge-recipe-updater"}
    if token:
        headers["Authorization"] = f"token {token}"
    return HTTPClient().json(f"https://api.github.com/repos/{owner}/{repo}/releases/latest", headers)


def sha256_hex_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_from_checksum_txt(filename: str, txt: str) -> Optional[str]:
    for line in txt.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[1].lstrip("*") == filename:
            return validate_sha256(parts[0])
        match = re.fullmatch(r"SHA256 \((.+)\) = (\S+)", line.strip())
        if match and match[1] == filename:
            return validate_sha256(match[2])
    return None


def get_gcs_checksums(version: str) -> Dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+", version):
        raise ValueError("Invalid GCS version")
    manifest = HTTPClient().json(f"{CLAUDE_CODE_GCS_BUCKET}/{version}/manifest.json")
    return {platform: validate_sha256(info.get("checksum"))
            for platform, info in manifest.get("platforms", {}).items()}


def gcs_platform_for_if_cond(if_cond: str) -> Optional[str]:
    for os_name, arch, platform in (("linux", "x86_64", "linux-x64"), ("linux", "aarch64", "linux-arm64"),
                                    ("osx", "x86_64", "darwin-x64"), ("osx", "arm64", "darwin-arm64")):
        if os_name in if_cond and arch in if_cond:
            return platform
    return None


def asset_name_for(if_cond: str, version_tag: str, repo: Optional[str] = None) -> Optional[str]:
    """Legacy compatibility shim: asset names must now come from recipe URLs."""
    return None


def asset_name_from_recipe_pattern(recipe_url: Optional[str], if_cond: str, version: Optional[str]) -> Optional[str]:
    if not recipe_url:
        return None
    resolved = re.sub(r"\$\{\{\s*version\s*\}\}", str(version or ""), recipe_url.strip())
    filename = unquote(urlsplit(resolved).path.rsplit("/", 1)[-1])
    if "{" not in filename and ".." not in filename and VALID_ASSET_BASENAME_PATTERN.fullmatch(filename):
        return filename
    return None


def find_asset(assets: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    return next((asset for asset in assets if asset.get("name") == name), None)


def compute_sha_for_asset(asset: Dict[str, Any], headers: Dict[str, str]) -> str:
    digest = asset.get("digest")
    if digest:
        match = re.fullmatch(r"sha-?256:([0-9a-fA-F]{64})", str(digest), re.IGNORECASE)
        if not match:
            raise ValueError("Invalid SHA256 release digest")
        return validate_sha256(match[1])
    name = asset.get("name")
    if not name:
        raise RuntimeError("asset has no name")
    client = HTTPClient()
    for candidate in asset.get("_release_assets_cache", []):
        candidate_name = candidate.get("name", "")
        url = candidate.get("browser_download_url")
        if url and ("sha" in candidate_name.lower() or "checksum" in candidate_name.lower()):
            text = client.text(url, download_headers(url, headers))
            got = digest_from_checksum_txt(name, text)
            if got:
                return got
            if candidate_name in {name + suffix for suffix in (".sha256", ".sha256sum", ".sha256.txt", ".sha256sums")} and len(text.split()) == 1:
                return validate_sha256(text.strip())
    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("asset has no download url")
    return client.sha256(url, download_headers(url, headers))
