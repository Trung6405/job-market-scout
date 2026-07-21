from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from scout.sub_agents.scraper.mcp_client import parse_search_jobs_result


def _tool_result(payload: dict):
    return SimpleNamespace(
        isError=False, content=[SimpleNamespace(text=json.dumps(payload))]
    )


def test_parse_search_jobs_result_returns_jobs_list():
    result = _tool_result({"jobs": [{"id": "1"}], "count": 1})

    jobs = parse_search_jobs_result(result)

    assert jobs == [{"id": "1"}]


def test_parse_search_jobs_result_defaults_to_empty_list():
    result = _tool_result({"count": 0, "message": "no results"})

    jobs = parse_search_jobs_result(result)

    assert jobs == []


def test_parse_search_jobs_result_returns_empty_list_and_logs_on_tool_error(
    caplog,
):
    result = SimpleNamespace(
        isError=True, content=[], error={"message": "boom"}
    )

    with caplog.at_level(logging.WARNING):
        jobs = parse_search_jobs_result(result)

    assert jobs == []
    assert "boom" in caplog.text
