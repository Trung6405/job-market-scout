# Architecture — Pipeline Overview

> **Status:** Living document — reflects the current code, not a plan.
> Feature-level design decisions live in `docs/agent/specs/<feature>/spec.md`
> and `docs/agent/plans/<feature>/plan.md`; this file is the map that ties
> those pieces together. For how this shape diverges from the original
> product scope, see `docs/project/specification/product-requirements-spec-amendments.md`.

## Pipeline

`scout/agent.py`'s `ScoutPipelineAgent` runs seven stages in order, in a
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
Scraper → Tracker → Scorer → Advisor → Coach → Persistence/Report → Briefing
```

🤖 = LLM-calling stage · ⚙️ = deterministic code stage

| Stage | Type | Module | Responsibility |
|---|---|---|---|
| **Scraper** | 🤖 | `scout/sub_agents/scraper/` | Fetch current job listings for the configured roles/locations via the vendored `jobspy-mcp-server` (`mcp_client.py` talks to it; `normalize.py` deterministically normalizes what comes back). |
| **Tracker** | ⚙️ | `scout/sub_agents/tracker/` | Diff scraped listings against the DB; persist all listings; mark new/changed/closed; dedupe; pass only new/changed listings downstream. |
| **Scorer** | 🤖 | `scout/sub_agents/scorer/` | LLM-score every relevant listing 0–100 against the configured profile, batched. Preference-neutral: `remote_only`/`preferred_locations`/`min_salary` are not scoring inputs, so a listing the student wouldn't want still gets a fair score and a place on the dashboard — preferences narrow the Briefing instead (see below). |
| **Advisor** | 🤖 + ⚙️ | `scout/sub_agents/advisor/` | Turn raw scores into personalized guidance — see below. |
| **Coach** | 🤖 + ⚙️ | `scout/sub_agents/coach/` | Turn each listing's unmet skill gaps into short, actionable tips that cite only real learning resources from the curated `resources` corpus — see below. |
| **Persistence/Report** | ⚙️ | `scout/shared/db.py` + `scout/sub_agents/advisor/report.py` | Persist the run (scores, bands, gaps, tips) in a single transaction and render the HTML report pages from that data — see Persistence below. |
| **Briefing** | 🤖 | `scout/sub_agents/briefing/` | Filter scored matches to the ones passing the student's preferences (`scout/sub_agents/briefing/filters.py::passes_preferences`) and the minimum score, summarize the top matches, and post the daily briefing to Discord, linking to the rendered report. |

## Why the Advisor stage exists

The Scorer only produces a number (0–100) per listing, used once for
the daily briefing and then discarded. That's not enough to answer "why is this
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

## Why the Coach stage exists

The Advisor names what's missing; it doesn't say what to do about it.
The Coach stage closes that half, and does so without letting the model
invent study material:

- **`runner.py` (+ `bootstrap.py`, `github_search.py`, `tagging.py`,
  `embeddings.py`)** — the corpus aggregator: it harvests candidate learning
  resources for the skills that actually show up as gaps, skill-tags and
  embeds them into the `resources` table. It runs on a weekly cadence
  (entrypoint `scout/coach_aggregator.py`), separately from
  `ScoutPipelineAgent` — the daily *pipeline* run only ever reads the corpus.
- **`link_health.py`** — `run_link_health()` (entrypoint
  `scout/coach_link_health.py`), a daily job that re-verifies recently
  surfaced resources' URLs and writes `last_verified` /
  `consecutive_failures` / `dead_since` on `resources`; a resource marked
  dead drops out of retrieval until it verifies again. See
  `docs/agent/specs/career-coach-p5-link-health/spec.md`.
- **`retriever.py`** — `retrieve_for_skills(conn, skills, ...)` embeds each
  *distinct* gap skill once for the whole run and pulls its top-k resources,
  so a skill that is a gap on twenty listings costs one embedding.
- **`tips.py`** — `run_grounded_tips()`, one `complete_json` call per listing
  (size-1 batches through `run_batches`, so a failed call costs that listing's
  tips and nothing else), prompted with only that listing's gaps and their
  retrieved resources. A listing whose gaps retrieve nothing is never sent to
  the model at all.
- **`grounding.py`** — `validate_grounding()` re-checks the reply
  deterministically against the allowlist actually given to the model: a URL
  the corpus didn't supply is stripped from the tip and logged as a grounding
  violation, and a tip left citing nothing is dropped. Only the validator
  constructs a `GroundedTip`, so an unvalidated tip can't reach the DB by
  mistake.

Generation runs **before** the run transaction opens (`scout/agent.py`), for
the same reason the Scorer and Advisor calls do: it takes its own short-lived
connection for retrieval — the corpus is read-only to this run — rather than
holding the run transaction open across minutes of model calls. Only the
`record_listing_tips` write goes inside.

The run reports its result as a `Coach: N grounded tip(s) across M listing(s)`
pipeline event.

### How tips reach the page

Each stored tip renders inside the job-detail page's gap block for the gap it
answers, joined on the gap skill's raw stored wording — which is why
`GroundedTip.gap_skill` is never normalized. Gaps render must-haves first, so
priority is carried by position and the requirement pill; the static "How to
position your application" section that used to restate the gap list in prose
is gone, along with its inability to name a resource.

Citations are linked in the tip's own prose by a `linkify` Jinja filter in
`scout/sub_agents/advisor/report.py`, which escapes the text itself — returning
`Markup` opts it out of Jinja's autoescape, and the text is model output. Its
URL pattern is deliberately kept identical to the grounding validator's, with a
test asserting so: the validator decides what may be *stored* and the filter
what is *clickable*, and if they disagreed on where a URL begins, a validated
citation could render as dead text.

Every citation in a tip is linked. An earlier version of this stage capped
links per page and left the rest as plain text, which sounded prudent and was
not: most generated tips cite two or three resources, so the cap left more than
half of all citations as bare unclickable URLs beside linked ones. How many
links a page carries is governed upstream by `COACH_TOP_K`, which bounds how
many resources a tip can cite at all.

A listing whose gaps have no tips — every run recorded before the Coach stage
existed, and any listing the corpus does not cover — says so in one line rather
than falling back to generic advice. Because `rerender.py` rebuilds pages from
the database alone, that is what the historical archive shows after a
re-render.

## Persistence

`scout/shared/db.py` owns two run-scoped tables written by
`ScoutPipelineAgent` after scoring: `runs` (one row per run, keyed by
date) and `run_listings` (score + band per listing), plus
`listing_gaps` (flagged missing skills per listing, when a profile
exists) and `listing_tips` (the Coach's grounded tips, one row per tip,
each carrying the `cited_urls` it was validated against). This is what
makes `history.html` real instead of hardcoded sample data — see `docs/agent/specs/advisor-report/spec.md` for the original
problem statement and success criteria.

The full schema (`scout/shared/schema.sql`) also holds `listings` — every
listing the Tracker has ever seen, with lifecycle state and `content_hash` —
and the Coach's `resources` corpus (pgvector `embedding` column via the
`vector` extension, plus the link-health columns `last_verified` /
`consecutive_failures` / `dead_since`). `listings` is written by the Tracker
each run; `resources` is written only by the weekly aggregator and the daily
link-health job, never by the pipeline.

### Run identity & idempotency

`runs` is keyed by the **local** `run_date` (`UNIQUE (run_date)`), so any
two fires on the same local date — the daily cron plus a manual
`workflow_dispatch`, say — map to the **same** run row; the later fire is a
same-day *refresh*, not a new historical run. Intraday history is
deliberately not kept (see the same-day-overwrite decision in
`docs/agent/specs/pipeline-hardening/spec.md`).

A run persists all-or-nothing: after both LLM passes complete,
`ScoutPipelineAgent` writes `run_listings` (scores + bands), the extracted
meta onto those rows, `listing_gaps`, `listing_tips`, the finished marker, and the report
renders inside a **single transaction** (`scout/agent.py`). If a run dies partway through
the Advisor, that transaction rolls back and only the `start_run` row
survives (with `finished_at` NULL) — the marker that the run is
incomplete. The **next same-date run heals it** deterministically:
`start_run` upserts the run row, `record_run_listings` upserts on
`(run_id, listing_id)`, and `record_listing_gaps` / `record_listing_tips`
delete-then-insert (scoped to the listings supplied, so a partial re-run
doesn't wipe the rest of the run's rows). So
re-running a broken day is always safe and converges to a clean state.

## Scheduling & hosting

GitHub Actions is the sole orchestrator — no Azure-native scheduler is
used. `.github/workflows/scheduled-run.yml` cron-triggers once daily
(19:00 UTC = 05:00 Melbourne time the next morning), then:

1. Starts the Azure VM `scout-vm` (`az vm start`, idempotent) and waits
   for SSH.
2. Runs one pipeline cycle over SSH (`docker compose run --rm app`).
3. Rsyncs `reports/` off the VM and publishes it to an
   Azure Storage Account configured for static website hosting
   (`infra/dashboard.bicep`), via `az storage blob upload-batch`
   reusing the workflow's OIDC login — no separate deploy-token secret.
4. Runs the Coach corpus aggregator (`scout/coach_aggregator.py`) —
   weekly only, the step self-limits to Sundays UTC — and the link-health
   check (`scout/coach_link_health.py`) daily. Both are
   `continue-on-error: true`, so a corpus hiccup never fails the run.
5. Deallocates the VM (`if: always()`, so a failed run still stops
   billing).

`deploy.yml` drives the **same single VM** through the same
start → SSH → deallocate cycle, so the two must never run at once: the
first to finish deallocates the VM out from under the other, and the
loser's SSH dies mid-step with `Connection closed by remote host`
(exit 255). Both VM-touching jobs therefore share a job-level
`concurrency: group: scout-vm` with `cancel-in-progress: false` —
cancelling would skip the `if: always()` deallocate and leak a running
VM. `tests/test_vm_workflow_concurrency.py` pins this, since the lock is
only a matching string across two files.

This decouples dashboard availability from the VM's start/deallocate
cycle: the VM is deallocated ~23h/day to control cost, but the
dashboard stays reachable at the storage account's static website
endpoint the whole time. See
`docs/agent/plans/static-dashboard-hosting/plan.md` for the full
rationale, including why Azure Static Web Apps was tried first and
replaced with a Storage static website (region policy on this
subscription doesn't offer Static Web Apps anywhere it allows
deployment).

## Entrypoints

- `scout/main.py` — the daily batch run (the Dockerfile's `CMD`)
- `scout/rerender.py` — rebuild every report page from the DB; no scrape, no LLM calls
- `scout/coach_aggregator.py` — weekly Coach corpus aggregation
- `scout/coach_link_health.py` — daily Coach link-health check
- `scout/backfill_hashes.py` — one-off maintenance after a `content_hash` definition change

See `docs/commands.md` for how to invoke each.

## Where to go next

- Stage-by-stage design rationale and requirements: `docs/agent/specs/<stage>/spec.md`
- Phased implementation history: `docs/agent/plans/<stage>/plan.md` (+ `phase-N.md`)
- Current product scope: `docs/project/specification/product-requirements-spec.md`; for the v1.0 → v2.0 → v2.1 → v2.2 change history, see its `product-requirements-spec-amendments.md`
- Candidate-source consolidation: `docs/agent/specs/profile-candidate-source/spec.md`
- Dashboard hosting: `docs/agent/plans/static-dashboard-hosting/plan.md`
- Static HTML mockups the Advisor's templates now replace: `docs/project/prototypes/`
