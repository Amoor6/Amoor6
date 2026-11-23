"""Offline tests: fixture values are not real GitHub metrics."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("profile_stats", ROOT / "scripts/generate_profile_stats.py")
profile_stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile_stats)


class StatsTests(unittest.TestCase):
    def test_activity_aggregated_without_private_names(self):
        def fake_request(url, payload=None):
            self.assertEqual(url, "https://api.github.com/graphql")
            return {"data": {"user": {"contributionsCollection": {
                "contributionCalendar": {"totalContributions": 30},
                "totalCommitContributions": 12,
                "restrictedContributionsCount": 8,
            }}}}
        with patch.object(profile_stats, "TOKEN", "test-placeholder"), patch.object(profile_stats, "request_json", side_effect=fake_request):
            data = profile_stats.get_activity(datetime(2026, 11, 23, tzinfo=timezone.utc))
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]["contributions"], 30)
        svg = profile_stats.activity_svg(data, "dark", datetime(2026, 11, 23, tzinfo=timezone.utc))
        ElementTree.fromstring(svg)
        self.assertNotIn("restrictedContributionsCount", svg)

    def test_languages_only_public_originals(self):
        repositories = [
            {"name": "sample-public", "private": False, "visibility": "public", "fork": False, "archived": False, "owner": {"login": "Amoor6"}},
            {"name": "client-private", "private": True, "visibility": "private", "fork": False, "archived": False, "owner": {"login": "Amoor6"}},
            {"name": "forked", "private": False, "visibility": "public", "fork": True, "archived": False, "owner": {"login": "Amoor6"}},
            {"name": "Amoor6", "private": False, "visibility": "public", "fork": False, "archived": False, "owner": {"login": "Amoor6"}},
        ]
        called = []
        def fake_request(url, payload=None):
            called.append(url)
            if "/users/" in url:
                return repositories
            return {"TypeScript": 600, "JavaScript": 400}
        with patch.object(profile_stats, "request_json", side_effect=fake_request):
            langs, total = profile_stats.get_languages()
        self.assertEqual(total, 1000)
        self.assertEqual(langs[0], ("TypeScript", 600))
        self.assertEqual(len(called), 2)
        self.assertTrue(called[1].endswith("/sample-public/languages"))
        for mode in ("light", "dark"):
            ElementTree.fromstring(profile_stats.languages_svg(langs, total, mode))

    def test_svg_has_accessible_labels_and_no_fake_counts(self):
        sample = [{"year": 2024, "contributions": 0, "commits": 0, "restricted": 0}]
        svg = profile_stats.activity_svg(sample, "light", datetime(2024, 6, 1, tzinfo=timezone.utc))
        root = ElementTree.fromstring(svg)
        self.assertEqual(root.attrib["role"], "img")
        self.assertIn("0 accessible commits", svg)


if __name__ == "__main__":
    unittest.main()
