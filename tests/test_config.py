from scout.config import Settings

import pytest

def test_settings_uses_defaults_when_env_unset(monkeypatch):
    for var in (
        "JOBSPY_MCP_URL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "SEARCH_ROLES",
        "SEARCH_LOCATIONS",
        "RESULTS_WANTED",
        "HOURS_OLD",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings()

    assert settings.jobspy_mcp_url == "http://jobspy-mcp:9423"
    assert settings.deepseek_model == "deepseek/deepseek-chat"
    assert settings.search_roles == ["software engineer"]
    assert settings.search_locations == ["Remote"]
    assert settings.results_wanted == 20
    assert settings.hours_old == 72


def test_settings_reads_env_overrides(monkeypatch):
    monkeypatch.setenv("JOBSPY_MCP_URL", "http://localhost:9423")
    monkeypatch.setenv("SEARCH_ROLES", "backend engineer, platform engineer")
    monkeypatch.setenv("RESULTS_WANTED", "50")

    settings = Settings()

    assert settings.jobspy_mcp_url == "http://localhost:9423"
    assert settings.search_roles == ["backend engineer", "platform engineer"]
    assert settings.results_wanted == 50


def test_settings_can_be_constructed_with_explicit_overrides():
    settings = Settings(jobspy_mcp_url="http://test-jobspy:9423")

    assert settings.jobspy_mcp_url == "http://test-jobspy:9423"

def test_settings_uses_scorer_defaults_when_env_unset(monkeypatch):
    for var in (
        "RESUME_PATH",
        "PREFERRED_LOCATIONS",
        "REMOTE_ONLY",
        "MIN_SALARY",
        "MIN_MATCH_SCORE",
        "DESCRIPTION_CHAR_LIMIT",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings()

    assert settings.preferred_locations == []
    assert settings.remote_only is False
    assert settings.min_salary is None
    assert settings.min_match_score == 60
    assert settings.description_char_limit == 1500


def test_settings_reads_resume_text_from_default_resume_path():
    settings = Settings()

    assert settings.resume_text.strip() != ""

def test_settings_reads_scorer_env_overrides(monkeypatch, tmp_path):
    resume_file = tmp_path / "custom_resume.txt"
    resume_file.write_text("Senior backend engineer, 6 years Python.")
    monkeypatch.setenv("RESUME_PATH", str(resume_file))
    monkeypatch.setenv("PREFERRED_LOCATIONS", "Sydney, Remote")
    monkeypatch.setenv("REMOTE_ONLY", "true")
    monkeypatch.setenv("MIN_SALARY", "120000")
    monkeypatch.setenv("MIN_MATCH_SCORE", "75")
    monkeypatch.setenv("DESCRIPTION_CHAR_LIMIT", "800")

    settings = Settings()

    assert settings.resume_text == "Senior backend engineer, 6 years Python."
    assert settings.preferred_locations == ["Sydney", "Remote"]
    assert settings.remote_only is True
    assert settings.min_salary == 120000.0
    assert settings.min_match_score == 75
    assert settings.description_char_limit == 800

def test_settings_raises_when_resume_path_missing(monkeypatch):
    monkeypatch.setenv("RESUME_PATH", "does/not/exist.txt")

    with pytest.raises(FileNotFoundError):
        Settings()


def test_settings_uses_database_url_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings()

    assert settings.database_url == "postgresql://scout:scout@localhost:5433/scout"


def test_settings_reads_database_url_env_override(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5433/test")

    settings = Settings()

    assert settings.database_url == "postgresql://test:test@localhost:5433/test"


def test_settings_uses_briefing_defaults_when_env_unset(monkeypatch):
    for var in (
        "BRIEFING_MAX_MATCHES",
        "GMAIL_ADDRESS",
        "GMAIL_APP_PASSWORD",
        "GMAIL_RECIPIENT",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings()

    assert settings.briefing_max_matches == 5
    assert settings.gmail_address == ""
    assert settings.gmail_app_password == ""
    assert settings.gmail_recipient == ""


def test_settings_reads_briefing_env_overrides(monkeypatch):
    monkeypatch.setenv("BRIEFING_MAX_MATCHES", "3")
    monkeypatch.setenv("GMAIL_ADDRESS", "scout@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-password")
    monkeypatch.setenv("GMAIL_RECIPIENT", "me@example.com")

    settings = Settings()

    assert settings.briefing_max_matches == 3
    assert settings.gmail_address == "scout@example.com"
    assert settings.gmail_app_password == "app-password"
    assert settings.gmail_recipient == "me@example.com"