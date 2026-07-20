from datetime import datetime, timezone

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from scout.config import Settings
from scout.shared.schemas import BriefingProse, Listing, MatchResult
from scout.sub_agents.briefing.agent import build_briefing_agent


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


def test_build_briefing_agent_uses_configured_model():
    settings = Settings(deepseek_model="deepseek/deepseek-reasoner")

    agent = build_briefing_agent([_make_match("1", "Platform Engineer", 88)], settings)

    assert isinstance(agent, LlmAgent)
    assert isinstance(agent.model, LiteLlm)
    assert agent.model.model == "deepseek/deepseek-reasoner"


def test_build_briefing_agent_outputs_briefing_prose():
    agent = build_briefing_agent([_make_match("1", "Platform Engineer", 88)], Settings())

    assert agent.output_schema == BriefingProse


def test_build_briefing_agent_requests_json_object_mode():
    agent = build_briefing_agent([_make_match("1", "Platform Engineer", 88)], Settings())

    assert agent.model._additional_args.get("response_format") == {
        "type": "json_object"
    }


def test_build_briefing_agent_registers_no_tools():
    agent = build_briefing_agent([_make_match("1", "Platform Engineer", 88)], Settings())

    assert agent.tools == []


def test_build_briefing_agent_instruction_includes_match_title():
    agent = build_briefing_agent([_make_match("1", "Platform Engineer", 88)], Settings())

    assert "Platform Engineer" in agent.instruction
