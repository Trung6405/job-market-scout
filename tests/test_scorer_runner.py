from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scout.config import Settings
from scout.shared.schemas import Listing, ListingScore
from scout.sub_agents.scorer.runner import parse_scores, run_scorer


def _score_dict(**overrides):
    defaults = dict(source="linkedin", external_id="1", score=75, reasoning="Good fit.")
    defaults.update(overrides)
    return defaults


def test_parse_scores_valid_json():
    raw = json.dumps([_score_dict()])

    scores = parse_scores(raw)

    assert scores == [ListingScore(**_score_dict())]


def test_parse_scores_strips_markdown_code_fence():
    raw = "```json\n" + json.dumps([_score_dict(external_id="2")]) + "\n```"

    scores = parse_scores(raw)

    assert scores[0].external_id == "2"


def test_parse_scores_empty_list():
    assert parse_scores("[]") == []


def _make_listing(**overrides):
    defaults = dict(
        source="linkedin",
        external_id="1",
        title="Backend Engineer",
        company="Acme Corp",
        location="Sydney, AU",
        is_remote=True,
        url="https://www.linkedin.com/jobs/view/1",
        description="Build backend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Listing(**defaults)


@pytest.mark.asyncio
async def test_run_scorer_returns_parsed_scores(monkeypatch):
    raw = json.dumps([_score_dict()])

    async def _fake_run(agent):
        return raw

    monkeypatch.setattr(
        "scout.sub_agents.scorer.runner._run_scorer_agent", _fake_run
    )

    scores = await run_scorer([_make_listing()], Settings())

    assert scores == [ListingScore(**_score_dict())]
