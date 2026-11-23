#!/usr/bin/env python3
"""Generate theme-aware Yearly & Monthly GitHub Activity SVG cards for Amoor6."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GRAPHQL_URL = "https://api.github.com/graphql"
USERNAME = os.environ.get("PROFILE_USERNAME", "Amoor6")
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
OUTPUT_DIR = Path(os.environ.get("PROFILE_OUTPUT_DIR", "dist"))
YEARS_TO_SHOW = 3

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0D1117",
        "panel": "#111827",
        "border": "#1E293B",
        "divider": "#1E293B",
        "title": "#60A5FA",
        "text": "#F8FAFC",
        "subtext": "#CBD5E1",
        "muted": "#64748B",
        "track": "#1E293B",
        "bar_start": "#2563EB",
        "bar_end": "#60A5FA",
        "bar_secondary": "#1D4ED8",
        "pill_bg": "#172554",
        "pill_border": "#1E3A8A",
        "pill_text": "#93C5FD",
    },
    "light": {
        "bg": "#FFFFFF",
        "panel": "#F8FAFC",
        "border": "#E2E8F0",
        "divider": "#E2E8F0",
        "title": "#2563EB",
        "text": "#0F172A",
        "subtext": "#334155",
        "muted": "#64748B",
        "track": "#E2E8F0",
        "bar_start": "#1D4ED8",
        "bar_end": "#3B82F6",
        "bar_secondary": "#60A5FA",
        "pill_bg": "#EFF6FF",
        "pill_border": "#BFDBFE",
        "pill_text": "#1D4ED8",
    },
}

ACTIVITY_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def request_json(url: str, payload: dict[str, Any] | None = None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USERNAME}-profile-visuals",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"GitHub API request failed for {url}: {exc}") from exc


def get_activity(now: datetime) -> dict[str, Any]:
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required to query GitHub GraphQL contribution totals.")

    years_data: list[dict[str, Any]] = []
    current_year = now.year

    for offset in range(YEARS_TO_SHOW - 1, -1, -1):
        year = current_year - offset
        start = f"{year}-01-01T00:00:00Z"
        end = (
            now.strftime("%Y-%m-%dT%H:%M:%SZ")
            if year == current_year
            else f"{year}-12-31T23:59:59Z"
        )
        response = request_json(
            GRAPHQL_URL,
            {"query": ACTIVITY_QUERY, "variables": {"login": USERNAME, "from": start, "to": end}},
        )
        errors = response.get("errors")
        if errors:
            raise RuntimeError(f"GraphQL error for {year}: {errors[0].get('message', 'unknown error')}")

        collection = ((response.get("data") or {}).get("user") or {}).get("contributionsCollection")
        if not collection:
            raise RuntimeError(f"Missing contributionsCollection for {USERNAME} in {year}")

        calendar = collection.get("contributionCalendar") or {}
        total = calendar.get("totalContributions")
        commits = collection.get("totalCommitContributions")
        restricted = collection.get("restrictedContributionsCount", 0)
        if not isinstance(total, int) or not isinstance(commits, int):
            raise RuntimeError(f"Incomplete contribution totals returned for {year}")

        days: list[dict[str, Any]] = []
        for week in calendar.get("weeks") or []:
            for day in week.get("contributionDays") or []:
                date_str = str(day.get("date", ""))
                if date_str.startswith(f"{year}-"):
                    days.append(
                        {
                            "date": date_str,
                            "count": int(day.get("contributionCount", 0)),
                        }
                    )

        years_data.append(
            {
                "year": year,
                "contributions": total,
                "commits": commits,
                "restricted": int(restricted) if isinstance(restricted, int) else 0,
                "days": days,
            }
        )

    return summarize_activity(years_data, current_year)


def summarize_activity(years_data: list[dict[str, Any]], current_year: int) -> dict[str, Any]:
    total_all_years = sum(item["contributions"] for item in years_data)
    current_entry = next((item for item in years_data if item["year"] == current_year), years_data[-1])
    prev_entry = next((item for item in years_data if item["year"] == current_year - 1), None)

    yoy_label = "Active"
    if prev_entry and prev_entry["contributions"] > 0:
        ratio = current_entry["contributions"] / prev_entry["contributions"]
        if ratio >= 2.0:
            yoy_label = f"{ratio:.1f}x YoY"
        elif ratio >= 1.0:
            pct = int(round((ratio - 1.0) * 100))
            yoy_label = f"+{pct}% YoY"

    monthly_counts = [0] * 12
    active_days = 0
    best_day_date = ""
    best_day_count = 0

    for day in current_entry.get("days", []):
        date_str = day["date"]
        count = int(day["count"])
        try:
            month_idx = int(date_str[5:7]) - 1
        except (ValueError, IndexError):
            continue
        if 0 <= month_idx < 12:
            monthly_counts[month_idx] += count
        if count > 0:
            active_days += 1
        if count > best_day_count:
            best_day_count = count
            best_day_date = date_str

    peak_month_count = max(monthly_counts) if monthly_counts else 0
    peak_month_idx = monthly_counts.index(peak_month_count) if peak_month_count > 0 else 0
    peak_month_name = MONTH_NAMES[peak_month_idx] if peak_month_count > 0 else "—"

    best_day_formatted = "—"
    if best_day_date and best_day_count > 0:
        try:
            dt = datetime.strptime(best_day_date, "%Y-%m-%d")
            best_day_formatted = f"{MONTH_NAMES[dt.month - 1]} {dt.day}"
        except ValueError:
            best_day_formatted = best_day_date

    return {
        "years": years_data,
        "current_year": current_entry["year"],
        "total_all_years": total_all_years,
        "yoy_label": yoy_label,
        "monthly_counts": monthly_counts,
        "active_days": active_days,
        "peak_month_count": peak_month_count,
        "peak_month_name": peak_month_name,
        "best_day_count": best_day_count,
        "best_day_label": best_day_formatted,
    }


def activity_svg(summary: dict[str, Any], mode: str, now: datetime) -> str:
    t = THEMES[mode]
    w, h = 880, 260
    years = list(reversed(summary["years"]))  # Show newest year on top (2026, 2025, 2024)
    max_year_val = max([item["contributions"] for item in years] + [1])

    current_year = summary["current_year"]
    total_all = summary["total_all_years"]
    yoy_label = summary["yoy_label"]

    parts: list[str] = [
        "<defs>",
        f'  <linearGradient id="barGrad-{mode}" x1="0%" y1="0%" x2="100%" y2="0%">',
        f'    <stop offset="0%" stop-color="{t["bar_start"]}" />',
        f'    <stop offset="100%" stop-color="{t["bar_end"]}" />',
        "  </linearGradient>",
        f'  <linearGradient id="vBarGrad-{mode}" x1="0%" y1="100%" x2="0%" y2="0%">',
        f'    <stop offset="0%" stop-color="{t["bar_start"]}" />',
        f'    <stop offset="100%" stop-color="{t["bar_end"]}" />',
        "  </linearGradient>",
        "</defs>",
        # Card background
        f'<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="12" fill="{t["bg"]}" stroke="{t["border"]}" stroke-width="1.5" />',
        # Vertical divider between Left Panel and Right Panel
        f'<line x1="408" y1="24" x2="408" y2="{h - 24}" stroke="{t["divider"]}" stroke-width="1" />',
        # ================= LEFT PANEL: MULTI-YEAR CONTRIBUTIONS =================
        f'<text x="28" y="38" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="15" font-weight="700" fill="{t["title"]}">Yearly Contributions ({years[-1]["year"]}–{years[0]["year"]})</text>',
        f'<text x="28" y="56" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="11.5" fill="{t["muted"]}">Includes public &amp; private contributions across repositories</text>',
        # 3-Year Total Badge in top-right of left panel
        f'<rect x="292" y="22" width="94" height="24" rx="12" fill="{t["pill_bg"]}" stroke="{t["pill_border"]}" stroke-width="1" />',
        f'<text x="339" y="38" text-anchor="middle" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="11.5" font-weight="700" fill="{t["pill_text"]}">{total_all:,} Total</text>',
    ]

    # Yearly horizontal bars
    bar_x = 76
    bar_max_w = 232
    for idx, item in enumerate(years):
        y = 84 + idx * 46
        val = item["contributions"]
        is_current = idx == 0
        fill_w = max(8.0, (val / max_year_val) * bar_max_w) if val > 0 else 4.0
        bar_fill = f"url(#barGrad-{mode})" if is_current else t["bar_secondary"]
        year_color = t["text"] if is_current else t["subtext"]

        parts.extend(
            [
                f'<text x="28" y="{y + 13}" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="13.5" font-weight="{"700" if is_current else "600"}" fill="{year_color}">{item["year"]}</text>',
                f'<rect x="{bar_x}" y="{y}" width="{bar_max_w}" height="16" rx="8" fill="{t["track"]}" />',
                f'<rect x="{bar_x}" y="{y}" width="{fill_w:.1f}" height="16" rx="8" fill="{bar_fill}" />',
                f'<text x="384" y="{y + 13}" text-anchor="end" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="13.5" font-weight="{"700" if is_current else "600"}" fill="{year_color}">{val:,}</text>',
            ]
        )

    # Bottom summary pill on left panel
    current_total = years[0]["contributions"]
    parts.extend(
        [
            f'<rect x="28" y="214" width="358" height="26" rx="8" fill="{t["panel"]}" stroke="{t["border"]}" stroke-width="1" />',
            f'<text x="40" y="231" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="11.5" font-weight="600" fill="{t["subtext"]}">{current_year} Pace: <tspan fill="{t["title"]}" font-weight="700">{current_total:,} contributions</tspan></text>',
            f'<text x="374" y="231" text-anchor="end" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="11.5" font-weight="700" fill="{t["pill_text"]}">{escape(yoy_label)}</text>',
        ]
    )

    # ================= RIGHT PANEL: MONTHLY BREAKDOWN & KPIS =================
    parts.extend(
        [
            f'<text x="432" y="38" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="15" font-weight="700" fill="{t["title"]}">{current_year} Monthly Breakdown</text>',
            f'<text x="432" y="56" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="11.5" fill="{t["muted"]}">Monthly contribution rhythm &amp; consistency metrics</text>',
            f'<text x="852" y="38" text-anchor="end" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="11" fill="{t["muted"]}">Updated {now.strftime("%b %d, %Y")}</text>',
        ]
    )

    monthly_counts: list[int] = summary["monthly_counts"]
    max_month = max(monthly_counts + [1])
    chart_x = 434
    chart_base_y = 178
    chart_max_h = 92
    col_step = 35.5
    bar_w = 20

    # Baseline for monthly chart
    parts.append(
        f'<line x1="{chart_x - 2}" y1="{chart_base_y}" x2="852" y2="{chart_base_y}" stroke="{t["track"]}" stroke-width="1.5" />'
    )

    for m_idx, count in enumerate(monthly_counts):
        bx = chart_x + m_idx * col_step
        cx = bx + bar_w / 2
        # Background track column
        parts.append(
            f'<rect x="{bx:.1f}" y="{chart_base_y - chart_max_h}" width="{bar_w}" height="{chart_max_h}" rx="5" fill="{t["track"]}" opacity="0.45" />'
        )
        if count > 0:
            bh = max(6.0, (count / max_month) * chart_max_h)
            by = chart_base_y - bh
            is_peak = count == summary["peak_month_count"] and count > 0
            m_fill = f"url(#vBarGrad-{mode})" if is_peak or count >= (max_month * 0.4) else t["bar_secondary"]
            parts.extend(
                [
                    f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w}" height="{bh:.1f}" rx="5" fill="{m_fill}" />',
                    f'<text x="{cx:.1f}" y="{by - 5:.1f}" text-anchor="middle" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="10" font-weight="{"700" if is_peak else "600"}" fill="{t["text"] if is_peak else t["subtext"]}">{count}</text>',
                ]
            )
        parts.append(
            f'<text x="{cx:.1f}" y="{chart_base_y + 15}" text-anchor="middle" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="10.5" font-weight="500" fill="{t["muted"]}">{MONTH_NAMES[m_idx]}</text>'
        )

    # Bottom 3 KPI pills on right panel
    kpis = [
        ("Active Days", f'{summary["active_days"]} days'),
        ("Peak Month", f'{summary["peak_month_count"]} ({summary["peak_month_name"]})'),
        ("Best Day", f'{summary["best_day_count"]} ({summary["best_day_label"]})'),
    ]
    pill_w = 134
    pill_gap = 9
    for k_idx, (k_label, k_val) in enumerate(kpis):
        px = 432 + k_idx * (pill_w + pill_gap)
        parts.extend(
            [
                f'<rect x="{px}" y="214" width="{pill_w}" height="26" rx="8" fill="{t["panel"]}" stroke="{t["border"]}" stroke-width="1" />',
                f'<text x="{px + 10}" y="231" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="10.5" fill="{t["muted"]}">{escape(k_label)}:</text>',
                f'<text x="{px + pill_w - 10}" y="231" text-anchor="end" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="11" font-weight="700" fill="{t["title"]}">{escape(k_val)}</text>',
            ]
        )

    title_text = f"GitHub contribution analytics for {USERNAME} ({years[-1]['year']} to {years[0]['year']})"
    body = "\n".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title_text)}">\n'
        f"<title>{escape(title_text)}</title>\n"
        f"{body}\n</svg>\n"
    )


def main() -> None:
    today = datetime.now(timezone.utc)
    summary = get_activity(today)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for mode in THEMES:
        (OUTPUT_DIR / f"activity-{mode}.svg").write_text(
            activity_svg(summary, mode, today), encoding="utf-8"
        )
    print(
        f"Generated activity SVGs for {USERNAME}: "
        f"{summary['total_all_years']} total contributions across {len(summary['years'])} years, "
        f"{summary['active_days']} active days in {summary['current_year']}."
    )


if __name__ == "__main__":
    main()
