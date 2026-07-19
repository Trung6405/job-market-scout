from __future__ import annotations

from email.message import EmailMessage

import pytest

from scout.config import Settings
from scout.shared.schemas import BriefingProse, ListingScore
from scout.sub_agents.briefing.briefing import run_briefing
from tests.test_briefing_agent import _make_match


def _listing_and_score(match):
    return match.listing, ListingScore(
        source=match.listing.source,
        external_id=match.listing.external_id,
        score=match.score,
        reasoning=match.reasoning,
    )


@pytest.mark.asyncio
async def test_run_briefing_summarizes_and_sends_when_matches_qualify(monkeypatch):
    match = _make_match("1", "Platform Engineer", 88)
    listing, score = _listing_and_score(match)
    settings = Settings(
        min_match_score=60,
        gmail_address="scout@example.com",
        gmail_app_password="secret",
    )

    summarize_calls = []
    build_calls = []
    send_calls = []

    async def _fake_summarize(top_matches, active_settings):
        summarize_calls.append(top_matches)
        return BriefingProse(intro="Nice matches.", takeaways=[])

    def _fake_build(top_matches, prose, active_settings):
        build_calls.append((top_matches, prose))
        return EmailMessage()

    def _fake_send(message, active_settings):
        send_calls.append(message)

    monkeypatch.setattr(
        "scout.sub_agents.briefing.briefing.summarize_matches", _fake_summarize
    )
    monkeypatch.setattr(
        "scout.sub_agents.briefing.briefing.build_email", _fake_build
    )
    monkeypatch.setattr(
        "scout.sub_agents.briefing.briefing.send_email", _fake_send
    )

    await run_briefing([listing], [score], settings)

    assert len(summarize_calls) == 1
    assert [m.listing.external_id for m in summarize_calls[0]] == ["1"]
    assert len(build_calls) == 1
    assert len(send_calls) == 1


@pytest.mark.asyncio
async def test_run_briefing_skips_summarize_when_no_matches_qualify(monkeypatch):
    match = _make_match("1", "Platform Engineer", 10)
    listing, score = _listing_and_score(match)
    settings = Settings(
        min_match_score=60,
        gmail_address="scout@example.com",
        gmail_app_password="secret",
    )

    summarize_calls = []
    build_calls = []

    async def _fake_summarize(top_matches, active_settings):
        summarize_calls.append(top_matches)
        return BriefingProse(intro="", takeaways=[])

    def _fake_build(top_matches, prose, active_settings):
        build_calls.append((top_matches, prose))
        return EmailMessage()

    def _fake_send(message, active_settings):
        pass

    monkeypatch.setattr(
        "scout.sub_agents.briefing.briefing.summarize_matches", _fake_summarize
    )
    monkeypatch.setattr(
        "scout.sub_agents.briefing.briefing.build_email", _fake_build
    )
    monkeypatch.setattr(
        "scout.sub_agents.briefing.briefing.send_email", _fake_send
    )

    await run_briefing([listing], [score], settings)

    assert summarize_calls == []
    assert build_calls == [([], None)]


@pytest.mark.asyncio
async def test_run_briefing_raises_before_summarizing_when_gmail_not_configured(
    monkeypatch,
):
    match = _make_match("1", "Platform Engineer", 88)
    listing, score = _listing_and_score(match)
    settings = Settings(
        min_match_score=60, gmail_address="", gmail_app_password=""
    )

    summarize_calls = []

    async def _fake_summarize(top_matches, active_settings):
        summarize_calls.append(top_matches)
        return BriefingProse(intro="Nice matches.", takeaways=[])

    monkeypatch.setattr(
        "scout.sub_agents.briefing.briefing.summarize_matches", _fake_summarize
    )

    with pytest.raises(ValueError):
        await run_briefing([listing], [score], settings)

    assert summarize_calls == []
