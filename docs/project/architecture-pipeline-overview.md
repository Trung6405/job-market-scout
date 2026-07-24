# Architecture — Pipeline Overview

> **Status:** Living document — reflects the current code, not a plan.
> Feature-level design decisions live in `docs/agent/specs/<feature>/spec.md`
> and `docs/agent/plans/<feature>/plan.md`; this file is the map that ties
> those pieces together. For how this shape diverges from the original
> product scope, see `docs/project/specification/product-requirements-spec-amendments.md`.

## Pipeline

`scout/agent.py`'s `ScoutPipelineAgent` runs six stages in order, in a
single container, per daily run. It is a plain class — no external agent
framework — with a `run()` method yielding `PipelineEvent`s
(`scout/shared/events.py`) that `scout/main.py` logs as it iterates them.
Every LLM call in the pipeline goes through one helper,
`complete_json()` (`scout/shared/llm.py`): a stateless prompt-in,
schema-out call to `litellm.acompletion` with `response_format={"type":
"json_object"}`, validated into a Pydantic model. Stages whose model
response can grow with the number of listings (Scorer, Advisor) batch
their calls through `scout/shared/batching.py`, which runs batches
concurrently under a bounded semaphore and retries a failed batch once
before skipping it with a warning — one truncated or malformed response
costs that batch's listings, not the whole run.

```
Scraper → Tracker → Scorer → Advisor → Persistence/Report → Briefing
```

🤖 = LLM-calling stage · ⚙️ = deterministic code stage

| Stage | Type | Module | Responsibility |
|---|---|---|---|
| **Scraper** | 🤖 | `scout/sub_agents/scraper/` | Fetch current job listings for the configured roles/locations from job boards and the web. |
| **Tracker** | ⚙️ | `scout/sub_agents/tracker/` | Diff scraped listings against the DB; persist all listings; mark new/changed/closed; dedupe; pass only new/changed listings downstream. |
| **Scorer** | 🤖 | `scout/sub_agents/scorer/` | LLM-score every relevant listing 0–100 against the configured profile, batched. Preference-neutral: `remote_only`/`preferred_locations`/`min_salary` are not scoring inputs, so a listing the student wouldn't want still gets a fair score and a place on the dashboard — preferences narrow the Briefing instead (see below). |
| **Advisor** | 🤖 + ⚙️ | `scout/sub_agents/advisor/` | Turn raw scores into personalized guidance — see below. |
| **Briefing** | 🤖 | `scout/sub_agents/briefing/` | Filter scored matches to the ones passing the student's preferences (`scout/sub_agents/briefing/filters.py::passes_preferences`) and the minimum score, summarize the top matches, and send the daily briefing, linking to the rendered report. |

## Why the Advisor stage exists

The Scorer only produces a number (0–100) per listing, used once for
the email and then discarded. That's not enough to answer "why is this
job a good/bad match for me" or to let a student browse past runs. The
Advisor stage exists to close that gap. It has four responsibilities:

- **`runner.py`** — a second, batched LLM pass (DeepSeek, via
  `complete_json`) that extracts structured requirements (must-have /
  nice-to-have skills) from each listing's raw text. Deliberately
  profile-blind — the prompt never renders the student's profile, so a
  requirement can't be softened or dropped because the student happens
  not to meet it (see `docs/agent/specs/pipeline-efficiency/spec.md`'s
  Amendment for why this ruled out merging this pass with the Scorer's).
- **`gaps.py`** — pure function `evaluate_requirements(requirements, profile)`
  diffing extracted requirements against the student's `profile.json`
  `tech_stack`, returning a met/unmet checklist entry per requirement
  (persisted in full; callers filter to just the gaps for reporting).
- **`bands.py`** — pure function `classify_band(score, settings)`
  mapping the Scorer's 0–100 score into a qualitative band
  (`strong_match` / `competitive` / `reach`) using threshold settings.
- **`report.py`** — renders persisted run data (via Jinja2 templates in
  `advisor/templates/`) into the actual HTML screens: a per-run
  dashboard, per-job detail pages with flagged gaps, a cross-run
  history page, and a profile page.

`profile.json` is the single, required candidate source (`Settings`
fails fast at startup if it's missing or invalid — see
`docs/agent/specs/profile-candidate-source/spec.md`), so gap detection
always runs; there's no missing-profile skip path.

## Persistence

`scout/shared/db.py` owns two run-scoped tables written by
`ScoutPipelineAgent` after scoring: `runs` (one row per run, keyed by
date) and `run_listings` (score + band per listing), plus
`listing_gaps` (flagged missing skills per listing, when a profile
exists). This is what makes `history.html` real instead of hardcoded
sample data — see `docs/agent/specs/advisor-report/spec.md` for the original
problem statement and success criteria.

### Run identity & idempotency

`runs` is keyed by the **local** `run_date` (`UNIQUE (run_date)`), so both
daily cron fires (05:00 and 11:00 Melbourne) map to the **same** run row —
the later fire is a same-day *refresh*, not a new historical run. Intraday
history is deliberately not kept (see the same-day-overwrite decision in
`docs/agent/specs/pipeline-hardening/spec.md`).

A run persists all-or-nothing: after both LLM passes complete,
`ScoutPipelineAgent` writes `run_listings` (scores + bands), the extracted
meta onto those rows, `listing_gaps`, the finished marker, and the report
renders inside a **single transaction** (`scout/agent.py`). If a run dies partway through
the Advisor, that transaction rolls back and only the `start_run` row
survives (with `finished_at` NULL) — the marker that the run is
incomplete. The **next same-date run heals it** deterministically:
`start_run` upserts the run row, `record_run_listings` upserts on
`(run_id, listing_id)`, and `record_listing_gaps` delete-then-inserts. So
re-running a broken day is always safe and converges to a clean state.

## Scheduling & hosting

GitHub Actions is the sole orchestrator — no Azure-native scheduler is
used. `.github/workflows/scheduled-run.yml` cron-triggers twice daily
(19:00 and 01:00 UTC = 05:00 and 11:00 Melbourne time), then:

1. Starts the Azure VM `scout-vm` (`az vm start`, idempotent) and waits
   for SSH.
2. Runs one pipeline cycle over SSH (`docker compose run --rm app`).
3. Rsyncs `reports/` off the VM and publishes it to an
   Azure Storage Account configured for static website hosting
   (`infra/dashboard.bicep`), via `az storage blob upload-batch`
   reusing the workflow's OIDC login — no separate deploy-token secret.
4. Deallocates the VM (`if: always()`, so a failed run still stops
   billing).

This decouples dashboard availability from the VM's start/deallocate
cycle: the VM is deallocated ~23h/day to control cost, but the
dashboard stays reachable at the storage account's static website
endpoint the whole time. See
`docs/agent/plans/static-dashboard-hosting/plan.md` for the full
rationale, including why Azure Static Web Apps was tried first and
replaced with a Storage static website (region policy on this
subscription doesn't offer Static Web Apps anywhere it allows
deployment).

## Where to go next

- Stage-by-stage design rationale and requirements: `docs/agent/specs/<stage>/spec.md`
- Phased implementation history: `docs/agent/plans/<stage>/plan.md` (+ `phase-N.md`)
- Current product scope: `docs/project/specification/product-requirements-spec.md`; for the v1.0 → v2.0 → v2.1 change history, see its `product-requirements-spec-amendments.md`
- Candidate-source consolidation: `docs/agent/specs/profile-candidate-source/spec.md`
- Dashboard hosting: `docs/agent/plans/static-dashboard-hosting/plan.md`
- Static HTML mockups the Advisor's templates now replace: `docs/project/prototypes/`
