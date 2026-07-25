# Phase 3: Runner, entrypoint & CI wiring

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 1 (schemas/config/db helpers) and Phase 2
> (github_search/bootstrap/tagging/embeddings) complete

---

## Goal

Wire Phase 1's data layer and Phase 2's building blocks into one
orchestrated pass (`run_coach_aggregator`), give it a standalone entrypoint
(`python -m scout.coach_aggregator`), and add the weekly step to the
existing nightly SSH session — with no new workflow file and no new VM
start/stop. After this phase, the spec's Success Criteria are all
checkable end-to-end.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes, transitively — `runner.py` orchestrates every external call from
  Phase 2. New here: `runner.py` no-ops (returns a zeroed `CoachSummary`
  and logs why) when `github_pat` is unset, mirroring the
  `discord_bot_token`-unset no-op already used in `scout/agent.py:156`, so
  an unconfigured environment never crashes.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  The CI workflow edit (Task 3) is not itself a one-way door (revertible),
  but it depends on a manual, out-of-code prerequisite: `GITHUB_PAT` must
  be added to the VM's `.env` before the step can succeed against prod.
  **Gate:** Task 3's workflow edit may be committed and merged without this
  (the step will simply fail with an auth error and `continue-on-error:
  true` prevents it from blocking anything else), but confirm with the
  human before relying on the weekly run actually producing data — flagged
  again in Verification below.

---

## Tasks

### Task 1: `runner.py` — orchestrate one aggregation pass

- **Files:**
  - Create: `scout/sub_agents/coach/runner.py`
  - Modify: `scout/shared/schemas.py` (add `CoachSummary`)
  - Test: `tests/test_coach_runner.py`
- **Gate:** none.
- **Interfaces:**
  - Consumes: `create_pool`, `get_distinct_gap_skills`, `get_resource_urls`,
    `insert_resource` (`scout/shared/db.py`, Phase 1);
    `search_candidates`, `fetch_readme` (`github_search.py`, Phase 2);
    `harvest_awesome_list` (`bootstrap.py`, Phase 2); `tag_readme`
    (`tagging.py`, Phase 2); `embed` (`embeddings.py`, Phase 2); `Resource`
    (Phase 1).
  - Produces: `run_coach_aggregator(settings: Settings | None = None) ->
    CoachSummary` and `CoachSummary` (`candidates_seen: int, inserted:
    int, duplicates: int`). Task 2's `coach_aggregator.py` relies on this
    exact name/signature/return type.

- [ ] **Step 1: Write the failing test**

Create `tests/test_coach_runner.py`:

```python
from __future__ import annotations

from datetime import date

import pytest

from scout.config import Settings
from scout.shared.db import (
    record_listing_gaps,
    record_run_listings,
    start_run,
    upsert_listing,
)
from scout.shared.schemas import ResourceTags, SkillGap
from scout.sub_agents.coach import runner


def _test_settings(**overrides) -> Settings:
    test_db_url = Settings().database_url.rsplit("/", 1)[0] + "/scout_test"
    return Settings(
        database_url=test_db_url,
        github_pat="test-pat",
        coach_awesome_lists=[],
        **overrides,
    )


async def _seed_kubernetes_gap(db_pool, listing_factory, match_factory) -> None:
    async with db_pool.acquire() as conn:
        run_id = await start_run(conn, date(2026, 7, 25))
        listing = listing_factory(external_id="ext-1", url="https://example.com/1")
        await upsert_listing(conn, listing)
        match = match_factory(listing=listing)
        await record_run_listings(conn, run_id, [(match, "competitive")])
        gap = SkillGap(skill="kubernetes", requirement_level="must_have", met=False)
        await record_listing_gaps(conn, run_id, [(match, [gap])])


def _mock_candidate_pipeline(monkeypatch) -> None:
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.search_candidates",
        lambda skill, settings: ["https://github.com/kubernetes/kubernetes"],
    )
    monkeypatch.setattr(
        "scout.sub_agents.coach.runner.fetch_readme",
        lambda url, settings: "# Kubernetes\n\nContainer orchestration.",
    )

    async def _fake_tag_readme(readme_text, settings):
        return ResourceTags(
            skills=["kubernetes"],
            resource_type="repo",
            level="intermediate",
            summary="Container orchestration platform.",
        )

    monkeypatch.setattr("scout.sub_agents.coach.runner.tag_readme", _fake_tag_readme)
    monkeypatch.setattr("scout.sub_agents.coach.runner.embed", lambda text: [0.1] * 384)


@pytest.mark.asyncio
async def test_run_coach_aggregator_inserts_new_resource(
    db_pool, listing_factory, match_factory, monkeypatch
):
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    _mock_candidate_pipeline(monkeypatch)

    summary = await runner.run_coach_aggregator(_test_settings())

    assert summary.inserted == 1
    assert summary.duplicates == 0
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT skills FROM resources WHERE url = $1",
            "https://github.com/kubernetes/kubernetes",
        )
    assert row["skills"] == ["kubernetes"]


@pytest.mark.asyncio
async def test_run_coach_aggregator_second_run_inserts_nothing_new(
    db_pool, listing_factory, match_factory, monkeypatch
):
    await _seed_kubernetes_gap(db_pool, listing_factory, match_factory)
    _mock_candidate_pipeline(monkeypatch)

    await runner.run_coach_aggregator(_test_settings())
    second_summary = await runner.run_coach_aggregator(_test_settings())

    assert second_summary.inserted == 0
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM resources WHERE url = $1",
            "https://github.com/kubernetes/kubernetes",
        )
    assert count == 1


@pytest.mark.asyncio
async def test_run_coach_aggregator_skips_when_github_pat_unset(db_pool):
    summary = await runner.run_coach_aggregator(_test_settings(github_pat=""))
    assert summary == type(summary)(candidates_seen=0, inserted=0, duplicates=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named
'scout.sub_agents.coach.runner'`.

- [ ] **Step 3: Write minimal implementation**

In `scout/shared/schemas.py`, append:

```python
class CoachSummary(BaseModel):
    """One aggregator pass's result — logged by coach_aggregator.py."""

    candidates_seen: int
    inserted: int
    duplicates: int
```

Create `scout/sub_agents/coach/runner.py`:

```python
from __future__ import annotations

import logging

from scout.config import Settings
from scout.config import settings as default_settings
from scout.shared.db import (
    create_pool,
    get_distinct_gap_skills,
    get_resource_urls,
    insert_resource,
)
from scout.shared.schemas import CoachSummary, Resource
from scout.sub_agents.coach.bootstrap import harvest_awesome_list
from scout.sub_agents.coach.embeddings import embed
from scout.sub_agents.coach.github_search import fetch_readme, search_candidates
from scout.sub_agents.coach.tagging import tag_readme

logger = logging.getLogger("scout.coach.runner")


def _title_from_url(url: str) -> str:
    return url.removeprefix("https://github.com/").rstrip("/")


def _gather_candidate_urls(settings: Settings, skills: list[str]) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []
    for list_url in settings.coach_awesome_lists:
        for url in harvest_awesome_list(list_url, settings):
            if url not in seen:
                seen.add(url)
                candidates.append(url)
    for skill in skills:
        for url in search_candidates(skill, settings):
            if url not in seen:
                seen.add(url)
                candidates.append(url)
    return candidates


async def run_coach_aggregator(settings: Settings | None = None) -> CoachSummary:
    active_settings = settings or default_settings
    if not active_settings.github_pat:
        logger.info("GITHUB_PAT not set — skipping coach aggregator run.")
        return CoachSummary(candidates_seen=0, inserted=0, duplicates=0)

    pool = await create_pool(active_settings)
    try:
        async with pool.acquire() as conn:
            skills = await get_distinct_gap_skills(conn)
            existing_urls = await get_resource_urls(conn)

        candidate_urls = _gather_candidate_urls(active_settings, skills)
        # Dedup happens once, up front, against a single snapshot of stored
        # URLs — an already-stored candidate is skipped before any
        # README fetch, LLM tagging, or embedding call (spec requirement).
        new_urls = [url for url in candidate_urls if url not in existing_urls]

        inserted = 0
        duplicates = 0
        for url in new_urls:
            readme = fetch_readme(url, active_settings)
            if readme is None:
                continue
            tags = await tag_readme(readme, active_settings)
            resource = Resource(
                url=url,
                title=_title_from_url(url),
                resource_type=tags.resource_type,
                skills=tags.skills,
                level=tags.level,
                summary=tags.summary,
                source="github",
            )
            embedding = embed(tags.summary)
            async with pool.acquire() as conn:
                result = await insert_resource(conn, resource, embedding)
            if result == "new":
                inserted += 1
            else:
                duplicates += 1
        return CoachSummary(
            candidates_seen=len(candidate_urls),
            inserted=inserted,
            duplicates=duplicates,
        )
    finally:
        await pool.close()
```

Add `Resource` to `db.py`'s import if not already there from Phase 1 (it
is — no change needed here).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_runner.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add scout/shared/schemas.py scout/sub_agents/coach/runner.py \
        tests/test_coach_runner.py
git commit -m "feat(coach): orchestrate the aggregation pass in runner.py

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 2: `scout/coach_aggregator.py` — standalone entrypoint

- **Files:**
  - Create: `scout/coach_aggregator.py`
  - Test: `tests/test_coach_aggregator_entrypoint.py`
- **Gate:** none.
- **Interfaces:**
  - Consumes: `run_coach_aggregator` (Task 1).
  - Produces: `main()` (mirrors `scout/main.py`'s shape exactly: no CLI
    args, `logging.basicConfig`, `sys.exit(1)` on any exception). Task 3's
    workflow step invokes this via `python -m scout.coach_aggregator`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_coach_aggregator_entrypoint.py`:

```python
from __future__ import annotations

import pytest

from scout.shared.schemas import CoachSummary


@pytest.mark.asyncio
async def test_run_once_logs_summary(monkeypatch, caplog):
    async def _fake_run_coach_aggregator(settings=None):
        return CoachSummary(candidates_seen=4, inserted=2, duplicates=2)

    monkeypatch.setattr(
        "scout.coach_aggregator.run_coach_aggregator", _fake_run_coach_aggregator
    )

    from scout.coach_aggregator import run_once

    with caplog.at_level("INFO"):
        await run_once()

    assert "2 inserted" in caplog.text


def test_main_exits_nonzero_when_run_once_raises(monkeypatch):
    async def _fake_run_once():
        raise RuntimeError("boom")

    monkeypatch.setattr("scout.coach_aggregator.run_once", _fake_run_once)

    from scout.coach_aggregator import main

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_aggregator_entrypoint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named
'scout.coach_aggregator'`.

- [ ] **Step 3: Write minimal implementation**

Create `scout/coach_aggregator.py`:

```python
from __future__ import annotations

import asyncio
import logging
import sys

from scout.sub_agents.coach.runner import run_coach_aggregator

logger = logging.getLogger("scout.coach_aggregator")


async def run_once() -> None:
    summary = await run_coach_aggregator()
    logger.info(
        "Coach aggregator: %s candidate(s) seen, %s inserted, %s duplicate(s)",
        summary.candidates_seen,
        summary.inserted,
        summary.duplicates,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_once())
    except Exception:
        logger.exception("coach aggregator run failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_aggregator_entrypoint.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add scout/coach_aggregator.py tests/test_coach_aggregator_entrypoint.py
git commit -m "feat(coach): add standalone coach_aggregator entrypoint

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 3: Weekly CI step + env documentation

- **Files:**
  - Modify: `.github/workflows/scheduled-run.yml`
  - Modify: `scout/.env.example`
  - Test: `tests/test_scheduled_run_workflow.py`
- **Gate:** ⚠️ human sign-off before relying on this in prod — `GITHUB_PAT`
  must be added to the VM's `.env` for the step to succeed there (see
  Safety Checklist). The code/workflow change itself needs no sign-off
  (`continue-on-error: true` makes a missing PAT a harmless no-op failure,
  not a blocking one).
- **Interfaces:**
  - Consumes: nothing new in-process — this task only adds a step that
    shells out to `python -m scout.coach_aggregator` (Task 2) inside the
    already-running container.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scheduled_run_workflow.py`:

```python
from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent / ".github" / "workflows" / "scheduled-run.yml"
)


def _steps() -> list[dict]:
    workflow = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    return workflow["jobs"]["run-job"]["steps"]


def test_coach_aggregator_step_runs_between_dashboard_deploy_and_deallocate():
    names = [step["name"] for step in _steps()]
    assert "Run coach aggregator (weekly)" in names
    deploy_idx = names.index("Deploy dashboard to Storage static website")
    coach_idx = names.index("Run coach aggregator (weekly)")
    deallocate_idx = names.index("Deallocate VM")
    assert deploy_idx < coach_idx < deallocate_idx


def test_coach_aggregator_step_does_not_block_the_job():
    coach_step = next(
        s for s in _steps() if s["name"] == "Run coach aggregator (weekly)"
    )
    assert coach_step.get("continue-on-error") is True


def test_coach_aggregator_step_invokes_the_module():
    coach_step = next(
        s for s in _steps() if s["name"] == "Run coach aggregator (weekly)"
    )
    assert "python -m scout.coach_aggregator" in coach_step["run"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduled_run_workflow.py -v`
Expected: FAIL — `AssertionError` (`"Run coach aggregator (weekly)" not in
[...]`) on the first test; step doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

In `.github/workflows/scheduled-run.yml`, insert a new step after "Deploy
dashboard to Storage static website" (after line 104) and before
"Deallocate VM":

```yaml
      - name: Run coach aggregator (weekly)
        # Runs once a week, piggybacking on the 01:00 UTC (11:00 Melbourne)
        # cron slot only — the 19:00 UTC slot never triggers this step —
        # then self-limits to Monday inside the script. Manual
        # workflow_dispatch runs (github.event.schedule == '') always run
        # it, for testing. continue-on-error so a coach failure (e.g.
        # GITHUB_PAT not yet set on the VM) never blocks the dashboard
        # deploy above or the deallocate step below.
        if: github.event.schedule == '0 1 * * *' || github.event.schedule == ''
        continue-on-error: true
        run: |
          set -euo pipefail
          if [ "${GITHUB_EVENT_NAME}" = "schedule" ] && [ "$(date -u +%u)" != "1" ]; then
            echo "Not Monday UTC — skipping coach aggregator this run."
            exit 0
          fi
          ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=accept-new \
            "$VM_USER@$VM_HOST" \
            "cd $APP_DIR && docker compose -f docker-compose.yaml -f docker-compose.prod.yaml run --rm app python -m scout.coach_aggregator"
```

In `scout/.env.example`, append after `DISCORD_CHANNEL_ID=` (after line 33):

```
# Career Coach resource aggregator (runs weekly). Create a GitHub personal
# access token (no special scopes needed for public repo search/read) at
# https://github.com/settings/tokens. On the deployed VM, this must be set
# in the VM's own .env (not just here) before the weekly CI step can write
# any resources — see docs/agent/plans/career-coach-p1-aggregator/plan.md.
GITHUB_PAT=
COACH_TOP_N_PER_SKILL=5
COACH_AWESOME_LISTS=
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scheduled_run_workflow.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/scheduled-run.yml scout/.env.example \
        tests/test_scheduled_run_workflow.py
git commit -m "feat(coach): wire weekly aggregator step into the nightly SSH session

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verification

- [ ] All phase tests pass: `pytest tests/test_coach_runner.py tests/test_coach_aggregator_entrypoint.py tests/test_scheduled_run_workflow.py -v`
- [ ] Full regression: `pytest` (whole suite green).
- [ ] Manual (spec's Success Criteria, checked for real): with a real
  `GITHUB_PAT` and `DEEPSEEK_API_KEY` set locally and at least one real gap
  skill in the dev DB's `listing_gaps`, run
  `python -m scout.coach_aggregator` and confirm a `resources` row lands
  with a reachable GitHub URL, a non-empty summary, and a 384-dim
  embedding; run it again and confirm the row count for that URL is still 1.
- [ ] ⚠️ Human confirms `GITHUB_PAT` has been added to the VM's `.env`
  before treating the weekly prod run as expected to produce data (Safety
  Checklist gate) — tracked here, not blocking merge of the code itself.

## Observability

`scout.coach_aggregator`'s single `logger.info` line
(`"Coach aggregator: N candidate(s) seen, N inserted, N duplicate(s)"`) is
the only signal this phase adds, visible in the SSH'd container's stdout
during the weekly CI step (same place the daily "Run scout cycle" step's
output already goes — no new log sink). A run that logs `0 candidate(s)
seen, 0 inserted, 0 duplicate(s)` either found no gap skills and empty
bootstrap lists, or (check the preceding log line) skipped entirely because
`GITHUB_PAT` was unset.

## Rollback

Revert the three feat commits. Task 3's workflow step is the only prod-
facing change; reverting it (or just deleting the step) immediately stops
the weekly SSH command with no other side effect — `continue-on-error:
true` means it was never on the critical path for the daily dashboard
deploy to begin with. No data to unwind (see `plan.md` → Rollout &
Reversibility).

---

## Notes / Learnings

<Filled in during execution.>
