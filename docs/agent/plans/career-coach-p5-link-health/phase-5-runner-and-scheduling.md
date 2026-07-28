# Phase 5: Runner, Entrypoint & Scheduling

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phases 1–4 complete (settings, checker, persistence, exclusion)

---

## Goal

Assemble the pieces into a runnable job — select a batch, check each URL,
record each verdict, report a summary — expose it as its own module entrypoint,
and give it a step on the existing daily scheduled run. Done when a real run
against the live corpus produces plausible counts and the scheduled step cannot
fail the pipeline.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — it is the first thing to make link-check requests for real, and it
  writes to the production corpus. No secrets are needed (checks are
  unauthenticated public HTTP, unlike the aggregator's PAT). Its scheduled step
  is `continue-on-error` so a failure cannot block the deallocate step and
  leave the VM billing.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. The workflow step is one YAML addition, removable in one commit.

---

## Tasks

### Task 1: The run summary

- **Files:** `scout/shared/schemas.py`, `tests/test_coach_schemas.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: `LinkHealthSummary` carries `checked`, `verified`,
        `recovered`, `newly_dead`, `still_dead` and `failing` counts
  - [ ] Verify it fails (`pytest tests/test_coach_schemas.py -q`)
  - [ ] Implement the model beside `CoachSummary`, with a docstring saying it
        is what `coach_link_health.py` logs — the counts map one-to-one onto
        the transitions `record_link_check` returns
  - [ ] Verify it passes (`pytest tests/test_coach_schemas.py -q`)
  - [ ] Commit: `feat(coach): add LinkHealthSummary`

### Task 2: The run loop

- **Files:** `scout/sub_agents/coach/link_health.py`,
  `tests/test_coach_link_health_runner.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test, with the batch query, `check_url`, and
        `record_link_check` stubbed: `run_link_health` checks exactly the rows
        the batch returned, passes each verdict through to persistence, tallies
        the returned transitions into the summary, and — the one that matters —
        keeps going when one URL's check raises, counting it as a transient
        failure rather than abandoning the rest of the batch
  - [ ] Verify it fails (`pytest tests/test_coach_link_health_runner.py -q`)
  - [ ] Implement `run_link_health(settings=None) -> LinkHealthSummary`:
        acquire a pool, select `coach_link_health_batch` rows, check each
        sequentially with the aggregator's throttle discipline, record each
        result, and return the tally. An empty batch is a valid, successful,
        zero-count run
  - [ ] Verify it passes (`pytest tests/test_coach_link_health_runner.py -q`)
  - [ ] Commit: `feat(coach): add the link-health run loop`

### Task 3: The module entrypoint

- **Files:** `scout/coach_link_health.py`,
  `tests/test_coach_link_health_entrypoint.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test, mirroring `test_coach_aggregator_entrypoint.py`:
        `run_once` logs the summary counts at INFO, and `main` exits non-zero
        when the run raises
  - [ ] Verify it fails (`pytest tests/test_coach_link_health_entrypoint.py -q`)
  - [ ] Implement the entrypoint as a near-copy of `scout/coach_aggregator.py`
        — same logging setup, same `asyncio.run`, same exception-to-exit-code
        handling — so the two coach jobs are operated identically
  - [ ] Verify it passes (`pytest tests/test_coach_link_health_entrypoint.py -q`)
  - [ ] Commit: `feat(coach): add the coach_link_health entrypoint`

### Task 4: A runnable link-health audit

- **Files:** `scripts/audit_link_health.py`, `tests/test_audit_link_health.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: the audit's reporting function turns a set of
        resource rows into the counts it prints — live, dead, never-checked,
        and failing-but-not-yet-dead — and reports cleanly on an empty corpus
        rather than implying an empty corpus passed
  - [ ] Verify it fails (`pytest tests/test_audit_link_health.py -q`)
  - [ ] Implement, following `scripts/audit_rendered_citations.py`: a read-only
        `python -m scripts.audit_link_health` that queries the corpus and prints
        the health distribution plus every dead resource's URL, `dead_since`
        and `last_check_error`. Reads only — it never issues a check or writes
        a row, so it is safe to run against production at any time. The
        docstring records why it exists: stubs prove only the HTTP behaviour
        the test author imagined, and what real hosts do to a `HEAD` request is
        exactly what the suite cannot see — the same blind spot that made P4's
        link budget pass every fixture test while being wrong
  - [ ] Verify it passes (`pytest tests/test_audit_link_health.py -q`)
  - [ ] Commit: `feat(scripts): add a link-health audit for the Coach corpus`

### Task 5: The scheduled step

- **Files:** `.github/workflows/scheduled-run.yml`,
  `tests/test_scheduled_run_workflow.py`, `docs/commands.md`
- **Gate:** ⚠️ human sign-off required before committing — this is the point
  the job starts running against the production corpus on a schedule and
  writing health state to real rows. Confirm the manual run below looked right
  first.
- **Steps:**
  - [ ] Write failing test: the workflow has a link-health step that runs on
        the daily cron slot (not gated to one weekday, unlike the aggregator),
        invokes `python -m scout.coach_link_health` over SSH in the app
        container, and is `continue-on-error: true`
  - [ ] Verify it fails (`pytest tests/test_scheduled_run_workflow.py -q`)
  - [ ] Implement: add the step after the aggregator step and before
        `Deallocate VM`, with a comment explaining the daily-vs-weekly
        difference — the batch cap is what bounds each run, and daily cycling
        is what makes the check happen *between* aggregations (NFR-CC-4).
        Document the manual invocation in `docs/commands.md` next to the
        aggregator's
  - [ ] Verify it passes (`pytest tests/test_scheduled_run_workflow.py -q`)
  - [ ] Commit: `feat(coach): run the link-health check on the daily schedule`

---

## Verification

- [ ] All phase tests pass:
      `pytest tests/test_coach_schemas.py tests/test_coach_link_health_runner.py tests/test_coach_link_health_entrypoint.py tests/test_audit_link_health.py tests/test_scheduled_run_workflow.py -q`
- [ ] Full suite green: `pytest -q`
- [ ] **Manual, before Task 5's commit:** run
      `python -m scout.coach_link_health` once against the live corpus, then
      `python -m scripts.audit_link_health`, and confirm the picture is
      plausible — nearly everything verified, few or no newly-dead, and no
      whole-batch failure (which would indicate rate limiting or a `HEAD`
      problem rather than genuinely dead links). Open two or three of the URLs
      the audit reports as dead and confirm they really are.
- [ ] Re-run it a second time and confirm the batch advances to different rows
      rather than rechecking the first ones.

## Observability

One INFO line per run, in the aggregator's shape: checked, verified, recovered,
newly dead, still dead, failing. A run where `newly_dead` approaches the batch
size is the signal that the checker itself is wrong (rate limiting, blocked
user agent) rather than that the corpus died — worth watching on the first few
scheduled runs. Between runs, `python -m scripts.audit_link_health` answers what
has dropped out and why, without touching the corpus.

## Rollback

Remove the workflow step to stop scheduled runs — that alone halts all
production effect. Reverting the remaining commits removes the job; the corpus
keeps whatever health state was already written, which Phase 4's filter honours
until that is reverted too. To restore every excluded resource, use the
`UPDATE` in plan.md → Rollout & Reversibility.

---

## Notes / Learnings

<Filled in during execution.>
