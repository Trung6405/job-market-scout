from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from dotenv import load_dotenv

from scout.shared.profile import load_profile
from scout.shared.schemas import Profile

load_dotenv(Path(__file__).resolve().parent / ".env")

def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


def _env_csv(name: str, default: str) -> list[str]:
    return _split_csv(os.getenv(name, default))


def _env_optional_float(name: str) -> float | None:
    raw = os.getenv(name)
    return float(raw) if raw else None


def _env_optional_str(name: str) -> str | None:
    raw = os.getenv(name)
    return raw if raw else None


@dataclass(frozen=True)
class Settings:
    jobspy_mcp_url: str = field(
        default_factory=partial(_env_str, "JOBSPY_MCP_URL", "http://jobspy-mcp:9423")
    )
    deepseek_api_key: str = field(
        default_factory=partial(_env_str, "DEEPSEEK_API_KEY", "")
    )
    deepseek_model: str = field(
        default_factory=partial(
            _env_str, "DEEPSEEK_MODEL", "deepseek/deepseek-chat"
        )
    )
    search_roles: list[str] = field(
        default_factory=partial(_env_csv, "SEARCH_ROLES", "software engineer")
    )
    search_locations: list[str] = field(
        default_factory=partial(_env_csv, "SEARCH_LOCATIONS", "Remote")
    )
    search_site_names: list[str] = field(
        default_factory=partial(
            _env_csv,
            "SEARCH_SITE_NAMES",
            "indeed,linkedin,zip_recruiter,glassdoor,google",
        )
    )
    results_wanted: int = field(
        default_factory=partial(_env_int, "RESULTS_WANTED", 20)
    )
    hours_old: int = field(default_factory=partial(_env_int, "HOURS_OLD", 72))
    profile_path: str = field(
        default_factory=partial(
            _env_str,
            "PROFILE_PATH",
            str(Path(__file__).resolve().parent / "profile.json"),
        )
    )
    report_output_dir: str = field(
        default_factory=partial(_env_str, "REPORT_OUTPUT_DIR", "reports")
    )
    report_host_dir: str | None = field(
        default_factory=partial(_env_optional_str, "REPORT_HOST_DIR")
    )
    preferred_locations: list[str] = field(
        default_factory=partial(_env_csv, "PREFERRED_LOCATIONS", "")
    )
    remote_only: bool = field(
        default_factory=partial(_env_bool, "REMOTE_ONLY", False)
    )
    min_salary: float | None = field(
        default_factory=partial(_env_optional_float, "MIN_SALARY")
    )
    min_match_score: int = field(
        default_factory=partial(_env_int, "MIN_MATCH_SCORE", 60)
    )
    strong_match_score: int = field(
        default_factory=partial(_env_int, "STRONG_MATCH_SCORE", 85)
    )
    description_char_limit: int = field(
        default_factory=partial(_env_int, "DESCRIPTION_CHAR_LIMIT", 1500)
    )
    database_url: str = field(
        default_factory=partial(
            _env_str,
            "DATABASE_URL",
            "postgresql://scout:scout@localhost:5433/scout",
        )
    )
    briefing_max_matches: int = field(
        default_factory=partial(_env_int, "BRIEFING_MAX_MATCHES", 5)
    )
    gmail_address: str = field(default_factory=partial(_env_str, "GMAIL_ADDRESS", ""))
    gmail_app_password: str = field(
        default_factory=partial(_env_str, "GMAIL_APP_PASSWORD", "")
    )
    gmail_recipient: str = field(
        default_factory=partial(_env_str, "GMAIL_RECIPIENT", "")
    )
    profile: Profile = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", load_profile(self.profile_path))


settings = Settings()
