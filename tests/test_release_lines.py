"""Offline coverage for opt-in GitHub major release lines."""
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
    def select(self, pages, major=1, token=None):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.path, "/repos/example/tool/releases")
            self.assertEqual(request.url.params["per_page"], "100")
            return httpx.Response(200, json=pages[int(request.url.params["page"]) - 1])

        client = HTTPClient(transport=httpx.MockTransport(handler))
        with patch.object(upstream, "HTTPClient", return_value=client):
            result = upstream.get_release_for_major("example", "tool", token, major)
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
