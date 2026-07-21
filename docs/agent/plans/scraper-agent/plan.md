# Scraper Sub-Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working ADK `LlmAgent` scraper sub-agent that fetches LinkedIn job listings via a self-hosted `jobspy-mcp-server` MCP connection and returns them as structured `Listing` objects.

**Architecture:** `scout/sub_agents/scraper` is an ADK `LlmAgent` (DeepSeek via LiteLLM) with one MCP tool (`search_jobs`, exposed by `jobspy-mcp-server` over SSE). Config (search roles/locations, MCP URL, DeepSeek model) is centralized in `scout/config.py`. The agent's output is validated against a `Listing` Pydantic model in `scout/shared/schemas.py`. `jobspy-mcp-server` runs as a `docker-compose` service.

**Tech Stack:** Python 3.12, `google-adk==2.4.0` (`LlmAgent`, `LiteLlm`, `McpToolset`, `SseConnectionParams`), `mcp` SDK (new dependency, `mcp==1.28.1`), `pydantic`, `python-dotenv`, `pytest` (new dev dependency, `pytest==9.1.1`), Docker Compose.

## Global Constraints

- Spec: `docs/agent/specs/scraper-agent/spec.md` — this plan implements it in full; do not add Seek support, career-page search, DB persistence, or other sub-agents (out of scope per that spec).
- `google-adk==2.4.0` is already installed; do not change its version.
- `mcp` must be pinned `>=1.24,<2` (the range `google-adk[mcp]` requires) — use `mcp==1.28.1`.
- All new Python dependencies are installed into the existing project venv at `.venv` (already active for this repo) and captured in `requirements.txt` via `pip freeze`, not hand-typed version guesses.
- Run all commands from the repository root: `c:\Users\trung\OneDrive\Documents\FPT Internship\job-market-scout`.
- Use the project's venv Python explicitly: `./.venv/Scripts/python.exe` (Bash) — this ensures commands hit the right interpreter regardless of shell `PATH`.
- Tests go in the existing flat `tests/` package (matches `tests/test_schemas.py` convention already in the repo) — no new subpackages.
- No code comments except where a non-obvious constraint justifies one (project convention).

---

### Task 1: Listing schema + pytest bootstrap

**Files:**
- Modify: `requirements.txt`
- Modify: `scout/shared/schemas.py` (currently empty)
- Modify: `tests/test_schemas.py` (currently empty)

**Interfaces:**
- Produces: `scout.shared.schemas.Listing` — a `pydantic.BaseModel` with fields `source: str`, `external_id: str`, `title: str`, `company: str`, `location: str`, `is_remote: bool`, `url: HttpUrl`, `description: str`, `salary_min: float | None = None`, `salary_max: float | None = None`, `date_posted: datetime | None = None`, `scraped_at: datetime`. Later tasks import this as `from scout.shared.schemas import Listing`.

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

from scout.shared.schemas import Listing


def test_listing_accepts_valid_data():
    listing = Listing(
        source="linkedin",
        external_id="123",
        title="Backend Engineer",
        company="Acme Corp",
        location="Remote",
        is_remote=True,
        url="https://www.linkedin.com/jobs/view/123",
        description="Build backend systems.",
        salary_min=100000.0,
        salary_max=140000.0,
        date_posted=datetime(2026, 7, 10, tzinfo=timezone.utc),
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    assert listing.title == "Backend Engineer"
    assert listing.is_remote is True


def test_listing_allows_missing_optional_salary_and_date():
    listing = Listing(
        source="linkedin",
        external_id="124",
        title="Frontend Engineer",
        company="Acme Corp",
        location="Sydney, AU",
        is_remote=False,
        url="https://www.linkedin.com/jobs/view/124",
        description="Build frontend systems.",
        scraped_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_schemas.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'Listing' from 'scout.shared.schemas'`

- [ ] **Step 4: Implement the schema**

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_schemas.py -v`
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt scout/shared/schemas.py tests/test_schemas.py
git commit -m "feat(scout): add Listing schema and pytest bootstrap"
```

---

### Task 2: Scraper config settings

**Files:**
- Modify: `scout/config.py` (currently empty)
- Modify: `scout/.env.example` (currently empty)
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `scout.config.Settings` — a frozen dataclass with fields `jobspy_mcp_url: str`, `deepseek_api_key: str`, `deepseek_model: str`, `search_roles: list[str]`, `search_locations: list[str]`, `results_wanted: int`, `hours_old: int`, each read from an env var of the same name (upper-cased) with a default, evaluated fresh on each `Settings()` construction (not cached at import time). Also produces `scout.config.settings` — a module-level `Settings()` instance for convenience. Later tasks import `from scout.config import Settings, settings`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'Settings' from 'scout.config'`

- [ ] **Step 3: Implement config**

Write `scout/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


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
```

Write `scout/.env.example`:

```
JOBSPY_MCP_URL=http://jobspy-mcp:9423
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek/deepseek-chat
SEARCH_ROLES=software engineer
SEARCH_LOCATIONS=Remote
RESULTS_WANTED=20
HOURS_OLD=72
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add scout/config.py scout/.env.example tests/test_config.py
git commit -m "feat(scout): add scraper config settings"
```

---

### Task 3: MCP tool wiring for the scraper

**Files:**
- Modify: `requirements.txt`
- Modify: `scout/sub_agents/scraper/tools.py` (currently empty)
- Create: `tests/test_scraper_tools.py`

**Interfaces:**
- Consumes: `scout.config.Settings`, `scout.config.settings` (Task 2).
- Produces: `scout.sub_agents.scraper.tools.build_scraper_toolset(settings: Settings | None = None) -> McpToolset`. Later tasks call this as `build_scraper_toolset(active_settings)`.

- [ ] **Step 1: Install the mcp SDK and record it in requirements.txt**

Run:
```bash
./.venv/Scripts/python.exe -m pip install "mcp==1.28.1"
./.venv/Scripts/python.exe -m pip freeze > requirements.txt
```
Expected: `mcp==1.28.1` (and its dependencies) now appear in `requirements.txt`.

- [ ] **Step 2: Verify the ADK MCP tool classes are now importable**

Run: `./.venv/Scripts/python.exe -c "from google.adk.tools.mcp_tool import McpToolset, SseConnectionParams; print('ok')"`
Expected: `ok` (before Step 1 this raises `ImportError: cannot import name 'McpToolset'` because `google.adk.tools.mcp_tool` silently no-ops without the `mcp` package installed)

- [ ] **Step 3: Write the failing tests**

Create `tests/test_scraper_tools.py`:

```python
from google.adk.tools.mcp_tool import McpToolset, SseConnectionParams

from scout.config import Settings
from scout.sub_agents.scraper.tools import build_scraper_toolset


def test_build_scraper_toolset_returns_mcp_toolset():
    toolset = build_scraper_toolset(Settings())

    assert isinstance(toolset, McpToolset)


def test_build_scraper_toolset_targets_configured_mcp_url():
    settings = Settings(jobspy_mcp_url="http://test-jobspy:9423")

    toolset = build_scraper_toolset(settings)

    assert isinstance(toolset.connection_params, SseConnectionParams)
    assert toolset.connection_params.url == "http://test-jobspy:9423/mcp/connect"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scraper_tools.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'build_scraper_toolset' from 'scout.sub_agents.scraper.tools'`

- [ ] **Step 5: Implement the tool wiring**

Write `scout/sub_agents/scraper/tools.py`:

```python
from __future__ import annotations

from google.adk.tools.mcp_tool import McpToolset, SseConnectionParams

from scout.config import Settings
from scout.config import settings as default_settings


def build_scraper_toolset(settings: Settings | None = None) -> McpToolset:
    active_settings = settings or default_settings
    return McpToolset(
        connection_params=SseConnectionParams(
            url=f"{active_settings.jobspy_mcp_url}/mcp/connect"
        ),
        tool_filter=["search_jobs"],
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scraper_tools.py -v`
Expected: `2 passed`

- [ ] **Step 7: Commit**

```bash
git add requirements.txt scout/sub_agents/scraper/tools.py tests/test_scraper_tools.py
git commit -m "feat(scout): wire scraper MCP toolset for jobspy-mcp-server"
```

---

### Task 4: Scraper LlmAgent

**Files:**
- Modify: `scout/prompts.py` (currently empty)
- Modify: `scout/sub_agents/scraper/agent.py` (currently empty)
- Create: `tests/test_scraper_agent.py`

**Interfaces:**
- Consumes: `scout.config.Settings`, `scout.config.settings` (Task 2); `scout.sub_agents.scraper.tools.build_scraper_toolset` (Task 3); `scout.shared.schemas.Listing` (Task 1); `scout.prompts.SCRAPER_INSTRUCTION` (this task).
- Produces: `scout.sub_agents.scraper.agent.build_scraper_agent(settings: Settings | None = None) -> LlmAgent` and `scout.sub_agents.scraper.agent.root_agent` (a pre-built instance using default settings, per ADK convention of exposing `root_agent` for `adk` CLI discovery).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scraper_agent.py`:

```python
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import McpToolset

from scout.config import Settings
from scout.shared.schemas import Listing
from scout.sub_agents.scraper.agent import build_scraper_agent


def test_build_scraper_agent_uses_configured_model():
    settings = Settings(deepseek_model="deepseek/deepseek-reasoner")

    agent = build_scraper_agent(settings)

    assert isinstance(agent, LlmAgent)
    assert isinstance(agent.model, LiteLlm)
    assert agent.model.model == "deepseek/deepseek-reasoner"


def test_build_scraper_agent_registers_mcp_toolset():
    agent = build_scraper_agent(Settings())

    assert len(agent.tools) == 1
    assert isinstance(agent.tools[0], McpToolset)


def test_build_scraper_agent_outputs_listing_list():
    agent = build_scraper_agent(Settings())

    assert agent.output_schema == list[Listing]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scraper_agent.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'build_scraper_agent' from 'scout.sub_agents.scraper.agent'`

- [ ] **Step 3: Implement the prompt and the agent**

Write `scout/prompts.py`:

```python
from __future__ import annotations

SCRAPER_INSTRUCTION = """\
You are the job-listing scraper for Job Market Scout.

Call the `search_jobs` tool once for each of the configured search roles,
using the configured locations, result count, and freshness window. Do not
invent listings or call any other tool.

Normalize every result the tool returns into the Listing schema:
- Keep `title`, `company`, `location`, and `url` exactly as provided.
- Set `is_remote` to true only if the listing is explicitly remote.
- Leave `salary_min`/`salary_max`/`date_posted` unset when the source does
  not provide them.
- Set `scraped_at` to the current UTC time.

Drop any result missing a `title`, `company`, or `url` instead of guessing
values. Return only the normalized list of listings, no commentary.
"""
```

Write `scout/sub_agents/scraper/agent.py`:

```python
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import SCRAPER_INSTRUCTION
from scout.shared.schemas import Listing
from scout.sub_agents.scraper.tools import build_scraper_toolset


def build_scraper_agent(settings: Settings | None = None) -> LlmAgent:
    active_settings = settings or default_settings
    return LlmAgent(
        name="scraper",
        model=LiteLlm(model=active_settings.deepseek_model),
        instruction=SCRAPER_INSTRUCTION,
        tools=[build_scraper_toolset(active_settings)],
        output_schema=list[Listing],
    )


root_agent = build_scraper_agent()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scraper_agent.py -v`
Expected: `3 passed`

- [ ] **Step 5: Run the full test suite**

Run: `./.venv/Scripts/python.exe -m pytest -v`
Expected: all tests across `tests/test_schemas.py`, `tests/test_config.py`, `tests/test_scraper_tools.py`, `tests/test_scraper_agent.py` pass (11 passed)

- [ ] **Step 6: Commit**

```bash
git add scout/prompts.py scout/sub_agents/scraper/agent.py tests/test_scraper_agent.py
git commit -m "feat(scout): build scraper LlmAgent"
```

---

### Task 5: docker-compose wiring for jobspy-mcp-server

**Files:**
- Modify: `docker-compose.yaml` (currently empty)

**Interfaces:**
- Consumes: `scout/.env` (git-ignored, user-provided, shaped like `scout/.env.example` from Task 2) for the `app` service's environment; `JOBSPY_MCP_URL` in that file must match the `jobspy-mcp` service's in-network address for `build_scraper_toolset` (Task 3) to reach it when running under Compose.
- Produces: a `jobspy-mcp` service reachable at `http://jobspy-mcp:9423` from other Compose services, and an `app` service built from the existing `Dockerfile`.

- [ ] **Step 1: Write docker-compose.yaml**

```yaml
services:
  app:
    build: .
    env_file:
      - scout/.env
    environment:
      JOBSPY_MCP_URL: http://jobspy-mcp:9423
    depends_on:
      - jobspy-mcp
    ports:
      - "8000:8000"

  jobspy-mcp:
    build: https://github.com/borgius/jobspy-mcp-server.git
    environment:
      ENABLE_SSE: "1"
      PORT: "9423"
      HOST: "0.0.0.0"
    ports:
      - "9423:9423"
```

- [ ] **Step 2: Validate the compose file syntax**

Run: `docker compose config --quiet`
Expected: no output, exit code 0. If it fails because `scout/.env` doesn't exist yet, run `cp scout/.env.example scout/.env` first (this file is git-ignored and won't be committed) and re-run.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yaml
git commit -m "feat(scout): add jobspy-mcp-server to docker-compose"
```

## Manual Verification (post-plan, not part of TDD loop)

The tasks above are fully unit-testable without a live MCP server or DeepSeek API key. Before relying on the scraper for real listings:

1. Set real values in `scout/.env` (`DEEPSEEK_API_KEY` at minimum).
2. `docker compose up --build`
3. Run the scraper via `adk run scout` (or `adk api_server scout` per the existing `Dockerfile` `CMD`) and confirm it returns real LinkedIn listings for the configured `SEARCH_ROLES`/`SEARCH_LOCATIONS`.

This step needs a live DeepSeek key and network access, so it isn't part of the automated task loop above — do it once after Task 5.
