from __future__ import annotations

import os

import pytest

from scout.config import Settings


@pytest.fixture(autouse=True)
def _clear_coach_env(monkeypatch):
    for name in (
        "GITHUB_PAT",
        "COACH_TOP_N_PER_SKILL",
        "COACH_AWESOME_LISTS",
        "COACH_TOP_K",
        "COACH_RESOURCE_MAX_AGE_DAYS",
        "COACH_TIPS_RESOURCES_PER_GAP",
        "COACH_TIPS_MAX_GAPS_PER_LISTING",
        "COACH_LINK_HEALTH_BATCH",
        "COACH_LINK_HEALTH_MAX_FAILURES",
        "COACH_LINK_HEALTH_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_github_pat_defaults_empty():
    assert Settings().github_pat == ""


def test_github_pat_reads_env(monkeypatch):
    monkeypatch.setenv("GITHUB_PAT", "ghp_test123")
    assert Settings().github_pat == "ghp_test123"


def test_coach_top_n_per_skill_defaults_to_five():
    assert Settings().coach_top_n_per_skill == 5


def test_coach_awesome_lists_has_five_defaults():
    """Five, not six: awesome-azure was removed after the harvest measured it
    yielding exactly 1 repo link (its README links Azure services and docs,
    not GitHub repos) against 129-547 from every other list. A source that
    contributes ~nothing still costs a README fetch every run and implies
    Azure coverage the corpus does not get that way — Azure rides on the
    per-skill dynamic search instead."""
    lists = Settings().coach_awesome_lists
    assert len(lists) == 5
    assert "https://github.com/vinta/awesome-python" in lists
    assert not any("awesome-azure" in url for url in lists)


def test_coach_awesome_lists_reads_csv_env(monkeypatch):
    monkeypatch.setenv("COACH_AWESOME_LISTS", "https://github.com/a/b,https://github.com/c/d")
    assert Settings().coach_awesome_lists == [
        "https://github.com/a/b",
        "https://github.com/c/d",
    ]


def test_coach_top_k_defaults_to_three():
    """The PRS specifies "top 2-3"; 3 gives P3 the widest choice to trim from."""
    assert Settings().coach_top_k == 3


def test_coach_top_k_reads_env(monkeypatch):
    monkeypatch.setenv("COACH_TOP_K", "2")
    assert Settings().coach_top_k == 2


def test_coach_resource_max_age_days_defaults_to_ninety():
    assert Settings().coach_resource_max_age_days == 90


def test_coach_resource_max_age_days_reads_env(monkeypatch):
    monkeypatch.setenv("COACH_RESOURCE_MAX_AGE_DAYS", "30")
    assert Settings().coach_resource_max_age_days == 30


def test_coach_tips_settings_default():
    settings = Settings()
    assert settings.coach_tips_resources_per_gap == 3
    assert settings.coach_tips_max_gaps_per_listing == 5


def test_coach_tips_settings_read_env(monkeypatch):
    monkeypatch.setenv("COACH_TIPS_RESOURCES_PER_GAP", "2")
    monkeypatch.setenv("COACH_TIPS_MAX_GAPS_PER_LISTING", "8")
    settings = Settings()
    assert settings.coach_tips_resources_per_gap == 2
    assert settings.coach_tips_max_gaps_per_listing == 8


def test_coach_link_health_settings_default():
    settings = Settings()
    assert settings.coach_link_health_batch == 50
    assert settings.coach_link_health_max_failures == 3
    assert settings.coach_link_health_timeout_seconds == 10


def test_coach_link_health_settings_read_env(monkeypatch):
    monkeypatch.setenv("COACH_LINK_HEALTH_BATCH", "20")
    monkeypatch.setenv("COACH_LINK_HEALTH_MAX_FAILURES", "5")
    monkeypatch.setenv("COACH_LINK_HEALTH_TIMEOUT_SECONDS", "15")
    settings = Settings()
    assert settings.coach_link_health_batch == 20
    assert settings.coach_link_health_max_failures == 5
    assert settings.coach_link_health_timeout_seconds == 15
