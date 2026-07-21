# Architecture — Pipeline Overview

> **Status:** Living document — reflects the current code, not a plan.
> Feature-level design decisions live in `docs/agent/specs/<feature>/spec.md`
> and `docs/agent/plans/<feature>/plan.md`; this file is the map that ties
> those pieces together.

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

## Changes vs. the PRS

The original product requirements spec
(`docs/project/requirements/product-requirements-spec.md`, v1.0) scoped
a four-stage pipeline — Scraper → Tracker → Scorer → Briefing — with
match scores explicitly *not* persisted (Decision D4). The
`advisor-report` initiative (`docs/agent/specs/advisor-report/spec.md`)
added a fifth stage and changed that decision. Each row below is a
deviation from the PRS as originally written, and why:

| PRS said (v1.0) | Now | Why |
|---|---|---|
| Four stages: Scraper → Tracker → Scorer → Briefing. | Six stages: adds **Advisor** and a **Persistence/Report** step between Scorer and Briefing. | A raw 0–100 score used once for the email and discarded (per D4) can't answer "why is this job a good/bad fit for me" or let a student browse past runs — that gap is the whole reason the `advisor-report` work exists (spec, "Problem"). |
| D4: match scores are **not persisted**; the `matches` table and `config_version` correlation are deferred. | Scores (and bands, and gaps) **are persisted**, in `runs` / `run_listings` / `listing_gaps` (`scout/shared/db.py`). | D4 was accepted on the explicit basis that "a persistence step can be added after the Scorer later without redesign" (PRS §5) — this is that step, and it's what makes `history.html` show real past runs instead of hardcoded samples. |
| Only a raw numeric score — no qualitative tiers. | Scores are also classified into a band (`strong_match` / `competitive` / `reach`) via `classify_band(score, settings)`. | A bare number reads as a fake percentage in the UI; a deterministic threshold function (reusing `min_match_score`, adding `strong_match_score`) is simpler and easier to test than an LLM doing the classification. |
| No requirement/skill-gap analysis — out of scope entirely. | A second LLM pass extracts must-have/nice-to-have requirements per listing; `detect_gaps(requirements, profile)` flags skills missing from the student's `profile.json`. | "Gap-first coaching" was the core feature of the `job-detail.html` mockup this initiative wires up — a score alone doesn't tell the student what to go learn. |
| §2.2/§8: no UI beyond the email; rendering deferred/out of scope. | Jinja2 templates render real HTML (dashboard, job-detail, history, profile) from persisted run data; the email gains a link to that day's report. | The `docs/project/prototypes/` mockups were static demos with hardcoded sample data — persisted scores/bands/gaps are dead weight with nothing to render them, so rendering was built in the same initiative instead of deferred again. |
| D2/D3: only the Tracker (deterministic code) writes to the DB; LLM stages produce content only. | **Unchanged.** Advisor's persistence writes happen in the deterministic pipeline layer, not inside its LLM-calling `agent.py`/`runner.py`. | Not revisited — the single-writer rule still holds, just extended to the new tables. |

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
- Original (now partially superseded) product scope: `docs/project/requirements/product-requirements-spec.md`
- Static HTML mockups the Advisor's templates now replace: `docs/project/prototypes/`
