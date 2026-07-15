from google.adk.tools.mcp_tool import McpToolset, SseConnectionParams

from scout.config import Settings
from scout.sub_agents.scraper.tools import build_scraper_toolset


def test_build_scraper_toolset_returns_mcp_toolset():
    toolset = build_scraper_toolset(Settings())

    assert isinstance(toolset, McpToolset)


def test_build_scraper_toolset_targets_configured_mcp_url():
    settings = Settings(jobspy_mcp_url="http://test-jobspy:9423")

    toolset = build_scraper_toolset(settings)

    assert isinstance(toolset.connection_params, SseConnectionParams)
    assert toolset.connection_params.url == "http://test-jobspy:9423/sse"


def test_build_scraper_toolset_restricts_to_search_jobs_tool():
    toolset = build_scraper_toolset(Settings())

    assert toolset.tool_filter == ["search_jobs"]
