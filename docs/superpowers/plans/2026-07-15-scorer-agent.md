# Scorer Sub-Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working ADK `LlmAgent` scorer sub-agent that rule-filters listings against preferences, then scores the survivors against a resume with DeepSeek, returning `MatchResult` objects above a minimum score.

**Architecture:** `scout/sub_agents/scorer` (folder name from the existing scaffold; agent `name="scorer"`) is an ADK `LlmAgent` (DeepSeek via LiteLLM) with no tools. A plain Python function, `filters.filter_listings`, runs *before* the agent is built and drops hard-reject listings (remote/location/salary) using `scout.config.Settings`. The survivors are serialized into the agent's instruction alongside resume text, so the LLM only reasons over listings that already passed the deterministic filter. The agent's `output_schema` is **not** `list[MatchResult]` — the LLM outputs `list[ListingScore]` (`external_id`, `score`, `reasoning` only, no echoed listing fields), and a separate deterministic function, `results.join_match_results`, pairs each score back to its source `Listing` by `external_id` to produce `list[MatchResult]`. The agent returns every scored survivor, including scores below `min_match_score` — no in-agent threshold drop. This is a deliberate reconciliation with `docs/scout-architecture.md` Decision 4 ("relevance filtering happens at Briefing query time, never at write time"): dropping sub-threshold matches inside the Scorer would make it impossible for a future persistence layer to store full score history or re-query with a different threshold. `min_match_score` remains a config field (read by a future Briefing-query stage), but the Scorer itself does not filter on it.

**Update (2026-07-16, post-implementation review):** Tasks 1, 3, and 5 below are shown in their original as-planned form for historical record, but the actual implementation diverged from them after a code-review pass caught real issues. The differences, in order of what changed:
- **`ListingScore` schema added** (`scout/shared/schemas.py`): `{external_id: str, score: int = Field(ge=0, le=100), reasoning: str}`. The Scorer's `output_schema` is `list[ListingScore]`, not `list[MatchResult]` — having the LLM echo the full `Listing` object back (as originally planned) costs roughly 3x the output tokens for zero new information and risks the model silently mutating/hallucinating listing fields on the way through.
- **`scout/sub_agents/scorer/results.py` added**: `join_match_results(listings: list[Listing], scores: list[ListingScore]) -> list[MatchResult]` — deterministic code that pairs each `ListingScore` back to its source `Listing` by `external_id`. Scores with an `external_id` that doesn't match any input listing (a hallucinated ID) are silently dropped rather than raising, consistent with the spec's "filter don't fail" stance on malformed LLM output. Listings the LLM didn't score at all are simply absent from the result — no zero-score placeholder is invented.
- **`filters.filter_listings` fixed** (`scout/sub_agents/scorer/filters.py`): the `preferred_locations` check is skipped entirely when `listing.is_remote` is `True`. Without this, a remote listing like `"Remote (AUS)"` was hard-rejected by `preferred_locations=["Melbourne"]` even though a remote role satisfies any location preference — a real correctness gap in the original filter.
- **`description_char_limit` added to `Settings`** (default `1500`, env var `DESCRIPTION_CHAR_LIMIT`): `build_scorer_instruction` truncates each listing's `description` to this many characters before serializing it into the prompt. Scraped descriptions are routinely 3-8k characters of boilerplate (About Us, EEO statements, benefits) that add input-token cost without improving scoring quality.
- **`build_scorer_instruction` projects a trimmed listing view**, not `listing.model_dump()` — only `external_id`, `title`, `company`, `location`, `is_remote`, `salary_min`, `salary_max`, and the truncated `description` are serialized into the prompt. Fields the LLM never needs to reason about (`url`, `source`, `scraped_at`, raw timestamps) are dropped from the prompt entirely.
- **`temperature=0`** passed to `LiteLlm(model=..., temperature=0)` in `build_scorer_agent`, for score reproducibility across runs (scores feed into a `matches` table history in a future session; comparing scores across runs is only meaningful if scoring is as deterministic as the model allows).

Explicitly **not** adopted from that review, with reasoning:
- **Retry-on-validation-failure** and **batching listings into chunks of ~10-15 with per-batch retry** — both directly contradict the spec's stated stance: *"No retry logic for LLM calls yet — add once real failure modes are observed (YAGNI), same stance as the scraper spec."* No evidence of either failure mode has been observed yet. Revisit once `results_wanted` grows large enough that a single-call prompt becomes unreliable, or once a real malformed-output failure is seen in practice.
- **Restructuring `build_scorer_agent` to read listings from ADK session state** (`ctx.state.get("scraped_listings")`) instead of taking `listings` as an explicit argument — this invents a session-state key contract that doesn't exist anywhere in the codebase (the scraper agent has no `output_key` set). Root pipeline wiring, including how the scraper's output reaches the Scorer, is explicitly out of scope per the spec and deferred to a future session that will design that contract properly.
- **Recording model name / prompt-template hash in the `matches` table** — the `matches` table doesn't exist yet; DB persistence is out of scope for this session. Correct direction for whichever future session wires up persistence, alongside `config_version` (architecture Decision 5/6) — no action here.

**Update (2026-07-16, live-verification finding — do not re-attempt without reading this):** manual verification against a real `DEEPSEEK_API_KEY` (see "Manual Verification" below) surfaced a live bug in the reasoning above. `output_schema=list[ListingScore]` triggers a `WARNING: Unsupported response_schema type <class 'types.GenericAlias'> for LiteLLM structured outputs` from ADK (`_to_litellm_response_format` in `google/adk/models/lite_llm.py` has no branch for a bare `list[BaseModel]` generic alias), which means `response_format=None` is sent to DeepSeek — no JSON-schema enforcement at the API level, only the prompt's textual instruction. This was flagged as a gap and "fixed" by wrapping the list in a single `BaseModel` (`ScoredListings{scores: list[ListingScore]}`), since a bare `BaseModel` subclass *does* hit `_to_litellm_response_format`'s structured-output branch.

That fix was reverted after live testing. Wrapping the schema makes ADK send `response_format={"type": "json_schema", "strict": True, ...}` to DeepSeek's `/beta/chat/completions` endpoint, which DeepSeek rejects outright with `400 Bad Request: "This response_format type is unavailable now"` — DeepSeek's API does not currently support OpenAI's strict `json_schema` response-format mode, only `json_object` (or none). The scorer call fails completely with the wrapper; it works with the bare list. **Net result: `output_schema=list[ListingScore]` (unenforced at the API level, prompt-only) is the only configuration confirmed working against live DeepSeek right now** — the "Unsupported response_schema type" warning is expected and can be ignored. The `ScoredListings` wrapper model and its tests were added and then removed in the same session once this was discovered; they do not exist in the final code. Do not reintroduce a `BaseModel`-wrapped `output_schema` for this agent without first confirming DeepSeek has added `json_schema` support, or without getting ADK to send `type: json_object` instead (not currently configurable through `LlmAgent`/`LiteLlm` without patching ADK).

**Tech Stack:** Python 3.12, `google-adk==2.4.0` (`LlmAgent`, `LiteLlm`), `pydantic`, `python-dotenv`, `pytest==9.1.1` (new dev dependency — not yet in `requirements.txt` on `main`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-15-scorer-agent-design.md` — this plan implements it in full; do not add DB persistence, the briefing agent, root pipeline wiring, or skill/seniority rule-filters (out of scope per that spec).
- **Update (2026-07-16): the scraper worktree has merged into `main` and this branch.** `scout/shared/schemas.py`, `scout/config.py`, and `scout/prompts.py` are no longer empty — they hold the scraper sub-agent's real implementation. Concretely:
  - `scout/shared/schemas.py` already defines `Listing` exactly as this plan needs it (`source`, `external_id`, `title`, `company`, `location`, `is_remote`, `url`, `description`, `salary_min`, `salary_max`, `date_posted`, `scraped_at`). Task 1 must **add `MatchResult` to the existing file**, not write `Listing` again.
  - `scout/config.py` already defines a frozen `Settings` dataclass with scraper fields (`jobspy_mcp_url`, `deepseek_api_key`, `deepseek_model`, `search_roles`, `search_locations`, `results_wanted`, `hours_old`) and a module-level `settings` instance, but **no `__post_init__`**. Task 2 must **extend this existing `Settings`** with the scorer's new fields (`resume_path`, `resume_text`, `preferred_locations`, `remote_only`, `min_salary`, `min_match_score`) and add a `__post_init__` for `resume_text` — do not replace the scraper fields.
  - `scout/.env.example` already lists the scraper's env vars (`JOBSPY_MCP_URL`, `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `SEARCH_ROLES`, `SEARCH_LOCATIONS`, `RESULTS_WANTED`, `HOURS_OLD`). Task 2 appends the scorer's new vars below them.
  - `scout/prompts.py` already defines `build_scraper_instruction`. Task 5 appends `build_scorer_instruction` alongside it (as originally planned — no change needed there).
  - `tests/test_config.py` and `tests/test_schemas.py` already contain passing tests for the scraper's `Settings` and `Listing`. Task 1/2 must **add** new test functions for `MatchResult` / the scorer's settings fields, not overwrite these files wholesale as the original step-by-step content below shows — treat those code blocks as "these tests must exist," inserted alongside the scraper's existing tests, not a full-file replacement.
  - `pytest==9.1.1` is already installed and pinned in `requirements.txt` (merged from the scraper branch). Task 1 Step 1 (`pip install pytest`) is a no-op now — skip straight to writing tests.
  - `scout/sub_agents/scorer/agent.py` and `scout/sub_agents/scorer/tools.py` are still empty stubs, as expected — nothing to reconcile there.
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

- [x] **Step 1: (skip — already done)** `pytest==9.1.1` is already installed and in `requirements.txt` from the merged scraper branch. No action needed.

- [x] **Step 2: Write the failing tests**

`tests/test_schemas.py` already contains three passing tests for `Listing` (`test_listing_accepts_valid_data`, `test_listing_allows_missing_optional_salary_and_date`, `test_listing_requires_title`) — leave them in place. Append a `_make_listing` helper and the `MatchResult` tests below them:

```python
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

Note: `MatchResult` is not yet imported by the file, and `pytest` / `ValidationError` may already be imported — check the existing imports at the top of the file before appending to avoid duplicates.

- [x] **Step 3: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_schemas.py -v`
Expected: the 3 existing `Listing` tests pass; the 2 new `MatchResult` tests FAIL with `ImportError: cannot import name 'MatchResult' from 'scout.shared.schemas'`

- [x] **Step 4: Implement the schema**

`scout/shared/schemas.py` already defines `Listing` — do not touch it. Append `MatchResult` below it:

```python
class MatchResult(BaseModel):
    listing: Listing
    score: int
    reasoning: str
```

- [x] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_schemas.py -v`
Expected: `5 passed`

- [x] **Step 6: Commit**

```bash
git add scout/shared/schemas.py tests/test_schemas.py
git commit -m "feat(scout): add MatchResult schema"
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

- [x] **Step 1: Write the failing tests**

`tests/test_config.py` already contains three passing tests for the scraper's `Settings` fields (`test_settings_uses_defaults_when_env_unset`, `test_settings_reads_env_overrides`, `test_settings_can_be_constructed_with_explicit_overrides`) — leave them in place, but add the scorer's new env vars to the existing `monkeypatch.delenv` loop in `test_settings_uses_defaults_when_env_unset` so scorer env vars don't leak between tests: `RESUME_PATH`, `PREFERRED_LOCATIONS`, `REMOTE_ONLY`, `MIN_SALARY`, `MIN_MATCH_SCORE`. Then append these new tests:

```python
def test_settings_uses_scorer_defaults_when_env_unset(monkeypatch):
    for var in (
        "RESUME_PATH",
        "PREFERRED_LOCATIONS",
        "REMOTE_ONLY",
        "MIN_SALARY",
        "MIN_MATCH_SCORE",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings()

    assert settings.preferred_locations == []
    assert settings.remote_only is False
    assert settings.min_salary is None
    assert settings.min_match_score == 60


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
```

Note: `pytest` is likely not yet imported in `tests/test_config.py` — check the existing imports before appending.

- [x] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: the 3 existing scraper `Settings` tests pass; the new scorer tests FAIL — `TypeError: Settings.__init__() got an unexpected keyword argument` or `AttributeError: 'Settings' object has no attribute 'resume_text'`

- [x] **Step 3: Create the default resume fixture file**

Write `scout/resume.txt`:

```
Software Engineer with 5 years of experience building backend services in
Python and Go. Comfortable with distributed systems, REST/gRPC APIs, and
SQL databases. Looking for backend or platform engineering roles.
```

- [x] **Step 4: Extend config**

`scout/config.py` already defines `Settings` with the scraper's fields (`jobspy_mcp_url`, `deepseek_api_key`, `deepseek_model`, `search_roles`, `search_locations`, `results_wanted`, `hours_old`), the `_split_csv` helper, `load_dotenv(...)`, and a module-level `settings = Settings()` — do not remove or restructure any of that. Add a `_read_resume_text` helper, a `_DEFAULT_RESUME_PATH` constant, the six new scorer fields on the existing `Settings` dataclass, and a `__post_init__` (the dataclass has none today):

```python
_DEFAULT_RESUME_PATH = str(Path(__file__).resolve().parent / "resume.txt")


def _read_resume_text(resume_path: str) -> str:
    path = Path(resume_path)
    if not path.is_file():
        raise FileNotFoundError(f"resume file not found: {resume_path}")
    return path.read_text(encoding="utf-8")
```

Add to the `Settings` dataclass body (after the existing `hours_old` field):

```python
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
```

Append to `scout/.env.example` (below the existing scraper vars):

```
RESUME_PATH=scout/resume.txt
PREFERRED_LOCATIONS=
REMOTE_ONLY=false
MIN_SALARY=
MIN_MATCH_SCORE=60
```

- [x] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: `7 passed`

- [x] **Step 6: Commit**

```bash
git add scout/config.py scout/.env.example scout/resume.txt tests/test_config.py
git commit -m "feat(scout): extend Settings with scorer config"
```

---

### Task 3: Rule-based pre-filter

**Files:**
- Create: `scout/sub_agents/scorer/filters.py`
- Create: `tests/test_scorer_filters.py`

**Interfaces:**
- Consumes: `scout.config.Settings` (Task 2), `scout.shared.schemas.Listing` (Task 1).
- Produces: `scout.sub_agents.scorer.filters.filter_listings(listings: list[Listing], settings: Settings) -> list[Listing]`. Later tasks call this as `filter_listings(listings, active_settings)`.

- [x] **Step 1: Write the failing tests**

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

- [x] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scorer_filters.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'scout.sub_agents.scorer.filters'`

- [x] **Step 3: Implement the filter**

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

- [x] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scorer_filters.py -v`
Expected: `6 passed`

- [x] **Step 5: Commit**

```bash
git add scout/sub_agents/scorer/filters.py tests/test_scorer_filters.py
git commit -m "feat(scout): add scorer rule-based pre-filter"
```

---

### Task 4: (dropped — see architecture reconciliation)

**Update (2026-07-16):** this task originally built an `after_model_callback` (`callbacks.build_drop_low_scores_callback`) that dropped `MatchResult`s below `min_match_score` from the Scorer's output before it was returned. Comparing the spec against `docs/scout-architecture.md` Decision 4 ("Relevance filtering happens at Briefing query time ... never at write time") surfaced a real conflict: if the Scorer discards sub-threshold matches before they ever leave the agent, a future persistence layer has nothing to write for those listings, and the architecture's goal of a full re-queryable score history is structurally impossible to satisfy later.

Resolved by dropping this task. The Scorer (Task 5) returns the full `list[MatchResult]` for every filtered survivor, unfiltered by score. `min_match_score` stays a `Settings` field (already added in Task 2) for a future Briefing-query stage to apply at read time. `scout/sub_agents/scorer/callbacks.py` and `tests/test_scorer_callbacks.py` are not created.

---

### Task 5: Scorer LlmAgent

**Files:**
- Modify: `scout/prompts.py` (currently empty)
- Modify: `scout/sub_agents/scorer/agent.py` (currently empty)
- Create: `tests/test_scorer_agent.py`

**Interfaces:**
- Consumes: `scout.config.Settings`, `scout.config.settings` (Task 2); `scout.shared.schemas.Listing`, `scout.shared.schemas.MatchResult` (Task 1); `scout.sub_agents.scorer.filters.filter_listings` (Task 3).
- Produces: `scout.prompts.build_scorer_instruction(settings: Settings, listings: list[Listing]) -> str`. Produces `scout.sub_agents.scorer.agent.build_scorer_agent(listings: list[Listing], settings: Settings | None = None) -> LlmAgent`. `build_scorer_agent` takes `listings` explicitly (rather than reading from session state) because root pipeline wiring — how the scraper's output reaches this agent inside a `SequentialAgent` — is out of scope per the spec; a future session will decide that wiring and can adapt this signature then. The agent has no `after_model_callback` — it returns every scored survivor, unfiltered by `min_match_score` (see Task 4 note above).

- [x] **Step 1: Write the failing tests**

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


def test_build_scorer_agent_has_no_score_threshold_callback():
    agent = build_scorer_agent([_make_listing()], Settings())

    assert agent.after_model_callback is None
```

- [x] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scorer_agent.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'build_scorer_instruction' from 'scout.prompts'`

- [x] **Step 3: Implement the prompt and the agent**

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
    )
```

Note: unlike the scraper (which exposes a module-level `root_agent` built from `default_settings` for `adk` CLI discovery), the scorer has no `root_agent` in this task — it requires `listings` as an argument that isn't available at import time, and root pipeline wiring is out of scope per the spec. The agent has no `after_model_callback` — see the Task 4 note above on why threshold-dropping was removed from this stage.

- [x] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_scorer_agent.py -v`
Expected: `6 passed`

- [x] **Step 5: Run the full test suite**

Run: `./.venv/Scripts/python.exe -m pytest -v`
Expected: all tests pass. If the venv is missing dependencies (e.g. a fresh checkout), run `./.venv/Scripts/python.exe -m pip install -r requirements.txt` first.

**Actual final count (post-review, see the Update note above)**: `tests/test_prompts.py`, `tests/test_scraper_agent.py`, `tests/test_scraper_tools.py` — 10; `tests/test_schemas.py` — 8 (5 original + 3 `ListingScore` tests); `tests/test_config.py` — 7 (includes `description_char_limit`); `tests/test_scorer_filters.py` — 7 (includes the remote-bypass fix); `tests/test_scorer_results.py` — 3 (new, `join_match_results`); `tests/test_scorer_agent.py` — 10 (covers the trimmed projection, truncation, `list[ListingScore]` output, and `temperature=0`): **45 passed**.

- [x] **Step 6: Commit**

```bash
git add scout/prompts.py scout/sub_agents/scorer/agent.py tests/test_scorer_agent.py
git commit -m "feat(scout): build scorer LlmAgent"
```

## Manual Verification (post-plan, not part of TDD loop)

The tasks above are fully unit-testable without a live DeepSeek API key. Before relying on the scorer for real scoring:

1. Set `DEEPSEEK_API_KEY` and a real `RESUME_PATH` in `scout/.env`.
2. In a Python shell: build some `Listing` objects, or run the now-merged `build_scraper_agent()` (`scout/sub_agents/scraper/agent.py`) to get real scraped output, call `build_scorer_agent(listings)`, and run it via the ADK runner (`adk run` equivalent for a single sub-agent, or a small script using `google.adk.runners.Runner`) to get back `list[ListingScore]`.
3. Call `join_match_results(listings, scores)` (`scout/sub_agents/scorer/results.py`) on the filtered survivors and the returned scores to get `list[MatchResult]`.
4. Confirm the joined `MatchResult` list contains every listing the LLM actually scored (regardless of score value — `min_match_score` is not applied at this stage, a future Briefing-query stage applies it at read time), with sensible scores/reasoning relative to the resume, and that no hallucinated `external_id`s made it through the join.

This step needs a live DeepSeek key, so it isn't part of the automated task loop above — do it once after Task 5.
