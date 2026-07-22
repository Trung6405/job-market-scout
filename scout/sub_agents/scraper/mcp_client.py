from __future__ import annotations

import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)


def parse_search_jobs_result(result: Any) -> list[dict]:
    if getattr(result, "isError", False):
        error = getattr(result, "error", None)
        message = (error or {}).get("message", error) if isinstance(
            error, dict
        ) else error
        logger.warning("search_jobs tool call failed: %s", message)
        return []
    payload = json.loads(result.content[0].text)
    return payload.get("jobs", [])


async def fetch_jobs(url: str, **params: Any) -> list[dict]:
    logger.debug("Connecting to MCP server at %s with params=%r", url, params)
    async with sse_client(f"{url}/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            logger.debug("MCP session initialized, calling search_jobs")
            result = await session.call_tool("search_jobs", params)
            jobs = parse_search_jobs_result(result)
            logger.debug("search_jobs returned %d job(s)", len(jobs))
            return jobs
