from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

_DEFAULT_RESUME_PATH = str(Path(__file__).resolve().parent / "resume.txt")

def _read_resume_text(resume_path: str) -> str:
    path = Path(resume_path)
    if not path.is_file():
        raise FileNotFoundError(f"resume file not found: {resume_path}")
    return path.read_text(encoding="utf-8")


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
    resume_path: str = field(
        default_factory=lambda: os.getenv("RESUME_PATH", _DEFAULT_RESUME_PATH)
    )
    preferred_locations: list[str] = field(
        default_factory=lambda: _split_csv(os.getenv("PREFERRED_LOCATIONS", ""))
    )
    remote_only: bool = field(
        default_factory=lambda: os.getenv("REMOTE_ONLY", "false").strip().lower()
        == "true"
    )
    min_salary: float | None = field(
        default_factory=lambda: (
            float(os.getenv("MIN_SALARY")) if os.getenv("MIN_SALARY") else None
        )
    )
    min_match_score: int = field(
        default_factory=lambda: int(os.getenv("MIN_MATCH_SCORE", "60"))
    )
    description_char_limit: int = field(
        default_factory=lambda: int(os.getenv("DESCRIPTION_CHAR_LIMIT", "1500"))
    )
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "postgresql://scout:scout@localhost:5432/scout"
        )
    )
    resume_text: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "resume_text", _read_resume_text(self.resume_path))


settings = Settings()
