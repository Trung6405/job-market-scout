from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scout.shared.profile import load_profile

_EXAMPLE_PATH = (
    Path(__file__).resolve().parent.parent / "scout" / "profile.json.example"
)


def test_load_profile_parses_example_file():
    profile = load_profile(_EXAMPLE_PATH)

    assert profile.name
    assert profile.tech_stack
    assert profile.domain_knowledge
    assert profile.background
    assert profile.projects


def test_load_profile_raises_file_not_found_for_missing_path(tmp_path):
    missing_path = tmp_path / "does-not-exist.json"

    with pytest.raises(FileNotFoundError):
        load_profile(missing_path)


def test_load_profile_raises_validation_error_for_malformed_data(tmp_path):
    malformed_path = tmp_path / "profile.json"
    malformed_path.write_text('{"name": "Minh"}', encoding="utf-8")

    with pytest.raises(ValidationError):
        load_profile(malformed_path)
