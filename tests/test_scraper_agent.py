from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import McpToolset

from scout.config import Settings
from scout.shared.schemas import Listing
from scout.sub_agents.scraper.agent import build_scraper_agent


def test_build_scraper_agent_uses_configured_model():
    settings = Settings(deepseek_model="deepseek/deepseek-reasoner")

    agent = build_scraper_agent(settings)

    assert isinstance(agent, LlmAgent)
    assert isinstance(agent.model, LiteLlm)
    assert agent.model.model == "deepseek/deepseek-reasoner"


def test_build_scraper_agent_registers_mcp_toolset():
    agent = build_scraper_agent(Settings())

    assert len(agent.tools) == 1
    assert isinstance(agent.tools[0], McpToolset)


def test_build_scraper_agent_outputs_listing_list():
    agent = build_scraper_agent(Settings())

    assert agent.output_schema == list[Listing]
