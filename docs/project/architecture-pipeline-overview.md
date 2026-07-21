# Architecture — Pipeline Overview

> **Status:** Living document — reflects the current code, not a plan.
> Feature-level design decisions live in `docs/agent/specs/<feature>/spec.md`
> and `docs/agent/plans/<feature>/plan.md`; this file is the map that ties
> those pieces together. For how this shape diverges from the original
> product scope, see `docs/project/specification/product-requirements-spec-amendments.md`.

## Pipeline

`scout/agent.py`'s `ScoutPipelineAgent` runs six stages in order, in a
single container, per daily run:

```
Scraper → Tracker → Scorer → Advisor → Persistence/Report → Briefing
```

🤖 = LLM agent stage · ⚙️ = deterministic code stage

| Stage | Type | Module | Responsibility |
|---|---|---|---|
| **Scraper** | 🤖 | `scout/sub_agents/scraper/` | Fetch current job listings for the configured roles/locations from job boards and the web. |
| **Tracker** | ⚙️ | `scout/sub_agents/tracker/` | Diff scraped listings against the DB; persist all listings; mark new/changed/closed; dedupe; pass only new/changed listings downstream. |
| **Scorer** | 🤖 | `scout/sub_agents/scorer/` | LLM-score each relevant listing 0–100 against the configured resume/preferences. |
| **Advisor** | 🤖 + ⚙️ | `scout/sub_agents/advisor/` | Turn raw scores into personalized guidance — see below. |
| **Briefing** | 🤖 | `scout/sub_agents/briefing/` | Summarize the run and email the daily briefing, linking to the rendered report. |

## Why the Advisor stage exists

The Scorer only produces a number (0–100) per listing, used once for
the email and then discarded. That's not enough to answer "why is this
job a good/bad match for me" or to let a student browse past runs. The
Advisor stage exists to close that gap. It has four responsibilities:

- **`agent.py` / `runner.py`** — a second LLM pass (DeepSeek via
  `LiteLlm`) that extracts structured requirements (must-have /
  nice-to-have skills) from each listing's raw text.
- **`gaps.py`** — pure function `detect_gaps(requirements, profile)`
  diffing extracted requirements against the student's
  `profile.json` `tech_stack`, flagging missing skills.
- **`bands.py`** — pure function `classify_band(score, settings)`
  mapping the Scorer's 0–100 score into a qualitative band
  (`strong_match` / `competitive` / `reach`) using threshold settings.
- **`report.py`** — renders persisted run data (via Jinja2 templates in
  `advisor/templates/`) into the actual HTML screens: a per-run
  dashboard, per-job detail pages with flagged gaps, a cross-run
  history page, and a profile page.

The requirements-extraction step is skipped (with a status event) if
no `profile.json` exists yet — bands still render, but gap detection
needs a profile to diff against.

## Persistence

`scout/shared/db.py` owns two run-scoped tables written by
`ScoutPipelineAgent` after scoring: `runs` (one row per run, keyed by
date) and `run_listings` (score + band per listing), plus
`listing_gaps` (flagged missing skills per listing, when a profile
exists). This is what makes `history.html` real instead of hardcoded
sample data — see `docs/agent/specs/advisor-report/spec.md` for the original
problem statement and success criteria.

## Where to go next

- Stage-by-stage design rationale and requirements: `docs/agent/specs/<stage>/spec.md`
- Phased implementation history: `docs/agent/plans/<stage>/plan.md` (+ `phase-N.md`)
- Current product scope: `docs/project/specification/product-requirements-spec.md`; for the v1.0 → v2.0 change history, see its `product-requirements-spec-amendments.md`
- Static HTML mockups the Advisor's templates now replace: `docs/project/prototypes/`
