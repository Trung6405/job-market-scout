# Spec: Student Profile Schema

> **Status:** Approved
> **Created:** 2026-07-21 · **Approved:** 2026-07-21
> **Implementation plan:** [plan.md](../../plans/profile-schema/plan.md)

---

## Problem

The `docs/project/prototypes/` HTML mockups for the Advisor report UI (dashboard,
history, job-detail, profile) were built as throwaway static demos with
hardcoded sample data. `profile.html` in particular assumes a structured
student profile — categorised tech-stack proficiency, domain-knowledge
levels, background, and tagged projects — that the pipeline has no way to
represent today. The only student-facing input the pipeline currently
reads is `scout/resume.txt`, a plain-text blob fed straight into the
scorer's LLM prompt; it has no structure a program can reason over (e.g.
"which skills is this student below-target on"). Wiring the mockups to
real pipeline output requires a real data source for that structure —
starting with a schema and loader for it.

## Success Criteria

- A student profile can be authored as a JSON file and loaded into a
  validated, typed Python object that mirrors every section shown in
  `profile.html` (identity/target, tech stack by category, domain
  knowledge, background, projects).
- Malformed or missing profile data fails loudly and specifically
  (missing file vs. invalid schema), the same way the existing resume
  loader does.
- The existing pipeline (scraper → scorer → tracker → briefing) is
  provably unaffected — nothing new is required at startup that isn't
  already required today.

---

## Requirements

### Must have

- Pydantic models for: tech skill (name, 1-5 proficiency, optional
  note), tech category (freeform name + list of skills), domain
  knowledge (name, 0-100 proficiency, description), background
  (education, experience, preferred roles, locations), project (title,
  description, tags), and a top-level `Profile` tying them together with
  name, target role, and target locations.
- A `load_profile(path)` function that reads a JSON file and returns a
  validated `Profile`, raising `FileNotFoundError` for a missing file and
  letting `pydantic.ValidationError` propagate for malformed data.
- An example profile file (`scout/profile.json.example`) populated with
  the same "Minh Nguyen" sample data used in `profile.html`, following
  the existing `resume.txt.example` convention.

### Should have

- A single, unambiguous source of truth for the domain-knowledge "level"
  label (Solid/Good/Developing/Emerging) shown next to each proficiency
  bar in the mockup, so the label can never disagree with the number.

### Won't have

- Rendering `profile.json` into `profile.html` or any other template —
  that belongs to the later "report rendering" sub-project, once
  persistence and gap-detection data exist to render alongside it.
- Wiring `profile.json` into `scout.config.Settings`, the scorer, or the
  briefing pipeline — no existing behaviour should change as a result of
  this work.
- Replacing `resume.txt` — it keeps driving the scorer's LLM prompt
  unchanged; `profile.json` is an additive, separate source for the
  advisor-report line of work.
- GitHub resource verification for skill gaps — descoped from the
  overall advisor feature for now, tracked separately if picked up
  later.

---

## Proposed Approach

Add the profile data model to `scout/shared/schemas.py`, alongside the
existing `Listing`/`MatchResult`/`BriefingProse` models, so all pipeline
schemas live in one place. Add a small loader module,
`scout/shared/profile.py`, mirroring the pattern already used for resume
loading in `scout/config.py` (`_read_resume_text`): resolve the path,
raise `FileNotFoundError` if it's missing, otherwise parse and validate.
Ship `scout/profile.json.example` as the reference instance, matching
`scout/resume.txt.example`'s role as a checked-in template a student
copies and edits.

The domain-knowledge "level" label is derived from the stored 0-100
proficiency number via fixed thresholds (`>=70` Solid, `>=50` Good,
`>=30` Developing, else Emerging — chosen to match the mockup's own
worked examples), exposed as a computed property rather than a second
stored field.

Nothing wires this loader into `Settings` or any pipeline stage in this
pass — it's a standalone schema + loader that later sub-projects (gap
detection, report rendering) will import.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Replace `resume.txt` with `profile.json` as the scorer's input | Bigger blast radius (touches the working scorer prompt) for no immediate benefit; the mockups only need profile data for the *advisor report*, not for re-scoring. Deferred — can revisit once profile.json is proven out. |
| Fixed enum of tech-stack categories matching the mockup exactly | Stricter validation, but adding a category later (e.g. "Mobile") would require a code change; freeform strings cost nothing today and the mockup's categories are just examples, not a closed set. |
| Store the domain-knowledge level label as its own authored field | More editorial control over wording, but the label and the percentage bar could drift out of sync with no validation catching it. Deriving from a threshold keeps one source of truth. |
| Render `profile.html` from real data now, ahead of the full report-rendering sub-project | Would pull in a templating decision (Jinja2 vs. something else) before the report-rendering sub-project has scoped it, and duplicate work once that sub-project starts. Deferred. |

---

## Open Questions

None — all resolved during brainstorming before implementation started.

---

## Amendments

- 2026-07-21: The "report rendering" and "gap detection" sub-projects
  referenced above (Won't Have, Proposed Approach, Alternatives
  Considered) were merged into a single spec/plan,
  [`docs/agent/specs/advisor-report/spec.md`](../advisor-report/spec.md) /
  [`docs/agent/plans/advisor-report/plan.md`](../../plans/advisor-report/plan.md),
  since persistence, band/gap enrichment, and rendering turned out to
  be one initiative delivered in ordered phases, not independent
  sub-projects. No requirement or decision in this spec changed.
