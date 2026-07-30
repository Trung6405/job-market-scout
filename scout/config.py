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
    # jobspy's Indeed backend searches one country's index at a time, and the
    # MCP server defaults it to "USA" when the parameter is absent — which
    # silently returns nothing for non-US SEARCH_LOCATIONS. Mirror that default
    # here so the value is always sent explicitly and stays configurable.
    country_indeed: str = field(
        default_factory=partial(_env_str, "COUNTRY_INDEED", "USA")
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
    # Listings per model call. One response must hold every listing in its
    # batch, and the model caps output tokens, so a large batch truncates the
    # JSON mid-value and fails to parse. Separate sizes because a score is
    # far smaller per listing than a requirement list.
    scorer_batch_size: int = field(
        default_factory=partial(_env_int, "SCORER_BATCH_SIZE", 25)
    )
    requirements_batch_size: int = field(
        default_factory=partial(_env_int, "REQUIREMENTS_BATCH_SIZE", 15)
    )
    # Concurrent model calls in flight. Bounded so a large day doesn't trip
    # provider rate limits; lower it if 429s appear.
    model_concurrency: int = field(
        default_factory=partial(_env_int, "MODEL_CONCURRENCY", 3)
    )
    # Output-token ceiling per model call. Headroom below deepseek-chat's
    # 8192 output cap so a batch response is less likely to truncate mid-JSON.
    model_max_tokens: int = field(
        default_factory=partial(_env_int, "MODEL_MAX_TOKENS", 8000)
    )
    # Per-request timeout (seconds). Bounds a hung provider call so it can't
    # stall the whole asyncio.gather fan-out of a stage.
    model_timeout_seconds: int = field(
        default_factory=partial(_env_int, "MODEL_TIMEOUT_SECONDS", 120)
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
    # Days a listing may go unseen before it is treated as closed. A daily
    # scrape only sees RESULTS_WANTED per role within HOURS_OLD, so a still-open
    # listing routinely misses a day; closing on first absence made it reopen
    # as "changed" and bought a second full analysis of the same listing.
    listing_stale_days: int = field(
        default_factory=partial(_env_int, "LISTING_STALE_DAYS", 7)
    )
    discord_bot_token: str = field(
        default_factory=partial(_env_str, "DISCORD_BOT_TOKEN", "")
    )
    discord_channel_id: str = field(
        default_factory=partial(_env_str, "DISCORD_CHANNEL_ID", "")
    )
    github_pat: str = field(
        default_factory=partial(_env_str, "GITHUB_PAT", "")
    )
    # Candidates kept per skill after GitHub search filtering (stars,
    # pushed-within, archived, README) — bounds both API and LLM-tagging
    # spend per skill per run.
    coach_top_n_per_skill: int = field(
        default_factory=partial(_env_int, "COACH_TOP_N_PER_SKILL", 5)
    )
    # Seed coverage before per-skill search has run enough cycles to find
    # everything on its own. Default set covers the profile's current
    # domains (umbrella PRS Q1) — refinable via env, no code change needed.
    coach_awesome_lists: list[str] = field(
        default_factory=partial(
            _env_csv,
            "COACH_AWESOME_LISTS",
            # awesome-azure (kristofferandreasen) was in this set and is gone:
            # its README links Azure services and docs, not GitHub repos — the
            # harvest measured exactly 1 repo link against 129-547 from every
            # list below. Azure coverage comes from the per-skill dynamic
            # search instead (it is among the most frequent gap skills).
            "https://github.com/vinta/awesome-python,"
            "https://github.com/mjhea0/awesome-fastapi,"
            "https://github.com/enaqx/awesome-react,"
            "https://github.com/dzharii/awesome-typescript,"
            "https://github.com/veggiemonk/awesome-docker",
        )
    )
    # How many resources the retriever returns per gap. The PRS specifies
    # "top 2-3"; 3 gives the grounded-tip stage the widest choice, and it can
    # present fewer.
    coach_top_k: int = field(default_factory=partial(_env_int, "COACH_TOP_K", 3))
    # A resource stops being retrievable once its last successful link check
    # is this old. A never-checked resource has `last_verified` NULL, which
    # counts as live, so a freshly aggregated resource is retrievable before
    # its first link-health check (FR-CC-10).
    coach_resource_max_age_days: int = field(
        default_factory=partial(_env_int, "COACH_RESOURCE_MAX_AGE_DAYS", 90)
    )
    # Resources injected into the prompt per gap. Kept separate from
    # coach_top_k so the prompt's size can be tuned without changing what
    # the retriever returns to any other caller.
    coach_tips_resources_per_gap: int = field(
        default_factory=partial(_env_int, "COACH_TIPS_RESOURCES_PER_GAP", 3)
    )
    # Gaps tipped per listing, must-haves first. Bounds prompt size on a
    # listing that states twenty requirements the profile doesn't meet.
    coach_tips_max_gaps_per_listing: int = field(
        default_factory=partial(_env_int, "COACH_TIPS_MAX_GAPS_PER_LISTING", 5)
    )
    # Resources checked per link-health run, oldest-checked first. Bounds one
    # run's network time; the corpus cycles through over consecutive runs.
    coach_link_health_batch: int = field(
        default_factory=partial(_env_int, "COACH_LINK_HEALTH_BATCH", 50)
    )
    # Consecutive transient failures (timeout, 5xx, 429, ambiguous 401/403)
    # tolerated before a resource is excluded from retrieval. A permanent
    # 404/410 excludes immediately regardless of this setting.
    coach_link_health_max_failures: int = field(
        default_factory=partial(_env_int, "COACH_LINK_HEALTH_MAX_FAILURES", 3)
    )
    # Per-request timeout (seconds) for a single link-health HTTP check.
    coach_link_health_timeout_seconds: int = field(
        default_factory=partial(_env_int, "COACH_LINK_HEALTH_TIMEOUT_SECONDS", 10)
    )
    profile: Profile = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", load_profile(self.profile_path))


settings = Settings()
