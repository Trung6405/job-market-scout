"""Both paths into the corpus must apply the same quality bar.

The per-skill search enforces FR-CC-2's bar server-side (`stars:>200
archived:false`) plus a client-side freshness cutoff. The awesome-list bootstrap
enforced nothing at all: every `github.com/owner/repo` link in six READMEs became
a candidate, so 1,282 unfiltered repos each cost an LLM tagging call and then sat
in the corpus regardless of whether they were popular, maintained, or archived.

That is 45 minutes of tagging per seed run spent partly on repos the search path
would have rejected outright, and a corpus whose quality depends on which door a
resource came through.

The threshold lives in one constant used by both the query string and the
predicate, because two copies of "200" is exactly the kind of thing that drifts
silently.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scout.sub_agents.coach import github_search
from scout.sub_agents.coach.github_search import (
    _MIN_STARS,
    _STALE_AFTER,
    passes_quality_bar,
)


def _repo(**overrides) -> dict:
    """A repo payload that passes, so each test changes one thing."""
    fresh = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    return {
        "stargazers_count": _MIN_STARS + 500,
        "archived": False,
        "pushed_at": fresh.replace("+00:00", "Z"),
    } | overrides


def test_a_popular_maintained_repo_passes():
    assert passes_quality_bar(_repo())


def test_an_unpopular_repo_is_rejected():
    assert not passes_quality_bar(_repo(stargazers_count=_MIN_STARS - 1))


def test_the_threshold_is_exclusive_like_the_search_query():
    """The search query says `stars:>200`, which is strictly greater. A
    predicate using >= would admit repos the search path rejects, so the two
    doors into the corpus would disagree at the boundary."""
    assert not passes_quality_bar(_repo(stargazers_count=_MIN_STARS))
    assert passes_quality_bar(_repo(stargazers_count=_MIN_STARS + 1))


def test_an_archived_repo_is_rejected():
    assert not passes_quality_bar(_repo(archived=True))


def test_a_stale_repo_is_rejected():
    stale = datetime.now(timezone.utc) - _STALE_AFTER - timedelta(days=1)
    assert not passes_quality_bar(_repo(pushed_at=stale.isoformat().replace("+00:00", "Z")))


def test_a_repo_pushed_just_inside_the_cutoff_passes():
    edge = datetime.now(timezone.utc) - _STALE_AFTER + timedelta(hours=1)
    assert passes_quality_bar(_repo(pushed_at=edge.isoformat().replace("+00:00", "Z")))


def test_a_malformed_payload_is_rejected_rather_than_raising():
    """A missing field means we could not establish the repo clears the bar,
    and "unknown" must not read as "fine" for something that lands in the
    corpus permanently."""
    assert not passes_quality_bar({})
    assert not passes_quality_bar(_repo(pushed_at=None))
    assert not passes_quality_bar(_repo(pushed_at="not-a-date"))


def test_the_search_query_and_the_predicate_share_one_threshold():
    """Guards the drift this constant exists to prevent: if someone edits the
    query string to `stars:>500` without touching _MIN_STARS, the bootstrap
    filter would keep admitting 201-star repos."""
    import inspect

    source = inspect.getsource(github_search.search_candidates)
    assert "stars:>200" not in source, (
        "the star threshold must come from _MIN_STARS, not a literal in the query"
    )
    assert "_MIN_STARS" in source
