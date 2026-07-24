from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scout.config import Settings
from scout.prompts import build_requirements_instruction
from scout.shared.profile import render_profile_text
from scout.shared.schemas import ListingRequirements, ListingRequirementsBatch
from scout.sub_agents.advisor import runner


def _requirements(**overrides) -> ListingRequirements:
    defaults = dict(
        source="linkedin",
        external_id="1",
        must_have=[],
        nice_to_have=[],
    )
    defaults.update(overrides)
    return ListingRequirements(**defaults)


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
    from scout.shared.schemas import Listing

    return Listing(**defaults)


# --- run_requirements_extraction ---


@pytest.mark.asyncio
async def test_run_requirements_extraction_returns_parsed_requirements(monkeypatch):
    async def _fake_complete_json(prompt, schema, settings, **kwargs):
        assert schema is ListingRequirementsBatch
        return ListingRequirementsBatch(requirements=[_requirements()])

    monkeypatch.setattr(runner, "complete_json", _fake_complete_json)

    requirements = await runner.run_requirements_extraction(
        [_make_listing()], Settings()
    )

    assert requirements == [_requirements()]


@pytest.mark.asyncio
async def test_run_requirements_extraction_splits_listings_into_batches(monkeypatch):
    """A single LLM response is capped by the model's max output tokens, so
    extracting for many listings in one call truncates the JSON. Listings are
    split into batches small enough that each response parses."""
    listings = [_make_listing(external_id=str(i)) for i in range(5)]
    call_count = {"n": 0}

    async def _fake_complete_json(prompt, schema, settings, **kwargs):
        call_count["n"] += 1
        ids = [
            listing.external_id
            for listing in listings
            if f'"external_id": "{listing.external_id}"' in prompt
        ]
        return ListingRequirementsBatch(
            requirements=[_requirements(external_id=i) for i in ids]
        )

    monkeypatch.setattr(runner, "complete_json", _fake_complete_json)

    settings = Settings()
    object.__setattr__(settings, "requirements_batch_size", 2)
    requirements = await runner.run_requirements_extraction(listings, settings)

    # 5 listings at batch size 2 -> 3 calls, and every listing is covered once.
    assert call_count["n"] == 3
    assert sorted(r.external_id for r in requirements) == ["0", "1", "2", "3", "4"]


@pytest.mark.asyncio
async def test_run_requirements_extraction_makes_no_llm_call_for_no_listings(
    monkeypatch,
):
    async def _should_not_be_called(*args, **kwargs):
        raise AssertionError("no call expected for an empty listing set")

    monkeypatch.setattr(runner, "complete_json", _should_not_be_called)

    assert await runner.run_requirements_extraction([], Settings()) == []


# --- build_requirements_instruction ---


def test_build_requirements_instruction_includes_listing_titles_and_ids():
    settings = Settings()
    listings = [_make_listing(title="Platform Engineer")]

    instruction = build_requirements_instruction(settings, listings)

    assert "Platform Engineer" in instruction


def test_build_requirements_instruction_includes_external_id_for_joining():
    settings = Settings()
    listings = [_make_listing(external_id="job-42")]

    instruction = build_requirements_instruction(settings, listings)

    assert "job-42" in instruction


def test_build_requirements_instruction_includes_source_for_joining():
    settings = Settings()
    listings = [_make_listing(source="indeed")]

    instruction = build_requirements_instruction(settings, listings)

    assert "indeed" in instruction


def test_build_requirements_instruction_excludes_url_and_scraped_at():
    settings = Settings()
    listings = [_make_listing(url="https://www.linkedin.com/jobs/view/999")]

    instruction = build_requirements_instruction(settings, listings)

    assert "https://www.linkedin.com/jobs/view/999" not in instruction
    assert "2026-07-15" not in instruction


def test_build_requirements_instruction_truncates_description_to_char_limit():
    settings = Settings(description_char_limit=20)
    listings = [_make_listing(description="x" * 100)]

    instruction = build_requirements_instruction(settings, listings)

    assert "x" * 100 not in instruction
    assert "x" * 20 in instruction


def test_build_requirements_instruction_does_not_include_profile():
    settings = Settings()
    listings = [_make_listing()]

    instruction = build_requirements_instruction(settings, listings)

    assert render_profile_text(settings.profile) not in instruction


def test_build_requirements_instruction_distinguishes_must_have_and_nice_to_have():
    instruction = build_requirements_instruction(Settings(), [_make_listing()])

    assert "must" in instruction.lower()
    assert "nice" in instruction.lower() or "preferred" in instruction.lower()


def test_build_requirements_instruction_directs_not_inventing_requirements():
    instruction = build_requirements_instruction(Settings(), [_make_listing()])

    assert "invent" in instruction.lower() or "not stated" in instruction.lower()
