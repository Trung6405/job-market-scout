from __future__ import annotations

from google.adk.tools.mcp_tool import McpToolset, SseConnectionParams

from scout.config import Settings
from scout.config import settings as default_settings


def build_scraper_toolset(settings: Settings | None = None) -> McpToolset:
    active_settings = settings or default_settings
    return McpToolset(
        connection_params=SseConnectionParams(
            url=f"{active_settings.jobspy_mcp_url}/mcp/connect"
        ),
        tool_filter=["search_jobs"],
    )
