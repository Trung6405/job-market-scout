from __future__ import annotations

import pytest

from scout.sub_agents.coach.link_health import classify_status


@pytest.mark.parametrize("status_code", [200, 204, 302])
def test_classify_status_healthy(status_code):
    assert classify_status(status_code) == "healthy"


@pytest.mark.parametrize("status_code", [404, 410])
def test_classify_status_gone(status_code):
    assert classify_status(status_code) == "gone"


@pytest.mark.parametrize("status_code", [401, 403, 405, 429, 500, 502, 503])
def test_classify_status_transient(status_code):
    assert classify_status(status_code) == "transient"


def test_classify_status_unknown_code_is_transient():
    """An unexpected status is not evidence of removal."""
    assert classify_status(599) == "transient"
