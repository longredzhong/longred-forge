"""Offline updater reliability tests; all workspaces remain inside the checkout."""
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx
import yaml  # type: ignore

from scripts import update
from scripts.forge.http import HTTPClient
from scripts.forge import upstream


class HTTPTests(unittest.TestCase):
    def client(self, handler, **kwargs):
        return HTTPClient(transport=httpx.MockTransport(handler), sleep=lambda _: None, **kwargs)

    def test_retry_transient_and_honor_bounded_delay(self):
        calls, delays = [], []
        def handler(request):
            calls.append(request)
            return httpx.Response(429, headers={"Retry-After": "9999"}) if len(calls) < 3 else httpx.Response(200, json={"ok": True})
        client = self.client(handler)
        client.sleep = delays.append
        self.assertEqual(client.json("https://api.github.com/test"), {"ok": True})
        self.assertEqual(delays, [8, 8])
        self.assertEqual(len(calls), 3)

    def test_transport_retry_exhaustion_and_no_retry_404(self):
        for status, expected in ((503, 3), (404, 1)):
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status)
            with self.assertRaises(httpx.HTTPStatusError):
                self.client(handler).text("https://example.org/test")
            self.assertEqual(len(calls), expected)
        calls = []
        def disconnected(request):
            calls.append(request)
            raise httpx.ReadError("offline")
        with self.assertRaises(httpx.ReadError):
            self.client(disconnected).sha256("https://example.org/test")
        self.assertEqual(len(calls), 3)

    def test_redirect_strips_credentials_and_bounds_loops(self):
        seen = []
        def handler(request):
            seen.append(request)
            if len(seen) == 1:
                return httpx.Response(302, headers={"Location": "https://cdn.example.org/file", "Set-Cookie": "session=secret; Domain=example.org"})
            return httpx.Response(200, content=b"asset")
        digest = self.client(handler).sha256("https://api.github.com/file", {"Authorization": "token secret", "Cookie": "private=yes", "X-Api-Key": "secret"})
        self.assertEqual(digest, hashlib.sha256(b"asset").hexdigest())
        for header in ("authorization", "cookie", "x-api-key"):
            self.assertNotIn(header, seen[1].headers)
        with self.assertRaisesRegex(RuntimeError, "redirect limit"):
            self.client(lambda _: httpx.Response(302, headers={"Location": "/loop"}), max_redirects=2).text("https://example.org/loop")
        with self.assertRaises(ValueError):
            self.client(lambda _: httpx.Response(302, headers={"Location": "http://example.org/file"})).text("https://example.org/file")

    def test_stream_download(self):
        class Chunks(httpx.SyncByteStream):
            def __iter__(self):
                yield b"first"
                yield b"second"
        client = self.client(lambda _: httpx.Response(200, stream=Chunks()))
        self.assertEqual(client.sha256("https://example.org/asset"), hashlib.sha256(b"firstsecond").hexdigest())


class ProviderTests(unittest.TestCase):
    def test_strict_hashes_and_exact_checksum_filenames(self):
        digest = "a" * 64
        self.assertEqual(upstream.digest_from_checksum_txt("tool", digest + "  *tool"), digest)
        self.assertIsNone(upstream.digest_from_checksum_txt("tool", digest + "  other-tool"))
        for value in ("f" * 63, "z" * 64, "f" * 65, "f" * 64 + "\n"):
            with self.assertRaises(ValueError):
                upstream.validate_sha256(value)
            with self.assertRaises(ValueError):
                upstream.compute_sha_for_asset({"digest": "sha256:" + value}, {})
        with patch.object(upstream.HTTPClient, "json", return_value={"platforms": {"linux-x64": {"checksum": "bad"}}}):
            with self.assertRaises(ValueError):
                upstream.get_gcs_checksums("1.0")

    def test_asset_headers_and_url_name(self):
        with patch.object(upstream.HTTPClient, "sha256", return_value="a" * 64) as download:
            upstream.compute_sha_for_asset({"name": "tool", "browser_download_url": "https://cdn.example.org/tool"}, {"Authorization": "token secret"})
        self.assertEqual(download.call_args.args[1], {})
        self.assertEqual(update.asset_name_from_recipe_pattern("https://github.com/o/r/v${{ version }}/different-${{version}}.zip?download=1", "", "2.0"), "different-2.0.zip")


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix=".updater-test-")
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.recipe = self.root / "recipe.yaml"
        self.recipe.write_text('context: {version: "1.0"}\nabout: {repository: "https://github.com/example/tool"}\nsource:\n- url: "https://github.com/example/tool/releases/download/v${{ version }}/unusual-${{ version }}.zip"\n  sha256: ' + 'a' * 64 + '\n', encoding="utf-8")
        self.original = self.recipe.read_bytes()
        self.release = {"tag_name": "v2.0", "assets": [{"name": "unusual-2.0.zip", "digest": "sha256:" + "b" * 64}]}
        self.network = patch.object(update, "get_latest_release", return_value=self.release).start()
        self.addCleanup(patch.stopall)
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def run_update(self, apply=True, dry=False, refresh=False):
        return update.update_single_recipe(str(self.recipe), None, None, {}, None, apply, dry, refresh)

    def test_atomic_success_renders_all_targets_beside_resources(self):
        resource = self.root / "install.py"
        resource.write_text("local resource")
        def render(command, **kwargs):
            candidate = Path(command[command.index("--recipe") + 1])
            self.assertEqual(candidate.parent, self.root)
            self.assertTrue(resource.exists())
            self.assertEqual(self.recipe.read_bytes(), self.original)
            self.assertEqual(yaml.safe_load(candidate.read_text())["context"]["version"], "2.0")
            self.assertIn("--render-only", command)
        with patch.object(update.subprocess, "run", side_effect=render) as run:
            self.assertEqual(self.run_update(), "updated")
        self.assertEqual([call.args[0][5] for call in run.call_args_list], list(update.TARGET_PLATFORMS))
        self.assertEqual(yaml.safe_load(self.recipe.read_text())["source"][0]["sha256"], "b" * 64)
        self.assertEqual(list(self.root.glob(".update-*")), [])

    def test_source_mapping_and_then_mapping_preserve_resources(self):
        original_doc = yaml.safe_load(self.recipe.read_text())
        url_source = original_doc["source"][0]
        for source in (url_source, {"if": "linux", "then": dict(url_source)},
                       [dict(url_source), {"path": "assets", "target_directory": "resources"}]):
            with self.subTest(source=source):
                doc = dict(original_doc)
                doc["source"] = source
                doc["build"] = {"script": {"file": "install.py"}}
                doc["extra"] = {"resources": ["assets/data", "patches/fix.patch"]}
                resources = {"install.py": b"print('install')\n", "assets/data": b"\x00data", "patches/fix.patch": b"patch"}
                for name, content in resources.items():
                    resource = self.root / name
                    resource.parent.mkdir(parents=True, exist_ok=True)
                    resource.write_bytes(content)
                self.recipe.write_text(yaml.safe_dump(doc))
                def render(command, **kwargs):
                    candidate = Path(command[command.index("--recipe") + 1])
                    for name, content in resources.items():
                        self.assertEqual((candidate.parent / name).read_bytes(), content)
                with patch.object(update.subprocess, "run", side_effect=render) as renderer:
                    self.assertEqual(self.run_update(), "updated")
                self.assertEqual(renderer.call_count, 5)
                updated = yaml.safe_load(self.recipe.read_text())
                expected = yaml.safe_load(yaml.safe_dump(doc))
                expected["context"]["version"] = "2.0"
                for item, _ in update.checked_source_items(expected["source"]):
                    item["sha256"] = "b" * 64
                self.assertEqual(updated, expected)
                for name, content in resources.items():
                    self.assertEqual((self.root / name).read_bytes(), content)

    def test_unsupported_sources_never_retain_unchecked_hashes(self):
        original_doc = yaml.safe_load(self.recipe.read_text())
        valid = original_doc["source"][0]
        unsupported = (None, "bad", 42, [], {}, {"sha256": "a" * 64},
                       {"url": [valid["url"]], "sha256": "a" * 64},
                       {"if": "linux", "then": "bad"},
                       {"if": "linux", "then": valid, "else": valid},
                       {"path": "local", "sha256": "a" * 64},
                       [valid, {"git": "https://example.org/repo"}],
                       [valid, {"if": "linux", "then": [valid, None]}])
        for source in unsupported:
            with self.subTest(source=source):
                doc = dict(original_doc)
                doc["source"] = source
                self.recipe.write_text(yaml.safe_dump(doc))
                original = self.recipe.read_bytes()
                with patch.object(update.subprocess, "run") as render:
                    with self.assertRaises(RuntimeError):
                        self.run_update()
                render.assert_not_called()
                self.assertEqual(self.recipe.read_bytes(), original)

    def test_render_or_replace_failure_preserves_original_and_cleans_candidate(self):
        for failure in (subprocess.CalledProcessError(1, "render"), subprocess.TimeoutExpired("render", 120), FileNotFoundError("rattler-build")):
            with patch.object(update.subprocess, "run", side_effect=[None, failure]):
                with self.assertRaises(type(failure)):
                    self.run_update()
            self.assertEqual(self.recipe.read_bytes(), self.original)
            self.assertEqual(list(self.root.glob(".update-*")), [])
        with patch.object(update.subprocess, "run"), patch.object(update.os, "replace", side_effect=OSError("replace")):
            with self.assertRaises(OSError):
                self.run_update()
        self.assertEqual(self.recipe.read_bytes(), self.original)

    def test_dry_run_and_apply_false_never_replace(self):
        with patch.object(update.subprocess, "run") as render:
            self.assertEqual(self.run_update(dry=True), "dry-run")
            self.assertEqual(self.run_update(apply=False), "dry-run")
        self.assertEqual(render.call_count, 10)
        self.assertEqual(self.recipe.read_bytes(), self.original)

    def test_same_version_refresh_is_opt_in(self):
        self.release["tag_name"] = "v1.0"
        self.release["assets"][0]["name"] = "unusual-1.0.zip"
        with patch.object(update.subprocess, "run") as render:
            self.assertEqual(self.run_update(), "unchanged")
            render.assert_not_called()
            self.assertEqual(self.run_update(refresh=True), "updated")
            self.assertEqual(render.call_count, 5)

    def test_hash_failure_does_not_render_or_write(self):
        with patch.object(update, "compute_sha_for_asset", return_value="bad"), patch.object(update.subprocess, "run") as render:
            with self.assertRaises(RuntimeError):
                self.run_update()
        render.assert_not_called()
        self.assertEqual(self.recipe.read_bytes(), self.original)

    def test_checksum_exception_message_does_not_expose_auth(self):
        with patch.object(update, "compute_sha_for_asset", side_effect=RuntimeError("Authorization: token secret")):
            with self.assertRaises(RuntimeError) as caught:
                self.run_update()
        import traceback
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("secret", rendered)
        self.assertNotIn("Authorization", rendered)
        self.assertEqual(self.recipe.read_bytes(), self.original)

    def test_gcs_invalid_checksum_preserves_original(self):
        document = yaml.safe_load(self.recipe.read_text())
        document["source"][0] = {"if": "linux and x86_64", "then": [{"url": upstream.CLAUDE_CODE_GCS_BUCKET + "/${{ version }}/linux-x64/claude", "sha256": "a" * 64}]}
        self.recipe.write_text(yaml.safe_dump(document))
        original = self.recipe.read_bytes()
        with patch.object(update, "get_gcs_checksums", return_value={"linux-x64": "bad"}), patch.object(update.subprocess, "run") as render:
            with self.assertRaises(ValueError):
                self.run_update()
        self.assertEqual(self.recipe.read_bytes(), original)
        render.assert_not_called()

    def test_batch_partial_failure_report_and_exit(self):
        report = self.root / "nested" / "reports" / "report.json"
        output = io.StringIO()
        with patch("sys.argv", ["update.py", "--report", str(report)]), patch.object(update.glob, "glob", return_value=["broken", "healthy"]), patch.object(update, "update_single_recipe", side_effect=[RuntimeError("Authorization: token secret https://user:password@host/file?token=private"), "dry-run"]) as updater, redirect_stdout(output):
            with self.assertRaises(SystemExit) as result:
                update.main()
        for credential in ("secret", "password", "private", "Authorization"):
            self.assertNotIn(credential, output.getvalue())
            self.assertNotIn(credential, report.read_text())
        self.assertEqual(result.exception.code, 1)
        self.assertEqual(updater.call_count, 2)
        data = json.loads(report.read_text())
        self.assertEqual(data["failed"], 1)
        self.assertEqual(data["recipes"][1]["status"], "dry-run")
        self.assertNotIn("secret", report.read_text())


if __name__ == "__main__":
    unittest.main()
