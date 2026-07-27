# Phase 1: Renderer Filters

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** nothing

---

## Goal

Add the two pure functions the template will need — `linkify`, which turns the
first N distinct `http`/`https` URLs in tip text into safely-escaped anchors,
whether written bare or as `[label](url)`, and
`citation_cap`, which computes how many links each tipped gap may show. Both
are registered as Jinja filters. Nothing renders differently at the end of this
phase; the template is untouched.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — `linkify` renders LLM-authored text into HTML and returns `Markup`,
  which bypasses Jinja's autoescape. Escaping and scheme restriction are the
  subject of Tasks 2 and 4 and are tested explicitly, not assumed.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. Two module-private functions and two filter registrations, no new
  dependency — the standard library's `re` and `html` are enough.

---

## Tasks

### Task 1: Spike — pin URL extraction against real tip shapes

> **Read `scout/sub_agents/coach/grounding.py` first.** P3's validator solves
> the same lexing problem and its pattern is the one to copy, not to improve
> on — see the note below. If P3's Phase 2 has not landed when this task runs,
> take the pattern from its phase doc
> (`docs/agent/plans/career-coach-p3-grounded-tips/phase-2-grounding-validator.md`,
> Task 1) and re-check it against the merged module afterwards.

- **Files:** `tests/test_advisor_linkify.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: a parametrised test over the shapes tip prose
        actually contains, asserting the exact substring the extractor should
        treat as a URL for each — `see https://github.com/a/b.` (trailing full
        stop excluded), `(https://github.com/a/b)` (closing paren excluded),
        `[label](https://github.com/a/b)` (Markdown — URL found, brackets and
        parens excluded), `https://github.com/a/b, then` (comma excluded),
        `https://github.com/a/b#readme` and `?tab=x` (fragment and query
        included), `https://github.com/a/b/` (trailing slash included), a bare
        `github.com/a/b` with no scheme (not a URL — not linkified),
        `http://example.org/docs/` (plain http is a URL), and two URLs in one
        sentence (both found, in order).
  - [ ] Verify it fails (`pytest tests/test_advisor_linkify.py -v`) — expected:
        `ImportError` / `AttributeError`, no extractor exists.
  - [ ] Implement minimal change: `_iter_urls(text)` in
        `scout/sub_agents/advisor/report.py` yielding `(start, end, url)` spans,
        using P3's pattern verbatim —
        `re.compile(r"https?://[^\s<>\"'()\[\]]+")` with trailing `.,;:!?`
        trimmed — and a comment pointing at `grounding.py` as its source.
  - [ ] Verify it passes (`pytest tests/test_advisor_linkify.py -v`)
  - [ ] Commit: `test(advisor): pin URL extraction against real tip shapes`

> **Why copy rather than reinvent.** P3's validator and this filter stay
> separate in *policy* — P3 decides what may be stored, this decides what is
> clickable, and coupling them would let a presentation change alter the
> grounding guarantee. They must not diverge in *lexing*: if this filter found
> a different span than P3 did, it could fail to linkify a URL P3 validated and
> stored. Excluding `()[]` from the character class rather than balancing
> brackets afterwards is also what makes the Markdown case fall out for free.

### Task 2: Escape-then-wrap, with the label shortened

- **Files:** `scout/sub_agents/advisor/report.py`,
  `tests/test_advisor_linkify.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: `linkify` on `"Work through https://github.com/k/k
        first."` returns markup containing
        `<a href="https://github.com/k/k" ...>github.com/k/k</a>` — full URL in
        the `href`, scheme-stripped label as the text; on
        `"See https://www.example.com/x"` the label drops `www.` too; and on
        text containing `<script>alert(1)</script>` the angle brackets come
        back escaped as `&lt;script&gt;`, with the tag not present as markup.
  - [ ] Verify it fails (`pytest tests/test_advisor_linkify.py -v`)
  - [ ] Implement minimal change: `_linkify(text, limit)` — walk the spans
        `_iter_urls` finds in the **raw** text, and build the output piecewise:
        `escape(prose_before)`, then the anchor with `escape(url)` in its
        `href` and the escaped label as its text, then on to the next span,
        finishing with `escape(prose_after)`. Join and wrap in `Markup`.
        Anchors get `rel="noopener noreferrer"` and `target="_blank"`.
  - [ ] Verify it passes (`pytest tests/test_advisor_linkify.py -v`)
  - [ ] Commit: `feat(advisor): add linkify filter escaping before wrapping`

> **Lex raw, escape per piece.** Every character of output goes through
> `escape` exactly once, so nothing renders as live markup, and escaping
> cannot destroy an anchor because the anchors are assembled last. The
> alternative — escape the whole string, then match on the escaped result —
> is subtly wrong here: P3's validator lexes the **raw** stored text, so
> lexing escaped text risks finding a different span than the one P3
> validated. It also creates entity collisions, e.g. a URL ending in `&`
> escapes to `&amp;` and the trailing-`;` trim would then corrupt it.

### Task 3: A Markdown citation becomes one anchor

- **Files:** `scout/sub_agents/advisor/report.py`,
  `tests/test_advisor_linkify.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: `"Try [kubernetes/examples](https://github.com/k/k)
        first."` renders as a single anchor with `href="https://github.com/k/k"`
        whose visible text is `kubernetes/examples` — and the page contains no
        literal `[`, `]`, or `](` debris around it. A bare URL in the same text
        still gets the derived host+path label, so both forms coexist.
  - [ ] Verify it fails (`pytest tests/test_advisor_linkify.py -v`) — expected:
        the URL is linked but the brackets and parentheses render literally.
  - [ ] Implement minimal change: before emitting an anchor, check whether the
        span is immediately preceded by `](` and preceded before that by a
        `[…]` label; if so, consume the whole `[label](url)` construct and use
        `label` as the anchor text.
  - [ ] Verify it passes (`pytest tests/test_advisor_linkify.py -v`)
  - [ ] Commit: `feat(advisor): render Markdown citations as single anchors`

> This shape is not hypothetical. P3's prompt asks only that the URL be
> "written in full" and never forbids Markdown, and P3's validator has a
> dedicated case for `[label](url)` — but it rewrites that syntax **only** for
> URLs it strips. A surviving citation keeps its Markdown verbatim in
> `listing_tips.tip`, so it arrives here as stored text.

### Task 4: Honour the link limit, counting distinct URLs

- **Files:** `scout/sub_agents/advisor/report.py`,
  `tests/test_advisor_linkify.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: text containing three distinct URLs rendered with
        `limit=1` yields exactly one `<a` and the other two URLs still present
        as escaped, unlinked text; with `limit=3` yields three anchors; with
        `limit=0` yields no anchors and no lost text. Plus the distinctness
        case: text citing **one** URL three times with `limit=3` yields three
        anchors but spends one unit of budget — i.e. a fourth, different URL in
        the same text is still linked.
  - [ ] Verify it fails (`pytest tests/test_advisor_linkify.py -v`)
  - [ ] Implement minimal change: track the set of URLs already linked; a
        repeat of an already-linked URL is wrapped without consuming budget,
        and wrapping stops once `limit` **distinct** URLs have been linked.
  - [ ] Verify it passes (`pytest tests/test_advisor_linkify.py -v`)
  - [ ] Commit: `feat(advisor): cap the distinct links linkify emits per tip`

> Distinctness matters because P3 dedupes `cited_urls` but never touches the
> prose — its own `test_repeated_allowed_url_is_cited_once` stores a tip naming
> the same URL twice. Counting occurrences would let one resource consume the
> whole three-link budget while looking like three recommendations.

### Task 5: Reject non-http(s) schemes

- **Files:** `scout/sub_agents/advisor/report.py`,
  `tests/test_advisor_linkify.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: `javascript:alert(1)`, `data:text/html,x`, and
        `file:///etc/passwd` in tip text produce no `<a` and no `href` at all,
        and the text renders escaped and visible.
  - [ ] Verify it fails (`pytest tests/test_advisor_linkify.py -v`) — expected
        to already pass if Task 1's pattern is anchored to `https?://`; if so,
        keep the test as the regression guard and note it in Notes rather than
        weakening the pattern to manufacture a failure.
  - [ ] Implement minimal change: none needed if the pattern is already
        scheme-anchored; otherwise anchor it.
  - [ ] Verify it passes (`pytest tests/test_advisor_linkify.py -v`)
  - [ ] Commit: `test(advisor): guard linkify against non-http schemes`

### Task 6: The citation cap

- **Files:** `scout/sub_agents/advisor/report.py`,
  `tests/test_advisor_linkify.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: `citation_cap` over a `RunListingDetail` returns
        3 for one gap with a tip, 1 for two, 1 for three, 1 for five, and 0
        for a detail with no tips. A detail whose tips include one matching no
        gap counts only the gaps that actually have a tip — five tips against
        one real gap still yields 3.
  - [ ] Verify it fails (`pytest tests/test_advisor_linkify.py -v`)
  - [ ] Implement minimal change: `_CITATION_BUDGET = 3` as a module constant,
        and `_citation_cap(detail)` returning `0` when no gap has a tip, else
        `max(1, _CITATION_BUDGET // tipped)` where `tipped` counts gaps in
        `detail.gaps` having at least one tip whose `gap_skill` equals
        `gap.skill`.
  - [ ] Verify it passes (`pytest tests/test_advisor_linkify.py -v`)
  - [ ] Commit: `feat(advisor): compute the per-gap citation cap`

### Task 7: Register both filters

- **Files:** `scout/sub_agents/advisor/report.py`,
  `tests/test_advisor_linkify.py`
- **Gate:** none
- **Steps:**
  - [ ] Write failing test: rendering the string template
        `{{ text|linkify(1) }}` and `{{ detail|citation_cap }}` through
        `report._env` produces the expected output — i.e. both filters are
        reachable by the names the template will use.
  - [ ] Verify it fails (`pytest tests/test_advisor_linkify.py -v`)
  - [ ] Implement minimal change: add `env.filters["linkify"] = _linkify` and
        `env.filters["citation_cap"] = _citation_cap` in `_get_env()`,
        alongside the four existing registrations.
  - [ ] Verify it passes (`pytest tests/test_advisor_linkify.py -v`)
  - [ ] Commit: `feat(advisor): register linkify and citation_cap filters`

---

## Verification

- [ ] All phase tests pass: `pytest tests/test_advisor_linkify.py -v`
- [ ] No regression in the renderer suite:
      `pytest tests/test_advisor_report.py -v` (nothing rendered has changed
      yet — this phase adds capability the template does not call)

## Rollback

Revert the phase's commits. No template calls these filters yet, so removing
them changes no rendered output.

---

## Notes / Learnings

<Filled in during execution.>
