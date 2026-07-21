# Plan: Advisor Report

> **Status:** In progress
> **Created:** 2026-07-21 · **Last updated:** 2026-07-21
> **Spec:** [spec.md](../../specs/advisor-report/spec.md)

---

## Overview

Turn the throwaway Advisor mockups into real reports: persist each
run's scored listings, classify them into success bands, detect skill
gaps against the student's profile, and render all four mockup screens
from that real data. Done when a real pipeline run produces a
clickable, real-data dashboard/history/job-detail/profile set of HTML
files, and the email links to that day's report.

## Acceptance Criteria

- [x] `runs`/`run_listings` persist a run's scored listings, readable
      back by date; a same-day re-run updates rather than duplicates.
- [x] `classify_band` returns the correct band for scores at and around
      each threshold boundary; every persisted `run_listing` has a band.
- [x] Requirements extraction returns structured must-have/nice-to-have
      lists per listing; `detect_gaps` correctly flags requirement
      skills absent from the profile's `tech_stack`; gaps are persisted
      in `listing_gaps`.
- [x] `render_run`/`render_history`/`render_profile` produce HTML
      matching each mockup's layout, populated from real data, with
      working cross-screen links.
- [x] The email sends as it does today, with an added link to the
      day's rendered `dashboard.html`.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| Failure handling if persistence write fails after scoring succeeds | Email might not send even though scoring worked, or vice versa | Accepted default: propagate the exception like other stages (spec Open Questions), revisit if too strict in practice |
| `run_date` uniqueness assumes at most one meaningful run per calendar day | A deliberate second run same day silently overwrites the first instead of creating a second history entry | Accepted risk — matches the README's "one scrape → score → track → brief cycle"; revisit if multiple runs/day become a real use case |
| `strong_match_score` default (85) is a guess, not validated against real score distributions | Bands could skew almost everything into one bucket | Accepted risk — tunable via `.env`; revisit once real scored data exists |
| Exact-match skill comparison in `detect_gaps` may miss naming variants ("JS" vs "JavaScript") | Gaps under- or over-reported, undermining the "gap-first coaching" value | Accepted risk for this pass; revisit with real profile/listing data |
| ~~Requirements-extraction batching strategy (batched vs. per-listing) unresolved~~ | Could hit token limits if batched like the scorer | **Resolved in Phase 3**: batched pattern (mirroring the scorer) worked with no token-limit issue encountered |
| No hosting solution — files opened locally via `file://` or a shared path | Might be inconvenient day-to-day, especially from a phone | Accepted risk (spec Open Questions) — ship the simple version, revisit if inconvenient in practice |
| ~~Relative cross-screen links must resolve correctly regardless of where `report_output_dir` is mounted~~ | Broken navigation between rendered screens | **Resolved in Phase 4**: scripted verification against real rendered output found 23/23 links resolving correctly (after one nav-link gap was caught and fixed in review) |
| `run_listings.band` column is nullable with no default while `RunListing.band` is non-Optional `str` (found in Phase 2 review) | A row written before the band migration, or by a future caller that skips banding, would crash `get_run_listings` on read | Accepted risk — no pre-existing data exists yet and every current pipeline write supplies a real band; revisit if this schema ever runs against a database with pre-migration rows |

## Blast Radius

- **Code that will change:** `scout/shared/schema.sql` (additive
  tables/columns), `scout/shared/db.py` (new functions),
  `scout/shared/schemas.py` (new models), `scout/config.py` (new
  settings), `scout/agent.py` (new pipeline steps), new
  `scout/sub_agents/advisor/` package (bands, requirements agent, gap
  detection, templates, rendering), `scout/sub_agents/briefing/email_builder.py`
  (add report link), `docker-compose.yaml` (new volume mount),
  `requirements.txt` (add `jinja2`), `README.md`, new tests under
  `tests/`.
- **Existing behaviour that could break:** `ScoutPipelineAgent`'s
  status-event sequence gains new events (tests asserting the exact
  sequence need updating). `build_email`'s signature gains an optional
  report-link parameter — the no-report-path case must render
  identically to today's email. Scoring and the scorer sub-agent itself
  are not touched.
- **Off-limits:** no changes to `scout/sub_agents/scorer/` internals or
  any redesign of the mockups' HTML/CSS — reuse as-is.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 0 | Student profile schema and loader *(merged from profile-schema)* | [phase-0-profile-schema.md](phase-0-profile-schema.md) | Complete |
| 1 | Schema, db functions, and pipeline wiring (persistence) | [phase-1-persistence.md](phase-1-persistence.md) | Complete |
| 2 | Success-band classification | [phase-2-bands.md](phase-2-bands.md) | Complete |
| 3 | Requirements extraction & gap detection | [phase-3-gaps.md](phase-3-gaps.md) | Complete |
| 4 | Templates and rendering module | [phase-4-templates.md](phase-4-templates.md) | Complete |
| 5 | Pipeline and email wiring (rendering) | [phase-5-wiring.md](phase-5-wiring.md) | Complete |

---

## Testing Strategy

- **Unit:** db read/write functions against a real Postgres test
  database (matching `upsert_listing`'s existing pattern);
  `classify_band` boundary tests; `detect_gaps` tests with profiles
  that fully cover, partially cover, and entirely miss a listing's
  requirements; rendering tests asserting known fixture data appears in
  the rendered HTML.
- **Integration:** a full `ScoutPipelineAgent` run (fake scraper/scorer,
  matching existing `test_agent.py` fixtures) resulting in a persisted,
  banded, gap-annotated run with rendered report files and cross-screen
  links that resolve to files that were actually written.
- **Manual:** `docker compose up --build` end to end, then open
  `reports/<date>/dashboard.html` in a browser, click through to
  job-detail, profile, and history, and confirm the received email
  links to it.

## Rollout & Reversibility

- **Feature flag:** no — additive schema and pipeline steps, always on.
- **Migrations:** additive only (`CREATE TABLE IF NOT EXISTS`,
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`), applied automatically via
  the existing `apply_schema` on startup. No existing table's shape
  changes; reversible by dropping the new tables/columns.
- **Rollback plan:** each phase's wiring step can be reverted
  independently in `scout/agent.py` (persistence, then band/gap calls,
  then rendering calls) to stop writing new data; `build_email`'s
  report-link parameter is optional and falls back to today's plain
  email. Existing persisted/rendered data can be left in place
  (harmless, unread) or cleared manually.

---

## Key Decisions & Constraints

- Persistence, enrichment, and rendering are phases of one plan, not
  separate plans — none is independently useful (see spec.md
  Alternatives Considered).
- `run_listings` stores score/reasoning/band together; gaps live in a
  separate `listing_gaps` table.
- Bands are threshold-derived from the existing score, not LLM-assigned.
- Gap detection compares against `tech_stack` only, not
  `domain_knowledge`, in this pass; no GitHub resource verification.
- Jinja2 templates reuse the mockups' existing HTML/CSS as-is; reports
  are static files on a mounted volume, not a hosted server.
- Email is kept and gains a link; it is not replaced by the rendered
  report.
- ⚠️ **One-way doors:** the `runs`/`run_listings` schema (Phase 1) and
  the `run_listings.band` column + `listing_gaps` table (Phase 2/3) —
  each gated on human sign-off in its phase doc before running against
  a real database.

## Out of Scope

- GitHub resource verification for skill gaps.
- Domain-knowledge gap detection.
- Any hosting/server solution for the reports.
- Editing `profile.json` from a UI.
- Retention/pruning of old runs.

---

## Definition of Done

- [x] All acceptance criteria met
- [x] All phase verification steps pass — all automated checks; each
      phase's one "Manual" checkbox (browser click-through / `docker
      compose up --build`) was satisfied by an equivalent scripted
      check against real Postgres instead, except Phase 5's full
      `docker compose up --build` pass, still outstanding (see below)
- [ ] Feature verified manually in a running environment — **not yet
      done**: a real `docker compose up --build` end-to-end run
      (confirming `./reports/<date>/` appears on the host and a real
      email arrives with a working link) is outstanding. This is the
      one remaining item before merge — everything else is done.
- [x] Docs / README updated where behaviour changed (`reports/`
      output directory, new `.env` settings, `scout/profile.json`
      setup step)
- [x] No new lint or type-check warnings — full suite green throughout
      (197/197), no new warnings beyond pre-existing third-party
      deprecations

## Final Whole-Branch Review

Two rounds. First pass found the branch architecturally sound (clean
reuse of the scorer's LLM-agent pattern for requirements extraction,
consistent real-Postgres testing throughout, correct additive
migrations, genuine backward compatibility with no `profile.json`) but
caught one cross-phase issue no single task-scoped review could see:
the emailed report link resolved to the Docker container's internal
path (`/app/reports/...`), not the host path, so it would never open
for the user. Also flagged (Minor): the "My Profile" nav link 404s
when no profile is configured, since `profile.html` is only rendered
when one exists.

Both fixed: an optional `REPORT_HOST_DIR` setting now produces a real
clickable link when configured, falling back to a plain (never broken)
relative-path text by default; the nav link is now gated on profile
presence across all three templates that show it. Second review round
confirmed both fixes correct with no regressions.

**Verdict: Ready to merge** (pending the one outstanding manual
`docker compose up --build` pass — see Definition of Done above).

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.

## Amendments

- 2026-07-21: Merged the `profile-schema` plan into this one as Phase 0
  (its phase doc moved here unchanged as `phase-0-profile-schema.md`).
  Rationale: `profile.json`/`load_profile` is the data source this
  Advisor feature's gap-detection and profile-rendering phases (2-5)
  read from — the two were already described as one initiative in
  spec.md's Problem statement, and `profile-schema` was small enough
  not to warrant staying a separate top-level plan now that both are
  complete. Original `docs/agent/plans/profile-schema/` folder deleted.

### Merged: Student Profile Schema plan summary

**Status:** Complete.

**Goal:** a validated, typed data model for a student profile
(tech-stack proficiency by category, domain knowledge, background,
projects) plus a JSON loader for it, so the Advisor mockups have a
real data source to render from.

**Acceptance criteria (all met):**
- `Profile` and its nested models exist in `scout/shared/schemas.py`
  and validate every field shown in `profile.html`.
- `load_profile(path)` in `scout/shared/profile.py` loads and
  validates a profile JSON file, raising `FileNotFoundError` for a
  missing file and `pydantic.ValidationError` for malformed data.
- `scout/profile.json.example` parses successfully and matches the
  mockup's sample data.
- Full existing test suite passes unmodified.

**Key decisions carried forward:** `profile.json` is additive
alongside `resume.txt`, not a replacement; tech-stack categories are
freeform strings, not an enum; the domain-knowledge level label is
derived from the proficiency number, never stored separately; nothing
in this phase wired the loader into `Settings` or any pipeline stage —
that wiring is what Phases 1-5 of this plan (persistence, bands, gaps,
templates, rendering) built on top of it.
