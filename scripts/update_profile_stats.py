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


def get_activity_stats(year):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to fetch profile activity stats.")

    query = """
    query ProfileActivity($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalPullRequestReviewContributions
        }
        pullRequests {
          totalCount
        }
        issues {
          totalCount
        }
        repositoriesContributedTo(
          first: 1
          contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]
        ) {
          totalCount
        }
      }
    }
    """
    payload = {
        "query": query,
        "variables": {
            "login": USERNAME,
            "from": f"{year}-01-01T00:00:00Z",
            "to": f"{year}-12-31T23:59:59Z",
        },
    }
    request = Request(
        "https://api.github.com/graphql",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": "MObinXIV-profile-stats",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"GitHub GraphQL request failed: {error}") from error

    if result.get("errors"):
        messages = "; ".join(error.get("message", "Unknown GraphQL error") for error in result["errors"])
        raise RuntimeError(f"GitHub GraphQL query failed: {messages}")

    user = result.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub returned no public profile for {USERNAME}.")

    return {
        "pull_requests": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "reviews": user["contributionsCollection"]["totalPullRequestReviewContributions"],
        "repositories": user["repositoriesContributedTo"]["totalCount"],
    }


def svg_document(width, height, contents):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">
<style>
  text {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
  .title {{ fill: #e6edf3; font-size: 15px; font-weight: 600; }}
  .muted {{ fill: #8b949e; font-size: 11px; }}
  .label {{ fill: #8b949e; font-size: 11px; }}
  .value {{ fill: #e6edf3; font-size: 15px; font-weight: 600; }}
</style>
<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="7" fill="#0d1117" stroke="#30363d"/>
{contents}
</svg>
"""


def calculate_rank(commits, activity, stars, followers):
    exponential_cdf = lambda value: 1 - 2 ** -value
    log_normal_cdf = lambda value: value / (1 + value)
    score = 1 - (
        2 * exponential_cdf(commits / 250)
        + 3 * exponential_cdf(activity["pull_requests"] / 50)
        + exponential_cdf(activity["issues"] / 25)
        + exponential_cdf(activity["reviews"] / 2)
        + 4 * log_normal_cdf(stars / 50)
        + log_normal_cdf(followers / 10)
    ) / 12

    levels = ["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]
    thresholds = [1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100]
    return levels[next(index for index, threshold in enumerate(thresholds) if score * 100 <= threshold)]


def make_stats_card(user, repositories, activity, commits, year):
    owned_repositories = [repo for repo in repositories if not repo["fork"]]
    stars = sum(repo["stargazers_count"] for repo in owned_repositories)
    rank = calculate_rank(commits, activity, stars, user["followers"])
    items = [
        ("Commits this year", commits),
        ("Total PRs", activity["pull_requests"]),
        ("Total issues", activity["issues"]),
        ("Total stars", stars),
        ("Repos contributed", activity["repositories"]),
    ]

    content = [
        f'<text x="24" y="34" class="title">{html.escape(user["login"])}&#39;s GitHub Stats</text>',
        f'<text x="24" y="55" class="muted">Public activity · commits in {year}</text>',
    ]
    positions = [(28, 91), (245, 91), (28, 131), (245, 131), (28, 171)]
    for (label, value), (x, y) in zip(items, positions):
        content.append(f'<circle cx="{x}" cy="{y - 4}" r="3" fill="#c6f36b"/>')
        content.append(f'<text x="{x + 12}" y="{y}" class="label">{html.escape(label)}</text>')
        content.append(f'<text x="{x + 145}" y="{y}" class="value" text-anchor="end">{value:,}</text>')

    content.extend([
        '<circle cx="438" cy="106" r="37" fill="#111614" stroke="#30363d" stroke-width="2"/>',
        '<circle cx="438" cy="106" r="32" fill="none" stroke="#c6f36b" stroke-width="2"/>',
        f'<text x="438" y="106" text-anchor="middle" dominant-baseline="central" fill="#c6f36b" font-size="24" font-weight="700">{rank}</text>',
        '<text x="438" y="158" text-anchor="middle" class="label">RANK</text>',
    ])
    return svg_document(495, 200, "\n".join(content))


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


def main():
    current_year = date.today().year
    commits = get_contribution_count(current_year)
    user = get_json(f"{API}/users/{USERNAME}")
    activity = get_activity_stats(current_year)
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
        make_stats_card(user, repositories, activity, commits, current_year), encoding="utf-8"
    )
    (OUTPUT / "top-languages.svg").write_text(
        make_languages_card(language_totals), encoding="utf-8"
    )
    print(
        f"Updated profile cards for {len(repositories)} public repositories "
        f"and {len(language_totals)} languages; "
        f"{commits} commits in {current_year}; "
        f"rank {calculate_rank(commits, activity, sum(repo['stargazers_count'] for repo in repositories if not repo['fork']), user['followers'])}."
    )


if __name__ == "__main__":
    main()
