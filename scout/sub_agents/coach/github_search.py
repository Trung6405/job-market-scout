from __future__ import annotations

from datetime import UTC, datetime, timedelta

import requests

from scout.config import Settings

_SEARCH_URL = "https://api.github.com/search/repositories"
# One keep-alive session for every GitHub call — an aggregator run makes
# hundreds of requests to api.github.com, and a bare requests.get would pay
# a fresh TCP+TLS handshake for each one.
_session = requests.Session()
# The Search API has no relative-date query operator, so "pushed within
# ~18 months" (spec) is filtered client-side against this cutoff.
_STALE_AFTER = timedelta(days=548)
# FR-CC-2's popularity bar. One constant rather than a literal in the query,
# because the awesome-list bootstrap has to apply the *same* bar client-side
# (it has no search query to push filters into) and two copies of "200" drift
# without anything noticing.
_MIN_STARS = 200


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"token {settings.github_pat}",
        "Accept": "application/vnd.github+json",
    }


def passes_quality_bar(repo: dict, *, now: datetime | None = None) -> bool:
    """Whether a repo payload clears FR-CC-2's bar: popular, active, maintained.

    The search path gets this for free — `stars:>200 archived:false` in the query
    plus a freshness check on the results. The bootstrap path harvests raw links
    out of a README, so it has to ask GitHub about each one and apply the bar
    here, against the same constants.

    A payload missing or malforming any field it needs is rejected. "We could not
    establish that this clears the bar" must not read as "fine" for something
    that lands in the corpus permanently.
    """
    stars = repo.get("stargazers_count")
    if not isinstance(stars, int) or stars <= _MIN_STARS:
        return False
    if repo.get("archived") is not False:
        return False
    pushed_at = repo.get("pushed_at")
    if not isinstance(pushed_at, str):
        return False
    try:
        pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if pushed.tzinfo is None:
        pushed = pushed.replace(tzinfo=UTC)
    return pushed >= (now or datetime.now(UTC)) - _STALE_AFTER


def fetch_repo_metadata(repo_url: str, settings: Settings) -> dict | None:
    """The repo's API payload, or None if it is gone or inaccessible.

    Costs one core-REST call per candidate. That limit is 5,000/hour, not the
    Search API's 30/minute, so this needs no throttling — and it is far cheaper
    than the LLM tagging call it saves for every candidate it rejects.
    """
    owner_repo = repo_url.removeprefix("https://github.com/").rstrip("/")
    response = _session.get(
        f"https://api.github.com/repos/{owner_repo}",
        headers=_headers(settings),
        timeout=10,
    )
    if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
        # Rate limited, not a bad candidate. Dropping these silently would thin
        # the corpus by however long the limit lasted and look identical to
        # "those repos didn't qualify" — so fail loudly instead.
        response.raise_for_status()
    if response.status_code in (403, 404, 451):
        # Gone, renamed, private, or DMCA'd — all "drop this candidate", not
        # "fail the run". It will be re-harvested next week if it comes back.
        return None
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else None


def search_candidates(skill: str, settings: Settings) -> list[str]:
    """Return up to `coach_top_n_per_skill` candidate repo URLs for `skill`."""
    params: dict[str, str | int] = {
        "q": (
            f"{skill} in:readme,description "
            f"stars:>{_MIN_STARS} archived:false"
        ),
        "sort": "stars",
        "order": "desc",
        "per_page": 30,
    }
    response = _session.get(
        _SEARCH_URL,
        headers=_headers(settings),
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    cutoff = datetime.now(UTC) - _STALE_AFTER
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
    response = _session.get(
        f"https://api.github.com/repos/{owner_repo}/readme",
        headers={**_headers(settings), "Accept": "application/vnd.github.raw+json"},
        timeout=10,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text
