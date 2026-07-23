from __future__ import annotations

from scout.config import Settings
from scout.shared.schemas import BriefingProse, BriefingTakeaway
from scout.sub_agents.briefing.embed_builder import build_embed
from tests.test_briefing_agent import _make_match


def _settings():
    return Settings(discord_bot_token="bot-token", discord_channel_id="123")


def _single_embed(payload):
    assert set(payload) == {"embeds"}
    assert len(payload["embeds"]) == 1
    return payload["embeds"][0]


def test_build_embed_title_counts_matches():
    match = _make_match("1", "Platform Engineer", 88)
    prose = BriefingProse(intro="Nice matches.", takeaways=[])

    embed = _single_embed(build_embed([match], prose, _settings()))

    assert embed["title"] == "Job Market Scout: 1 match today"


def test_build_embed_pluralizes_title():
    matches = [_make_match("1", "Platform Engineer", 88), _make_match("2", "SRE", 90)]
    prose = BriefingProse(intro="Two good ones.", takeaways=[])

    embed = _single_embed(build_embed(matches, prose, _settings()))

    assert embed["title"] == "Job Market Scout: 2 matches today"


def test_build_embed_uses_intro_as_description_and_one_field_per_match():
    match = _make_match("1", "Platform Engineer", 88)
    prose = BriefingProse(
        intro="Nice matches.",
        takeaways=[
            BriefingTakeaway(source="linkedin", external_id="1", takeaway="Great fit.")
        ],
    )

    embed = _single_embed(build_embed([match], prose, _settings()))

    assert embed["description"] == "Nice matches."
    assert len(embed["fields"]) == 1
    field = embed["fields"][0]
    assert field["name"] == "Platform Engineer at Acme Corp — 88/100"
    assert str(match.listing.url) in field["value"]
    assert "Great fit." in field["value"]


def test_build_embed_uses_fallback_line_when_takeaway_missing():
    match = _make_match("1", "Platform Engineer", 88)
    prose = BriefingProse(intro="Nice matches.", takeaways=[])

    embed = _single_embed(build_embed([match], prose, _settings()))

    field = embed["fields"][0]
    assert "88" in field["value"]
    assert str(match.listing.url) in field["value"]


def test_build_embed_zero_matches_uses_no_match_embed():
    embed = _single_embed(build_embed([], None, _settings()))

    assert embed["title"] == "Job Market Scout: no strong matches today"
    assert embed.get("description")
    assert "fields" not in embed or embed["fields"] == []


def test_build_embed_clamps_overlong_field_name_to_discord_limit():
    match = _make_match("1", "X" * 500, 88)
    prose = BriefingProse(intro="Nice matches.", takeaways=[])

    embed = _single_embed(build_embed([match], prose, _settings()))

    name = embed["fields"][0]["name"]
    assert len(name) <= 256
    assert name.endswith("…")


def test_build_embed_clamps_overlong_field_value_to_discord_limit():
    match = _make_match("1", "Platform Engineer", 88)
    prose = BriefingProse(
        intro="Nice matches.",
        takeaways=[
            BriefingTakeaway(source="linkedin", external_id="1", takeaway="Y" * 2000)
        ],
    )

    embed = _single_embed(build_embed([match], prose, _settings()))

    value = embed["fields"][0]["value"]
    assert len(value) <= 1024
    assert value.endswith("…")
