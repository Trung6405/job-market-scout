from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from scout.config import Settings
from scout.prompts import build_requirements_instruction
from scout.shared.profile import render_profile_text
from scout.shared.schemas import Listing, ListingRequirements, ListingRequirementsBatch
from scout.sub_agents.advisor.agent import build_requirements_agent
from scout.sub_agents.advisor.runner import parse_requirements, run_requirements_extraction


def _requirements_dict(**overrides):
    defaults = dict(
        source="linkedin",
        external_id="1",
        must_have=["Python", "SQL"],
        nice_to_have=["Docker"],
    )
    defaults.update(overrides)
    return defaults


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


# --- parse_requirements ---


def test_parse_requirements_valid_json():
    raw = json.dumps({"requirements": [_requirements_dict()]})

    requirements = parse_requirements(raw)

    assert requirements == [ListingRequirements(**_requirements_dict())]


def test_parse_requirements_strips_markdown_code_fence():
    raw = (
        "```json\n"
        + json.dumps({"requirements": [_requirements_dict(external_id="2")]})
        + "\n```"
    )

    requirements = parse_requirements(raw)

    assert requirements[0].external_id == "2"


def test_parse_requirements_empty_list():
    assert parse_requirements(json.dumps({"requirements": []})) == []


@pytest.mark.asyncio
async def test_run_requirements_extraction_returns_parsed_requirements(monkeypatch):
    raw = json.dumps({"requirements": [_requirements_dict()]})

    async def _fake_run(agent):
        return raw

    monkeypatch.setattr(
        "scout.sub_agents.advisor.runner._run_requirements_agent", _fake_run
    )

    requirements = await run_requirements_extraction([_make_listing()], Settings())

    assert requirements == [ListingRequirements(**_requirements_dict())]


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


# --- build_requirements_agent ---


def test_build_requirements_agent_uses_configured_model():
    settings = Settings(deepseek_model="deepseek/deepseek-reasoner")

    agent = build_requirements_agent([_make_listing()], settings)

    assert isinstance(agent, LlmAgent)
    assert isinstance(agent.model, LiteLlm)
    assert agent.model.model == "deepseek/deepseek-reasoner"


def test_build_requirements_agent_uses_zero_temperature():
    agent = build_requirements_agent([_make_listing()], Settings())

    assert agent.model._additional_args.get("temperature") == 0


def test_build_requirements_agent_outputs_listing_requirements_batch():
    agent = build_requirements_agent([_make_listing()], Settings())

    assert agent.output_schema == ListingRequirementsBatch


def test_build_requirements_agent_requests_json_object_mode():
    agent = build_requirements_agent([_make_listing()], Settings())

    assert agent.model._additional_args.get("response_format") == {
        "type": "json_object"
    }


def test_build_requirements_agent_registers_no_tools():
    agent = build_requirements_agent([_make_listing()], Settings())

    assert agent.tools == []


def test_build_requirements_agent_does_not_filter_listings():
    settings = Settings(remote_only=True)
    listings = [
        _make_listing(external_id="1", title="Remote Role", is_remote=True),
        _make_listing(external_id="2", title="Onsite Role", is_remote=False),
    ]

    agent = build_requirements_agent(listings, settings)

    assert "Remote Role" in agent.instruction
    assert "Onsite Role" in agent.instruction
