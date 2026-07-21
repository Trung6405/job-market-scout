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
    async with sse_client(f"{url}/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search_jobs", params)
            return parse_search_jobs_result(result)
