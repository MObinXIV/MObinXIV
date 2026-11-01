import html
import json
import os
import re
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USERNAME = "MObinXIV"
API = "https://api.github.com"
OUTPUT = Path(__file__).resolve().parents[1] / "assets"
PALETTE = ["#c6f36b", "#79c0ff", "#d2a8ff", "#ffa657", "#ff7b72"]


def get_json(url):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MObinXIV-profile-stats",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token

    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"GitHub API request failed for {url}: {error}") from error


def get_contribution_count(year):
    url = (
        f"https://github.com/users/{USERNAME}/contributions"
        f"?from={year}-01-01&to={year}-12-31"
    )
    request = Request(url, headers={"User-Agent": "MObinXIV-profile-stats"})
    try:
        with urlopen(request, timeout=30) as response:
            page = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError) as error:
        raise RuntimeError(
            f"GitHub contributions request failed for {year}: {error}"
        ) from error

    heading = re.search(
        r'<h2\b[^>]*id="js-contribution-activity-description"[^>]*>(.*?)</h2>',
        page,
        re.IGNORECASE | re.DOTALL,
    )
    if not heading:
        raise RuntimeError(f"Could not find GitHub contribution total for {year}.")

    heading_text = html.unescape(re.sub(r"<[^>]+>", " ", heading.group(1)))
    result = re.search(r"([\d,]+)\s+contributions?\s+in\s+(\d{4})", heading_text)
    if not result or int(result.group(2)) != year:
        raise RuntimeError(f"Could not parse GitHub contribution total for {year}.")
    return int(result.group(1).replace(",", ""))


def svg_document(width, height, contents):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">
<style>
  text {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
  .title {{ fill: #e6edf3; font-size: 15px; font-weight: 600; }}
  .muted {{ fill: #8b949e; font-size: 11px; }}
  .value {{ fill: #e6edf3; font-size: 22px; font-weight: 600; }}
</style>
<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="7" fill="#0d1117" stroke="#30363d"/>
{contents}
</svg>
"""


def make_stats_card(user, repositories):
    owned_repositories = [repo for repo in repositories if not repo["fork"]]
    stars = sum(repo["stargazers_count"] for repo in owned_repositories)
    forks = sum(repo["forks_count"] for repo in owned_repositories)
    items = [
        ("Public repos", user["public_repos"]),
        ("Stars earned", stars),
        ("Forks", forks),
    ]

    content = ['<text x="24" y="34" class="title">GitHub statistics</text>']
    content.append(
        '<text x="24" y="55" class="muted">Public work, fetched directly from GitHub</text>'
    )
    for index, (label, value) in enumerate(items):
        x = 24 + index * 143
        content.append(
            f'<text x="{x}" y="104" class="value">{value:,}</text>'
            f'<text x="{x}" y="127" class="muted">{html.escape(label)}</text>'
        )
    content.append(
        f'<text x="24" y="164" class="muted">Updated from the GitHub API · {html.escape(user["login"])}</text>'
    )
    return svg_document(460, 190, "\n".join(content))


def make_languages_card(language_totals):
    languages = sorted(language_totals.items(), key=lambda item: item[1], reverse=True)[:5]
    total_bytes = sum(language_totals.values())
    if not languages or total_bytes == 0:
        raise RuntimeError("The GitHub API returned no language data for public repositories.")

    content = ['<text x="20" y="34" class="title">Top languages</text>']
    x = 20
    bar_y = 55
    bar_width = 290
    bar_height = 8
    for index, (_, byte_count) in enumerate(languages):
        segment_width = bar_width * byte_count / total_bytes
        content.append(
            f'<rect x="{x:.2f}" y="{bar_y}" width="{segment_width:.2f}" '
            f'height="{bar_height}" fill="{PALETTE[index % len(PALETTE)]}"/>'
        )
        x += segment_width
    content.append(f'<rect x="20" y="{bar_y}" width="{bar_width}" height="{bar_height}" rx="4" fill="none" stroke="#0d1117" stroke-width="1"/>')

    for index, (language, byte_count) in enumerate(languages):
        y = 91 + index * 20
        percent = byte_count / total_bytes * 100
        content.append(
            f'<circle cx="25" cy="{y - 4}" r="3" fill="{PALETTE[index % len(PALETTE)]}"/>'
            f'<text x="36" y="{y}" class="muted">{html.escape(language)}</text>'
            f'<text x="310" y="{y}" class="muted" text-anchor="end">{percent:.1f}%</text>'
        )
    return svg_document(330, 190, "\n".join(content))


def make_contributions_card(contribution_count, year):
    content = f"""<circle cx="110" cy="106" r="79" fill="#111614" stroke="#28312c" stroke-width="1"/>
<circle cx="110" cy="106" r="68" fill="none" stroke="#c6f36b" stroke-width="2"/>
<text x="110" y="106" text-anchor="middle" dominant-baseline="central" fill="#c6f36b" font-size="40" font-weight="700">{contribution_count:,}</text>
<text x="110" y="192" text-anchor="middle" class="title">CONTRIBUTIONS</text>
<text x="110" y="209" text-anchor="middle" class="muted">IN {year} SO FAR</text>"""
    return svg_document(220, 220, content)


def main():
    current_year = date.today().year
    contribution_count = get_contribution_count(current_year)
    user = get_json(f"{API}/users/{USERNAME}")
    repositories = []
    page = 1
    while True:
        batch = get_json(
            f"{API}/users/{USERNAME}/repos?per_page=100&page={page}&type=owner"
        )
        repositories.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    language_totals = {}
    for repo in repositories:
        if repo["fork"]:
            continue
        for language, byte_count in get_json(repo["languages_url"]).items():
            language_totals[language] = language_totals.get(language, 0) + byte_count

    if len(repositories) != user["public_repos"]:
        raise RuntimeError(
            f"Fetched {len(repositories)} public repositories, "
            f"but the GitHub profile reports {user['public_repos']}."
        )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "github-stats.svg").write_text(
        make_stats_card(user, repositories), encoding="utf-8"
    )
    (OUTPUT / "top-languages.svg").write_text(
        make_languages_card(language_totals), encoding="utf-8"
    )
    (OUTPUT / "contributions.svg").write_text(
        make_contributions_card(contribution_count, current_year), encoding="utf-8"
    )
    print(
        f"Updated profile cards for {len(repositories)} public repositories "
        f"and {len(language_totals)} languages; "
        f"{contribution_count} contributions in {current_year}."
    )


if __name__ == "__main__":
    main()
