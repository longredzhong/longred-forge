"""Offline coverage for opt-in GitHub major and tag-prefix release lines."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx
import yaml  # type: ignore

from scripts import update
from scripts.forge import upstream
from scripts.forge.http import HTTPClient


def release(tag, **fields):
    return {"tag_name": tag, "draft": False, "prerelease": False, "assets": [], **fields}


class ReleaseLineProviderTests(unittest.TestCase):
    def select(self, pages, major=1, token=None, prefix=None):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.path, "/repos/example/tool/releases")
            self.assertEqual(request.url.params["per_page"], "100")
            return httpx.Response(200, json=pages[int(request.url.params["page"]) - 1])

        client = HTTPClient(transport=httpx.MockTransport(handler))
        with patch.object(upstream, "HTTPClient", return_value=client):
            result = (upstream.get_release_for_major("example", "tool", token, major)
                      if prefix is None else upstream.get_release_for_prefix("example", "tool", token, prefix))
        return result, requests

    def test_mixed_tags_flags_and_numeric_sorting(self):
        tags = [release("daemon-v9.0.0"), release("v2.0.0"), release("v1.9.99"),
                release("v1.10.2"), release("1.10.12"), release("v1.99.0", draft=True),
                release("v1.98.0", prerelease=True), release("v1.97.0-rc.1"),
                release("v1.96.0+build"), release("v1.95"), release("vv1.94.0"),
                release("v1.93.0\n")]
        result, requests = self.select([tags, []], token="test-token")
        self.assertEqual(result["tag_name"], "1.10.12")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].headers["Authorization"], "token test-token")
        result, _ = self.select([tags, []], major=2)
        self.assertEqual(result["tag_name"], "v2.0.0")

    def test_pagination_stops_at_last_partial_page_regardless_of_order(self):
        pages = [[release("v1.10.0", created_at="2030-01-01T00:00:00Z")] * 100,
                 [release("v1.100.0", created_at="2000-01-01T00:00:00Z")] * 100,
                 [release("v1.20.0")]]
        result, requests = self.select(pages)
        self.assertEqual(result["tag_name"], "v1.100.0")
        self.assertEqual([r.url.params["page"] for r in requests], ["1", "2", "3"])
        self.assertNotIn("authorization", requests[0].headers)

    def test_full_last_page_requires_empty_page_to_prove_exhaustion(self):
        result, requests = self.select([[release("v1.2.3")] * 100, []])
        self.assertEqual(result["tag_name"], "v1.2.3")
        self.assertEqual(len(requests), 2)

    def test_no_match_fails(self):
        for pages in ([[]], [[release("v2.0.0"), release("daemon-v1.0.0"),
                                release("v1.0.0", draft=True),
                                release("v1.1.0", prerelease=True)], []]):
            with self.subTest(pages=pages), self.assertRaisesRegex(RuntimeError, "No stable release"):
                self.select(pages)

    def test_invalid_major_and_repository_fail_before_http(self):
        with patch.object(upstream, "HTTPClient") as client:
            for major in (None, True, False, 0, -1, 1.0, "1", [], {}):
                with self.subTest(major=major), self.assertRaises(ValueError):
                    upstream.get_release_for_major("example", "tool", None, major)
            with self.assertRaises(ValueError):
                upstream.get_release_for_major("bad/owner", "tool", None, 1)
            client.assert_not_called()


    def test_prefix_mixed_tags_and_numeric_ordering(self):
        tags = [release(tag) for tag in (
            "v9.0.0", "rust-v0.9.99", "rust-v0.166.0", "rust-v0.99.0",
            "rust-v0.999.0-alpha.1", "rust-v0.998.0+build", "rust-v0.997",
            "other-rust-v0.999.0", "rust-v0.996.0\n", "rust-v０.999.0")]
        tags += [release("rust-v0.999.0", draft=True),
                 release("rust-v0.998.0", prerelease=True)]
        result, requests = self.select([tags], prefix="rust-v", token="test-token")
        self.assertEqual(result["tag_name"], "rust-v0.166.0")
        self.assertEqual(requests[0].headers["Authorization"], "token test-token")
        result, _ = self.select([[release("rust.v0.166.0"), release("rustXv9.0.0")]], prefix="rust.v")
        self.assertEqual(result["tag_name"], "rust.v0.166.0")

    def test_prefix_pagination_and_empty_final_page(self):
        for last in ([release("rust-v0.166.0")], [release("rust-v0.166.0")] * 100):
            pages = [[release("rust-v0.99.0")] * 100, last, []]
            result, requests = self.select(pages, prefix="rust-v")
            self.assertEqual(result["tag_name"], "rust-v0.166.0")
            self.assertEqual(len(requests), 2 if len(last) < 100 else 3)

    def test_prefix_missing_and_invalid(self):
        for tags in ([], [release("v0.166.0"), release("rust-v0.167.0-alpha.1"),
                          release("rust-v0.168.0", draft=True)]):
            with self.subTest(tags=tags), self.assertRaisesRegex(RuntimeError, "No stable release"):
                self.select([tags], prefix="rust-v")
        with patch.object(upstream, "HTTPClient") as client:
            for prefix in (None, "", " ", "rust/v", "../", "rust-v\n", "a?", "a+", True, 1, [], {}):
                with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, "tag_prefix"):
                    upstream.get_release_for_prefix("example", "tool", None, prefix)
            with self.assertRaises(ValueError):
                upstream.get_release_for_prefix("bad/owner", "tool", None, "rust-v")
            client.assert_not_called()


class ReleaseLineUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix=".release-line-test-")
        self.addCleanup(self.workspace.cleanup)
        self.recipe = Path(self.workspace.name) / "recipe.yaml"
        self.doc = {"context": {"version": "1.9.0"},
                    "about": {"repository": "https://github.com/example/tool"},
                    "extra": {"update": {"major": 1}},
                    "source": {"url": "https://example.org/tool-${{ version }}.zip", "sha256": "a" * 64}}
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def write_recipe(self):
        self.recipe.write_text(yaml.safe_dump(self.doc), encoding="utf-8")
        return self.recipe.read_bytes()

    def run_update(self, refresh=False):
        return update.update_single_recipe(str(self.recipe), None, None, {}, "test-token", False, True, refresh)

    def test_configured_line_selects_provider_and_updates_numerically(self):
        original = self.write_recipe()
        chosen = release("v1.10.0", assets=[{"name": "tool-1.10.0.zip", "digest": "sha256:" + "b" * 64}])
        with patch.object(update, "get_release_for_major", return_value=chosen) as line, \
                patch.object(update, "get_latest_release") as latest, \
                patch.object(update, "validate_and_write") as validate:
            self.assertEqual(self.run_update(), "dry-run")
        line.assert_called_once_with("example", "tool", "test-token", 1)
        latest.assert_not_called()
        candidate = yaml.safe_load(validate.call_args.args[1])
        self.assertEqual(candidate["context"]["version"], "1.10.0")
        self.assertEqual(candidate["source"]["sha256"], "b" * 64)
        self.assertFalse(validate.call_args.args[2])
        self.assertEqual(self.recipe.read_bytes(), original)

    def test_invalid_selector_fails_before_provider(self):
        with patch.object(update, "get_release_for_major") as line, \
                patch.object(update, "get_latest_release") as latest:
            for major in (None, True, False, 0, -1, 1.0, "1", [], {}):
                self.doc["extra"]["update"]["major"] = major
                original = self.write_recipe()
                with self.subTest(major=major), self.assertRaisesRegex(ValueError, "positive integer"):
                    self.run_update()
                self.assertEqual(self.recipe.read_bytes(), original)
            line.assert_not_called()
            latest.assert_not_called()

    def test_downgrade_rejected_even_with_refresh(self):
        for current, selected in (("1.10.0", "v1.9.99"), ("2.0.0", "v1.99.99"),
                                  ("v1.10.0", "1.9.0")):
            for refresh in (False, True):
                self.doc["context"]["version"] = current
                original = self.write_recipe()
                with self.subTest(current=current, refresh=refresh), \
                        patch.object(update, "get_release_for_major", return_value=release(selected)), \
                        patch.object(update, "validate_and_write") as validate, \
                        self.assertRaisesRegex(RuntimeError, "downgrade"):
                    self.run_update(refresh)
                validate.assert_not_called()
                self.assertEqual(self.recipe.read_bytes(), original)

    def test_no_match_does_not_fall_back_or_write(self):
        original = self.write_recipe()
        with patch.object(update, "get_release_for_major", side_effect=RuntimeError("No stable release")), \
                patch.object(update, "get_latest_release") as latest, \
                patch.object(update, "validate_and_write") as validate, \
                self.assertRaisesRegex(RuntimeError, "No stable release"):
            self.run_update()
        latest.assert_not_called()
        validate.assert_not_called()
        self.assertEqual(self.recipe.read_bytes(), original)

    def test_configured_unchanged_and_invalid_current_version(self):
        self.write_recipe()
        with patch.object(update, "get_release_for_major", return_value=release("v1.9.0")):
            self.assertEqual(self.run_update(), "unchanged")
        self.doc["context"]["version"] = "1.9"
        self.write_recipe()
        with patch.object(update, "get_release_for_major", return_value=release("v1.9.0")), \
                self.assertRaisesRegex(ValueError, "numeric version triples"):
            self.run_update()

    def configure_prefix(self, current="0.165.0"):
        self.doc["context"]["version"] = current
        self.doc["extra"]["update"] = {"tag_prefix": "rust-v"}
        self.doc["source"]["url"] = (
            "https://github.com/openai/codex/releases/download/rust-v${{ version }}/codex-${{ version }}.zip")

    def test_prefix_stripped_and_literal_source_url_preserved(self):
        self.configure_prefix()
        original = self.write_recipe()
        chosen = release("rust-v0.166.0", assets=[
            {"name": "codex-0.166.0.zip", "digest": "sha256:" + "b" * 64}])
        with patch.object(update, "get_release_for_prefix", return_value=chosen) as prefix, \
                patch.object(update, "get_latest_release") as latest, \
                patch.object(update, "get_release_for_major") as major, \
                patch.object(update, "validate_and_write") as validate:
            self.assertEqual(self.run_update(), "dry-run")
        prefix.assert_called_once_with("example", "tool", "test-token", "rust-v")
        latest.assert_not_called()
        major.assert_not_called()
        candidate = yaml.safe_load(validate.call_args.args[1])
        self.assertEqual(candidate["context"]["version"], "0.166.0")
        self.assertEqual(candidate["source"]["url"], self.doc["source"]["url"])
        self.assertEqual(candidate["source"]["sha256"], "b" * 64)
        self.assertEqual(self.recipe.read_bytes(), original)

    def test_prefix_invalid_config_before_providers(self):
        self.configure_prefix()
        with patch.object(update, "get_release_for_prefix") as prefix, \
                patch.object(update, "get_latest_release") as latest, \
                patch.object(update, "get_release_for_major") as major:
            for value in (None, "", " ", "rust/v", "a?", True, 1, [], {}):
                self.doc["extra"]["update"]["tag_prefix"] = value
                self.write_recipe()
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "tag_prefix"):
                    self.run_update()
            self.doc["extra"]["update"] = {"major": 1, "tag_prefix": "rust-v"}
            self.write_recipe()
            with self.assertRaisesRegex(ValueError, "cannot be combined"):
                self.run_update()
            prefix.assert_not_called()
            latest.assert_not_called()
            major.assert_not_called()

    def test_prefix_paginated_downgrade_rejected_even_with_refresh(self):
        for refresh in (False, True):
            self.configure_prefix("0.167.0")
            original = self.write_recipe()
            pages = [[release("rust-v0.99.0")] * 100, [release("rust-v0.166.0")]]
            client = HTTPClient(transport=httpx.MockTransport(lambda request: httpx.Response(
                200, json=pages[int(request.url.params["page"]) - 1])))
            with self.subTest(refresh=refresh), \
                    patch.object(upstream, "HTTPClient", return_value=client), \
                    patch.object(update, "validate_and_write") as validate, \
                    self.assertRaisesRegex(RuntimeError, "downgrade"):
                self.run_update(refresh)
            validate.assert_not_called()
            self.assertEqual(self.recipe.read_bytes(), original)

    def test_prefix_missing_never_falls_back(self):
        self.configure_prefix()
        original = self.write_recipe()
        with patch.object(update, "get_release_for_prefix", side_effect=RuntimeError("No stable release")), \
                patch.object(update, "get_latest_release") as latest, \
                patch.object(update, "validate_and_write") as validate, \
                self.assertRaisesRegex(RuntimeError, "No stable release"):
            self.run_update()
        latest.assert_not_called()
        validate.assert_not_called()
        self.assertEqual(self.recipe.read_bytes(), original)

    def test_prefix_unchanged_and_invalid_versions(self):
        self.configure_prefix("0.166.0")
        self.write_recipe()
        with patch.object(update, "get_release_for_prefix", return_value=release("rust-v0.166.0")):
            self.assertEqual(self.run_update(), "unchanged")
        for current, tag in (("0.166", "rust-v0.166.0"), ("0.166.0", "rust-v0.167.0-alpha.1"),
                             ("0.166.0", "v0.167.0")):
            self.configure_prefix(current)
            self.write_recipe()
            with self.subTest(current=current, tag=tag), \
                    patch.object(update, "get_release_for_prefix", return_value=release(tag)), \
                    self.assertRaises(ValueError):
                self.run_update()

    def test_unconfigured_recipes_keep_latest_patch_point_and_non_triple_tags(self):
        for extra in (None, {}, {"update": {}}, {"resources": ["file"]}):
            self.doc["extra"] = extra
            self.doc["context"]["version"] = "2.0"
            self.write_recipe()
            with self.subTest(extra=extra), \
                    patch.object(update, "get_latest_release", return_value=release("v2.0")) as latest, \
                    patch.object(update, "get_release_for_major") as line:
                self.assertEqual(self.run_update(), "unchanged")
                latest.assert_called_once_with("example", "tool", "test-token")
                line.assert_not_called()


if __name__ == "__main__":
    unittest.main()
