#!/usr/bin/env python3
"""Generate accurate, theme-aware profile graphics with only Python's stdlib.

Data policy:
- Calendar-year GitHub contribution totals, with optional aggregate private counts.
- Separate accessible commit contribution counts (not raw Git commits).
- Public, owned, non-fork, non-archived repository languages by byte volume.
- Never request, store, or publish private repository names or contents.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

USERNAME = os.environ.get("PROFILE_USERNAME", "Amoor6")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUTPUT_DIR = Path(os.environ.get("PROFILE_OUTPUT_DIR", "dist"))
START_YEAR = 2024

THEMES = {
    "light": {"background": "#FFFFFF", "text": "#0F172A", "muted": "#64748B", "track": "#E2E8F0", "accent": "#2563EB", "soft": "#93C5FD"},
    "dark": {"background": "#0D1117", "text": "#E2E8F0", "muted": "#94A3B8", "track": "#243247", "accent": "#60A5FA", "soft": "#2563EB"},
}

QUERY = """
query ProfileActivity($login: String!, $start: DateTime!, $end: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $start, to: $end) {
      contributionCalendar { totalContributions }
      totalCommitContributions
      restrictedContributionsCount
    }
  }
}
"""


def request_json(url: str, payload: dict | None = None) -> object:
    """GitHub REST/GraphQL request; fail instead of generating invented data."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Amoor6-profile-readme-generator",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = Request(url, data=data, headers=headers, method="POST" if data else "GET")
    for attempt in range(3):
        try:
            with urlopen(req, timeout=30) as resp:
                result = json.load(resp)
            if isinstance(result, dict) and result.get("errors"):
                raise RuntimeError(f"GitHub API returned GraphQL errors: {result['errors']}")
            return result
        except (HTTPError, URLError) as error:
            retryable = isinstance(error, URLError) or getattr(error, "code", 0) in (429, 500, 502, 503, 504)
            if attempt >= 2 or not retryable:
                raise RuntimeError(f"GitHub API request failed: {url} ({error})") from error
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def get_activity(today: datetime) -> list[dict]:
    if not TOKEN:
        raise RuntimeError("Set GITHUB_TOKEN to query GitHub's GraphQL API")
    activity = []
    for year in range(START_YEAR, today.year + 1):
        start = f"{year}-01-01T00:00:00Z"
        end = (today.isoformat().replace("+00:00", "Z") if year == today.year
               else f"{year}-12-31T23:59:59Z")
        result = request_json("https://api.github.com/graphql", {
            "query": QUERY, "variables": {"login": USERNAME, "start": start, "end": end}
        })
        collection = result["data"]["user"]["contributionsCollection"]
        total = collection["contributionCalendar"]["totalContributions"]
        commits = collection["totalCommitContributions"]
        restricted = collection["restrictedContributionsCount"]
        if any(type(value) is not int or value < 0 for value in (total, commits, restricted)):
            raise ValueError("GitHub returned invalid contribution data")
        activity.append({"year": year, "contributions": total, "commits": commits, "restricted": restricted})
    return activity


def public_owned_repositories() -> list[dict]:
    repos = []
    page = 1
    while True:
        url = f"https://api.github.com/users/{quote(USERNAME)}/repos?type=owner&per_page=100&page={page}"
        batch = request_json(url)
        if not isinstance(batch, list):
            raise RuntimeError("Unexpected GitHub repository response")
        repos.extend(repo for repo in batch
                     if not repo.get("private") and repo.get("visibility", "public") == "public"
                     and not repo.get("fork") and not repo.get("archived")
                     and repo.get("name", "").casefold() != USERNAME.casefold())
        if len(batch) < 100:
            break
        page += 1
    return repos


def get_languages() -> tuple[list[tuple[str, int]], int]:
    languages: Counter[str] = Counter()
    repos = public_owned_repositories()
    for repo in repos:
        owner = repo["owner"]["login"]
        name = repo["name"]
        url = f"https://api.github.com/repos/{quote(owner)}/{quote(name)}/languages"
        result = request_json(url)
        if not isinstance(result, dict):
            raise RuntimeError("Unexpected GitHub languages response")
        for language, count in result.items():
            if type(count) is not int or count < 0:
                raise ValueError("GitHub returned invalid language sizes")
            languages[language] += count
    if not languages or not sum(languages.values()):
        raise RuntimeError("No usable public repository languages found")
    return languages.most_common(5), sum(languages.values())


def svg_document(width: int, height: int, theme: dict, title: str, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{escape(title, quote=True)}" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
<title>{escape(title)}</title>
<rect width="100%" height="100%" fill="{theme['background']}" rx="12" />
{body}
</svg>\n'''


def activity_svg(activity: list[dict], mode: str, today: datetime) -> str:
    theme = THEMES[mode]
    w, h = 860, 304
    n = len(activity)
    maximum = max(1, *(item["contributions"] for item in activity))
    item_width = min(125, 680 / max(n, 1))
    gap = (740 - n * item_width) / max(1, n - 1) if n > 1 else 0
    left = 60 + max(0, (740 - (n * item_width + max(0, n-1) * gap)) / 2)
    pieces = [
        f'<text x="30" y="42" font-family="Arial, sans-serif" font-size="23" font-weight="700" fill="{theme["text"]}">Yearly contributions</text>',
        f'<text x="30" y="65" font-family="Arial, sans-serif" font-size="13" fill="{theme["muted"]}">GitHub contribution calendar · {START_YEAR}–{today.year}</text>',
        f'<line x1="30" x2="830" y1="229" y2="229" stroke="{theme["track"]}" />',
    ]
    for index, entry in enumerate(activity):
        x = left + index * (item_width + gap)
        center = x + item_width / 2
        bar_h = max(3, round(112 * entry["contributions"] / maximum)) if entry["contributions"] else 0
        bar_y = 229 - bar_h
        fill = theme["accent"] if index == n-1 else theme["soft"]
        if bar_h:
            pieces.append(f'<rect x="{x:.1f}" y="{bar_y}" width="{item_width:.1f}" height="{bar_h}" rx="6" fill="{fill}" />')
        pieces.extend([
            f'<text x="{center:.1f}" y="{max(105, bar_y-10)}" text-anchor="middle" font-size="18" font-weight="700" font-family="Arial, sans-serif" fill="{theme["text"]}">{entry["contributions"]:,}</text>',
            f'<text x="{center:.1f}" y="251" text-anchor="middle" font-size="13" font-family="Arial, sans-serif" fill="{theme["text"]}">{entry["year"]}{" YTD" if entry["year"] == today.year else ""}</text>',
            f'<text x="{center:.1f}" y="269" text-anchor="middle" font-size="11" font-family="Arial, sans-serif" fill="{theme["muted"]}">{entry["commits"]:,} accessible commits</text>',
        ])
    pieces.append(f'<text x="30" y="292" font-size="11" font-family="Arial, sans-serif" fill="{theme["muted"]}">Contributions include more than commits; private counts depend on GitHub visibility and token access.</text>')
    return svg_document(w, h, theme, "GitHub contributions and accessible commit contributions by calendar year", "\n".join(pieces))


def languages_svg(languages: list[tuple[str, int]], total: int, mode: str) -> str:
    theme = THEMES[mode]
    w, h = 860, 112 + 36 * len(languages)
    parts = [
        f'<text x="30" y="39" font-family="Arial, sans-serif" font-size="23" font-weight="700" fill="{theme["text"]}">Languages</text>',
        f'<text x="30" y="62" font-family="Arial, sans-serif" font-size="13" fill="{theme["muted"]}">Public owned repositories · share of classified bytes</text>',
    ]
    for i, (language, byte_count) in enumerate(languages):
        percentage = 100 * byte_count / total
        y = 90 + 36 * i
        bar_width = 560 * byte_count / total
        parts.extend([
            f'<text x="30" y="{y+10}" font-family="Arial, sans-serif" font-size="13" fill="{theme["text"]}">{escape(language)}</text>',
            f'<rect x="205" y="{y}" width="560" height="12" rx="6" fill="{theme["track"]}" />',
            f'<rect x="205" y="{y}" width="{bar_width:.1f}" height="12" rx="6" fill="{theme["accent"] if i == 0 else theme["soft"]}" />',
            f'<text x="815" y="{y+10}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="{theme["muted"]}">{percentage:.1f}%</text>',
        ])
    return svg_document(w, h, theme, "Top languages by code bytes across public owned repositories", "\n".join(parts))


def main() -> None:
    today = datetime.now(timezone.utc)
    activity = get_activity(today)
    languages, total = get_languages()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for mode in THEMES:
        (OUTPUT_DIR / f"activity-{mode}.svg").write_text(activity_svg(activity, mode, today), encoding="utf-8")
        (OUTPUT_DIR / f"languages-{mode}.svg").write_text(languages_svg(languages, total, mode), encoding="utf-8")
    print(f"Created theme-aware profile charts for {USERNAME}: {len(activity)} years and {len(languages)} languages")


if __name__ == "__main__":
    main()
