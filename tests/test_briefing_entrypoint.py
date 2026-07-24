from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout.config import Settings
from scout.shared.schemas import BriefingProse, Listing, MatchResult
from scout.sub_agents.briefing.briefing import run_briefing


def _make_match(external_id: str, title: str, score: int) -> MatchResult:
    listing = Listing(
        source="linkedin",
        external_id=external_id,
        title=title,
        company="Acme Corp",
        location="Remote",
        is_remote=True,
        url=f"https://www.linkedin.com/jobs/view/{external_id}",
        description="Build backend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    return MatchResult(listing=listing, score=score, reasoning="Good fit.")


def _discord_settings(**overrides):
    base = dict(
        min_match_score=60,
        discord_bot_token="bot-token",
        discord_channel_id="123456789",
    )
    base.update(overrides)
    return Settings(**base)


def _patch_briefing(monkeypatch, *, summarize, build, send):
    monkeypatch.setattr(
        "scout.sub_agents.briefing.briefing.summarize_matches", summarize
    )
    monkeypatch.setattr("scout.sub_agents.briefing.briefing.build_embed", build)
    monkeypatch.setattr("scout.sub_agents.briefing.briefing.send_message", send)


@pytest.mark.asyncio
async def test_run_briefing_summarizes_and_sends_when_matches_qualify(monkeypatch):
    match = _make_match("1", "Platform Engineer", 88)
    settings = _discord_settings()

    summarize_calls = []
    build_calls = []
    send_calls = []

    async def _fake_summarize(top_matches, active_settings):
        summarize_calls.append(top_matches)
        return BriefingProse(intro="Nice matches.", takeaways=[])

    def _fake_build(top_matches, prose, active_settings):
        build_calls.append((top_matches, prose))
        return {"embeds": [{"title": "built"}]}

    async def _fake_send(payload, active_settings):
        send_calls.append(payload)

    _patch_briefing(
        monkeypatch, summarize=_fake_summarize, build=_fake_build, send=_fake_send
    )

    result = await run_briefing([match], settings)

    assert len(summarize_calls) == 1
    assert [m.listing.external_id for m in summarize_calls[0]] == ["1"]
    assert len(build_calls) == 1
    # The built payload is exactly what gets sent and returned.
    assert send_calls == [{"embeds": [{"title": "built"}]}]
    assert result == {"embeds": [{"title": "built"}]}


@pytest.mark.asyncio
async def test_run_briefing_accepts_report_path_without_error(monkeypatch):
    match = _make_match("1", "Platform Engineer", 88)
    settings = _discord_settings()
    report_path = Path("reports/2026-07-21/dashboard.html")

    async def _fake_summarize(top_matches, active_settings):
        return BriefingProse(intro="Nice matches.", takeaways=[])

    def _fake_build(top_matches, prose, active_settings):
        return {"embeds": []}

    async def _fake_send(payload, active_settings):
        pass

    _patch_briefing(
        monkeypatch, summarize=_fake_summarize, build=_fake_build, send=_fake_send
    )

    # report_path is accepted for call-site compatibility; it is not part of
    # the Discord message (report link dropped).
    await run_briefing([match], settings, report_path=report_path)


@pytest.mark.asyncio
async def test_run_briefing_skips_summarize_when_no_matches_qualify(monkeypatch):
    match = _make_match("1", "Platform Engineer", 10)
    settings = _discord_settings()

    summarize_calls = []
    build_calls = []

    async def _fake_summarize(top_matches, active_settings):
        summarize_calls.append(top_matches)
        return BriefingProse(intro="", takeaways=[])

    def _fake_build(top_matches, prose, active_settings):
        build_calls.append((top_matches, prose))
        return {"embeds": []}

    async def _fake_send(payload, active_settings):
        pass

    _patch_briefing(
        monkeypatch, summarize=_fake_summarize, build=_fake_build, send=_fake_send
    )

    await run_briefing([match], settings)

    assert summarize_calls == []
    assert build_calls == [([], None)]


@pytest.mark.asyncio
async def test_run_briefing_raises_before_summarizing_when_discord_not_configured(
    monkeypatch,
):
    match = _make_match("1", "Platform Engineer", 88)
    settings = _discord_settings(discord_bot_token="", discord_channel_id="")

    summarize_calls = []

    async def _fake_summarize(top_matches, active_settings):
        summarize_calls.append(top_matches)
        return BriefingProse(intro="Nice matches.", takeaways=[])

    monkeypatch.setattr(
        "scout.sub_agents.briefing.briefing.summarize_matches", _fake_summarize
    )

    with pytest.raises(ValueError):
        await run_briefing([match], settings)

    assert summarize_calls == []
