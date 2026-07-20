from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone

from scout.config import Settings
from scout.shared.schemas import Listing
from scout.sub_agents.scraper.runner import parse_listings, run_scraper


def _listing_dict(**overrides):
    defaults = dict(
        source="linkedin",
        external_id="1",
        title="Backend Engineer",
        company="Acme Corp",
        location="Sydney, AU",
        is_remote=True,
        url="https://www.linkedin.com/jobs/view/1",
        description="Build backend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc).isoformat(),
    )
    defaults.update(overrides)
    return defaults


def test_parse_listings_valid_json():
    raw = json.dumps([_listing_dict()])

    listings = parse_listings(raw)

    assert listings == [Listing(**_listing_dict())]


def test_parse_listings_strips_markdown_code_fence():
    raw = "```json\n" + json.dumps([_listing_dict(external_id="2")]) + "\n```"

    listings = parse_listings(raw)

    assert listings[0].external_id == "2"


def test_parse_listings_empty_list():
    assert parse_listings("[]") == []


@pytest.mark.asyncio
async def test_run_scraper_returns_parsed_listings(monkeypatch):
    raw = json.dumps([_listing_dict()])

    async def _fake_run(agent):
        return raw

    monkeypatch.setattr(
        "scout.sub_agents.scraper.runner._run_scraper_agent", _fake_run
    )

    listings = await run_scraper(Settings())

    assert listings == [Listing(**_listing_dict())]
