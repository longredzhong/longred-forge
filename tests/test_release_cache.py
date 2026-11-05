"""Release cache behavior across independent updater runs."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from scripts.forge import upstream
from scripts.forge.http import HTTPClient


def release(tag):
    return {"tag_name": tag, "draft": False, "prerelease": False, "assets": []}


class ReleaseCacheTests(unittest.TestCase):
    def test_incremental_http_error_does_not_advance_or_reuse_cache(self):
        fail = False
        def handler(request):
            if "/tags/" in request.url.path:
                return httpx.Response(200, json=release("v1.2.3"))
            if fail:
                return httpx.Response(503)
            return httpx.Response(200, json=[release("v1.2.3")] * 30 if int(request.url.params["page"]) == 1 else [])

        client = HTTPClient(transport=httpx.MockTransport(handler), attempts=1)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"RELEASE_CACHE_DIR": tmp}), \
                patch.object(upstream, "HTTPClient", return_value=client):
            upstream.get_release_for_major("example", "tool", None, 1)
            cache = next(Path(tmp).glob('*.json'))
            previous = cache.read_bytes()
            fail = True
            with self.assertRaises(httpx.HTTPStatusError):
                upstream.get_release_for_major("example", "tool", None, 1)
            self.assertEqual(cache.read_bytes(), previous)

    def test_incremental_rechecks_cached_tag_and_periodically_audits_history(self):
        pages = [[release("v1.1.0")] * 30 for _ in range(3)] + [[release("v1.99.0")]]
        calls = []
        def handler(request):
            calls.append(request.url.path)
            if "/tags/" in request.url.path:
                return httpx.Response(200, json=release(request.url.path.rsplit("/", 1)[-1]))
            return httpx.Response(200, json=pages[int(request.url.params["page"]) - 1])

        client = HTTPClient(transport=httpx.MockTransport(handler))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"RELEASE_CACHE_DIR": tmp}), \
                patch.object(upstream, "HTTPClient", return_value=client), patch.object(upstream.time, "time", return_value=100000):
            self.assertEqual(upstream.get_release_for_major("example", "tool", "token", 1)["tag_name"], "v1.99.0")
            self.assertEqual(len(calls), 4)
            calls.clear()
            pages[0][0] = release("v1.100.0")
            pages[3] = [release("v1.101.0")]
            self.assertEqual(upstream.get_release_for_major("example", "tool", "token", 1)["tag_name"], "v1.100.0")
            self.assertEqual(len(calls), 4)  # one tag plus three pages
            cache = json.loads(next(Path(tmp).glob('*.json')).read_text())
            self.assertEqual(cache["audited_at"], 100000)  # incremental runs never postpone the audit
            self.assertNotIn("token", json.dumps(cache))
            calls.clear()
            with patch.object(upstream.time, "time", return_value=100000 + upstream.RELEASES_AUDIT_SECONDS):
                self.assertEqual(upstream.get_release_for_major("example", "tool", "token", 1)["tag_name"], "v1.101.0")
            self.assertEqual(len(calls), 4)

    def test_missing_cached_release_forces_full_scan(self):
        calls = []
        def handler(request):
            calls.append(request.url.path)
            if "/tags/" in request.url.path:
                return httpx.Response(404)
            page = int(request.url.params["page"])
            return httpx.Response(200, json=[release("rust-v0.1.0")] * 30 if page <= 3 else [release("rust-v0.2.0")])

        client = HTTPClient(transport=httpx.MockTransport(handler))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"RELEASE_CACHE_DIR": tmp}), \
                patch.object(upstream, "HTTPClient", return_value=client):
            self.assertEqual(upstream.get_release_for_prefix("example", "tool", None, "rust-v")["tag_name"], "rust-v0.2.0")
            calls.clear()
            self.assertEqual(upstream.get_release_for_prefix("example", "tool", None, "rust-v")["tag_name"], "rust-v0.2.0")
            self.assertEqual(len(calls), 5)


if __name__ == "__main__":
    unittest.main()
