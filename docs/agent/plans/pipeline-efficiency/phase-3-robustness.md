# Phase 3: Robustness & Cleanup

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** Phase 1 complete (Task 4 removes `has_profile`, which
> Phase 1 leaves in place). Phase 2 is independent of this phase.

---

## Goal

Stop a single malformed listing from killing a run, make the history page
cost two queries instead of sixty, and remove the dead weight review turned
up. We'll know it worked when a run survives a job missing its `id`, and
`render_history` no longer fetches listing descriptions.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — Task 1 hardens the boundary where scraped third-party data enters
  the system. That is the point of the task.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No.

---

## Tasks

### Task 1: Tolerant scraper normalisation

- **Files:** `scout/sub_agents/scraper/normalize.py`,
  `scout/sub_agents/scraper/runner.py`, `tests/test_scraper_normalize.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test in `tests/test_scraper_normalize.py`:

```python
from datetime import datetime, timezone

from scout.sub_agents.scraper.normalize import normalize_job

_SCRAPED_AT = datetime(2026, 7, 24, tzinfo=timezone.utc)


def _job(**overrides) -> dict:
    return {
        "site": "indeed",
        "id": "abc123",
        "title": "Backend Engineer",
        "company": "Acme Corp",
        "jobUrl": "https://example.com/job/1",
        "location": "Melbourne VIC",
        "isRemote": False,
        "description": "Python.",
        **overrides,
    }


def test_normalize_job_skips_missing_site():
    assert normalize_job(_job(site=None), _SCRAPED_AT) is None


def test_normalize_job_skips_missing_id():
    assert normalize_job(_job(id=None), _SCRAPED_AT) is None


def test_normalize_job_skips_unparseable_url():
    assert normalize_job(_job(jobUrl="not-a-url"), _SCRAPED_AT) is None


def test_normalize_job_still_accepts_a_valid_job():
    listing = normalize_job(_job(), _SCRAPED_AT)
    assert listing is not None
    assert listing.source == "indeed"
    assert listing.external_id == "abc123"
```

  - [ ] Verify it fails (`pytest tests/test_scraper_normalize.py -v`) —
        expect `ValidationError` rather than `None` on the first three
  - [ ] Rewrite `normalize_job`:

```python
def normalize_job(job: dict, scraped_at: datetime) -> Listing | None:
    """Convert one scraped job into a Listing, or None if it isn't usable.

    ``site`` and ``id`` are guarded alongside the display fields because
    together they are the primary key every later stage joins on. The
    blanket ``ValidationError`` catch is deliberate: a single malformed job
    out of a hundred should cost that job, not the whole scrape.
    """
    title = job.get("title")
    company = job.get("company")
    url = job.get("jobUrl")
    source = job.get("site")
    external_id = job.get("id")
    if not title or not company or not url or not source or not external_id:
        logger.warning(
            "skipping job with missing required field(s): "
            "site=%r id=%r title=%r company=%r url=%r",
            source,
            external_id,
            title,
            company,
            url,
        )
        return None

    try:
        return Listing(
            source=source,
            external_id=external_id,
            title=title,
            company=company,
            location=job.get("location") or "",
            is_remote=bool(job.get("isRemote")),
            url=url,
            description=job.get("description") or "",
            salary_min=job.get("minAmount"),
            salary_max=job.get("maxAmount"),
            date_posted=job.get("datePosted"),
            scraped_at=scraped_at,
        )
    except ValidationError as exc:
        logger.warning("skipping job %s/%s: %s", source, external_id, exc)
        return None
```

  - [ ] Add the imports the new body needs to
        `scout/sub_agents/scraper/normalize.py`:

```python
import logging

from pydantic import ValidationError

logger = logging.getLogger(__name__)
```

  - [ ] Add a skipped-count log to `run_scraper` in
        `scout/sub_agents/scraper/runner.py`, so silent drops are visible:
        track how many `normalize_job` calls returned `None` and include it
        in the existing "Finished scrape" log line
  - [ ] Verify it passes (`pytest tests/test_scraper_normalize.py tests/test_scraper_runner.py -v`)
  - [ ] Commit: `fix(scraper): skip malformed jobs instead of failing the run`

### Task 2: Aggregate query for the history page

- **Files:** `scout/shared/db.py`, `scout/sub_agents/advisor/report.py`,
  `scout/agent.py`, `tests/test_db.py`, `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test in `tests/test_db.py`:

```python
async def test_get_run_summaries_returns_band_counts(
    db_pool, listing_factory, match_factory
):
    from datetime import date

    from scout.shared.db import (
        get_run_summaries,
        record_run_listings,
        start_run,
        upsert_listing,
    )

    async with db_pool.acquire() as conn:
        strong = listing_factory(external_id="strong")
        reach = listing_factory(external_id="reach")
        for listing in (strong, reach):
            await upsert_listing(conn, listing)
        run_id = await start_run(conn, date(2026, 7, 24))
        await record_run_listings(
            conn,
            run_id,
            [
                (match_factory(listing=strong, score=90), "strong_match"),
                (match_factory(listing=reach, score=30), "reach"),
            ],
        )

        summaries = await get_run_summaries(conn, limit=30)
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.run.id == run_id
        assert summary.stats["scored"] == 2
        assert summary.stats["strong"] == 1
        assert summary.stats["reach"] == 1
        assert summary.stats["avg_score"] == 60
```

  - [ ] Verify it fails (`pytest tests/test_db.py -k run_summaries -v`)
  - [ ] Add a `RunSummary` model to `scout/shared/schemas.py`:

```python
class RunSummary(BaseModel):
    """A run plus its aggregate counts, without any listing rows.

    The history page needs band counts and an average, not descriptions.
    Fetching full details per run meant loading every stored description
    for the last thirty runs to render a table of numbers.
    """

    run: Run
    stats: dict[str, int]
```

  - [ ] Implement `get_run_summaries` in `scout/shared/db.py`:

```python
async def get_run_summaries(
    conn: asyncpg.Connection, limit: int
) -> list[RunSummary]:
    """Per-run aggregates for the history page, in two queries total."""
    runs = await list_runs(conn, limit)
    if not runs:
        return []
    rows = await conn.fetch(
        """
        SELECT run_listings.run_id,
               count(*) AS scored,
               count(*) FILTER (WHERE run_listings.band = 'strong_match') AS strong,
               count(*) FILTER (WHERE run_listings.band = 'competitive') AS competitive,
               count(*) FILTER (WHERE run_listings.band = 'reach') AS reach,
               coalesce(round(avg(run_listings.score)), 0) AS avg_score,
               count(listing_gaps.id) FILTER (
                   WHERE listing_gaps.kind = 'skill' AND NOT listing_gaps.met
               ) AS gaps
        FROM run_listings
        LEFT JOIN listing_gaps ON listing_gaps.run_listing_id = run_listings.id
        WHERE run_listings.run_id = ANY($1::bigint[])
        GROUP BY run_listings.run_id
        """,
        [run.id for run in runs],
    )
    stats_by_run = {row["run_id"]: dict(row) for row in rows}
    summaries: list[RunSummary] = []
    for run in runs:
        row = stats_by_run.get(run.id, {})
        summaries.append(
            RunSummary(
                run=run,
                stats={
                    "scored": int(row.get("scored", 0)),
                    "strong": int(row.get("strong", 0)),
                    "competitive": int(row.get("competitive", 0)),
                    "reach": int(row.get("reach", 0)),
                    "avg_score": int(row.get("avg_score", 0)),
                    "gaps": int(row.get("gaps", 0)),
                },
            )
        )
    return summaries
```

  - [ ] Verify it passes (`pytest tests/test_db.py -k run_summaries -v`)
  - [ ] Rewrite `render_history` in `scout/sub_agents/advisor/report.py` to
        call `get_run_summaries(conn, limit)` and build its `days` list from
        the summaries — `{"run": summary.run, "details": [], "stats": summary.stats}`.
        Check `templates/history.html.jinja` for any use of `day.details`; if
        it only reads `day.stats` and `day.run`, drop the `details` key
        entirely rather than passing an empty list.
  - [ ] Move both `render_history` calls in `scout/agent.py` **outside** the
        `async with conn.transaction()` block — the history page reads only
        committed aggregate counts and does not need the run's transaction
  - [ ] Verify it passes (`pytest tests/test_advisor_report.py tests/test_agent.py -v`)
  - [ ] Commit: `perf(report): render history from aggregate counts`

### Task 3: Non-optional get_run

- **Files:** `scout/shared/db.py`, `tests/test_db.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test in `tests/test_db.py`:

```python
async def test_get_run_raises_for_unknown_id(db_pool):
    import pytest

    from scout.shared.db import get_run

    async with db_pool.acquire() as conn:
        with pytest.raises(LookupError, match="no run with id"):
            await get_run(conn, 999_999)
```

  - [ ] Verify it fails (`pytest tests/test_db.py -k get_run_raises -v`) —
        expect `None` returned rather than a raise
  - [ ] Change `get_run` in `scout/shared/db.py`:

```python
async def get_run(conn: asyncpg.Connection, run_id: int) -> Run:
    """Fetch a run by id.

    Non-optional on purpose: every caller dereferences the result
    immediately, so an Optional return only moved the failure to a less
    informative ``AttributeError`` further down.
    """
    row = await conn.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)
    if row is None:
        raise LookupError(f"no run with id {run_id}")
    return Run(**dict(row))
```

  - [ ] Verify it passes (`pytest tests/test_db.py -k get_run -v`)
  - [ ] Commit: `refactor(db): make get_run non-optional`

### Task 4: Remove dead weight

- **Files:** `scout/sub_agents/briefing/tools.py` (delete),
  `scout/sub_agents/advisor/report.py`, `scout/rerender.py`,
  `scout/agent.py`, `scout/sub_agents/advisor/templates/*.jinja`,
  `Dockerfile`, `docker-compose.yaml`, `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [ ] Delete `scout/sub_agents/briefing/tools.py` — it is an empty file
        left from the ADK layout. (`scout/sub_agents/scorer/tools.py` was
        already removed in Phase 1 Task 7; the `scorer` package itself
        survives, now holding only `runner.py`, `results.py` and
        `__init__.py`.)
  - [ ] Remove the `has_profile` parameter from `render_run` and
        `render_history` in `scout/sub_agents/advisor/report.py`, and the
        corresponding `{% if has_profile %}` guards in
        `templates/dashboard.html.jinja`, `templates/history.html.jinja` and
        `templates/job-detail.html.jinja` — the profile page is always
        rendered, because `scout/config.py` loads `profile.json` at import
        and raises if it is missing, so `has_profile=False` is unreachable
  - [ ] Update the three call sites in `scout/agent.py` and the four in
        `scout/rerender.py` (including its now-redundant
        `Path(settings.profile_path).is_file()` check, which can never be
        `False` for the same reason)
  - [ ] Update `tests/test_advisor_report.py` — drop the `has_profile`
        arguments and the two tests asserting the `has_profile=False`
        navigation behaviour
  - [ ] Remove `EXPOSE 8000` from `Dockerfile` and the `ports: - "8000:8000"`
        mapping from the `app` service in `docker-compose.yaml` — the app is
        a batch job (`CMD ["python", "-m", "scout.main"]`) and binds nothing
  - [ ] Verify (`pytest -q`)
  - [ ] Manual: `docker compose run --rm app python -m scout.rerender` still
        regenerates the dashboard, history and profile pages
  - [ ] Commit: `chore: remove dead weight found in pipeline review`

### Task 5: Record the kept test probes

- **Files:** `scout/shared/db.py`
- **Gate:** none
- **Steps:**
  - [ ] Add a docstring to each of `get_run_by_date` and `get_run_listings`
        in `scout/shared/db.py` recording why they exist, so a future
        cleanup does not read them as dead code:

```python
async def get_run_by_date(conn: asyncpg.Connection, run_date: date) -> Run | None:
    """Fetch a run by date. Used only by tests.

    No production caller: the pipeline holds the run id from ``start_run``.
    Kept as an assertion probe for ``tests/test_agent.py`` and
    ``tests/test_db.py`` — not dead code, do not remove.
    """
```

  - [ ] Verify (`pytest -q`)
  - [ ] Commit: `docs(db): note the test-only run accessors`

---

## Verification

- [x] All phase tests pass: `pytest -q` — 241 passed
- [x] No empty modules remain:
      `find scout -name "*.py" -empty -not -name "__init__.py"` returns nothing
- [x] Manual: `docker compose run --rm app` completes and the scrape log
      line reports any skipped malformed jobs — 2026-07-24 run logged
      `Finished scrape: 79 unique listing(s) after dedup (from 80 raw, 0
      skipped)`
- [x] Manual: `docker compose run --rm app python -m scout.rerender`
      regenerates every page without error — regenerated all 3 stored runs
      plus history and profile pages against the live dev DB

## Observability

- `scout.sub_agents.scraper.normalize` logs `skipping job with missing
  required field(s)` and `skipping job <source>/<id>` at WARNING — a sudden
  run of these means the upstream scraper's payload shape changed.
- `run_scraper`'s "Finished scrape" line gains a skipped count, so drops are
  visible without grepping for warnings.

## Rollback

`git revert` the phase's commits. No stored data changes in this phase, and
`schema.sql` is untouched, so a revert is clean. The only cross-phase
coupling is Task 4's removal of `has_profile`, which depends on Phase 1
having landed — revert Task 4 before Phase 1 if unwinding both.

---

## Notes / Learnings

<Filled in during execution.>
