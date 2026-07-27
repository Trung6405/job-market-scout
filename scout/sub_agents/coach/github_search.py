from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from scout.config import Settings

_SEARCH_URL = "https://api.github.com/search/repositories"
# The Search API has no relative-date query operator, so "pushed within
# ~18 months" (spec) is filtered client-side against this cutoff.
_STALE_AFTER = timedelta(days=548)


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"token {settings.github_pat}",
        "Accept": "application/vnd.github+json",
    }


def search_candidates(skill: str, settings: Settings) -> list[str]:
    """Return up to `coach_top_n_per_skill` candidate repo URLs for `skill`."""
    response = requests.get(
        _SEARCH_URL,
        headers=_headers(settings),
        params={
            "q": f"{skill} in:readme,description stars:>200 archived:false",
            "sort": "stars",
            "order": "desc",
            "per_page": 30,
        },
        timeout=10,
    )
    response.raise_for_status()
    cutoff = datetime.now(timezone.utc) - _STALE_AFTER
    candidates: list[str] = []
    for repo in response.json().get("items", []):
        if len(candidates) >= settings.coach_top_n_per_skill:
            break
        pushed_at = datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))
        if pushed_at < cutoff:
            continue
        candidates.append(repo["html_url"])
    return candidates


def fetch_readme(repo_url: str, settings: Settings) -> str | None:
    """Fetch a repo's README as plain text, or None if it has none.

    Doubles as the "has a README" filter (a 404 here means "drop this
    candidate") and as the text tagging.py tags — one fetch per surviving
    candidate, not two.
    """
    owner_repo = repo_url.removeprefix("https://github.com/").rstrip("/")
    response = requests.get(
        f"https://api.github.com/repos/{owner_repo}/readme",
        headers={**_headers(settings), "Accept": "application/vnd.github.raw+json"},
        timeout=10,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text
