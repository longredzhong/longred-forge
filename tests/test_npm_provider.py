"""Offline coverage for the npm registry update provider."""
import base64
import hashlib
import unittest
from unittest.mock import patch

import httpx

from scripts.forge import npm
from scripts.forge.http import HTTPClient


def integrity_for(data: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")


class ValidationTests(unittest.TestCase):
    def test_package_names(self):
        self.assertEqual(npm.validate_npm_package("cf"), "cf")
        self.assertEqual(npm.validate_npm_package(" @cloudflare/config "), "@cloudflare/config")
        for bad in ("CF", "../x", "cf/", "@scope/", "", None, 42, "cf&"):
            with self.assertRaises(ValueError):
                npm.validate_npm_package(bad)

    def test_versions(self):
        self.assertEqual(npm.validate_npm_version("1.0.0-rc.1"), "1.0.0-rc.1")
        for bad in ("", None, 42, "1.0.0 rc.1", "../evil"):
            with self.assertRaises(ValueError):
                npm.validate_npm_version(bad)

    def test_tarball_urls(self):
        self.assertEqual(npm.npm_tarball_url("cf", "1.0.0-rc.1"),
                         "https://registry.npmjs.org/cf/-/cf-1.0.0-rc.1.tgz")
        self.assertEqual(npm.npm_tarball_url("@cloudflare/config", "0.1.30"),
                         "https://registry.npmjs.org/@cloudflare/config/-/config-0.1.30.tgz")
        for bad_package in ("CF", "", None):
            with self.assertRaises(ValueError):
                npm.npm_tarball_url(bad_package, "1.0.0")


class LatestVersionTests(unittest.TestCase):
    def document(self, **overrides):
        data = b"tarball-bytes"
        body = {"name": "cf", "version": "1.0.0-rc.1",
                "dist": {"integrity": integrity_for(data),
                         "tarball": npm.npm_tarball_url("cf", "1.0.0-rc.1")}}
        body.update(overrides)
        return body

    def select(self, body, status=200, package="cf"):
        requests = []

        def handler(request):
            requests.append(request)
            if status != 200:
                return httpx.Response(status)
            return httpx.Response(200, json=body)

        client = HTTPClient(transport=httpx.MockTransport(handler))
        with patch.object(npm, "HTTPClient", return_value=client):
            return npm.npm_latest_version(package), requests

    def test_happy_path_fails_closed_on_surprises(self):
        result, requests = self.select(self.document())
        self.assertEqual(result["version"], "1.0.0-rc.1")
        self.assertEqual(result["tarball"], npm.npm_tarball_url("cf", "1.0.0-rc.1"))
        self.assertEqual(requests[0].url.path, "/cf/latest")
        self.assertEqual(requests[0].headers["Accept"], "application/vnd.npm+json")
        self.assertNotIn("authorization", requests[0].headers)
        with self.assertRaises(httpx.HTTPStatusError):
            self.select(self.document(), status=404)
        for error, overrides in (
            (ValueError, {"version": None}),
            (ValueError, {"version": "1.0.0 rc"}),
            (RuntimeError, {"name": "other"}),
            (RuntimeError, {"dist": {"integrity": "sha1-abc", "tarball": npm.npm_tarball_url("cf", "1.0.0-rc.1")}}),
            (RuntimeError, {"dist": {"integrity": integrity_for(b"tarball-bytes"), "tarball": "https://evil.example.org/cf.tgz"}}),
            (RuntimeError, {"dist": None}),
        ):
            with self.assertRaises(error):
                self.select(self.document(**overrides))
        with self.assertRaises(RuntimeError):
            self.select([{"not": "a manifest"}])

    def test_integrity_decode(self):
        data = bytes(range(64))
        encoded = integrity_for(data)
        self.assertEqual(npm.integrity_sha512_hex(encoded), hashlib.sha512(data).hexdigest())
        for bad in ("sha256-" + base64.b64encode(data).decode("ascii"), "sha512-AAAA",
                    None, 42):
            with self.assertRaises(ValueError):
                npm.integrity_sha512_hex(bad)


class TarballHashTests(unittest.TestCase):
    def hashes(self, data, url="https://registry.npmjs.org/cf/-/cf-1.0.0-rc.1.tgz", headers=None):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, content=data)

        client = HTTPClient(transport=httpx.MockTransport(handler))
        with patch.object(npm, "HTTPClient", return_value=client):
            return npm.npm_tarball_hashes(url, headers or {}), requests

    def test_streamed_dual_hashes_and_token_hygiene(self):
        (sha256, sha512), requests = self.hashes(
            b"asset-bytes", headers={"Authorization": "token secret", "Accept": "*/*"})
        self.assertEqual(sha256, hashlib.sha256(b"asset-bytes").hexdigest())
        self.assertEqual(sha512, hashlib.sha512(b"asset-bytes").hexdigest())
        self.assertNotIn("authorization", requests[0].headers)


class SemverTests(unittest.TestCase):
    def test_semver_spec_precedence(self):
        # Official semver.org section 11 ordering example.
        expected = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta",
                    "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
        self.assertEqual(sorted(expected, key=npm.semver_key), expected)
        self.assertEqual(sorted(reversed(expected), key=npm.semver_key), expected)

    def test_rc_numbering_and_releases(self):
        expected = ["1.0.0-beta.32", "1.0.0-rc.1", "1.0.0-rc.2", "1.0.0-rc.10", "1.0.0", "1.1.0"]
        self.assertEqual(sorted(reversed(expected), key=npm.semver_key), expected)

    def test_build_metadata_ignored_and_non_semver_rejected(self):
        self.assertEqual(npm.semver_key("1.0.0+build.5"), npm.semver_key("1.0.0"))
        for bad in ("1.0", "v1.0.0", "1.0.0-", "01.0.0", "1.0.0-rc..1", "", None, "cf@1.0.0"):
            with self.assertRaises(ValueError):
                npm.semver_key(bad)

    def test_conda_version_transforms(self):
        self.assertEqual(npm.conda_version_from_npm("1.0.0-rc.1"), "1.0.0rc.1")
        self.assertEqual(npm.conda_version_from_npm("1.0.0-beta.32"), "1.0.0beta.32")
        self.assertEqual(npm.conda_version_from_npm("1.0.0"), "1.0.0")
        self.assertEqual(npm.conda_version_from_npm("1.0.0-beta-2+build"), "1.0.0beta_2")
        self.assertEqual(npm.conda_version_from_npm("1.0.0-rc.1+meta-data"), "1.0.0rc.1")
        for bad in ("1.0.0-", "01.2.3", "", None):
            with self.assertRaises(ValueError):
                npm.conda_version_from_npm(bad)


if __name__ == "__main__":
    unittest.main()
