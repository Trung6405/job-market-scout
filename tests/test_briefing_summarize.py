from __future__ import annotations

import json

import pytest

from scout.config import Settings
from scout.shared.schemas import BriefingProse
from scout.sub_agents.briefing.summarize import (
    parse_briefing_prose,
    summarize_matches,
)
from tests.test_briefing_agent import _make_match


def test_parse_briefing_prose_valid_json():
    raw = json.dumps(
        {
            "intro": "Nice matches today.",
            "takeaways": [
                {"source": "linkedin", "external_id": "1", "takeaway": "Great fit."}
            ],
        }
    )

    prose = parse_briefing_prose(raw)

    assert prose.intro == "Nice matches today."
    assert prose.takeaways[0].external_id == "1"


def test_parse_briefing_prose_rejects_non_json():
    with pytest.raises(Exception):
        parse_briefing_prose("not json")


def test_parse_briefing_prose_strips_markdown_code_fence():
    raw = (
        "```json\n"
        + json.dumps(
            {
                "intro": "Nice matches today.",
                "takeaways": [
                    {
                        "source": "linkedin",
                        "external_id": "1",
                        "takeaway": "Great fit.",
                    }
                ],
            }
        )
        + "\n```"
    )

    prose = parse_briefing_prose(raw)

    assert prose.intro == "Nice matches today."
    assert prose.takeaways[0].external_id == "1"


def test_parse_briefing_prose_strips_bare_code_fence_without_language_tag():
    raw = '```\n{"intro": "Hi.", "takeaways": []}\n```'

    prose = parse_briefing_prose(raw)

    assert prose.intro == "Hi."


@pytest.mark.asyncio
async def test_summarize_matches_returns_parsed_prose(monkeypatch):
    raw = json.dumps(
        {
            "intro": "Nice matches today.",
            "takeaways": [
                {"source": "linkedin", "external_id": "1", "takeaway": "Great fit."}
            ],
        }
    )

    async def _fake_run(agent):
        return raw

    monkeypatch.setattr(
        "scout.sub_agents.briefing.summarize._run_briefing_agent", _fake_run
    )

    prose = await summarize_matches(
        [_make_match("1", "Platform Engineer", 88)], Settings()
    )

    assert isinstance(prose, BriefingProse)
    assert prose.takeaways[0].takeaway == "Great fit."
