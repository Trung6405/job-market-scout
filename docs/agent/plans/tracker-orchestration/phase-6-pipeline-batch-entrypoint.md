# Phase 4: Batch Entrypoint + Dockerfile

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 3 complete (needs `ScoutPipelineAgent`)

---

## Goal

Add `scout/main.py`, a thin non-interactive entrypoint that drives
`ScoutPipelineAgent` through an `InMemoryRunner` once, logs each stage's
progress event, and exits non-zero if the run raises. Point the
`Dockerfile`'s `CMD` at it instead of `adk api_server`. Done when
`python -m scout.main` runs the pipeline once and exits with the right
code, and a full local Docker dry run (this phase's manual verification)
completes end-to-end against the Docker Postgres on port 5433.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?** Yes — same as
  Phase 3, this drives the real pipeline. Automated tests monkeypatch the
  same four `scout.agent` functions Phase 3 already established a pattern
  for.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No — the `Dockerfile` `CMD` change alters what a deployed container
  does by default, but it is an ordinary, fully reversible code change
  (revert the commit), not a schema or public API change.

---

## Tasks

### Task 1: `run_once` completes a full pipeline pass

- **Files:** `scout/main.py`, `tests/test_main_entrypoint.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test:

    ```python
    from __future__ import annotations

    from datetime import datetime, timezone
    from email.message import EmailMessage

    import pytest

    from scout.shared.schemas import Listing, ListingScore


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


    @pytest.mark.asyncio
    async def test_run_once_completes_without_raising(monkeypatch):
        listing = _make_listing()
        score = ListingScore(source="linkedin", external_id="1", score=80, reasoning="Good fit.")

        async def _fake_run_scraper(settings):
            return [listing]

        async def _fake_track_listings(listings, settings=None):
            return listings

        async def _fake_run_scorer(listings, settings):
            return [score]

        async def _fake_run_briefing(listings, scores, settings):
            return EmailMessage()

        monkeypatch.setattr("scout.agent.run_scraper", _fake_run_scraper)
        monkeypatch.setattr("scout.agent.track_listings", _fake_track_listings)
        monkeypatch.setattr("scout.agent.run_scorer", _fake_run_scorer)
        monkeypatch.setattr("scout.agent.run_briefing", _fake_run_briefing)

        from scout.main import run_once

        await run_once()
    ```

  - [ ] Verify it fails (`pytest tests/test_main_entrypoint.py -v`)
    Expected: `ModuleNotFoundError: No module named 'scout.main'`
  - [ ] Implement `scout/main.py`:

    ```python
    from __future__ import annotations

    import asyncio
    import logging
    import sys

    from google.adk.runners import InMemoryRunner
    from google.genai import types as genai_types

    from scout.agent import ScoutPipelineAgent

    logger = logging.getLogger("scout.main")

    _APP_NAME = "scout"
    _USER_ID = "scout"
    _SESSION_ID = "scout"


    async def run_once() -> None:
        runner = InMemoryRunner(agent=ScoutPipelineAgent(), app_name=_APP_NAME)
        await runner.session_service.create_session(
            app_name=_APP_NAME, user_id=_USER_ID, session_id=_SESSION_ID
        )
        message = genai_types.Content(
            role="user", parts=[genai_types.Part(text="Run the daily pipeline.")]
        )
        async for event in runner.run_async(
            user_id=_USER_ID, session_id=_SESSION_ID, new_message=message
        ):
            if event.content and event.content.parts and event.content.parts[0].text:
                logger.info(event.content.parts[0].text)


    def main() -> None:
        logging.basicConfig(level=logging.INFO)
        try:
            asyncio.run(run_once())
        except Exception:
            logger.exception("pipeline run failed")
            sys.exit(1)


    if __name__ == "__main__":
        main()
    ```

  - [ ] Verify it passes (`pytest tests/test_main_entrypoint.py -v`)
    Expected: 1 passed
  - [ ] Commit: `feat(main): add batch entrypoint driving ScoutPipelineAgent`

### Task 2: `main` exits non-zero on failure

- **Files:** `scout/main.py`, `tests/test_main_entrypoint.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test (append to `tests/test_main_entrypoint.py`):

    ```python
    def test_main_exits_nonzero_when_run_once_raises(monkeypatch):
        async def _fake_run_once():
            raise RuntimeError("boom")

        monkeypatch.setattr("scout.main.run_once", _fake_run_once)

        from scout.main import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
    ```

  - [ ] Verify it fails (`pytest tests/test_main_entrypoint.py -v`)
    Expected: fails if `main`'s `try/except` isn't wired yet, or passes
    already if Task 1's implementation already included it — in that case
    skip straight to the next check step and note it in this phase's
    Notes / Learnings.
  - [ ] Confirm/adjust `main()` in `scout/main.py` matches the `try: asyncio.run(run_once()) / except Exception: ... sys.exit(1)` shape from Task 1 (no change expected if Task 1 was implemented as shown above).
  - [ ] Verify it passes (`pytest tests/test_main_entrypoint.py -v`)
    Expected: 2 passed
  - [ ] Commit: `test(main): cover main() non-zero exit on failure` (only if a code change was needed; otherwise fold this test into Task 1's commit instead of creating an empty one)

### Task 3: Point the Dockerfile at the batch entrypoint

- **Files:** `Dockerfile`
- **Gate:** none
- **Steps:**
  - [ ] Edit `Dockerfile`'s last line from:
    ```
    CMD ["adk", "api_server", "--host", "0.0.0.0", "--port", "8000", "scout"]
    ```
    to:
    ```
    CMD ["python", "-m", "scout.main"]
    ```
  - [ ] Verify: `docker build -t job-market-scout .` succeeds (this is a
    build check, not a unit test — run it locally)
  - [ ] Commit: `chore(docker): run batch pipeline entrypoint instead of adk api_server`

---

## Verification

- [ ] All phase tests pass: `pytest tests/test_main_entrypoint.py -v`
- [ ] Full suite still green: `pytest -v`
- [ ] **Manual — local dry run matching the eventual CI/Azure path** (this
  is the acceptance bar for the whole plan, not just this phase):
  1. `docker compose up -d postgres jobspy-mcp jobspy-scraper` to bring up
     dependencies, confirm Postgres is healthy on port 5433 (isolated from
     any native Windows Postgres on 5432).
  2. `docker build -t job-market-scout .` then
     `docker compose run --rm app` (or `docker run` with the same env) to
     execute one full pipeline pass exactly as the container will run in
     production.
  3. **Per-stage checks**, not just the exit code:
     - Scraper: listing count in the logged `"Scraper: N listing(s)
       found"` line is in a sane range for the configured
       `search_roles`/`search_locations` — not 0, not far above the
       configured `results_wanted` (a wildly high count usually means
       duplicates or a broken selector still returning "results").
     - Tracker: re-run immediately after a successful run and confirm the
       `"Tracker: 0 new/changed"` short-circuit message appears — proves
       no duplicate inserts happen for listings that already existed.
     - Scorer: hand-inspect 3–5 rows in the `listings` table (or the
       scored output) against `scout/resume.txt` and `preferred_locations`
       / `remote_only` / `min_salary` — does the highest-scored listing
       actually look like a good match? No automated test can catch a
       scorer whose numbers are self-consistent but wrong.
     - Briefing: confirm the sent email is non-empty, readable, and its
       takeaways actually reference the top-scored listings.
  4. **Edge cases to deliberately trigger at least once:**
     - Zero listings scraped — temporarily set `SEARCH_ROLES` to something
       that returns nothing (or point `hours_old` very low) and confirm
       the run logs `"Scraper: 0 listing(s) found"` and then the Tracker
       short-circuit message, rather than a hollow "success" briefing.
     - Running twice same day — run step 2 twice in a row; the second run
       must short-circuit at the Tracker stage (see per-stage check above)
       instead of re-scoring/re-briefing the same listings.
     - A malformed config value — set `MIN_SALARY=not-a-number` (or an
       equivalent bad value for another numeric/bool setting) and confirm
       `scout/main.py` fails fast with a clear error during `Settings()`
       construction, rather than silently coercing it and producing
       garbage scores. If it doesn't fail clearly, that's a bug to fix
       before considering this plan done — file it, don't route around it
       by editing `scout/config.py` as an unplanned addition to this
       phase; note it in Notes / Learnings and flag it to the human.

## Rollback

Revert the `Dockerfile` and `scout/main.py` commits; the container goes
back to starting `adk api_server`. No data or schema involved.

---

## Notes / Learnings

<Filled in during execution — anything that should inform later phases.>
