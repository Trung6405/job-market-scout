# Phase 1: Model Layer & Brief-Time Filtering

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** nothing

---

## Goal

Replace `google-adk` with a small project-local JSON-completion helper, give
both model stages shared batching with per-batch failure isolation, and move
preference filtering to brief selection. We'll know it worked when no
response size scales with run length, the dashboard contains
preference-failing listings, and the brief does not.

The Scorer and Extractor stay **separate calls**. See the spec's Amendment
for why merging them was withdrawn — in short, extraction must not see the
profile, and the Scorer must see the whole description.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — `complete_json` is the only outbound model call. The API key comes
  from `settings.deepseek_api_key` and is never logged; Task 3's helper
  raises on empty content, and Task 5 bounds concurrency and absorbs a
  single per-batch failure.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  Yes — **Task 4** removes the preference inputs from the scoring prompt,
  changing the meaning of every score stored afterwards. Gated on human
  sign-off.

---

## Tasks

### Task 1: Spike — verify direct litellm JSON mode

- **Files:** `scripts/spike_litellm_json.py` (throwaway)
- **Gate:** none
- **Steps:**
  - [ ] Write a script calling `litellm.acompletion` directly with
        `model=settings.deepseek_model`,
        `response_format={"type": "json_object"}`, and a trivial prompt
        asking for `{"ok": true}`
  - [ ] Run: `python scripts/spike_litellm_json.py`
  - [ ] Confirm the response parses as JSON without fence-stripping
  - [ ] Record in Notes / Learnings whether `strip_code_fence` is still
        needed defensively (it is retained either way)
  - [ ] Commit: `spike: verify litellm json_object mode against deepseek`

### Task 2: Shared test factories and the project-local event type

- **Files:** `tests/conftest.py`, `scout/shared/events.py`,
  `tests/test_shared_events.py`, `tests/test_agent.py`
- **Gate:** none
- **Steps:**
  - [ ] Add shared factories to `tests/conftest.py` — later tasks all build
        `Listing` and `MatchResult` objects, and building them inline each
        time invites drift:

```python
from datetime import datetime, timezone

from scout.shared.schemas import Listing, MatchResult


@pytest.fixture
def listing_factory():
    def _make(**overrides) -> Listing:
        defaults = dict(
            source="indeed",
            external_id="ext-1",
            title="Backend Engineer",
            company="Acme Corp",
            location="Melbourne VIC",
            is_remote=False,
            url="https://example.com/job/1",
            description="We need Python and PostgreSQL.",
            salary_min=None,
            salary_max=None,
            date_posted=None,
            scraped_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        )
        return Listing(**{**defaults, **overrides})

    return _make


@pytest.fixture
def match_factory(listing_factory):
    def _make(listing: Listing | None = None, score: int = 70, reasoning: str = "ok") -> MatchResult:
        return MatchResult(
            listing=listing if listing is not None else listing_factory(),
            score=score,
            reasoning=reasoning,
        )

    return _make
```

  - [ ] Verify the fixtures load (`pytest tests/test_schemas.py -q`) — an
        unused fixture must not break collection
  - [ ] Write failing test in `tests/test_shared_events.py`:

```python
import dataclasses

import pytest

from scout.shared.events import PipelineEvent


def test_pipeline_event_carries_author_and_text():
    event = PipelineEvent(author="scout", text="Scraper: 3 listing(s) found")
    assert event.author == "scout"
    assert event.text == "Scraper: 3 listing(s) found"


def test_pipeline_event_is_frozen():
    event = PipelineEvent(author="scout", text="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.text = "y"
```

  - [ ] Verify it fails (`pytest tests/test_shared_events.py -v`) — expect
        `ModuleNotFoundError: No module named 'scout.shared.events'`
  - [ ] Implement `scout/shared/events.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineEvent:
    """One status line emitted by a pipeline stage.

    Replaces ADK's ``Event``. The pipeline never needed invocation ids,
    branches or multi-part content — only an author and a line of text
    for the entrypoint to log.
    """

    author: str
    text: str
```

  - [ ] Verify it passes (`pytest tests/test_shared_events.py -v`)
  - [ ] Migrate `tests/test_agent.py`: replace every assertion reading
        `event.content.parts[0].text` with `event.text`, and drop the
        `google.genai` / `google.adk` imports from that file. The pipeline
        still yields ADK events until Task 6, so **these tests fail in
        between**; mark the migrated assertions
        `@pytest.mark.xfail(reason="pipeline rewired in Task 6", strict=False)`
  - [ ] Verify the rest of the suite is unaffected (`pytest -q`)
  - [ ] Commit: `feat(shared): add PipelineEvent and shared test factories`

### Task 3: JSON completion helper

- **Files:** `scout/shared/llm.py`, `tests/test_shared_llm.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test in `tests/test_shared_llm.py`:

```python
from __future__ import annotations

import pytest
from pydantic import BaseModel

from scout.config import Settings
from scout.shared import llm


class _Toy(BaseModel):
    value: int


def _fake_response(content: str | None):
    class _Message:
        def __init__(self, c):
            self.content = c

    class _Choice:
        def __init__(self, c):
            self.message = _Message(c)

    class _Response:
        def __init__(self, c):
            self.choices = [_Choice(c)]

    return _Response(content)


async def test_complete_json_validates_into_schema(monkeypatch):
    async def _fake_acompletion(**kwargs):
        return _fake_response('{"value": 7}')

    monkeypatch.setattr(llm.litellm, "acompletion", _fake_acompletion)
    result = await llm.complete_json("prompt", _Toy, Settings())
    assert result.value == 7


async def test_complete_json_strips_code_fence(monkeypatch):
    async def _fake_acompletion(**kwargs):
        return _fake_response('```json\n{"value": 3}\n```')

    monkeypatch.setattr(llm.litellm, "acompletion", _fake_acompletion)
    result = await llm.complete_json("prompt", _Toy, Settings())
    assert result.value == 3


async def test_complete_json_raises_on_empty_content(monkeypatch):
    async def _fake_acompletion(**kwargs):
        return _fake_response(None)

    monkeypatch.setattr(llm.litellm, "acompletion", _fake_acompletion)
    with pytest.raises(ValueError, match="no content"):
        await llm.complete_json("prompt", _Toy, Settings())


async def test_complete_json_passes_model_and_json_mode(monkeypatch):
    seen: dict = {}

    async def _fake_acompletion(**kwargs):
        seen.update(kwargs)
        return _fake_response('{"value": 1}')

    monkeypatch.setattr(llm.litellm, "acompletion", _fake_acompletion)
    settings = Settings()
    await llm.complete_json("prompt", _Toy, settings, temperature=0.3)
    assert seen["model"] == settings.deepseek_model
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["temperature"] == 0.3
    assert seen["messages"] == [{"role": "user", "content": "prompt"}]
```

  - [ ] Verify it fails (`pytest tests/test_shared_llm.py -v`) — expect
        `ModuleNotFoundError: No module named 'scout.shared.llm'`
  - [ ] Implement `scout/shared/llm.py`:

```python
from __future__ import annotations

from typing import TypeVar

import litellm
from pydantic import BaseModel

from scout.config import Settings
from scout.shared.parsing import strip_code_fence

T = TypeVar("T", bound=BaseModel)


async def complete_json(
    prompt: str,
    schema: type[T],
    settings: Settings,
    *,
    temperature: float = 0.0,
) -> T:
    """Send one prompt and validate the reply into ``schema``.

    Replaces the ADK ``LlmAgent`` + ``InMemoryRunner`` pair that used to
    wrap every call. Nothing in this pipeline needs tools, delegation or a
    retained session — every call is one stateless turn returning JSON.

    ``strip_code_fence`` is kept even though ``response_format`` is set:
    it costs nothing and models occasionally fence their output anyway.
    """
    response = await litellm.acompletion(
        model=settings.deepseek_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        response_format={"type": "json_object"},
        api_key=settings.deepseek_api_key or None,
    )
    raw = response.choices[0].message.content
    if raw is None:
        raise ValueError("model returned no content")
    return schema.model_validate_json(strip_code_fence(raw))
```

  - [ ] Verify it passes (`pytest tests/test_shared_llm.py -v`)
  - [ ] Commit: `feat(shared): add complete_json litellm helper`

### Task 4: Preference-neutral scoring prompt

- **Files:** `scout/prompts.py`, `tests/test_prompts.py`
- **Gate:** ⚠️ **Human sign-off required before this task.** Removing the
  preference inputs changes the meaning of every score stored afterwards.
- **Steps:**
  - [ ] Write failing test in `tests/test_prompts.py`:

```python
def test_scorer_instruction_omits_preferences(listing_factory):
    from scout.config import Settings
    from scout.prompts import build_scorer_instruction

    settings = Settings()
    object.__setattr__(settings, "preferred_locations", ["Melbourne"])
    object.__setattr__(settings, "remote_only", True)
    object.__setattr__(settings, "min_salary", 90000.0)

    instruction = build_scorer_instruction(settings, [listing_factory()])
    assert "Preferred locations" not in instruction
    assert "Remote only" not in instruction
    assert "Minimum salary" not in instruction


def test_scorer_instruction_keeps_profile_and_rubric(listing_factory):
    from scout.config import Settings
    from scout.prompts import build_scorer_instruction

    instruction = build_scorer_instruction(Settings(), [listing_factory()])
    assert "Candidate profile:" in instruction
    assert "90-100" in instruction
    assert '"scores"' in instruction


def test_requirements_instruction_never_includes_the_profile(listing_factory):
    """Extraction must stay profile-blind — see the spec's Amendment.

    If the profile leaks into this prompt, a model can soften a requirement
    the student doesn't meet, and the gap silently disappears.
    """
    from scout.config import Settings
    from scout.prompts import build_requirements_instruction

    settings = Settings()
    instruction = build_requirements_instruction(settings, [listing_factory()])
    assert settings.profile.name not in instruction
    assert "Candidate profile:" not in instruction
```

  - [ ] Verify it fails (`pytest tests/test_prompts.py -v`) — the first test
        fails; the third should already pass and is a regression guard
  - [ ] In `scout/prompts.py`, delete these three lines from
        `build_scorer_instruction`'s template, and nothing else:

```
Preferred locations: {settings.preferred_locations or "no preference"}
Remote only: {settings.remote_only}
Minimum salary: {settings.min_salary if settings.min_salary is not None else "no floor"}
```

  - [ ] Add a comment above the function recording why they are absent:

```python
# Preferences (location, remote, salary) are deliberately NOT given to the
# scorer. They gate the brief instead — see briefing/filters.py. Scoring
# them here too would count them twice: a strong role in the wrong city
# would reach the dashboard already marked down, when the dashboard is
# meant to show the day's full market.
```

  - [ ] Verify it passes (`pytest tests/test_prompts.py -v`)
  - [ ] Commit: `feat(scorer): make scoring preference-neutral`

### Task 5: Shared batching with per-batch tolerance

- **Files:** `scout/shared/batching.py`, `scout/config.py`,
  `scout/sub_agents/scorer/runner.py`, `scout/sub_agents/advisor/runner.py`,
  `scout/sub_agents/scorer/agent.py` (delete),
  `scout/sub_agents/advisor/agent.py` (delete),
  `tests/test_shared_batching.py`, `tests/test_scorer_runner.py`,
  `tests/test_advisor_requirements.py`
- **Gate:** none
- **Steps:**
  - [ ] Add to `scout/config.py`, replacing `requirements_batch_size`:

```python
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
```

  - [ ] Write failing test in `tests/test_shared_batching.py`:

```python
from __future__ import annotations

from scout.shared.batching import batches, run_batches


def test_batches_splits_by_size():
    assert batches([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_batches_treats_zero_size_as_one():
    assert batches([1, 2], 0) == [[1], [2]]


def test_batches_of_empty_list_is_empty():
    assert batches([], 5) == []


async def test_run_batches_concatenates_results():
    async def _call(batch):
        return [item * 10 for item in batch]

    result = await run_batches([[1, 2], [3]], _call, concurrency=2, label="test")
    assert sorted(result) == [10, 20, 30]


async def test_run_batches_retries_once_then_skips(caplog):
    attempts = {"n": 0}

    async def _always_fails(batch):
        attempts["n"] += 1
        raise ValueError("truncated JSON")

    result = await run_batches([[1]], _always_fails, concurrency=1, label="scorer")
    assert result == []
    assert attempts["n"] == 2
    assert "scorer batch failed" in caplog.text


async def test_run_batches_keeps_good_batches_when_one_fails():
    async def _fail_first(batch):
        if batch == [1]:
            raise ValueError("bad")
        return batch

    result = await run_batches([[1], [2]], _fail_first, concurrency=1, label="scorer")
    assert result == [2]
```

  - [ ] Verify it fails (`pytest tests/test_shared_batching.py -v`)
  - [ ] Implement `scout/shared/batching.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

_MAX_ATTEMPTS = 2


def batches(items: list[T], size: int) -> list[list[T]]:
    """Split items into consecutive chunks of at most ``size``."""
    step = max(1, size)
    return [items[i : i + step] for i in range(0, len(items), step)]


async def run_batches(
    batch_list: list[list[T]],
    call: Callable[[list[T]], Awaitable[list[R]]],
    *,
    concurrency: int,
    label: str,
) -> list[R]:
    """Run ``call`` over each batch concurrently, tolerating batch failure.

    A batch is retried once, then skipped with a warning. One truncated or
    malformed response should cost that batch's listings, not the whole
    day's run — and because the Scorer and Extractor are separate stages, a
    skipped extraction batch costs gaps while the listing keeps its score.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(batch: list[T]) -> list[R]:
        async with semaphore:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    return await call(batch)
                except Exception as exc:
                    if attempt == _MAX_ATTEMPTS:
                        logger.warning(
                            "%s batch failed after %d attempt(s), skipping %d item(s): %s",
                            label,
                            attempt,
                            len(batch),
                            exc,
                        )
                        return []
                    logger.info(
                        "%s batch attempt %d failed, retrying: %s", label, attempt, exc
                    )
            return []

    results = await asyncio.gather(*(_one(batch) for batch in batch_list))
    return [item for batch_result in results for item in batch_result]
```

  - [ ] Verify it passes (`pytest tests/test_shared_batching.py -v`)
  - [ ] Rewrite `scout/sub_agents/scorer/runner.py` onto the helper, deleting
        `scout/sub_agents/scorer/agent.py` and its ADK `LlmAgent` factory.
        Note `filter_listings` is **not** called here any more — Task 7 moves
        it to the brief:

```python
from __future__ import annotations

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import build_scorer_instruction
from scout.shared.batching import batches, run_batches
from scout.shared.llm import complete_json
from scout.shared.schemas import Listing, ListingScore, ListingScoreBatch


async def run_scorer(
    listings: list[Listing], settings: Settings | None = None
) -> list[ListingScore]:
    """Score every listing, batched.

    Batched for the same reason extraction is: one response must cover its
    whole batch, and the model caps output tokens. The Scorer previously
    issued a single call for the entire run — the shape that truncated the
    Advisor's output and aborted a run in July.
    """
    active_settings = settings or default_settings
    if not listings:
        return []

    async def _call(batch: list[Listing]) -> list[ListingScore]:
        result = await complete_json(
            build_scorer_instruction(active_settings, batch),
            ListingScoreBatch,
            active_settings,
        )
        return result.scores

    return await run_batches(
        batches(listings, active_settings.scorer_batch_size),
        _call,
        concurrency=active_settings.model_concurrency,
        label="scorer",
    )
```

  - [ ] Rewrite `scout/sub_agents/advisor/runner.py` the same way, deleting
        `scout/sub_agents/advisor/agent.py`:

```python
from __future__ import annotations

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import build_requirements_instruction
from scout.shared.batching import batches, run_batches
from scout.shared.llm import complete_json
from scout.shared.schemas import (
    Listing,
    ListingRequirements,
    ListingRequirementsBatch,
)


async def run_requirements_extraction(
    listings: list[Listing], settings: Settings | None = None
) -> list[ListingRequirements]:
    """Extract stated requirements for every listing, batched.

    Deliberately profile-blind: ``build_requirements_instruction`` never
    renders the profile, so a requirement can't be softened or dropped
    because the student doesn't meet it. See the spec's Amendment.
    """
    active_settings = settings or default_settings
    if not listings:
        return []

    async def _call(batch: list[Listing]) -> list[ListingRequirements]:
        result = await complete_json(
            build_requirements_instruction(active_settings, batch),
            ListingRequirementsBatch,
            active_settings,
        )
        return result.requirements

    return await run_batches(
        batches(listings, active_settings.requirements_batch_size),
        _call,
        concurrency=active_settings.model_concurrency,
        label="requirements",
    )
```

  - [ ] Update `tests/test_scorer_runner.py` and
        `tests/test_advisor_requirements.py` to monkeypatch
        `complete_json` on the runner module instead of stubbing an ADK
        agent; delete `tests/test_scorer_agent.py`
  - [ ] Verify (`pytest tests/test_scorer_runner.py tests/test_advisor_requirements.py -v`)
  - [ ] Commit: `feat(model): batch both stages on a shared helper`

### Task 6: Rewire the pipeline onto the local shell

- **Files:** `scout/agent.py`, `scout/main.py`,
  `scout/shared/adk_runner.py` (delete), `tests/test_agent.py`,
  `tests/test_main_entrypoint.py`, `tests/test_shared_parsing.py`
- **Gate:** none
- **Steps:**
  - [ ] Remove the `xfail` marks added in Task 2 from `tests/test_agent.py`
  - [ ] Verify they fail (`pytest tests/test_agent.py -v`)
  - [ ] Rewrite `scout/agent.py`: keep the class name `ScoutPipelineAgent`
        and its `name = "scout"` attribute, but drop `BaseAgent`,
        `InvocationContext`, `Event` and `genai_types`. Rename
        `_run_async_impl(self, ctx)` to `run(self)` returning
        `AsyncGenerator[PipelineEvent, None]`, and replace `_status_event`
        with `PipelineEvent(author=self.name, text=...)`. The stage
        sequence, the transaction block and the existing
        `requirements_by_key` join all stay exactly as they are — this task
        changes only the event plumbing.
  - [ ] Update `scout/main.py` to drop `InMemoryRunner` and `genai_types`:

```python
async def run_once() -> None:
    agent = ScoutPipelineAgent()
    async for event in agent.run():
        logger.info(event.text)
```

  - [ ] Delete `scout/shared/adk_runner.py`; `strip_code_fence` stays in
        `scout/shared/parsing.py` and keeps its tests
  - [ ] Verify they pass (`pytest tests/test_agent.py tests/test_main_entrypoint.py -v`)
  - [ ] Commit: `refactor(pipeline): run on project-local event shell`

### Task 7: Preference filtering at brief selection

- **Files:** `scout/sub_agents/briefing/filters.py` (moved from
  `scout/sub_agents/scorer/filters.py`),
  `scout/sub_agents/briefing/select.py`,
  `scout/sub_agents/briefing/briefing.py`, `scout/agent.py`,
  `tests/test_briefing_filters.py` (renamed from
  `tests/test_scorer_filters.py`), `tests/test_briefing_select.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test in `tests/test_briefing_select.py`:

```python
def test_select_top_matches_excludes_preference_failures(
    match_factory, listing_factory
):
    from scout.config import Settings
    from scout.sub_agents.briefing.select import select_top_matches

    settings = Settings()
    object.__setattr__(settings, "min_match_score", 50)
    object.__setattr__(settings, "remote_only", True)

    remote = match_factory(listing=listing_factory(external_id="r", is_remote=True), score=80)
    onsite = match_factory(listing=listing_factory(external_id="o", is_remote=False), score=90)

    selected = select_top_matches([remote, onsite], settings)
    assert [m.listing.external_id for m in selected] == ["r"]


def test_select_top_matches_still_applies_score_floor(match_factory):
    from scout.config import Settings
    from scout.sub_agents.briefing.select import select_top_matches

    settings = Settings()
    object.__setattr__(settings, "min_match_score", 60)
    object.__setattr__(settings, "remote_only", False)
    object.__setattr__(settings, "preferred_locations", [])
    object.__setattr__(settings, "min_salary", None)

    assert select_top_matches([match_factory(score=59)], settings) == []
```

  - [ ] Verify it fails (`pytest tests/test_briefing_select.py -v`)
  - [ ] `git mv scout/sub_agents/scorer/filters.py scout/sub_agents/briefing/filters.py`
        and `git mv tests/test_scorer_filters.py tests/test_briefing_filters.py`,
        updating imports in both. Refactor to a single predicate, keeping
        the existing rules byte-for-byte:

```python
def passes_preferences(listing: Listing, settings: Settings) -> bool:
    """Whether a listing matches the student's stated preferences.

    Applied at brief selection, deliberately *not* before scoring: every
    listing is scored so the dashboard shows the day's full market, and
    preferences narrow only what reaches Discord.
    """
    if settings.remote_only and not listing.is_remote:
        return False
    if (
        settings.preferred_locations
        and not listing.is_remote
        and not any(
            preferred.lower() in listing.location.lower()
            for preferred in settings.preferred_locations
        )
    ):
        return False
    if settings.min_salary is not None:
        salary = (
            listing.salary_max
            if listing.salary_max is not None
            else listing.salary_min
        )
        if salary is not None and salary < settings.min_salary:
            return False
    return True
```

  - [ ] Update `select_top_matches` to apply it:

```python
def select_top_matches(
    matches: list[MatchResult], settings: Settings
) -> list[MatchResult]:
    qualifying = [
        match
        for match in matches
        if match.score >= settings.min_match_score
        and passes_preferences(match.listing, settings)
    ]
    qualifying.sort(key=lambda m: m.score, reverse=True)
    return qualifying[: settings.briefing_max_matches]
```

  - [ ] Delete the now-unused `scout/sub_agents/scorer/tools.py` (empty) and
        confirm `scout/sub_agents/scorer/` still holds only `runner.py`,
        `results.py` and `__init__.py`
  - [ ] Change `run_briefing`'s signature to
        `run_briefing(matches: list[MatchResult], settings, report_path)` and
        delete its internal `join_match_results` call; update
        `scout/agent.py` to pass the `matches` it already computed
  - [ ] Verify (`pytest tests/test_briefing_select.py tests/test_briefing_filters.py tests/test_briefing_agent.py -v`)
  - [ ] Commit: `feat(briefing): apply preference filters at selection`

### Task 8: Drop the agent-framework dependency

- **Files:** `requirements.txt`, `docs/project/architecture-pipeline-overview.md`
- **Gate:** none
- **Steps:**
  - [ ] Confirm nothing imports the framework:
        `grep -rn "google.adk\|google_adk\|google.genai" scout/ tests/`
        — expect no matches
  - [ ] Remove `google-adk==2.4.0`, `google-genai==2.11.0` and
        `google-auth==2.56.0` from `requirements.txt`. Leave
        `litellm==1.83.7` (now a direct dependency) and `mcp==1.28.1`
        (the scraper's transport) in place.
  - [ ] Rebuild to confirm the pruned set still installs and imports:
        `docker compose build app && docker compose run --rm app python -c "import scout.agent"`
  - [ ] Update `docs/project/architecture-pipeline-overview.md` to describe
        the local event shell and shared batching in place of ADK
  - [ ] Verify (`pytest -q`)
  - [ ] Commit: `chore: drop google-adk dependency`

### Task 9: Spike — prefix-cache ordering

- **Files:** `scripts/spike_prefix_cache.py` (throwaway)
- **Gate:** none. **Adopt only if measurement shows a real reduction.**
- **Steps:**
  - [ ] Write a script that sends the same listings payload twice: once with
        the listings JSON *last* (today's prompt shape), once with it *first*
        so both prompts share a byte-identical prefix
  - [ ] Read `response.usage` on each call and record any
        cached/prompt-token split the provider reports
  - [ ] Run: `python scripts/spike_prefix_cache.py`
  - [ ] Record the measured difference in Notes / Learnings
  - [ ] If the reduction is real, open a follow-up task to reorder both
        prompt builders so the listings block leads; if not, record that and
        stop — do **not** reorder the prompts speculatively
  - [ ] Commit: `spike: measure prefix-cache effect of prompt ordering`

---

## Verification

- [ ] All phase tests pass: `pytest -q`
- [ ] No framework imports remain:
      `grep -rn "google.adk\|google.genai" scout/ tests/` returns nothing
- [ ] Extraction is still profile-blind:
      `pytest tests/test_prompts.py -k never_includes_the_profile -v` passes
- [ ] Manual: `docker compose run --rm app` completes, and the log shows
      both stages issuing `ceil(N / <stage batch size>)` calls
- [ ] Manual: with `REMOTE_ONLY=true` set, an on-site listing appears on the
      rendered dashboard with a score, and is absent from the Discord brief

## Observability

- `scout.shared.batching` logs `<label> batch attempt N failed, retrying` at
  INFO and `<label> batch failed after N attempt(s), skipping M item(s)` at
  WARNING, with `label` distinguishing `scorer` from `requirements` — so it
  is clear whether a shortfall cost scores or only gaps.
- The pipeline keeps its existing `Scorer: N scored` and
  `Warning: N scored listing(s) had no extracted requirements` events.

## Rollback

`git revert` the phase's commits in reverse order and restore
`google-adk==2.4.0`, `google-genai==2.11.0`, `google-auth==2.56.0` to
`requirements.txt`, then `docker compose build app`. No stored data is
written differently by this phase — scores recorded under the
preference-neutral prompt remain valid rows.

---

## Notes / Learnings

<Filled in during execution — record the Task 1 finding on whether DeepSeek
fences its JSON, and the Task 9 prefix-cache measurement.>
