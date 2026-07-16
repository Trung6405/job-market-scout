from scout.config import Settings


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
