from __future__ import annotations

import pytest
import requests

from scout.config import Settings
from scout.sub_agents.coach.link_health import check_url, classify_status


class _FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def close(self):
        pass


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


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


def test_check_url_healthy_head_issues_no_get(monkeypatch):
    calls = []

    def _fake_head(url, timeout, allow_redirects):
        calls.append("head")
        return _FakeResponse(200)

    def _fake_get(*a, **k):
        calls.append("get")
        return _FakeResponse(200)

    monkeypatch.setattr("scout.sub_agents.coach.link_health.requests.head", _fake_head)
    monkeypatch.setattr("scout.sub_agents.coach.link_health.requests.get", _fake_get)

    result = check_url("https://example.com/repo", _settings())

    assert result.verdict == "healthy"
    assert calls == ["head"]


def test_check_url_falls_back_to_get_on_non_success_head(monkeypatch):
    monkeypatch.setattr(
        "scout.sub_agents.coach.link_health.requests.head",
        lambda *a, **k: _FakeResponse(405),
    )
    monkeypatch.setattr(
        "scout.sub_agents.coach.link_health.requests.get",
        lambda *a, **k: _FakeResponse(200),
    )

    result = check_url("https://example.com/repo", _settings())

    assert result.verdict == "healthy"


def test_check_url_get_confirms_gone(monkeypatch):
    monkeypatch.setattr(
        "scout.sub_agents.coach.link_health.requests.head",
        lambda *a, **k: _FakeResponse(404),
    )
    monkeypatch.setattr(
        "scout.sub_agents.coach.link_health.requests.get",
        lambda *a, **k: _FakeResponse(404),
    )

    result = check_url("https://example.com/repo", _settings())

    assert result.verdict == "gone"


def test_check_url_get_wins_over_head_verdict(monkeypatch):
    """A HEAD 404 that a GET resolves as 200 is healthy — the GET is authoritative."""
    monkeypatch.setattr(
        "scout.sub_agents.coach.link_health.requests.head",
        lambda *a, **k: _FakeResponse(404),
    )
    monkeypatch.setattr(
        "scout.sub_agents.coach.link_health.requests.get",
        lambda *a, **k: _FakeResponse(200),
    )

    result = check_url("https://example.com/repo", _settings())

    assert result.verdict == "healthy"


def test_check_url_passes_configured_timeout_and_follows_redirects(monkeypatch):
    captured = {}

    def _fake_head(url, timeout, allow_redirects):
        captured["timeout"] = timeout
        captured["allow_redirects"] = allow_redirects
        return _FakeResponse(200)

    monkeypatch.setattr("scout.sub_agents.coach.link_health.requests.head", _fake_head)

    check_url(
        "https://example.com/repo",
        _settings(coach_link_health_timeout_seconds=7),
    )

    assert captured["timeout"] == 7
    assert captured["allow_redirects"] is True


@pytest.mark.parametrize(
    "exc",
    [
        requests.Timeout("timed out"),
        requests.ConnectionError("connection refused"),
        requests.TooManyRedirects("too many redirects"),
    ],
)
def test_check_url_network_errors_are_transient(monkeypatch, exc):
    def _raise(*a, **k):
        raise exc

    monkeypatch.setattr("scout.sub_agents.coach.link_health.requests.head", _raise)
    monkeypatch.setattr("scout.sub_agents.coach.link_health.requests.get", _raise)

    result = check_url("https://example.com/repo", _settings())

    assert result.verdict == "transient"
    assert result.reason is not None


def test_check_url_reason_is_truncated(monkeypatch):
    def _raise(*a, **k):
        raise requests.ConnectionError("x" * 1000)

    monkeypatch.setattr("scout.sub_agents.coach.link_health.requests.head", _raise)

    result = check_url("https://example.com/repo", _settings())

    assert len(result.reason) <= 300


def test_check_url_get_network_error_after_head_transient(monkeypatch):
    """A HEAD 5xx followed by a GET that raises stays transient, not an exception."""
    monkeypatch.setattr(
        "scout.sub_agents.coach.link_health.requests.head",
        lambda *a, **k: _FakeResponse(503),
    )

    def _raise_get(*a, **k):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("scout.sub_agents.coach.link_health.requests.get", _raise_get)

    result = check_url("https://example.com/repo", _settings())

    assert result.verdict == "transient"
