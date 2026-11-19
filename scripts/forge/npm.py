"""npm registry provider: dist-tag version resolution, strict semver ordering,
and integrity-verified tarball hashing. Mirrors upstream.py fail-closed rules."""
import base64
import hashlib
import re
from typing import Any, Dict, Tuple

from .http import ASSET_DOWNLOAD_TIMEOUT, HTTPClient
from .upstream import download_headers

NPM_REGISTRY = "https://registry.npmjs.org"
NPM_PACKAGE_NAME_PATTERN = re.compile(r"^(@[a-z0-9-~][a-z0-9-._~]*/)?[a-z0-9-~][a-z0-9-._~]*$")
NPM_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._+-]+$")
# Strict semver: no leading zeros in numeric identifiers, dotted prerelease/build parts.
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:[0-9A-Za-z-]+)(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def validate_npm_package(name: str) -> str:
    """Accept npm package names, including scoped forms like @cloudflare/config."""
    if not isinstance(name, str) or not NPM_PACKAGE_NAME_PATTERN.fullmatch(name.strip()):
        raise ValueError("Invalid npm package name")
    return name.strip()


def validate_npm_version(version: str) -> str:
    if not isinstance(version, str) or not NPM_VERSION_PATTERN.fullmatch(version):
        raise ValueError("Invalid npm version")
    return version


def npm_tarball_url(package: str, version: str) -> str:
    """Registry tarball pattern; scoped packages drop the scope from the filename."""
    package = validate_npm_package(package)
    return f"{NPM_REGISTRY}/{package}/-/{package.rsplit('/', 1)[-1]}-{validate_npm_version(version)}.tgz"


def npm_latest_version(package: str) -> Dict[str, Any]:
    """Resolve the package's `latest` dist-tag and fail closed on any surprise."""
    package = validate_npm_package(package)
    headers = {"Accept": "application/vnd.npm+json", "User-Agent": "longred-forge-recipe-updater"}
    document = HTTPClient().json(f"{NPM_REGISTRY}/{package}/latest", headers)
    if not isinstance(document, dict):
        raise RuntimeError("npm registry returned an unexpected document")
    if document.get("name") != package:
        raise RuntimeError("npm registry document does not match the configured package")
    version = validate_npm_version(document.get("version"))
    dist = document.get("dist")
    if not isinstance(dist, dict) or not str(dist.get("integrity", "")).startswith("sha512-"):
        raise RuntimeError("npm registry document lacks a sha512 integrity value")
    tarball = dist.get("tarball")
    if tarball != npm_tarball_url(package, version):
        raise RuntimeError("npm registry tarball URL does not match the expected pattern")
    return {"version": version, "tarball": tarball, "integrity": dist["integrity"]}


def integrity_sha512_hex(integrity: str) -> str:
    """Decode a sha512-<base64> SRI value to lowercase hex."""
    if not isinstance(integrity, str) or not integrity.startswith("sha512-"):
        raise ValueError("npm integrity must be a sha512-<base64> value")
    digest = base64.b64decode(integrity[len("sha512-"):], validate=True)
    if len(digest) != 64:
        raise ValueError("npm sha512 integrity has an unexpected length")
    return digest.hex()


def npm_tarball_hashes(url: str, headers: Dict[str, str]) -> Tuple[str, str]:
    """Stream the tarball once and return (sha256, sha512) hex digests.

    download_headers keeps GitHub tokens off registry.npmjs.org requests.
    """
    sha256 = hashlib.sha256()
    sha512 = hashlib.sha512()

    def consume(response):
        for chunk in response.iter_bytes():
            sha256.update(chunk)
            sha512.update(chunk)

    HTTPClient().read(url, consume, download_headers(url, headers), ASSET_DOWNLOAD_TIMEOUT)
    return sha256.hexdigest(), sha512.hexdigest()


def semver_key(version: str) -> tuple:
    """Total-order key for strict semver precedence (semver.org section 11).

    Releases outrank prereleases; numeric prerelease identifiers rank below
    alphanumeric ones; numeric identifiers compare numerically; equal prefixes
    rank the longer identifier list higher. Build metadata is ignored.
    """
    match = SEMVER_PATTERN.fullmatch(version if isinstance(version, str) else "")
    if not match:
        raise ValueError(f"Not a strict semver version: {version!r}")
    major, minor, patch, prerelease, _build = match.groups()
    identifiers = tuple(
        (0, int(identifier), "") if identifier.isdigit() else (1, 0, identifier)
        for identifier in (prerelease.split(".") if prerelease else ())
    )
    # A release (empty prerelease) ranks above any prerelease of the same triple.
    return (int(major), int(minor), int(patch), 0 if prerelease else 1, identifiers)


def conda_version_from_npm(version: str) -> str:
    """Map a strict semver version onto a dash-free conda version.

    `1.0.0-rc.1` becomes `1.0.0rc.1` (conda-forge prerelease convention, sorts
    below the future `1.0.0` release); hyphens inside prerelease identifiers
    become underscores; build metadata is dropped.
    """
    match = SEMVER_PATTERN.fullmatch(version if isinstance(version, str) else "")
    if not match:
        raise ValueError(f"Not a strict semver version: {version!r}")
    major, minor, patch, prerelease, _build = match.groups()
    conda = f"{major}.{minor}.{patch}"
    if prerelease:
        conda += prerelease.replace("-", "_")
    return conda
