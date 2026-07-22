# Spec: Profile as the single candidate source

> **Status:** Draft
> **Created:** 2026-07-22 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/profile-candidate-source/plan.md) *(created after approval)*

---

## Problem

The pipeline describes the candidate twice: scoring and the briefing email
read a free-text `resume.txt`, while gap detection reads the structured
`profile.json`. The two drift — in the current deployment `resume.txt` is
the generic 3-line placeholder while `profile.json` holds the real,
detailed candidate data. As a result the scorer grades every listing
against a vague resume and rates them all "out of reach," even though a
rich profile (skills with proficiency, experience, projects) is available.
Maintaining two candidate representations is redundant and the source of
this quality gap.

## Success Criteria

- The scorer and briefing reason about the candidate using the profile's
  real content (skills, proficiency, background, projects), not a separate
  resume blob.
- There is exactly one candidate artifact to maintain (`profile.json`).
- A missing or invalid profile fails fast with a clear error instead of
  silently degrading output.

---

## Requirements

### Must have

- `profile.json` is the single, required candidate source, used by scoring,
  the briefing, and gap detection.
- The profile is rendered into a readable text block for the scorer and
  briefing LLM prompts (proficiency levels expressed as words).
- A missing/invalid profile raises a clear error at startup.
- `resume.txt`, its config loading, its Docker mount, and its deploy/CI
  steps are removed.

### Should have

- The profile→text renderer is a pure, independently unit-tested function
  reused by both prompts.

### Won't have

- No change to the operational filters (`preferred_locations`,
  `remote_only`, `min_salary`) — they stay as-is; the profile's
  `target_locations`/`target_role` remain informational, not wired into
  filtering. *(Keeps scope to candidate context, not a filtering overhaul.)*
- No scraper/proxy changes — the cloud-IP scrape shortfall is a separate
  issue.
- No change to requirements-extraction or gap-detection logic itself.

---

## Proposed Approach

Make `Settings` own the profile in the slot `resume_text` occupied.
At construction, config loads `profile_path` into `settings.profile: Profile`,
failing fast if the file is missing or invalid — exactly the role
`_read_resume_text` played for the resume.

A pure helper `render_profile_text(profile) → str` produces a resume-like
candidate block (target role; skills with proficiency mapped to words such
as "Python (advanced)"; background/experience; domain knowledge; project
one-liners). The scorer and briefing prompt builders call it in place of
the former `Resume:\n{settings.resume_text}` block; the surrounding
`preferred_locations` / `remote_only` / `min_salary` lines are unchanged.

Because the profile is now always present, the pipeline drops its separate
`load_profile` call and the "profile is None → skip gaps" branch: gap
detection always runs, reading `settings.profile`.

`resume.txt` is retired end to end: the file and its example, the
`./scout/resume.txt` compose mount, the deploy "Render resume.txt on VM"
and CI "Provide resume placeholder for tests" steps, and `RESUME_PATH` in
config/`.env.example`. `profile.json` is already committed and reaches the
VM via rsync, so no secret-injection step replaces the resume one.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Profile primary, resume optional supplement | Keeps two candidate artifacts that can drift — the exact problem being fixed. |
| Feed both resume and profile to the scorer | Doesn't remove drift and keeps the placeholder-resume footgun. |
| Embed the profile as raw JSON in the prompt | Reads less naturally; proficiency integers need an inline legend. Rendered text keeps the existing rubric shape. |
| Load profile in the pipeline and thread it through `run_scorer`/`run_briefing` | More plumbing and signature changes; asymmetric with how config already owns candidate data. |
| Do nothing | Scorer keeps grading against a placeholder resume; every listing stays "out of reach." |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| `load_profile` must not import `Settings` (circular import); if it does, the loader moves to a neutral module. | spike (phase 1) | no |
| Whether to eventually move `profile.json` out of git into a `PROFILE_JSON` secret. | human | no |

> Questions marked "blocks planning: yes" must be resolved before
> plan.md is written. The rest carry into the plan's Risks & Unknowns.

---

## Amendments *(only after approval — never silently edit approved content)*

- —
