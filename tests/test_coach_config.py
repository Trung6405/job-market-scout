from __future__ import annotations

import os

import pytest

from scout.config import Settings


@pytest.fixture(autouse=True)
def _clear_coach_env(monkeypatch):
    for name in ("GITHUB_PAT", "COACH_TOP_N_PER_SKILL", "COACH_AWESOME_LISTS"):
        monkeypatch.delenv(name, raising=False)


def test_github_pat_defaults_empty():
    assert Settings().github_pat == ""


def test_github_pat_reads_env(monkeypatch):
    monkeypatch.setenv("GITHUB_PAT", "ghp_test123")
    assert Settings().github_pat == "ghp_test123"


def test_coach_top_n_per_skill_defaults_to_five():
    assert Settings().coach_top_n_per_skill == 5


def test_coach_awesome_lists_has_six_defaults():
    lists = Settings().coach_awesome_lists
    assert len(lists) == 6
    assert "https://github.com/vinta/awesome-python" in lists


def test_coach_awesome_lists_reads_csv_env(monkeypatch):
    monkeypatch.setenv("COACH_AWESOME_LISTS", "https://github.com/a/b,https://github.com/c/d")
    assert Settings().coach_awesome_lists == [
        "https://github.com/a/b",
        "https://github.com/c/d",
    ]
