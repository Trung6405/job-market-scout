from __future__ import annotations

from scout.config import Settings
from scout.sub_agents.coach.bootstrap import harvest_awesome_list


def _settings() -> Settings:
    return Settings(github_pat="test-pat")


def test_harvest_awesome_list_extracts_repo_links(monkeypatch):
    readme = """
# Awesome Python

- [Django](https://github.com/django/django) - A web framework.
- [Flask](https://github.com/pallets/flask) - A microframework.
- Self-reference: [this list](https://github.com/vinta/awesome-python)
"""
    monkeypatch.setattr(
        "scout.sub_agents.coach.bootstrap.fetch_readme",
        lambda list_url, settings: readme,
    )
    candidates = harvest_awesome_list(
        "https://github.com/vinta/awesome-python", _settings()
    )
    assert candidates == [
        "https://github.com/django/django",
        "https://github.com/pallets/flask",
    ]


def test_harvest_awesome_list_dedupes_repeated_links(monkeypatch):
    readme = (
        "[Django](https://github.com/django/django) "
        "and again [Django](https://github.com/django/django)"
    )
    monkeypatch.setattr(
        "scout.sub_agents.coach.bootstrap.fetch_readme",
        lambda list_url, settings: readme,
    )
    candidates = harvest_awesome_list(
        "https://github.com/vinta/awesome-python", _settings()
    )
    assert candidates == ["https://github.com/django/django"]


def test_harvest_awesome_list_returns_empty_when_no_readme(monkeypatch):
    monkeypatch.setattr(
        "scout.sub_agents.coach.bootstrap.fetch_readme",
        lambda list_url, settings: None,
    )
    candidates = harvest_awesome_list("https://github.com/dead/list", _settings())
    assert candidates == []
