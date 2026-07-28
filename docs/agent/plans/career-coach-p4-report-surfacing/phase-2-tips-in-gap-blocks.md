# Phase 2: Tips in Gap Blocks

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
> **Depends on:** Phase 1 complete (`linkify` and `citation_cap` registered)

---

## Goal

Make each gap block in "Skill gaps to close" carry the tip that answers it,
linkified under the page's citation cap, with must-have gaps first. At the end
of this phase a seeded run's job-detail page shows grounded advice next to its
gap — while the static positioning section is still present below, untouched,
because retiring it is Phase 3.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes, indirectly — LLM-authored tip text now reaches the page. The escaping
  that makes that safe landed in Phase 1 and is re-asserted end-to-end in
  Task 5 against real rendered HTML rather than filter output alone.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. Template markup and CSS only.

---

## Tasks

### Task 1: A gap renders its own tip, and only its own

- **Files:**
  `scout/sub_agents/advisor/templates/job-detail.html.jinja`,
  `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: seed a run whose listing has two gaps
        (`Kubernetes` must-have, `Terraform` nice-to-have) and one stored tip
        for `Kubernetes`. Render, then assert the `Kubernetes` gap block
        contains the tip text and the `Terraform` block does not — sliced by
        splitting the rendered HTML on `class="gapblock"`, so the assertion is
        about *which* block, not merely about the page containing the string.
  - [x] Verify it fails (`pytest tests/test_advisor_report.py -v`) — expected:
        tip text absent from the page entirely.
  - [x] Implement minimal change: inside the `{% for gap in detail.gaps %}`
        loop, look up the gap's tips with
        `{% set gap_tips = detail.tips|selectattr('gap_skill', 'equalto', gap.skill)|list %}`
        and render `gap_tips[0].tip` in a `<p class="tip">` when the list is
        non-empty. Take `[0]` explicitly — one tip per gap, first stored wins.
  - [x] Verify it passes (`pytest tests/test_advisor_report.py -v`) — 12 passed
  - [x] Commit: `feat(advisor): render each gap's grounded tip in its block`

> The join is on raw stored wording on both sides. `GroundedTip`'s docstring
> states that `gap_skill` holds `listing_gaps.skill` unnormalised precisely so
> this lookup needs no normalisation; the test above is what will fail loudly
> if that ever stops being true.

### Task 2: A tip matching no gap renders nowhere

- **Files:** `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: seed a listing with one gap (`Kubernetes`) and two
        stored tips — one for `Kubernetes`, one for `Rust`, which is not a gap
        on this listing. Assert the `Rust` tip's text appears nowhere in the
        rendered page.
  - [x] Verify it fails (`pytest tests/test_advisor_report.py -v`) — expected
        to already pass, since the template iterates gaps rather than tips.
        Keep it as the regression guard that pins that direction of iteration;
        record in Notes that it passed on write rather than weakening the
        template to manufacture a failure.
  - [x] Implement minimal change: none expected.
  - [x] Verify it passes (`pytest tests/test_advisor_report.py -v`) — 14 passed
  - [x] Commit: `test(advisor): pin that orphan tips render nowhere`

### Task 3: Citations are linkified under the cap

- **Files:**
  `scout/sub_agents/advisor/templates/job-detail.html.jinja`,
  `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: three cases. (a) One gap, one tip citing three
        distinct URLs → three anchors in that block, each `href` the full URL.
        (b) Three gaps each with a one-URL tip → one anchor per block, three on
        the page. (c) One gap whose tip cites its resource as
        `[label](url)` → one anchor labelled `label`, with no literal brackets
        in the rendered block. Assert on anchor count within the sliced gap
        block.
  - [x] Verify it fails (`pytest tests/test_advisor_report.py -v`) — expected:
        URLs render as plain text, zero anchors.
  - [x] Implement minimal change: compute the cap once above the loop with
        `{% set cap = detail|citation_cap %}` and render the tip as
        `{{ gap_tips[0].tip|linkify(cap) }}`.
  - [x] Verify it passes (`pytest tests/test_advisor_report.py -v`) — 18 passed
  - [x] Commit: `feat(advisor): linkify tip citations under the page cap`

### Task 4: Must-have gaps render first

- **Files:**
  `scout/sub_agents/advisor/templates/job-detail.html.jinja`,
  `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: seed a listing whose gaps are stored
        nice-to-have-first (`Terraform` nice, `Kubernetes` must). Assert the
        rendered page's index of `Kubernetes` precedes that of `Terraform`.
  - [x] Verify it fails (`pytest tests/test_advisor_report.py -v`) — expected:
        stored order preserved, nice-to-have first.
  - [x] Implement minimal change: build the ordered list explicitly above the
        loop —
        `{% set ordered_gaps = (detail.gaps|selectattr('requirement_level', 'equalto', 'must_have')|list) + (detail.gaps|rejectattr('requirement_level', 'equalto', 'must_have')|list) %}`
        — and iterate that. Explicit concatenation rather than
        `sort(attribute='requirement_level')`, which would work only by the
        alphabetical accident that `must_have` sorts before `nice_to_have`.
  - [x] Verify it passes (`pytest tests/test_advisor_report.py -v`) — 19 passed
  - [x] Commit: `feat(advisor): order skill gaps must-have first`

### Task 5: Tip text cannot inject markup into the page

- **Files:** `tests/test_advisor_report.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: seed a tip whose text contains
        `<script>alert(1)</script>` and a `javascript:alert(1)` pseudo-URL.
        Assert the rendered page contains neither `<script>` as markup nor any
        `href="javascript:`, and does contain the escaped form — mirroring the
        existing description-injection test at `test_advisor_report.py:355-386`.
  - [x] Verify it fails (`pytest tests/test_advisor_report.py -v`) — expected
        to pass already, given Phase 1 Tasks 2 and 4. Keep it: this is the
        assertion at the layer that actually ships HTML, and Phase 1's covers
        only the filter in isolation.
  - [x] Implement minimal change: none expected.
  - [x] Verify it passes (`pytest tests/test_advisor_report.py -v`) — written and
        passing alongside Task 3's batch, since both assert on the same
        rendered page
  - [x] Commit: `test(advisor): assert tip text cannot inject markup` — folded
        into Task 3's commit

### Task 6: Style the tip inside the gap block

- **Files:** `scout/sub_agents/advisor/templates/job-detail.html.jinja`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: none — this is CSS in the template's inline
        `<style>` block, verified by eye. Recorded as a deliberate exception
        to the TDD ordering, per the project's right-size-TDD rule.
  - [x] Implement minimal change: add `.gapblock .tip` (body text size and
        muted colour matching `.no-gaps`) and `.gapblock .tip a` (accent
        colour, underlined) next to the existing `.gaphead` rules, and a small
        top margin so the tip sits under the skill row.
  - [x] Verify it passes (`pytest tests/test_advisor_report.py -v` — 19 passed)
        and open a rendered page to confirm it reads well — done: the tip sits
        under its skill row, the citation renders as an underlined
        `github.com/kubernetes/examples`, and the untipped nice-to-have gap is
        unchanged.
  - [x] Commit: `style(advisor): style grounded tips inside gap blocks`

---

## Verification

- [x] All phase tests pass: `pytest tests/test_advisor_report.py -v` — 19 passed
- [x] Full suite green: `pytest -v` — 521 passed
- [x] Manual: rendered a seeded detail page and read it back — must-have gap
      leads, its tip sits inside the block, the citation is an underlined
      `github.com/kubernetes/examples` anchoring the full URL, and the
      untipped nice-to-have gap renders exactly as before.

## Rollback

Revert the phase's commits. The template returns to rendering bare gap blocks;
Phase 1's filters remain registered but uncalled, which changes nothing.

---

## Notes / Learnings

- **Gap order within a requirement level is not defined.** Task 4's test first
  asserted that two nice-to-have gaps kept their stored order, and it failed:
  `get_run_details` selects `listing_gaps` with no `ORDER BY`
  (`scout/shared/db.py:555`), so the database never promised one and the page
  can reorder same-level gaps between renders of the same run. The assertion
  was wrong, not the template — it now asserts only what this phase decides
  (must-haves lead) and says why it stops there. Adding an `ORDER BY` belongs
  to whoever owns that read path; `scout/shared/` is outside this phase's
  blast radius.
- **A skipped DB test is not a passing DB test.** One run of this suite
  reported "16 passed, 2 skipped in 3056s" — the `db_pool` fixture skips when
  Postgres is unreachable, and the machine appears to have suspended mid-run.
  Read at a glance that looks green. Re-run against a healthy container it was
  18 passed, no skips, 28s. Worth running this suite with `-rs` so skips are
  named rather than counted.
