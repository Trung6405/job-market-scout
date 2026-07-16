from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    jobspy_mcp_url: str = field(
        default_factory=lambda: os.getenv("JOBSPY_MCP_URL", "http://jobspy-mcp:9423")
    )
    deepseek_api_key: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "")
    )
    deepseek_model: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek/deepseek-chat")
    )
    search_roles: list[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv("SEARCH_ROLES", "software engineer")
        )
    )
    search_locations: list[str] = field(
        default_factory=lambda: _split_csv(os.getenv("SEARCH_LOCATIONS", "Remote"))
    )
    results_wanted: int = field(
        default_factory=lambda: int(os.getenv("RESULTS_WANTED", "20"))
    )
    hours_old: int = field(
        default_factory=lambda: int(os.getenv("HOURS_OLD", "72"))
    )


settings = Settings()
