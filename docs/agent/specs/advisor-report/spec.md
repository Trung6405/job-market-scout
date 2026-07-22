# Spec: Advisor Report

> **Status:** Draft
> **Created:** 2026-07-21 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/advisor-report/plan.md) *(created after approval)*

---

## Problem

The `docs/project/prototypes/` HTML mockups (dashboard, history, job-detail,
profile) are throwaway static demos with hardcoded sample data — that's
the whole reason this line of work exists (the original ask: "wire the
pipeline output to these mockups"). Making them real requires three
things the pipeline doesn't do today, none of which is useful without
the others: nothing persists a run's scored listings past the next
scrape/score cycle (`run_scorer`'s output is used once for the email
and discarded), nothing turns a raw 0-100 score into the qualitative
success band the mockups show ("success = band, not a fake %"), nothing
identifies which of a role's requirements the student's profile doesn't
cover ("gap-first coaching," `job-detail.html`'s core feature), and
nothing renders any of it into the actual HTML screens. Because
persisted data with no bands/gaps is dead weight, and rendering has
nothing to read without persistence and enrichment, these are one
initiative delivered across ordered phases, not independent sub-projects
— unlike the student-profile schema (`docs/agent/specs/profile-schema/spec.md`),
which is useful standalone and is already built.

## Success Criteria

- After a pipeline run, a student can open that day's rendered
  `dashboard.html` and see real scored listings with real success
  bands, click into `job-detail.html` for a real role and see real
  flagged skill gaps against their profile, and browse `history.html`
  for past days — none of it hardcoded sample data.
- Re-running the pipeline on the same day updates rather than duplicates
  that day's history entry.
- The existing email keeps working exactly as it does today, with an
  added link to the day's report.

---

## Requirements

### Must have

- A `runs` table (one row per pipeline run, keyed by date) and a
  `run_listings` table (score, reasoning, and success band per scored
  listing in a run), persisted after scoring and readable back by date
  for history.
- A deterministic `classify_band(score, settings)` function mapping the
  scorer's existing 0-100 score to `strong_match` / `competitive` /
  `reach`, using threshold settings (reusing the existing
  `min_match_score` as the Competitive floor, plus a new
  `strong_match_score`).
- A new LLM extraction step producing structured must-have/nice-to-have
  requirements per listing, and a pure `detect_gaps(requirements,
  profile)` function flagging requirement skills absent from the
  student's `profile.json` `tech_stack`, persisted in a `listing_gaps`
  table.
- Jinja2 templates for all four mockup screens, adapted from the
  existing static HTML (same visual design — this is a data-wiring
  exercise, not a redesign), and a rendering module that, given a
  `run_id`, writes real HTML to disk with correct cross-screen links.
- The email keeps sending as it does today, with an added link to that
  day's rendered `dashboard.html`.

### Should have

- Band/threshold values pulled from `Settings` (`.env`-tunable), not
  hardcoded.
- Idempotent run creation (`run_date` unique) so a same-day re-run
  updates rather than duplicates.
- Report output written to a Docker-mounted directory (`./reports` on
  the host) so the student can open files directly, no server needed.

### Won't have

- GitHub resource verification for skill gaps — explicitly descoped
  from the Advisor feature for now; gaps are surfaced with a skill name
  and requirement level, no attached resource link.
- Domain-knowledge gap detection — job-detail's checklist is scoped to
  `tech_stack` skills only for this pass.
- Any hosting/server solution for the reports, or replacing the email
  with the rendered report — the email is kept and gains a link.
- Editing `profile.json` from the UI — `profile.html` stays read-only.
- Retention/pruning of old runs.

---

## Proposed Approach

Three ordered layers, each built as its own plan phase (see
`plan.md`), sharing one schema/db module and one new `advisor`
sub-agent package:

**Persistence** — additive tables in `scout/shared/schema.sql`
(`runs`, `run_listings`), applied automatically via the existing
`apply_schema` (no manual migration step, matching the `listings` table
convention):

```sql
CREATE TABLE IF NOT EXISTS runs (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL UNIQUE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    listings_scraped INT NOT NULL DEFAULT 0,
    listings_scored INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run_listings (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    listing_id BIGINT NOT NULL REFERENCES listings (id),
    score INT NOT NULL CHECK (score BETWEEN 0 AND 100),
    reasoning TEXT NOT NULL,
    UNIQUE (run_id, listing_id)
);
```

New read/write functions in `scout/shared/db.py`:

- `start_run(conn, run_date) -> int` — `INSERT ... ON CONFLICT (run_date)
  DO UPDATE SET started_at = now() RETURNING id`, so a same-day re-run
  reuses the row.
- `finish_run(conn, run_id, listings_scraped, listings_scored)` —
  updates counts and `finished_at`.
- `record_run_listings(conn, run_id, matches: list[MatchResult])` —
  bulk-inserts scored listings for the run, `ON CONFLICT (run_id,
  listing_id) DO UPDATE` so a re-run overwrites rather than duplicates.
- `get_run_by_date(conn, run_date) -> Run | None` and `list_runs(conn,
  limit) -> list[Run]` for history navigation.
- `get_run_listings(conn, run_id) -> list[RunListing]` for the dashboard
  view of one run.

Wired into `ScoutPipelineAgent` right after `run_scorer`, before
`run_briefing`.

**Enrichment** — a new `scout/sub_agents/advisor/` package, mirroring
the existing `scorer` sub-agent's shape: `bands.py` (pure
`classify_band`), `agent.py`/`runner.py` (an `LlmAgent` with
`output_schema=ListingRequirements`, reusing the scorer's exact
structured-output pattern), `gaps.py` (pure `detect_gaps`). Extends the
persistence schema additively (`run_listings.band`, new
`listing_gaps` table).

**Rendering** — templates in `scout/sub_agents/advisor/templates/`
(`.html.jinja` versions of the four mockups) and a `report.py` module
(`render_run`, `render_history`, `render_profile`) that reads persisted
data plus `load_profile` and writes HTML to
`settings.report_output_dir`. Wired into `ScoutPipelineAgent` after
enrichment and before `run_briefing`; `build_email` gains an optional
report-link parameter.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Keep persistence, enrichment, and rendering as three separate specs/plans (the original decomposition) | Revisited after drafting all three: none is independently shippable or useful on its own — persisted data with no rendering, or rendering with nothing persisted, delivers nothing. One spec/plan with ordered phases matches the actual dependency shape better and avoids three near-duplicate "why this matters" sections for one initiative. |
| Store score/band directly on `listings` instead of a separate `runs`/`run_listings` pair | `listings` rows are upserted in place on every scrape — today's score would overwrite yesterday's, making a day-by-day history impossible to reconstruct. |
| LLM-driven band classification instead of score thresholds | Non-deterministic and harder to test than a threshold function over the score the scorer already produces. |
| Keyword/regex matching for gap detection instead of an LLM extraction step | Brittle against phrasing variance, needs a maintained skill dictionary; the LLM extraction step reuses a pattern already proven by the scorer. |
| Replace the email body with the rendered report (inline HTML) | Bigger change to `email_builder.py`, and email clients render HTML inconsistently in ways the mockups aren't designed around. |
| A small local web server instead of static report files | Adds a new always-running process/port to the docker-compose stack for a single-user personal tool; static files opened directly match the mockups' own "no build step" philosophy. Revisit if remote/multi-device access is ever needed. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| If persisting a run fails partway (e.g. DB write error after scoring succeeds), should the pipeline still send the email, or abort? | human | no — default to propagating the exception, matching how scraper/scorer/briefing failures already abort the run |
| Exact value for the new `strong_match_score` threshold (proposed default: 85) | human | no — 85 is a reasonable starting default, tunable via `.env` like `MIN_MATCH_SCORE` already is |
| Exact-match vs. fuzzy-match for `detect_gaps` skill-name comparison | human | no — start with exact lower-cased match (simplest, no new dependency); revisit if it visibly over/under-flags against real profiles |
| Batch size / prompt shape for requirements extraction (one LLM call per listing vs. batched like the scorer) | human / spike | no — default to batched, mirroring `build_scorer_agent`'s existing pattern, unless token limits force per-listing calls |
| Reports are local files with no hosting — is a local path/`file://` link in the email good enough day to day? | human | no — ship the simple version first; revisit once actually used |
| Should `profile.html` re-render every run, or only when `profile.json`'s mtime changes? | human | no — default to "every run" (cheap render); optimize only if it becomes a measurable cost |

---

## Amendments

- 2026-07-21: Merged in the `profile-schema` spec (see appendix below) — the student-profile data model this Advisor feature reads via `load_profile`/`profile.json`. It was already independently useful and built before this spec existed (see this spec's Problem statement), but is small enough to fold in here rather than keep as its own top-level doc. Content unchanged in substance; original file deleted.
- 2026-07-22: Closed most of the gap Phase 4's review flagged but deliberately deferred ("`job-detail.html.jinja` conversion dropped several mockup sections... beyond what earlier phases built the underlying data for" — `phase-4-templates.md` Notes). Comparing the rendered output against `docs/project/prototypes/` found the mockup's role-snapshot grid, per-category match-breakdown bars, full requirements-vs-profile checklist, and positioning tips were still missing, plus two real bugs: `runs.listings_scored` counted the scorer's raw output instead of what actually got persisted/rendered (so the dashboard's run-meta line could disagree with its own stats/card list whenever `join_match_results` dropped a mismatched score), and the dashboard's prev/next day arrows were hardcoded `disabled` even when an adjacent day's run existed. Fixed:
  - `runs.listings_scored` now records `len(matches)` (the joined, persisted set), not `len(scores)` (`scout/agent.py`).
  - A new `get_adjacent_runs(conn, run_date)` (`scout/shared/db.py`) backs real prev/next links in the dashboard daybar (`render_run` now passes `prev_run`/`next_run` to the template), replacing the always-disabled arrows.
  - `SkillGap` gained a `met: bool` field; `gaps.py` gained `evaluate_requirements(requirements, profile)`, returning every stated requirement (met or not), with `detect_gaps` now a thin `not met` filter over it — the data the Phase 4 review said didn't exist yet. `listing_gaps` gained a `met` column and now stores the full per-listing requirement checklist, not just the gaps; `RunListingDetail` gained a parallel `requirements` list alongside the existing (unmet-only) `gaps`.
  - The must-have/nice-to-have extraction prompt (`build_requirements_instruction`) now also asks for `seniority`, `work_type`, and `team`, each nullable and extracted only when the listing states it — never guessed. `run_listings` gained matching nullable columns, written by a new `record_listing_meta(conn, run_id, meta_by_match)` call (needed because this data is only known after the requirements-extraction step, which runs after `record_run_listings`).
  - `job-detail.html.jinja` now renders a role-snapshot section (only the fields actually stated), a match-breakdown section (must-have and nice-to-have coverage bars, computed from real counts — no fabricated per-category scores like "domain knowledge fit" or "seniority match" the mockup showed, since nothing extracts those), the full requirements checklist (have/gap per stated requirement), and a deterministic "how to position your application" section derived from the real gap list (not a new LLM call).
  - GitHub resource cards remain out of scope (per this spec's own "Won't have" and the mockup README's framing as a distinct, unbuilt feature — live search, link verification, and a new sub-agent, not a template change).
  - All additive via the existing `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration convention; full test suite green (205/205) throughout.

---

## Appendix: Student Profile Schema *(merged from `docs/agent/specs/profile-schema/spec.md`, approved 2026-07-21)*

### Problem

The `docs/project/prototypes/` HTML mockups for the Advisor report UI (dashboard, history, job-detail, profile) were built as throwaway static demos with hardcoded sample data. `profile.html` in particular assumes a structured student profile — categorised tech-stack proficiency, domain-knowledge levels, background, and tagged projects — that the pipeline had no way to represent. The only student-facing input the pipeline read was `scout/resume.txt`, a plain-text blob fed straight into the scorer's LLM prompt with no structure a program could reason over. Wiring the mockups to real pipeline output required a real data source for that structure — starting with a schema and loader for it.

### Success Criteria

- A student profile can be authored as a JSON file and loaded into a validated, typed Python object that mirrors every section shown in `profile.html` (identity/target, tech stack by category, domain knowledge, background, projects).
- Malformed or missing profile data fails loudly and specifically (missing file vs. invalid schema), the same way the existing resume loader does.
- The existing pipeline (scraper → scorer → tracker → briefing) is provably unaffected — nothing new is required at startup that isn't already required today.

### Requirements

**Must have:** Pydantic models for tech skill (name, 1-5 proficiency, optional note), tech category (freeform name + list of skills), domain knowledge (name, 0-100 proficiency, description), background (education, experience, preferred roles, locations), project (title, description, tags), and a top-level `Profile` tying them together with name, target role, and target locations. A `load_profile(path)` function reading a JSON file and returning a validated `Profile`, raising `FileNotFoundError` for a missing file and letting `pydantic.ValidationError` propagate for malformed data. An example profile file (`scout/profile.json.example`) populated with sample data, following the existing `resume.txt.example` convention.

**Should have:** a single, unambiguous source of truth for the domain-knowledge "level" label (Solid/Good/Developing/Emerging) shown next to each proficiency bar, so the label can never disagree with the number.

**Won't have:** rendering `profile.json` into any template (that's this spec's own Rendering layer, above); wiring `profile.json` into `scout.config.Settings`, the scorer, or the briefing pipeline; replacing `resume.txt` (it keeps driving the scorer's LLM prompt unchanged — `profile.json` is additive); GitHub resource verification for skill gaps.

### Proposed Approach

The profile data model lives in `scout/shared/schemas.py`, alongside the existing `Listing`/`MatchResult`/`BriefingProse` models. A small loader module, `scout/shared/profile.py`, mirrors the pattern already used for resume loading in `scout/config.py` (`_read_resume_text`): resolve the path, raise `FileNotFoundError` if missing, otherwise parse and validate. `scout/profile.json.example` ships as the reference instance.

The domain-knowledge "level" label is derived from the stored 0-100 proficiency number via fixed thresholds (`>=70` Solid, `>=50` Good, `>=30` Developing, else Emerging — chosen to match the mockup's own worked examples), exposed as a computed property rather than a second stored field.

Nothing wires this loader into `Settings` or any pipeline stage — it's a standalone schema + loader that this Advisor feature (and any future sub-project) imports.

### Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Replace `resume.txt` with `profile.json` as the scorer's input | Bigger blast radius (touches the working scorer prompt) for no immediate benefit; the mockups only need profile data for the advisor report, not for re-scoring. Deferred. |
| Fixed enum of tech-stack categories matching the mockup exactly | Stricter validation, but adding a category later (e.g. "Mobile") would require a code change; freeform strings cost nothing today. |
| Store the domain-knowledge level label as its own authored field | More editorial control, but the label and the percentage bar could drift out of sync with no validation catching it. Deriving from a threshold keeps one source of truth. |
| Render `profile.html` from real data ahead of the full report-rendering work | Would pull in a templating decision before that work had scoped it, and duplicate work once it started. Deferred. |
