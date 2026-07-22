# Amendments to the Product Requirements Spec

> **Status:** Historical record of the v1.0 → v2.0 transition. `product-requirements-spec.md`
> was updated in place to v2.0 to incorporate these changes as current scope;
> this document keeps the deviation-by-deviation reasoning for why each
> change was made.

The original PRS (`product-requirements-spec.md`, v1.0) scoped a
four-stage pipeline — Scraper → Tracker → Scorer → Briefing — with match
scores explicitly *not* persisted (Decision D4). The `advisor-report`
initiative (`docs/agent/specs/advisor-report/spec.md`) added a fifth
stage and changed that decision. Each row below is a deviation from the
PRS as originally written, and why:

| PRS said (v1.0) | Now | Why |
|---|---|---|
| Four stages: Scraper → Tracker → Scorer → Briefing. | Six stages: adds **Advisor** and a **Persistence/Report** step between Scorer and Briefing. | A raw 0–100 score used once for the email and discarded (per D4) can't answer "why is this job a good/bad fit for me" or let a student browse past runs — that gap is the whole reason the `advisor-report` work exists (spec, "Problem"). |
| D4: match scores are **not persisted**; the `matches` table and `config_version` correlation are deferred. | Scores (and bands, and gaps) **are persisted**, in `runs` / `run_listings` / `listing_gaps` (`scout/shared/db.py`). | D4 was accepted on the explicit basis that "a persistence step can be added after the Scorer later without redesign" (PRS §5) — this is that step, and it's what makes `history.html` show real past runs instead of hardcoded samples. |
| Only a raw numeric score — no qualitative tiers. | Scores are also classified into a band (`strong_match` / `competitive` / `reach`) via `classify_band(score, settings)`. | A bare number reads as a fake percentage in the UI; a deterministic threshold function (reusing `min_match_score`, adding `strong_match_score`) is simpler and easier to test than an LLM doing the classification. |
| No requirement/skill-gap analysis — out of scope entirely. | A second LLM pass extracts must-have/nice-to-have requirements per listing; `detect_gaps(requirements, profile)` flags skills missing from the student's `profile.json`. | "Gap-first coaching" was the core feature of the `job-detail.html` mockup this initiative wires up — a score alone doesn't tell the student what to go learn. |
| §2.2/§8: no UI beyond the email; rendering deferred/out of scope. | Jinja2 templates render real HTML (dashboard, job-detail, history, profile) from persisted run data; the email gains a link to that day's report. | The `docs/project/prototypes/` mockups were static demos with hardcoded sample data — persisted scores/bands/gaps are dead weight with nothing to render them, so rendering was built in the same initiative instead of deferred again. |
| D2/D3: only the Tracker (deterministic code) writes to the DB; LLM stages produce content only. | **Unchanged.** Advisor's persistence writes happen in the deterministic pipeline layer, not inside its LLM-calling `agent.py`/`runner.py`. | Not revisited — the single-writer rule still holds, just extended to the new tables. |

## Where to go next

- Current pipeline shape and stage responsibilities: `docs/project/architecture-pipeline-overview.md`
- Stage-by-stage design rationale and requirements: `docs/agent/specs/<stage>/spec.md`
- Phased implementation history: `docs/agent/plans/<stage>/plan.md` (+ `phase-N.md`)
