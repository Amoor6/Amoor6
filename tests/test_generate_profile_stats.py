"""Unit tests for the two-panel Yearly & Monthly GitHub Activity SVG generator."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("profile_stats", ROOT / "scripts/generate_profile_stats.py")
profile_stats = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(profile_stats)


class ActivityStatsTests(unittest.TestCase):
    def test_get_activity_and_svg_generation(self) -> None:
        responses = {
            2024: {
                "totalContributions": 12,
                "totalCommitContributions": 9,
                "restrictedContributionsCount": 1,
                "weeks": [{"contributionDays": [{"date": "2024-05-10", "contributionCount": 12}]}],
            },
            2025: {
                "totalContributions": 82,
                "totalCommitContributions": 30,
                "restrictedContributionsCount": 45,
                "weeks": [{"contributionDays": [{"date": "2025-08-12", "contributionCount": 82}]}],
            },
            2026: {
                "totalContributions": 549,
                "totalCommitContributions": 23,
                "restrictedContributionsCount": 523,
                "weeks": [
                    {
                        "contributionDays": [
                            {"date": "2026-05-15", "contributionCount": 103},
                            {"date": "2026-06-25", "contributionCount": 20},
                            {"date": "2026-06-26", "contributionCount": 104},
                        ]
                    }
                ],
            },
        }

        def fake_request(url: str, payload: dict | None = None) -> dict:
            self.assertEqual(url, "https://api.github.com/graphql")
            assert payload is not None
            year = int(payload["variables"]["from"][:4])
            ydata = responses[year]
            return {
                "data": {
                    "user": {
                        "contributionsCollection": {
                            "totalCommitContributions": ydata["totalCommitContributions"],
                            "restrictedContributionsCount": ydata["restrictedContributionsCount"],
                            "contributionCalendar": {
                                "totalContributions": ydata["totalContributions"],
                                "weeks": ydata["weeks"],
                            },
                        }
                    }
                }
            }

        now = datetime(2026, 11, 23, tzinfo=timezone.utc)
        with patch.object(profile_stats, "TOKEN", "test-token"), patch.object(
            profile_stats, "request_json", side_effect=fake_request
        ):
            summary = profile_stats.get_activity(now)

        self.assertEqual(summary["total_all_years"], 643)
        self.assertEqual(summary["yoy_label"], "6.7x YoY")
        self.assertEqual(summary["active_days"], 3)
        self.assertEqual(summary["peak_month_count"], 124)
        self.assertEqual(summary["peak_month_name"], "Jun")
        self.assertEqual(summary["best_day_count"], 104)
        self.assertEqual(summary["best_day_label"], "Jun 26")

        for mode in ("dark", "light"):
            svg = profile_stats.activity_svg(summary, mode, now)
            root = ElementTree.fromstring(svg)
            self.assertEqual(root.attrib["role"], "img")
            self.assertIn("643 Total", svg)
            self.assertIn("6.7x YoY", svg)
            self.assertIn("124 (Jun)", svg)


if __name__ == "__main__":
    unittest.main()
