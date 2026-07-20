from __future__ import annotations

import json
from types import SimpleNamespace

from scout.sub_agents.scraper.mcp_client import parse_search_jobs_result


def _tool_result(payload: dict):
    return SimpleNamespace(
        content=[SimpleNamespace(text=json.dumps(payload))]
    )


def test_parse_search_jobs_result_returns_jobs_list():
    result = _tool_result({"jobs": [{"id": "1"}], "count": 1})

    jobs = parse_search_jobs_result(result)

    assert jobs == [{"id": "1"}]


def test_parse_search_jobs_result_defaults_to_empty_list():
    result = _tool_result({"count": 0, "message": "no results"})

    jobs = parse_search_jobs_result(result)

    assert jobs == []
