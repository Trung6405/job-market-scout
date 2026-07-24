# Phase 1: Model Layer & Brief-Time Filtering

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** nothing

---

## Goal

Replace `google-adk` with a small project-local JSON-completion helper,
merge scoring and requirements extraction into one Analyst stage that runs
over every new-or-changed listing, and move preference filtering to brief
selection. We'll know it worked when a full run makes one model call per
batch, the dashboard contains preference-failing listings, and the brief
does not.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — `complete_json` is the only outbound model call. The API key comes
  from `settings.deepseek_api_key` and is never logged; Task 4's helper
  raises on empty content, and Task 6 bounds concurrency and absorbs a
  single per-batch failure.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  Yes — **Task 5** changes the scoring rubric by removing the preference
  inputs, which changes the meaning of every score stored afterwards. It is
  gated on human sign-off and on review of Task 1's spike output.

---

## Tasks

### Task 1: Spike — score-quality comparison harness

- **Files:** `scripts/spike_score_comparison.py` (throwaway, not committed to `scout/`)
- **Gate:** none to run — but its **output must be reviewed by the human
  before Task 5 executes**.
- **Steps:**
  - [ ] Write a script that loads 20 real listings from the dev database
        (`SELECT ... FROM listings ORDER BY scraped_at DESC LIMIT 20`)
  - [ ] Score them via the current path: `run_scorer(listings, settings)`
  - [ ] Score them via a draft merged prompt built inline in the script
  - [ ] Print a per-listing table: `external_id | old_score | new_score | delta`
        plus mean absolute delta
  - [ ] Run: `python scripts/spike_score_comparison.py`
  - [ ] Record the mean absolute delta in this doc's Notes / Learnings
  - [ ] Commit: `spike: compare merged-prompt scores against two-call baseline`

> Decision rule: a mean absolute delta above 10 points means the merged
> prompt is not a drop-in — stop and revise the prompt before Task 5.

### Task 2: Spike — verify direct litellm JSON mode

- **Files:** `scripts/spike_litellm_json.py` (throwaway)
- **Gate:** none
- **Steps:**
  - [ ] Write a script calling `litellm.acompletion` directly with
        `model=settings.deepseek_model`, `response_format={"type": "json_object"}`,
        and a trivial prompt asking for `{"ok": true}`
  - [ ] Run: `python scripts/spike_litellm_json.py`
  - [ ] Confirm the response parses as JSON without fence-stripping
  - [ ] Record in Notes / Learnings whether `strip_code_fence` is still
        needed defensively (it is retained either way)
  - [ ] Commit: `spike: verify litellm json_object mode against deepseek`

### Task 3: Shared test factories and the project-local event type

- **Files:** `tests/conftest.py`, `scout/shared/events.py`,
  `tests/test_shared_events.py`, `tests/test_agent.py`
- **Gate:** none
- **Steps:**
  - [ ] Add shared factories to `tests/conftest.py` — Tasks 5, 6 and 8 all
        build `Listing` and `MatchResult` objects, and building them inline
        each time invites drift:

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
from scout.shared.events import PipelineEvent


def test_pipeline_event_carries_author_and_text():
    event = PipelineEvent(author="scout", text="Scraper: 3 listing(s) found")
    assert event.author == "scout"
    assert event.text == "Scraper: 3 listing(s) found"


def test_pipeline_event_is_frozen():
    import dataclasses
    import pytest

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
        `google.genai` / `google.adk` imports from that file. Leave the
        pipeline itself untouched — it still yields ADK events until Task 7,
        so **this file's tests will fail until then**; mark the migrated
        assertions with `@pytest.mark.xfail(reason="pipeline rewired in Task 7", strict=False)`
  - [ ] Verify the rest of the suite is unaffected (`pytest -q`)
  - [ ] Commit: `feat(shared): add PipelineEvent and shared test factories`

### Task 4: JSON completion helper

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

### Task 5: Merged analysis schema and prompt

- **Files:** `scout/shared/schemas.py`, `scout/prompts.py`,
  `tests/test_schemas.py`, `tests/test_prompts.py`
- **Gate:** ⚠️ **Human sign-off required before this task.** It removes the
  preference inputs from the scoring prompt, changing the meaning of every
  score stored afterwards. Task 1's spike output must be reviewed first.
- **Steps:**
  - [ ] Write failing test in `tests/test_schemas.py`:

```python
def test_listing_analysis_carries_score_and_requirements():
    from scout.shared.schemas import ListingAnalysis

    analysis = ListingAnalysis.model_validate(
        {
            "source": "indeed",
            "external_id": "abc",
            "score": 72,
            "reasoning": "Solid backend overlap.",
            "must_have": [{"name": "Python", "kind": "skill"}],
            "nice_to_have": [{"name": "Docker", "kind": "skill"}],
            "seniority": "Graduate / Entry",
            "work_type": None,
            "team": None,
        }
    )
    assert analysis.score == 72
    assert analysis.must_have[0].name == "Python"
    assert analysis.seniority == "Graduate / Entry"


def test_listing_analysis_rejects_out_of_range_score():
    import pytest
    from pydantic import ValidationError

    from scout.shared.schemas import ListingAnalysis

    with pytest.raises(ValidationError):
        ListingAnalysis.model_validate(
            {
                "source": "indeed",
                "external_id": "abc",
                "score": 101,
                "reasoning": "x",
                "must_have": [],
                "nice_to_have": [],
            }
        )
```

  - [ ] Write failing test in `tests/test_prompts.py`:

```python
def test_analysis_instruction_omits_preferences(listing_factory):
    from scout.config import Settings
    from scout.prompts import build_analysis_instruction

    settings = Settings()
    instruction = build_analysis_instruction(settings, [listing_factory()])
    assert "Preferred locations" not in instruction
    assert "Remote only" not in instruction
    assert "Minimum salary" not in instruction


def test_analysis_instruction_asks_for_score_and_requirements(listing_factory):
    from scout.config import Settings
    from scout.prompts import build_analysis_instruction

    instruction = build_analysis_instruction(Settings(), [listing_factory()])
    assert '"analyses"' in instruction
    assert '"score"' in instruction
    assert '"must_have"' in instruction
    assert '"nice_to_have"' in instruction
```

  - [ ] Verify both fail (`pytest tests/test_schemas.py tests/test_prompts.py -v`)
  - [ ] Add to `scout/shared/schemas.py`, replacing `ListingScore`,
        `ListingScoreBatch`, `ListingRequirements` and
        `ListingRequirementsBatch`:

```python
class ListingAnalysis(BaseModel):
    """One listing's complete model reading: fit plus stated requirements.

    Replaces the separate ``ListingScore`` and ``ListingRequirements``.
    Because both now come from a single call, a listing's score and its
    requirements can no longer reflect two different readings of the text.
    """

    source: str
    external_id: str
    score: int = Field(ge=0, le=100)
    reasoning: str
    must_have: list[RequirementItem]
    nice_to_have: list[RequirementItem]
    seniority: str | None = None
    work_type: str | None = None
    team: str | None = None


class ListingAnalysisBatch(BaseModel):
    analyses: list[ListingAnalysis]
```

  - [ ] Replace `build_scorer_instruction` and
        `build_requirements_instruction` in `scout/prompts.py` with a single
        `build_analysis_instruction(settings, listings)`. Carry the scoring
        rubric text and the extraction rules across **verbatim** from the two
        existing prompts, with exactly two changes: delete the three
        preference lines (`Preferred locations:` / `Remote only:` /
        `Minimum salary:`), and replace the two closing "Return a JSON
        object..." paragraphs with one asking for a single `"analyses"` key
        whose objects carry `source`, `external_id`, `score`, `reasoning`,
        `must_have`, `nice_to_have`, `seniority`, `work_type`, `team`.
  - [ ] Update `scout/shared/db.py`, which imports `ListingRequirements` for
        `record_listing_meta`'s annotation — deleting the class breaks that
        import immediately, so it must change in this task, not later:
        swap the import to `ListingAnalysis` and retype the parameter to
        `meta_by_match: list[tuple[MatchResult, ListingAnalysis]]`. The
        attributes it reads (`seniority`, `work_type`, `team`) are unchanged.
  - [ ] Confirm nothing else references the deleted names:
        `grep -rn "ListingScore\|ListingRequirements" scout/ tests/` — expect
        matches only in files Task 6 deletes
  - [ ] Verify both pass (`pytest tests/test_schemas.py tests/test_prompts.py -v`)
  - [ ] Commit: `feat(analyst): merge scoring and extraction into one prompt`

### Task 6: Analyst stage with batching and per-batch tolerance

- **Files:** `scout/sub_agents/analyst/__init__.py`,
  `scout/sub_agents/analyst/runner.py`,
  `scout/sub_agents/analyst/results.py`, `scout/config.py`,
  `tests/test_analyst_runner.py`, `tests/test_analyst_results.py`
- **Gate:** none
- **Steps:**
  - [ ] Add to `scout/config.py`, replacing `requirements_batch_size`:

```python
    # Listings per analysis LLM call. One response must hold every listing's
    # score AND requirements, and the model caps output tokens, so a large
    # batch truncates the JSON mid-value and fails to parse. Lower than the
    # old requirements-only default because each listing now costs more output.
    analysis_batch_size: int = field(
        default_factory=partial(_env_int, "ANALYSIS_BATCH_SIZE", 10)
    )
    # Concurrent analysis calls in flight. Bounded so a large day doesn't
    # trip provider rate limits; lower it if 429s appear.
    analysis_concurrency: int = field(
        default_factory=partial(_env_int, "ANALYSIS_CONCURRENCY", 3)
    )
```

  - [ ] Write failing test in `tests/test_analyst_runner.py`:

```python
from __future__ import annotations

from scout.config import Settings
from scout.shared.schemas import ListingAnalysis, ListingAnalysisBatch
from scout.sub_agents.analyst import runner


def _analysis(external_id: str) -> ListingAnalysis:
    return ListingAnalysis(
        source="indeed",
        external_id=external_id,
        score=70,
        reasoning="ok",
        must_have=[],
        nice_to_have=[],
    )


async def test_run_analysis_batches_by_size(monkeypatch, listing_factory):
    listings = [listing_factory(external_id=str(i)) for i in range(5)]
    calls: list[int] = []

    async def _fake_complete_json(prompt, schema, settings, **kwargs):
        count = prompt.count('"external_id"')
        calls.append(count)
        return ListingAnalysisBatch(analyses=[_analysis("0")])

    monkeypatch.setattr(runner, "complete_json", _fake_complete_json)
    settings = Settings()
    object.__setattr__(settings, "analysis_batch_size", 2)
    await runner.run_analysis(listings, settings)
    assert len(calls) == 3  # 2 + 2 + 1


async def test_run_analysis_retries_once_then_skips_bad_batch(
    monkeypatch, listing_factory, caplog
):
    attempts = {"n": 0}

    async def _always_fails(prompt, schema, settings, **kwargs):
        attempts["n"] += 1
        raise ValueError("truncated JSON")

    monkeypatch.setattr(runner, "complete_json", _always_fails)
    settings = Settings()
    object.__setattr__(settings, "analysis_batch_size", 10)
    result = await runner.run_analysis([listing_factory()], settings)
    assert result == []
    assert attempts["n"] == 2  # one retry, then give up
    assert "analysis batch failed" in caplog.text


async def test_run_analysis_keeps_good_batches_when_one_fails(
    monkeypatch, listing_factory
):
    seen = {"n": 0}

    async def _fail_first_batch(prompt, schema, settings, **kwargs):
        seen["n"] += 1
        if seen["n"] <= 2:  # first batch: initial attempt + retry
            raise ValueError("truncated JSON")
        return ListingAnalysisBatch(analyses=[_analysis("survivor")])

    monkeypatch.setattr(runner, "complete_json", _fail_first_batch)
    settings = Settings()
    object.__setattr__(settings, "analysis_batch_size", 1)
    object.__setattr__(settings, "analysis_concurrency", 1)
    listings = [listing_factory(external_id="a"), listing_factory(external_id="b")]
    result = await runner.run_analysis(listings, settings)
    assert [a.external_id for a in result] == ["survivor"]


async def test_run_analysis_returns_empty_for_no_listings(monkeypatch):
    async def _should_not_be_called(*args, **kwargs):
        raise AssertionError("no call expected for an empty listing set")

    monkeypatch.setattr(runner, "complete_json", _should_not_be_called)
    assert await runner.run_analysis([], Settings()) == []
```

  - [ ] Verify it fails (`pytest tests/test_analyst_runner.py -v`)
  - [ ] Implement `scout/sub_agents/analyst/runner.py`:

```python
from __future__ import annotations

import asyncio
import logging

from scout.config import Settings
from scout.config import settings as default_settings
from scout.prompts import build_analysis_instruction
from scout.shared.llm import complete_json
from scout.shared.schemas import Listing, ListingAnalysis, ListingAnalysisBatch

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 2


def _batches(listings: list[Listing], batch_size: int) -> list[list[Listing]]:
    size = max(1, batch_size)
    return [listings[i : i + size] for i in range(0, len(listings), size)]


async def _analyse_batch(
    batch: list[Listing], settings: Settings, semaphore: asyncio.Semaphore
) -> list[ListingAnalysis]:
    """Analyse one batch, retrying once before giving up on it.

    A batch that still fails is skipped rather than raised: one truncated
    or malformed response should cost that batch's listings, not the day.
    """
    async with semaphore:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                result = await complete_json(
                    build_analysis_instruction(settings, batch),
                    ListingAnalysisBatch,
                    settings,
                )
                return result.analyses
            except Exception as exc:
                if attempt == _MAX_ATTEMPTS:
                    logger.warning(
                        "analysis batch failed after %d attempt(s), skipping "
                        "%d listing(s): %s",
                        attempt,
                        len(batch),
                        exc,
                    )
                    return []
                logger.info("analysis batch attempt %d failed, retrying: %s", attempt, exc)
        return []


async def run_analysis(
    listings: list[Listing], settings: Settings | None = None
) -> list[ListingAnalysis]:
    """Score and extract requirements for every listing, batched.

    One response must hold every listing in its batch, and the model caps
    output tokens, so batches are kept small enough to parse. Batches run
    concurrently under a bounded semaphore.
    """
    active_settings = settings or default_settings
    if not listings:
        return []
    semaphore = asyncio.Semaphore(max(1, active_settings.analysis_concurrency))
    results = await asyncio.gather(
        *(
            _analyse_batch(batch, active_settings, semaphore)
            for batch in _batches(listings, active_settings.analysis_batch_size)
        )
    )
    return [analysis for batch_result in results for analysis in batch_result]
```

  - [ ] Verify it passes (`pytest tests/test_analyst_runner.py -v`)
  - [ ] Write failing test in `tests/test_analyst_results.py`:

```python
from scout.shared.schemas import ListingAnalysis
from scout.sub_agents.analyst.results import join_analyses


def _analysis(external_id: str, score: int = 70) -> ListingAnalysis:
    return ListingAnalysis(
        source="indeed",
        external_id=external_id,
        score=score,
        reasoning="ok",
        must_have=[],
        nice_to_have=[],
    )


def test_join_analyses_pairs_match_with_analysis(listing_factory):
    listing = listing_factory(external_id="a")
    pairs = join_analyses([listing], [_analysis("a", 88)])
    assert len(pairs) == 1
    match, analysis = pairs[0]
    assert match.listing.external_id == "a"
    assert match.score == 88
    assert analysis.external_id == "a"


def test_join_analyses_drops_unknown_listings(listing_factory):
    pairs = join_analyses([listing_factory(external_id="a")], [_analysis("ghost")])
    assert pairs == []
```

  - [ ] Verify it fails (`pytest tests/test_analyst_results.py -v`)
  - [ ] Implement `scout/sub_agents/analyst/results.py`:

```python
from __future__ import annotations

from scout.shared.schemas import Listing, ListingAnalysis, MatchResult


def join_analyses(
    listings: list[Listing], analyses: list[ListingAnalysis]
) -> list[tuple[MatchResult, ListingAnalysis]]:
    """Pair each analysis with its listing, dropping analyses we can't place.

    Replaces the old ``join_match_results`` plus the separate
    requirements-by-key lookup in the pipeline: because score and
    requirements now arrive together, one join covers both.
    """
    listings_by_key = {
        (listing.source, listing.external_id): listing for listing in listings
    }
    pairs: list[tuple[MatchResult, ListingAnalysis]] = []
    for analysis in analyses:
        listing = listings_by_key.get((analysis.source, analysis.external_id))
        if listing is None:
            continue
        pairs.append(
            (
                MatchResult(
                    listing=listing,
                    score=analysis.score,
                    reasoning=analysis.reasoning,
                ),
                analysis,
            )
        )
    return pairs
```

  - [ ] Verify it passes (`pytest tests/test_analyst_results.py -v`)
  - [ ] Delete `scout/sub_agents/scorer/` and
        `scout/sub_agents/advisor/{agent.py,runner.py}`, and delete
        `tests/test_scorer_agent.py`, `tests/test_scorer_runner.py`,
        `tests/test_scorer_results.py`, `tests/test_advisor_requirements.py`
  - [ ] Verify (`pytest -q`) — only `tests/test_agent.py` xfails remain
  - [ ] Commit: `feat(analyst): add batched analysis stage, retire scorer package`

### Task 7: Rewire the pipeline onto the local shell

- **Files:** `scout/agent.py`, `scout/main.py`, `scout/shared/adk_runner.py`
  (delete), `tests/test_agent.py`, `tests/test_main_entrypoint.py`
- **Gate:** none
- **Steps:**
  - [ ] Remove the `xfail` marks added in Task 3 from `tests/test_agent.py`
  - [ ] Verify they fail (`pytest tests/test_agent.py -v`)
  - [ ] Rewrite `scout/agent.py`: keep the class name `ScoutPipelineAgent`
        and its `name = "scout"` attribute, but drop `BaseAgent`,
        `InvocationContext`, `Event` and `genai_types`. Rename
        `_run_async_impl(self, ctx)` to `run(self)` returning
        `AsyncGenerator[PipelineEvent, None]`, and replace `_status_event`
        with `PipelineEvent(author=self.name, text=...)`. Replace the
        scorer + requirements block with:

```python
            analyses = await run_analysis(relevant, settings)
            pairs = join_analyses(relevant, analyses)
            yield PipelineEvent(self.name, f"Analyst: {len(pairs)} analysed")

            dropped = len(relevant) - len(pairs)
            if dropped:
                yield PipelineEvent(
                    self.name,
                    f"Warning: {dropped} listing(s) returned no analysis — "
                    "skipped for scoring, gaps and meta.",
                )

            matches = [match for match, _analysis in pairs]
            banded_matches = [
                (match, classify_band(match.score, settings)) for match in matches
            ]
            profile = load_profile(settings.profile_path)
            checks_by_match = [
                (match, evaluate_requirements(analysis, profile))
                for match, analysis in pairs
            ]
```

  - [ ] Update `record_listing_meta`'s call site to pass `pairs` — its
        annotation was already retyped to
        `list[tuple[MatchResult, ListingAnalysis]]` in Task 5
  - [ ] Update `evaluate_requirements` in `scout/sub_agents/advisor/gaps.py`
        to accept a `ListingAnalysis` instead of a `ListingRequirements` —
        the attributes it reads (`must_have`, `nice_to_have`) are unchanged,
        so only the type annotation and its docstring move
  - [ ] Update `scout/main.py` to drop `InMemoryRunner` and `genai_types`:

```python
async def run_once() -> None:
    agent = ScoutPipelineAgent()
    async for event in agent.run():
        logger.info(event.text)
```

  - [ ] Delete `scout/shared/adk_runner.py` and `tests/` references to it
  - [ ] Verify they pass (`pytest tests/test_agent.py tests/test_main_entrypoint.py -v`)
  - [ ] Commit: `refactor(pipeline): run on project-local event shell`

### Task 8: Preference filtering at brief selection

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
        updating imports in both. Refactor the module to expose a single
        predicate, keeping the existing rules byte-for-byte:

```python
def passes_preferences(listing: Listing, settings: Settings) -> bool:
    """Whether a listing matches the student's stated preferences.

    Applied at brief selection, deliberately *not* before analysis: every
    listing is analysed so the dashboard shows the day's full market, and
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

  - [ ] Change `run_briefing`'s signature to
        `run_briefing(matches: list[MatchResult], settings, report_path)` and
        delete its internal `join_match_results` call; update `scout/agent.py`
        to pass the `matches` it already computed
  - [ ] Verify they pass (`pytest tests/test_briefing_select.py tests/test_briefing_filters.py tests/test_briefing_agent.py -v`)
  - [ ] Commit: `feat(briefing): apply preference filters at selection`

### Task 9: Drop the agent-framework dependency

- **Files:** `requirements.txt`, `Dockerfile`, `docs/project/architecture-pipeline-overview.md`
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
        the Analyst stage and the local event shell in place of ADK
  - [ ] Verify (`pytest -q`)
  - [ ] Commit: `chore: drop google-adk dependency`

---

## Verification

- [ ] All phase tests pass: `pytest -q`
- [ ] No framework imports remain:
      `grep -rn "google.adk\|google.genai" scout/ tests/` returns nothing
- [ ] Manual: `docker compose run --rm app` completes, and the log shows
      `Analyst: N analysed` with one batch line per
      `ceil(N / ANALYSIS_BATCH_SIZE)`
- [ ] Manual: with `REMOTE_ONLY=true` set, an on-site listing appears on the
      rendered dashboard with a score, and is absent from the Discord brief

## Observability

- `scout.sub_agents.analyst.runner` logs `analysis batch attempt N failed,
  retrying` at INFO and `analysis batch failed after N attempt(s), skipping
  M listing(s)` at WARNING — the latter is the signal that a day's numbers
  are short.
- The pipeline emits `Analyst: N analysed` and, when the model omits
  listings, `Warning: N listing(s) returned no analysis`.

## Rollback

`git revert` the phase's commits in reverse order and restore
`google-adk==2.4.0`, `google-genai==2.11.0`, `google-auth==2.56.0` to
`requirements.txt`, then `docker compose build app`. No stored data is
written differently by this phase — scores recorded under the merged prompt
remain valid rows.

---

## Notes / Learnings

<Filled in during execution — record the Task 1 spike's mean absolute score
delta and the Task 2 finding on whether DeepSeek fences its JSON.>
