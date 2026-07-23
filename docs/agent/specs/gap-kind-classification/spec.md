# Spec: Requirement Kind Classification for Skill Gaps

> **Status:** Approved
> **Created:** 2026-07-23 · **Approved:** 2026-07-23
> **Implementation plan:** [plan.md](../../plans/gap-kind-classification/plan.md) *(created after approval)*

---

## Problem

The advisor's job-detail report lists "skill gaps to close" for each
listing, and users trust that list to decide where to invest. But the list
is polluted with false gaps: requirements that the candidate already
satisfies are shown as missing. The clearest example is a listing that
asks for "a STEM degree with a meaningful computer science component" being
flagged as an unmet gap even though the profile records a B.Sc. in Computer
Science. This happens for any requirement that is not a bare technical
skill — degrees, years-of-experience thresholds, and soft skills all appear
as gaps the candidate can never "close." The result is a report that
undercounts the candidate's fit and points them at work that isn't real.

## Success Criteria

- A requirement that is a qualification, an experience threshold, or a soft
  skill never appears in a listing's "skill gaps to close" list.
- The "STEM degree in CS" style requirement, for a profile that holds a CS
  degree, is not counted as a gap and does not reduce must-have coverage.
- Genuine technical-skill gaps (e.g. a required framework the profile lacks)
  are still detected and shown exactly as before.
- Non-skill requirements the listing states are still visible to the user
  as context, clearly separated from the pass/fail skill checklist.

---

## Requirements

### Must have

- Every extracted requirement carries a classification into a small, closed
  set of kinds distinguishing technical skills from non-skill requirements.
- Only technical-skill requirements are matched against the profile and are
  eligible to be gaps.
- Non-skill requirements are excluded from gap detection and from must-have
  coverage counts, regardless of any stored match flag.
- Non-skill requirements remain visible in the report as informational
  context, without a met/unmet mark.
- Persisted runs created before this change continue to render sensibly
  (their requirements default to the technical-skill kind, i.e. the legacy
  behavior).

### Should have

- The classification kind is a closed typed vocabulary validated at the
  schema boundary, consistent with the existing `band` vocabulary, so an
  unexpected kind fails loudly rather than silently mislabeling.

### Won't have

- Any met/unmet judgement on non-skill requirements — the tool will not try
  to decide whether the profile satisfies a degree/experience/soft-skill
  requirement, because fuzzy matching against free-text education and
  experience is exactly the false-positive source being removed.
- Handling of listings that extract zero requirements (typically vague,
  prose-heavy senior postings that surface as "reach" with no gaps) — that
  is an extraction-quality concern, out of scope here.
- Expanding skill matching beyond `profile.tech_stack` (e.g. into
  `domain_knowledge` or `projects`) — not needed to fix the false positives.

---

## Proposed Approach

Tag every extracted requirement with a **kind**, and only string-match the
skill kind against the profile. The requirements extractor already produces
`must_have` / `nice_to_have` lists; each entry becomes a small object
carrying its name plus a kind drawn from a closed vocabulary:

- `skill` — a concrete technical skill or tool (e.g. PostgreSQL, React).
- `qualification` — a degree, certification, or credential.
- `experience` — a years/seniority threshold.
- `soft_skill` — communication, teamwork, and similar non-technical traits.

The extractor prompt gains an instruction to classify each requirement; the
existing "canonical short skill name" rule is scoped to the `skill` kind,
while the other kinds may stay as natural phrases.

Gap evaluation normalizes and matches **only `skill`-kind** requirements
against `profile.tech_stack`, exactly as today. Non-skill requirements pass
through carrying their kind and are never treated as gaps — gap computation
selects on kind, not merely on a match flag, so a non-skill requirement can
never leak into the gap list.

Persistence carries the kind alongside each stored requirement. The report
renders the pass/fail checklist, the match breakdown, the "skill gaps to
close" list, and the must-have coverage count from `skill`-kind items only;
non-skill requirements render in a separate informational section with no
met/unmet mark. Existing stored rows, which have no kind, default to `skill`
so they keep their current rendering.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Split the schema into separate `skills[]` and `qualifications[]`/`experience[]` fields instead of one tagged list | Larger, more invasive change across prompt, schema, DB, and templates for no additional correctness; the tagged-list approach keeps the existing must/nice structure intact. |
| Constrain the extractor to emit only technical skills and drop degrees/experience/soft skills entirely | Loses information the user finds useful as context; the report would silently omit stated requirements. |
| Best-effort met/unmet on non-skill requirements (heuristic match against education/experience) | Reintroduces the fuzzy free-text matching that is the root cause of the false positives being fixed. |
| Do nothing | The gap list stays misleading — it flags work that isn't real and understates candidate fit, undermining the report's core purpose. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| None outstanding — design decisions (classify by kind, display-only non-skills, false-positives-only scope) resolved during brainstorming. | — | no |

---

## Amendments *(only after approval — never silently edit approved content)*

- —
