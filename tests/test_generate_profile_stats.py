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

    def test_enhance_snake_svg_adds_calendar_chrome_and_restores_keyframes(self) -> None:
        raw_snake = (
            '<svg viewBox="-16 -32 880 192" width="880" height="192" xmlns="http://www.w3.org/2000/svg">'
            "<style>@keyframes c0{10.00%{fill:var(--c2)}10.02%,100%{fill:var(--ce)}}</style>"
            '<rect class="c c0" x="2" y="2" rx="2" ry="2"/></svg>'
        )
        cal_info = {
            "total": 567,
            "today_count": 4,
            "today_date": "Nov 23",
            "yesterday_count": 1,
            "yesterday_date": "Nov 22",
            "last_7_count": 8,
            "month_labels": [(1, "Dec"), (5, "Jan")],
        }
        for mode in ("dark", "light"):
            enhanced = profile_stats.enhance_snake_svg(raw_snake, cal_info, mode)
            ElementTree.fromstring(enhanced)
            self.assertIn("567 contributions in the last year", enhanced)
            self.assertIn("Today (Nov 23): 4", enhanced)
            self.assertIn("Yesterday (Nov 22): <tspan", enhanced)
            self.assertIn("Dec", enhanced)
            self.assertIn("Mon", enhanced)
            self.assertIn("26.02%,100%{fill:var(--c2)}", enhanced)


if __name__ == "__main__":
    unittest.main()
