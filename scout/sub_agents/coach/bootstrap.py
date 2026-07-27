from __future__ import annotations

import re

from scout.config import Settings
from scout.sub_agents.coach.github_search import fetch_readme

# Matches a bare github.com/owner/repo URL as it appears inside markdown
# link syntax `[text](url)` or as a raw link, stopping at the first
# character that can't be part of a repo path segment.
_GITHUB_LINK_RE = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+?)(?:[)\s#>\]]|$)")


def harvest_awesome_list(list_url: str, settings: Settings) -> list[str]:
    """Extract distinct repo URLs linked from an awesome-list's README."""
    readme = fetch_readme(list_url, settings)
    if readme is None:
        return []
    seen: set[str] = set()
    candidates: list[str] = []
    for owner, repo in _GITHUB_LINK_RE.findall(readme):
        url = f"https://github.com/{owner}/{repo}"
        if url == list_url or url in seen:
            continue
        seen.add(url)
        candidates.append(url)
    return candidates
