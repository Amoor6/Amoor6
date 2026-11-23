#!/usr/bin/env python3
"""Generate theme-aware Yearly/Monthly GitHub Activity SVGs and frame the Contribution Snake SVG."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import re
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
        "c0": "#161B22",
        "c1": "#1E3A8A",
        "c2": "#2563EB",
        "c3": "#3B82F6",
        "c4": "#93C5FD",
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
        "c0": "#EBEDF0",
        "c1": "#DBEAFE",
        "c2": "#93C5FD",
        "c3": "#60A5FA",
        "c4": "#2563EB",
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

ROLLING_CALENDAR_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
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


def get_rolling_calendar() -> dict[str, Any]:
    response = request_json(
        GRAPHQL_URL,
        {"query": ROLLING_CALENDAR_QUERY, "variables": {"login": USERNAME}},
    )
    calendar = (
        (((response.get("data") or {}).get("user") or {}).get("contributionsCollection") or {}).get(
            "contributionCalendar"
        )
        or {}
    )
    weeks = calendar.get("weeks") or []
    all_days: list[dict[str, Any]] = []
    month_labels: list[tuple[int, str]] = []
    last_month = None
    last_label_week = -10

    for w_idx, week in enumerate(weeks):
        w_days = week.get("contributionDays") or []
        if not w_days:
            continue
        for day in w_days:
            d_str = str(day.get("date", ""))
            if d_str.endswith("-01") and len(d_str) >= 7:
                m_num = int(d_str[5:7])
                if w_idx - last_label_week >= 3:
                    month_labels.append((w_idx, MONTH_NAMES[m_num - 1]))
                    last_label_week = w_idx
                last_month = m_num
            all_days.append(
                {
                    "date": d_str,
                    "count": int(day.get("contributionCount", 0)),
                }
            )

    today_entry = all_days[-1] if all_days else {"date": "", "count": 0}
    yesterday_entry = all_days[-2] if len(all_days) >= 2 else {"date": "", "count": 0}
    last_7_total = sum(d["count"] for d in all_days[-7:])

    def short_date(d_str: str) -> str:
        try:
            dt = datetime.strptime(d_str, "%Y-%m-%d")
            return f"{MONTH_NAMES[dt.month - 1]} {dt.day}"
        except ValueError:
            return d_str

    return {
        "total": int(calendar.get("totalContributions", 0)),
        "today_count": today_entry["count"],
        "today_date": short_date(today_entry["date"]),
        "yesterday_count": yesterday_entry["count"],
        "yesterday_date": short_date(yesterday_entry["date"]),
        "last_7_count": last_7_total,
        "month_labels": month_labels,
    }


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


def enhance_snake_svg(raw_svg: str, calendar_info: dict[str, Any], mode: str) -> str:
    """Wrap Platane/snk output in an original GitHub-style Contribution Calendar card with Today/Yesterday counters."""
    t = THEMES[mode]
    # Replace original viewBox="-16 -32 880 192" width="880" height="192" with framed viewBox="-52 -78 924 264"
    framed_svg = re.sub(
        r'viewBox="[^"]+"[^>]*width="[^"]+"[^>]*height="[^"]+"',
        'viewBox="-52 -78 924 264" width="880" height="251"',
        raw_svg,
        count=1,
    )

    # Restore commit square colors ~15% after the snake eats them so the full commit graph stays visible
    def restore_after_snake(match: re.Match[str]) -> str:
        kf_name = match.group(1)
        t1 = float(match.group(2))
        color_var = match.group(3)
        t2 = float(match.group(4))
        if t2 < 82.0:
            t_hold = min(96.0, t2 + 12.0)
            t_restore = min(99.0, t2 + 16.0)
            return (
                f"@keyframes {kf_name}{{"
                f"{t1:.2f}%{{fill:{color_var}}}"
                f"{t2:.2f}%,{t_hold:.2f}%{{fill:var(--ce)}}"
                f"{t_restore:.2f}%,100%{{fill:{color_var}}}}}"
            )
        return match.group(0)

    framed_svg = re.sub(
        r"@keyframes (c[a-z0-9]+)\{([0-9.]+)%\{fill:(var\(--c[1-4]\))\}([0-9.]+)%,100%\{fill:var\(--ce\)\}\}",
        restore_after_snake,
        framed_svg,
    )

    total_last_year = calendar_info["total"]
    today_cnt = calendar_info["today_count"]
    today_dt = calendar_info["today_date"]
    yest_cnt = calendar_info["yesterday_count"]
    yest_dt = calendar_info["yesterday_date"]
    week_cnt = calendar_info["last_7_count"]

    bg_and_chrome: list[str] = [
        # Outer card background & border matching activity card
        f'<rect x="-51" y="-77" width="922" height="262" rx="12" fill="{t["bg"]}" stroke="{t["border"]}" stroke-width="1.5" />',
        # Top Header Left: Total contributions in the last year
        f'<text x="-30" y="-47" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="14.5" font-weight="700" fill="{t["text"]}">{total_last_year:,} contributions in the last year</text>',
        # Top Header Right: Today, Yesterday, Last 7 Days badges
        f'<rect x="444" y="-64" width="132" height="24" rx="12" fill="{t["pill_bg"]}" stroke="{t["pill_border"]}" stroke-width="1" />',
        f'<text x="510" y="-48" text-anchor="middle" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="11" font-weight="700" fill="{t["pill_text"]}">Today ({escape(today_dt)}): {today_cnt}</text>',
        f'<rect x="584" y="-64" width="144" height="24" rx="12" fill="{t["panel"]}" stroke="{t["border"]}" stroke-width="1" />',
        f'<text x="656" y="-48" text-anchor="middle" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="11" font-weight="600" fill="{t["subtext"]}">Yesterday ({escape(yest_dt)}): <tspan fill="{t["title"]}" font-weight="700">{yest_cnt}</tspan></text>',
        f'<rect x="736" y="-64" width="112" height="24" rx="12" fill="{t["panel"]}" stroke="{t["border"]}" stroke-width="1" />',
        f'<text x="792" y="-48" text-anchor="middle" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="11" font-weight="600" fill="{t["subtext"]}">Last 7d: <tspan fill="{t["title"]}" font-weight="700">{week_cnt}</tspan></text>',
        # Day-of-week labels on the left axis (Mon, Wed, Fri)
        f'<text x="-8" y="28" text-anchor="end" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="10.5" fill="{t["muted"]}">Mon</text>',
        f'<text x="-8" y="60" text-anchor="end" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="10.5" fill="{t["muted"]}">Wed</text>',
        f'<text x="-8" y="92" text-anchor="end" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="10.5" fill="{t["muted"]}">Fri</text>',
    ]

    # Month labels along the top of the 53-week grid (y=-21 sits cleanly above the snake's y=-16 top corridor)
    for w_idx, m_name in calendar_info.get("month_labels", []):
        mx = 2 + w_idx * 16
        bg_and_chrome.append(
            f'<text x="{mx}" y="-21" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="10.5" font-weight="500" fill="{t["muted"]}">{escape(m_name)}</text>'
        )

    # Bottom row below the snake progress bar (y=144..156): caption left + Less/More legend right
    legend_levels = [t["c0"], t["c1"], t["c2"], t["c3"], t["c4"]]
    bg_and_chrome.append(
        f'<text x="2" y="173" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="10.5" fill="{t["muted"]}">Live GitHub contribution calendar · animated snake overlay</text>'
    )
    bg_and_chrome.append(
        f'<text x="738" y="173" text-anchor="end" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="10.5" fill="{t["muted"]}">Less</text>'
    )
    for l_idx, color in enumerate(legend_levels):
        lx = 746 + l_idx * 14
        bg_and_chrome.append(
            f'<rect x="{lx}" y="163" width="10" height="10" rx="2" fill="{color}" />'
        )
    bg_and_chrome.append(
        f'<text x="846" y="173" text-anchor="end" font-family="Segoe UI, Ubuntu, Inter, sans-serif" font-size="10.5" fill="{t["muted"]}">More</text>'
    )

    chrome_block = "\n".join(bg_and_chrome)
    if "</style>" in framed_svg:
        framed_svg = framed_svg.replace("</style>", f"</style>\n{chrome_block}\n", 1)
    return framed_svg


def main() -> None:
    today = datetime.now(timezone.utc)
    summary = get_activity(today)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for mode in THEMES:
        (OUTPUT_DIR / f"activity-{mode}.svg").write_text(
            activity_svg(summary, mode, today), encoding="utf-8"
        )

    calendar_info = get_rolling_calendar()
    for mode in THEMES:
        snake_path = OUTPUT_DIR / f"snake-{mode}.svg"
        if snake_path.exists():
            raw_snake = snake_path.read_text(encoding="utf-8")
            if "contributions in the last year" not in raw_snake:
                snake_path.write_text(
                    enhance_snake_svg(raw_snake, calendar_info, mode), encoding="utf-8"
                )

    print(
        f"Generated activity SVGs for {USERNAME}: "
        f"{summary['total_all_years']} total contributions across {len(summary['years'])} years, "
        f"{summary['active_days']} active days in {summary['current_year']}."
    )


if __name__ == "__main__":
    main()
