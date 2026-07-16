# Scorer Sub-Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working ADK `LlmAgent` scorer sub-agent that rule-filters listings against preferences, then scores the survivors against a resume with DeepSeek, returning `MatchResult` objects above a minimum score.

**Architecture:** `scout/sub_agents/scorer` (folder name from the existing scaffold; agent `name="scorer"`) is an ADK `LlmAgent` (DeepSeek via LiteLLM) with no tools. A plain Python function, `filters.filter_listings`, runs *before* the agent is built and drops hard-reject listings (remote/location/salary) using `scout.config.Settings`. The survivors are serialized into the agent's instruction alongside resume text, so the LLM only reasons over listings that already passed the deterministic filter. An `after_model_callback` (`callbacks.build_drop_low_scores_callback`) drops any scored result below `min_match_score` from the LLM's JSON response before it's returned, mirroring the scraper sub-agent's `stamp_scraped_at` callback pattern.

**Tech Stack:** Python 3.12, `google-adk==2.4.0` (`LlmAgent`, `LiteLlm`), `pydantic`, `python-dotenv`, `pytest==9.1.1` (new dev dependency — not yet in `requirements.txt` on `main`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-15-scorer-agent-design.md` — this plan implements it in full; do not add DB persistence, the briefing agent, root pipeline wiring, or skill/seniority rule-filters (out of scope per that spec).
- `scout/shared/schemas.py`, `scout/config.py`, and `scout/prompts.py` are currently empty on `main` (the scraper sub-agent's implementation lives in an unmerged worktree). This plan writes `Listing` fresh alongside `MatchResult` so it is self-contained regardless of when that worktree merges. If `Listing` already exists when a task runs, skip re-adding it and only add what's missing.
- `google-adk==2.4.0` is already installed; do not change its version.
- All new Python dependencies are installed into the existing project venv at `.venv` and captured in `requirements.txt` via `pip freeze`, not hand-typed version guesses.
- Run all commands from the repository root: `c:\Users\trung\OneDrive\Documents\FPT Internship\job-market-scout`.
- Use the project's venv Python explicitly: `./.venv/Scripts/python.exe` (Bash) — ensures commands hit the right interpreter regardless of shell `PATH`.
- Tests go in the existing flat `tests/` package (matches `tests/test_schemas.py` convention already in the repo) — no new subpackages.
- No code comments except where a non-obvious constraint justifies one (project convention) — see `stamp_scraped_at` in the scraper worktree for the house style.

---

### Task 1: Listing + MatchResult schemas

**Files:**
- Modify: `requirements.txt`
- Modify: `scout/shared/schemas.py` (currently empty)
- Modify: `tests/test_schemas.py` (currently empty)

**Interfaces:**
- Produces: `scout.shared.schemas.Listing` — `pydantic.BaseModel` with fields `source: str`, `external_id: str`, `title: str`, `company: str`, `location: str`, `is_remote: bool`, `url: HttpUrl`, `description: str`, `salary_min: float | None = None`, `salary_max: float | None = None`, `date_posted: datetime | None = None`, `scraped_at: datetime`.
- Produces: `scout.shared.schemas.MatchResult` — `pydantic.BaseModel` with fields `listing: Listing`, `score: int`, `reasoning: str`. Later tasks import both as `from scout.shared.schemas import Listing, MatchResult`.

- [ ] **Step 1: Install pytest and record it in requirements.txt**

Run:
```bash
./.venv/Scripts/python.exe -m pip install pytest==9.1.1
./.venv/Scripts/python.exe -m pip freeze > requirements.txt
```
Expected: `pytest==9.1.1` (and its dependencies, e.g. `iniconfig`, `pluggy`) now appear in `requirements.txt`; no existing pinned versions change.

- [ ] **Step 2: Write the failing tests**

Replace the contents of `tests/test_schemas.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from scout.shared.schemas import Listing, MatchResult


def _make_listing(**overrides):
    defaults = dict(
        source="linkedin",
        external_id="123",
        title="Backend Engineer",
        company="Acme Corp",
        location="Remote",
        is_remote=True,
        url="https://www.linkedin.com/jobs/view/123",
        description="Build backend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Listing(**defaults)


def test_listing_accepts_valid_data():
    listing = _make_listing(salary_min=100000.0, salary_max=140000.0)
    assert listing.title == "Backend Engineer"
    assert listing.is_remote is True


def test_listing_allows_missing_optional_salary_and_date():
    listing = _make_listing(location="Sydney, AU", is_remote=False)
    assert listing.salary_min is None
    assert listing.date_posted is None


def test_listing_requires_title():
    with pytest.raises(ValidationError):
        Listing(
            source="linkedin",
            external_id="125",
            company="Acme Corp",
            location="Remote",
            is_remote=True,
            url="https://www.linkedin.com/jobs/view/125",
            description="Missing title.",
            scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )


def test_match_result_accepts_valid_data():
    result = MatchResult(
        listing=_make_listing(),
        score=82,
        reasoning="Strong backend overlap with resume experience.",
    )
    assert result.score == 82
    assert result.listing.title == "Backend Engineer"


def test_match_result_requires_score():
    with pytest.raises(ValidationError):
        MatchResult(listing=_make_listing(), reasoning="Missing score.")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_schemas.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'Listing' from 'scout.shared.schemas'` (or `MatchResult`, if `Listing` already exists from the scraper worktree merge)

- [ ] **Step 4: Implement the schemas**

Write `scout/shared/schemas.py`:

```python
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, HttpUrl


class Listing(BaseModel):
    source: str
    external_id: str
    title: str
    company: str
    location: str
    is_remote: bool
    url: HttpUrl
    description: str
    salary_min: float | None = None
    salary_max: float | None = None
    date_posted: datetime | None = None
    scraped_at: datetime


class MatchResult(BaseModel):
    listing: Listing
    score: int
    reasoning: str
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_schemas.py -v`
Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt scout/shared/schemas.py tests/test_schemas.py
git commit -m "feat(scout): add Listing and MatchResult schemas"
```

---

### Task 2: Scorer config settings

**Files:**
- Modify: `scout/config.py` (currently empty)
- Modify: `scout/.env.example` (currently empty)
- Create: `tests/test_config.py`
- Create: `scout/resume.txt` (fixture-style default resume file so `Settings()` has a valid default `resume_path` to read; real resume content is provided by the user via `.env` override in practice)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `scout.config.Settings` — a frozen dataclass with fields `deepseek_api_key: str`, `deepseek_model: str`, `resume_path: str`, `resume_text: str` (read from `resume_path` at construction time; raises `FileNotFoundError` if the file doesn't exist), `preferred_locations: list[str]`, `remote_only: bool`, `min_salary: float | None`, `min_match_score: int`, each read from an env var of the same name (upper-cased) with a default, evaluated fresh on each `Settings()` construction. Also produces `scout.config.settings` — a module-level `Settings()` instance. Later tasks import `from scout.config import Settings, settings`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
from pathlib import Path

import pytest

from scout.config import Settings

ENV_VARS = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "RESUME_PATH",
    "PREFERRED_LOCATIONS",
    "REMOTE_ONLY",
    "MIN_SALARY",
    "MIN_MATCH_SCORE",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_settings_uses_defaults_when_env_unset():
    settings = Settings()

    assert settings.deepseek_model == "deepseek/deepseek-chat"
    assert settings.preferred_locations == []
    assert settings.remote_only is False
    assert settings.min_salary is None
    assert settings.min_match_score == 60


def test_settings_reads_resume_text_from_default_resume_path():
    settings = Settings()

    assert settings.resume_text.strip() != ""


def test_settings_reads_env_overrides(monkeypatch, tmp_path):
    resume_file = tmp_path / "custom_resume.txt"
    resume_file.write_text("Senior backend engineer, 6 years Python.")
    monkeypatch.setenv("RESUME_PATH", str(resume_file))
    monkeypatch.setenv("PREFERRED_LOCATIONS", "Sydney, Remote")
    monkeypatch.setenv("REMOTE_ONLY", "true")
    monkeypatch.setenv("MIN_SALARY", "120000")
    monkeypatch.setenv("MIN_MATCH_SCORE", "75")

    settings = Settings()

    assert settings.resume_text == "Senior backend engineer, 6 years Python."
    assert settings.preferred_locations == ["Sydney", "Remote"]
    assert settings.remote_only is True
    assert settings.min_salary == 120000.0
    assert settings.min_match_score == 75


def test_settings_raises_when_resume_path_missing(monkeypatch):
    monkeypatch.setenv("RESUME_PATH", "does/not/exist.txt")

    with pytest.raises(FileNotFoundError):
        Settings()


def test_settings_can_be_constructed_with_explicit_overrides():
    settings = Settings(min_match_score=90)

    assert settings.min_match_score == 90
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'Settings' from 'scout.config'`

- [ ] **Step 3: Create the default resume fixture file**

Write `scout/resume.txt`:

```
Software Engineer with 5 years of experience building backend services in
Python and Go. Comfortable with distributed systems, REST/gRPC APIs, and
SQL databases. Looking for backend or platform engineering roles.
```

- [ ] **Step 4: Implement config**

Write `scout/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

_DEFAULT_RESUME_PATH = str(Path(__file__).resolve().parent / "resume.txt")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _read_resume_text(resume_path: str) -> str:
    path = Path(resume_path)
    if not path.is_file():
        raise FileNotFoundError(f"resume file not found: {resume_path}")
    return path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class Settings:
    deepseek_api_key: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "")
    )
    deepseek_model: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek/deepseek-chat")
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
    resume_text: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "resume_text", _read_resume_text(self.resume_path))


settings = Settings()
```

Write `scout/.env.example`:

```
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek/deepseek-chat
RESUME_PATH=scout/resume.txt
PREFERRED_LOCATIONS=
REMOTE_ONLY=false
MIN_SALARY=
MIN_MATCH_SCORE=60
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
git add scout/config.py scout/.env.example scout/resume.txt tests/test_config.py
git commit -m "feat(scout): add scorer config settings"
```

---

### Task 3: Rule-based pre-filter

**Files:**
- Create: `scout/sub_agents/scorer/filters.py`
- Create: `tests/test_scorer_filters.py`

**Interfaces:**
- Consumes: `scout.config.Settings` (Task 2), `scout.shared.schemas.Listing` (Task 1).
- Produces: `scout.sub_agents.scorer.filters.filter_listings(listings: list[Listing], settings: Settings) -> list[Listing]`. Later tasks call this as `filter_listings(listings, active_settings)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scorer_filters.py`:

```python
from datetime import datetime, timezone

from scout.config import Settings
from scout.shared.schemas import Listing
from scout.sub_agents.scorer.filters import filter_listings


def _make_listing(**overrides):
    defaults = dict(
        source="linkedin",
        external_id="1",
        title="Backend Engineer",
        company="Acme Corp",
        location="Sydney, AU",
        is_remote=False,
        url="https://www.linkedin.com/jobs/view/1",
        description="Build backend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Listing(**defaults)


def test_filter_listings_passes_through_with_no_preferences():
    settings = Settings(preferred_locations=[], remote_only=False, min_salary=None)
    listings = [_make_listing()]

    result = filter_listings(listings, settings)

    assert result == listings


def test_filter_listings_drops_non_remote_when_remote_only():
    settings = Settings(remote_only=True)
    listings = [
        _make_listing(external_id="1", is_remote=True),
        _make_listing(external_id="2", is_remote=False),
    ]

    result = filter_listings(listings, settings)

    assert [listing.external_id for listing in result] == ["1"]


def test_filter_listings_drops_location_mismatch():
    settings = Settings(preferred_locations=["Melbourne"])
    listings = [
        _make_listing(external_id="1", location="Melbourne, AU"),
        _make_listing(external_id="2", location="Sydney, AU"),
    ]

    result = filter_listings(listings, settings)

    assert [listing.external_id for listing in result] == ["1"]


def test_filter_listings_drops_below_min_salary_using_salary_max():
    settings = Settings(min_salary=100000)
    listings = [
        _make_listing(external_id="1", salary_max=120000),
        _make_listing(external_id="2", salary_max=80000),
    ]

    result = filter_listings(listings, settings)

    assert [listing.external_id for listing in result] == ["1"]


def test_filter_listings_falls_back_to_salary_min_when_max_missing():
    settings = Settings(min_salary=100000)
    listings = [_make_listing(external_id="1", salary_min=110000, salary_max=None)]

    result = filter_listings(listings, settings)

    assert [listing.external_id for listing in result] == ["1"]


def test_filter_listings_keeps_listing_with_no_salary_data():
    settings = Settings(min_salary=100000)
    listings = [_make_listing(external_id="1", salary_min=None, salary_max=None)]

    result = filter_listings(listings, settings)

    assert [listing.external_id for listing in result] == ["1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scorer_filters.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'scout.sub_agents.scorer.filters'`

- [ ] **Step 3: Implement the filter**

Write `scout/sub_agents/scorer/filters.py`:

```python
from __future__ import annotations

from scout.config import Settings
from scout.shared.schemas import Listing


def filter_listings(listings: list[Listing], settings: Settings) -> list[Listing]:
    survivors = []
    for listing in listings:
        if settings.remote_only and not listing.is_remote:
            continue
        if settings.preferred_locations and not any(
            preferred.lower() in listing.location.lower()
            for preferred in settings.preferred_locations
        ):
            continue
        if settings.min_salary is not None:
            salary = (
                listing.salary_max
                if listing.salary_max is not None
                else listing.salary_min
            )
            if salary is not None and salary < settings.min_salary:
                continue
        survivors.append(listing)
    return survivors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scorer_filters.py -v`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add scout/sub_agents/scorer/filters.py tests/test_scorer_filters.py
git commit -m "feat(scout): add scorer rule-based pre-filter"
```

---

### Task 4: Score-threshold callback

**Files:**
- Create: `scout/sub_agents/scorer/callbacks.py`
- Create: `tests/test_scorer_callbacks.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (operates on raw JSON, decoupled from `MatchResult` for the same reason `stamp_scraped_at` operates on raw JSON in the scraper worktree — the callback runs on the LLM's text output before Pydantic validation).
- Produces: `scout.sub_agents.scorer.callbacks.build_drop_low_scores_callback(min_score: int) -> Callable[[CallbackContext, LlmResponse], LlmResponse | None]`. Task 5 calls this as `after_model_callback=build_drop_low_scores_callback(active_settings.min_match_score)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scorer_callbacks.py`:

```python
import json

from google.genai import types

from scout.sub_agents.scorer.callbacks import build_drop_low_scores_callback


def _make_response(payload) -> types.GenerateContentResponse:
    from google.adk.models.llm_response import LlmResponse

    content = types.Content(parts=[types.Part(text=json.dumps(payload))])
    return LlmResponse(content=content)


def test_drop_low_scores_removes_results_below_threshold():
    callback = build_drop_low_scores_callback(min_score=60)
    response = _make_response(
        [
            {"listing": {"title": "A"}, "score": 80, "reasoning": "good fit"},
            {"listing": {"title": "B"}, "score": 40, "reasoning": "poor fit"},
        ]
    )

    result = callback(None, response)

    kept = json.loads(result.content.parts[0].text)
    assert len(kept) == 1
    assert kept[0]["score"] == 80


def test_drop_low_scores_keeps_results_at_or_above_threshold():
    callback = build_drop_low_scores_callback(min_score=60)
    response = _make_response(
        [{"listing": {"title": "A"}, "score": 60, "reasoning": "borderline"}]
    )

    result = callback(None, response)

    kept = json.loads(result.content.parts[0].text)
    assert len(kept) == 1


def test_drop_low_scores_returns_none_when_response_is_partial():
    callback = build_drop_low_scores_callback(min_score=60)
    from google.adk.models.llm_response import LlmResponse

    response = LlmResponse(partial=True)

    assert callback(None, response) is None


def test_drop_low_scores_returns_none_on_invalid_json():
    callback = build_drop_low_scores_callback(min_score=60)
    from google.adk.models.llm_response import LlmResponse

    content = types.Content(parts=[types.Part(text="not json")])
    response = LlmResponse(content=content)

    assert callback(None, response) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scorer_callbacks.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'scout.sub_agents.scorer.callbacks'`

- [ ] **Step 3: Implement the callback**

Write `scout/sub_agents/scorer/callbacks.py`:

```python
from __future__ import annotations

import json
from typing import Callable

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse


def build_drop_low_scores_callback(
    min_score: int,
) -> Callable[[CallbackContext, LlmResponse], LlmResponse | None]:
    def drop_low_scores(
        callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        if llm_response.partial or not llm_response.content:
            return None

        parts = llm_response.content.parts or []
        if not parts or parts[0].text is None:
            return None

        try:
            results = json.loads(parts[0].text)
        except json.JSONDecodeError:
            return None

        if not isinstance(results, list):
            return None

        kept = [
            result
            for result in results
            if isinstance(result, dict) and result.get("score", 0) >= min_score
        ]

        parts[0].text = json.dumps(kept)
        return llm_response

    return drop_low_scores
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scorer_callbacks.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add scout/sub_agents/scorer/callbacks.py tests/test_scorer_callbacks.py
git commit -m "feat(scout): add scorer score-threshold callback"
```

---

### Task 5: Scorer LlmAgent

**Files:**
- Modify: `scout/prompts.py` (currently empty)
- Modify: `scout/sub_agents/scorer/agent.py` (currently empty)
- Create: `tests/test_scorer_agent.py`

**Interfaces:**
- Consumes: `scout.config.Settings`, `scout.config.settings` (Task 2); `scout.shared.schemas.Listing`, `scout.shared.schemas.MatchResult` (Task 1); `scout.sub_agents.scorer.filters.filter_listings` (Task 3); `scout.sub_agents.scorer.callbacks.build_drop_low_scores_callback` (Task 4).
- Produces: `scout.prompts.build_scorer_instruction(settings: Settings, listings: list[Listing]) -> str`. Produces `scout.sub_agents.scorer.agent.build_scorer_agent(listings: list[Listing], settings: Settings | None = None) -> LlmAgent`. `build_scorer_agent` takes `listings` explicitly (rather than reading from session state) because root pipeline wiring — how the scraper's output reaches this agent inside a `SequentialAgent` — is out of scope per the spec; a future session will decide that wiring and can adapt this signature then.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scorer_agent.py`:

```python
from datetime import datetime, timezone

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from scout.config import Settings
from scout.prompts import build_scorer_instruction
from scout.shared.schemas import Listing, MatchResult
from scout.sub_agents.scorer.agent import build_scorer_agent


def _make_listing(**overrides):
    defaults = dict(
        source="linkedin",
        external_id="1",
        title="Backend Engineer",
        company="Acme Corp",
        location="Sydney, AU",
        is_remote=True,
        url="https://www.linkedin.com/jobs/view/1",
        description="Build backend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Listing(**defaults)


def test_build_scorer_instruction_includes_resume_and_listing_titles():
    settings = Settings()
    listings = [_make_listing(title="Platform Engineer")]

    instruction = build_scorer_instruction(settings, listings)

    assert settings.resume_text in instruction
    assert "Platform Engineer" in instruction


def test_build_scorer_agent_uses_configured_model():
    settings = Settings(deepseek_model="deepseek/deepseek-reasoner")

    agent = build_scorer_agent([_make_listing()], settings)

    assert isinstance(agent, LlmAgent)
    assert isinstance(agent.model, LiteLlm)
    assert agent.model.model == "deepseek/deepseek-reasoner"


def test_build_scorer_agent_outputs_match_result_list():
    agent = build_scorer_agent([_make_listing()], Settings())

    assert agent.output_schema == list[MatchResult]


def test_build_scorer_agent_excludes_rule_filtered_listings_from_instruction():
    settings = Settings(remote_only=True)
    listings = [
        _make_listing(external_id="1", title="Remote Role", is_remote=True),
        _make_listing(external_id="2", title="Onsite Role", is_remote=False),
    ]

    agent = build_scorer_agent(listings, settings)

    assert "Remote Role" in agent.instruction
    assert "Onsite Role" not in agent.instruction


def test_build_scorer_agent_registers_no_tools():
    agent = build_scorer_agent([_make_listing()], Settings())

    assert agent.tools == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scorer_agent.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'build_scorer_instruction' from 'scout.prompts'`

- [ ] **Step 3: Implement the prompt and the agent**

Append to `scout/prompts.py`:

```python
from __future__ import annotations

import json

from scout.config import Settings
from scout.shared.schemas import Listing


def build_scorer_instruction(settings: Settings, listings: list[Listing]) -> str:
    listings_json = json.dumps(
        [listing.model_dump(mode="json") for listing in listings], indent=2
    )
    return f"""\
You are the job-match scorer for Job Market Scout.

Score each listing below from 0 to 100 on how well it fits the resume and
preferences, and give one short sentence of reasoning per listing. Do not
invent listings beyond the ones provided, and do not call any tool.

Resume:
{settings.resume_text}

Preferred locations: {settings.preferred_locations or "no preference"}
Remote only: {settings.remote_only}
Minimum salary: {settings.min_salary if settings.min_salary is not None else "no floor"}

Listings to score:
{listings_json}

Return a JSON list of objects, each with "listing" (the original listing
object, unchanged), "score" (integer 0-100), and "reasoning" (one short
sentence). Return only the JSON list, no commentary.
"""
```

Write `scout/sub_agents/scorer/agent.py`:

```python
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import build_scorer_instruction
from scout.shared.schemas import Listing, MatchResult
from scout.sub_agents.scorer.callbacks import build_drop_low_scores_callback
from scout.sub_agents.scorer.filters import filter_listings


def build_scorer_agent(
    listings: list[Listing], settings: Settings | None = None
) -> LlmAgent:
    active_settings = settings or default_settings
    survivors = filter_listings(listings, active_settings)
    return LlmAgent(
        name="scorer",
        model=LiteLlm(model=active_settings.deepseek_model),
        instruction=build_scorer_instruction(active_settings, survivors),
        output_schema=list[MatchResult],
        after_model_callback=build_drop_low_scores_callback(
            active_settings.min_match_score
        ),
    )
```

Note: unlike the scraper (which exposes a module-level `root_agent` built from `default_settings` for `adk` CLI discovery), the scorer has no `root_agent` in this task — it requires `listings` as an argument that isn't available at import time, and root pipeline wiring is out of scope per the spec.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scorer_agent.py -v`
Expected: `5 passed`

- [ ] **Step 5: Run the full test suite**

Run: `./.venv/Scripts/python.exe -m pytest -v`
Expected: all tests across `tests/test_schemas.py`, `tests/test_config.py`, `tests/test_scorer_filters.py`, `tests/test_scorer_callbacks.py`, `tests/test_scorer_agent.py` pass (26 passed)

- [ ] **Step 6: Commit**

```bash
git add scout/prompts.py scout/sub_agents/scorer/agent.py tests/test_scorer_agent.py
git commit -m "feat(scout): build scorer LlmAgent"
```

## Manual Verification (post-plan, not part of TDD loop)

The tasks above are fully unit-testable without a live DeepSeek API key. Before relying on the scorer for real scoring:

1. Set `DEEPSEEK_API_KEY` and a real `RESUME_PATH` in `scout/.env`.
2. In a Python shell: build some `Listing` objects (or use the scraper's output once that worktree is merged), call `build_scorer_agent(listings)`, and run it via the ADK runner (`adk run` equivalent for a single sub-agent, or a small script using `google.adk.runners.Runner`).
3. Confirm the returned `MatchResult` list only contains listings that passed both the rule-based filter and the `min_match_score` threshold, with sensible scores/reasoning relative to the resume.

This step needs a live DeepSeek key, so it isn't part of the automated task loop above — do it once after Task 5.
