from datetime import datetime, timezone

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from scout.config import Settings
from scout.prompts import build_scorer_instruction
from scout.shared.schemas import Listing, ListingScoreBatch
from scout.sub_agents.scorer.agent import build_scorer_agent

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

def test_build_scorer_instruction_includes_resume_and_listing_titles():
    settings = Settings()
    listings = [_make_listing(title="Platform Engineer")]

    instruction = build_scorer_instruction(settings, listings)

    assert settings.resume_text in instruction
    assert "Platform Engineer" in instruction

def test_build_scorer_instruction_includes_external_id_for_joining():
    settings = Settings()
    listings = [_make_listing(external_id="job-42")]

    instruction = build_scorer_instruction(settings, listings)

    assert "job-42" in instruction

def test_build_scorer_instruction_includes_source_for_joining():
    settings = Settings()
    listings = [_make_listing(source="indeed")]

    instruction = build_scorer_instruction(settings, listings)

    assert "indeed" in instruction

def test_build_scorer_instruction_excludes_url_and_scraped_at():
    settings = Settings()
    listings = [_make_listing(url="https://www.linkedin.com/jobs/view/999")]

    instruction = build_scorer_instruction(settings, listings)

    assert "https://www.linkedin.com/jobs/view/999" not in instruction
    assert "2026-07-15" not in instruction

def test_build_scorer_instruction_truncates_description_to_char_limit():
    settings = Settings(description_char_limit=20)
    listings = [_make_listing(description="x" * 100)]

    instruction = build_scorer_instruction(settings, listings)

    assert "x" * 100 not in instruction
    assert "x" * 20 in instruction

def test_build_scorer_instruction_directs_weighing_missing_required_skills():
    instruction = build_scorer_instruction(Settings(), [_make_listing()])

    assert "required" in instruction.lower()
    assert "missing" in instruction.lower()

def test_build_scorer_instruction_directs_weighing_overqualification():
    instruction = build_scorer_instruction(Settings(), [_make_listing()])

    assert "overqualif" in instruction.lower()

def test_build_scorer_agent_uses_configured_model():
    settings = Settings(deepseek_model="deepseek/deepseek-reasoner")

    agent = build_scorer_agent([_make_listing()], settings)

    assert isinstance(agent, LlmAgent)
    assert isinstance(agent.model, LiteLlm)
    assert agent.model.model == "deepseek/deepseek-reasoner"

def test_build_scorer_agent_uses_zero_temperature():
    agent = build_scorer_agent([_make_listing()], Settings())

    assert agent.model._additional_args.get("temperature") == 0

def test_build_scorer_agent_outputs_listing_score_batch():
    agent = build_scorer_agent([_make_listing()], Settings())

    assert agent.output_schema == ListingScoreBatch

def test_build_scorer_agent_requests_json_object_mode():
    agent = build_scorer_agent([_make_listing()], Settings())

    assert agent.model._additional_args.get("response_format") == {
        "type": "json_object"
    }

def test_build_scorer_agent_excludes_rule_filtered_listings_from_instruction():
    settings = Settings(remote_only=True)
    listings = [
        _make_listing(external_id="1", title="Remote Role", is_remote=True),
        _make_listing(external_id="2", title="Onsite Role", is_remote=False),
    ]

    agent = build_scorer_agent(listings, settings)

    assert "Remote Role" in agent.instruction
    assert "Onsite Role" not in agent.instruction

def test_build_scorer_agent_registers_no_tools():
    agent = build_scorer_agent([_make_listing()], Settings())

    assert agent.tools == []

def test_build_scorer_agent_has_no_score_threshold_callback():
    agent = build_scorer_agent([_make_listing()], Settings())

    assert agent.after_model_callback is None
