from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import requests

from scout.config import Settings
from scout.sub_agents.coach.github_search import fetch_readme, search_candidates


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


def _settings(**overrides) -> Settings:
    return Settings(github_pat="test-pat", **overrides)


def _repo(name: str, days_old: int) -> dict:
    pushed_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    return {
        "html_url": f"https://github.com/org/{name}",
        "pushed_at": pushed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def test_search_candidates_filters_stale_repos(monkeypatch):
    items = [_repo("fresh", days_old=30), _repo("stale", days_old=600)]
    monkeypatch.setattr(
        "scout.sub_agents.coach.github_search.requests.get",
        lambda *a, **k: _FakeResponse(json_data={"items": items}),
    )
    candidates = search_candidates("kubernetes", _settings())
    assert candidates == ["https://github.com/org/fresh"]


def test_search_candidates_caps_at_top_n(monkeypatch):
    items = [_repo(f"repo{i}", days_old=1) for i in range(10)]
    monkeypatch.setattr(
        "scout.sub_agents.coach.github_search.requests.get",
        lambda *a, **k: _FakeResponse(json_data={"items": items}),
    )
    candidates = search_candidates("kubernetes", _settings(coach_top_n_per_skill=3))
    assert len(candidates) == 3


def test_search_candidates_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        "scout.sub_agents.coach.github_search.requests.get",
        lambda *a, **k: _FakeResponse(status_code=403),
    )
    with pytest.raises(requests.HTTPError):
        search_candidates("kubernetes", _settings())


def test_fetch_readme_returns_text(monkeypatch):
    monkeypatch.setattr(
        "scout.sub_agents.coach.github_search.requests.get",
        lambda *a, **k: _FakeResponse(text="# Kubernetes\n\nContainer orchestration."),
    )
    readme = fetch_readme("https://github.com/kubernetes/kubernetes", _settings())
    assert readme == "# Kubernetes\n\nContainer orchestration."


def test_fetch_readme_returns_none_on_404(monkeypatch):
    monkeypatch.setattr(
        "scout.sub_agents.coach.github_search.requests.get",
        lambda *a, **k: _FakeResponse(status_code=404),
    )
    readme = fetch_readme("https://github.com/no/readme", _settings())
    assert readme is None
