# Phase 1: Renderer Filters

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete
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
  - [x] Write failing test: a parametrised test over the shapes tip prose
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
  - [x] Verify it fails (`pytest tests/test_advisor_linkify.py -v`) — expected:
        `ImportError` / `AttributeError`, no extractor exists. Got
        `ImportError: cannot import name '_iter_urls'`.
  - [x] Implement minimal change: `_iter_urls(text)` in
        `scout/sub_agents/advisor/report.py` yielding `(start, end, url)` spans,
        using P3's pattern verbatim —
        `re.compile(r"https?://[^\s<>\"'()\[\]]+")` with trailing `.,;:!?`
        trimmed — and a comment pointing at `grounding.py` as its source.
  - [x] Verify it passes (`pytest tests/test_advisor_linkify.py -v`) — 14 passed
  - [x] Commit: `test(advisor): pin URL extraction against real tip shapes`

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
  - [x] Write failing test: `linkify` on `"Work through https://github.com/k/k
        first."` returns markup containing
        `<a href="https://github.com/k/k" ...>github.com/k/k</a>` — full URL in
        the `href`, scheme-stripped label as the text; on
        `"See https://www.example.com/x"` the label drops `www.` too; and on
        text containing `<script>alert(1)</script>` the angle brackets come
        back escaped as `&lt;script&gt;`, with the tag not present as markup.
  - [x] Verify it fails (`pytest tests/test_advisor_linkify.py -v`)
  - [x] Implement minimal change: `_linkify(text, limit)` — walk the spans
        `_iter_urls` finds in the **raw** text, and build the output piecewise:
        `escape(prose_before)`, then the anchor with `escape(url)` in its
        `href` and the escaped label as its text, then on to the next span,
        finishing with `escape(prose_after)`. Join and wrap in `Markup`.
        Anchors get `rel="noopener noreferrer"` and `target="_blank"`.
  - [x] Verify it passes (`pytest tests/test_advisor_linkify.py -v`) — 22 passed
  - [x] Commit: `feat(advisor): add linkify filter escaping before wrapping`

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
  - [x] Write failing test: `"Try [kubernetes/examples](https://github.com/k/k)
        first."` renders as a single anchor with `href="https://github.com/k/k"`
        whose visible text is `kubernetes/examples` — and the page contains no
        literal `[`, `]`, or `](` debris around it. A bare URL in the same text
        still gets the derived host+path label, so both forms coexist.
  - [x] Verify it fails (`pytest tests/test_advisor_linkify.py -v`) — expected:
        the URL is linked but the brackets and parentheses render literally.
  - [x] Implement minimal change: before emitting an anchor, check whether the
        span is immediately preceded by `](` and preceded before that by a
        `[…]` label; if so, consume the whole `[label](url)` construct and use
        `label` as the anchor text.
  - [x] Verify it passes (`pytest tests/test_advisor_linkify.py -v`) — 26 passed
  - [x] Commit: `feat(advisor): render Markdown citations as single anchors`

> This shape is not hypothetical. P3's validator carries a dedicated
> `_MARKDOWN_LINK_OPEN` case for `[label](url)` — but it rewrites that syntax
> **only** for URLs it strips. A surviving citation keeps its Markdown
> verbatim in `listing_tips.tip`, so it arrives here as stored text.
>
> **Corrected 2026-07-28.** This note originally justified the handling with
> "P3's prompt never forbids Markdown". That was true of the prompt as drafted
> and is no longer: P3 later constrained it to extractable citation shapes —
> *"Write each URL as plain text, optionally wrapped in parentheses. Do not
> wrap it in asterisks, underscores, backticks, or angle brackets, and do not
> nest it inside another bracketed phrase."* The handling stands unchanged,
> because a prompt rule is best-effort wording and the validator still
> tolerates the shape; only the reason it is needed changed, from "the prompt
> allows this" to "the prompt discourages it and nothing enforces that".

### Task 4: Honour the link limit, counting distinct URLs

- **Files:** `scout/sub_agents/advisor/report.py`,
  `tests/test_advisor_linkify.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: text containing three distinct URLs rendered with
        `limit=1` yields exactly one `<a` and the other two URLs still present
        as escaped, unlinked text; with `limit=3` yields three anchors; with
        `limit=0` yields no anchors and no lost text. Plus the distinctness
        case: text citing **one** URL three times with `limit=3` yields three
        anchors but spends one unit of budget — i.e. a fourth, different URL in
        the same text is still linked.
  - [x] Verify it fails (`pytest tests/test_advisor_linkify.py -v`)
  - [x] Implement minimal change: track the set of URLs already linked; a
        repeat of an already-linked URL is wrapped without consuming budget,
        and wrapping stops once `limit` **distinct** URLs have been linked.
  - [x] Verify it passes (`pytest tests/test_advisor_linkify.py -v`) — 32 passed
  - [x] Commit: `feat(advisor): cap the distinct links linkify emits per tip`

> Distinctness matters because P3 dedupes `cited_urls` but never touches the
> prose — its own `test_repeated_allowed_url_is_cited_once` stores a tip naming
> the same URL twice. Counting occurrences would let one resource consume the
> whole three-link budget while looking like three recommendations.

### Task 5: Reject non-http(s) schemes

- **Files:** `scout/sub_agents/advisor/report.py`,
  `tests/test_advisor_linkify.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `javascript:alert(1)`, `data:text/html,x`, and
        `file:///etc/passwd` in tip text produce no `<a` and no `href` at all,
        and the text renders escaped and visible.
  - [x] Verify it fails (`pytest tests/test_advisor_linkify.py -v`) — expected
        to already pass if Task 1's pattern is anchored to `https?://`; if so,
        keep the test as the regression guard and note it in Notes rather than
        weakening the pattern to manufacture a failure.
  - [x] Implement minimal change: none needed if the pattern is already
        scheme-anchored; otherwise anchor it.
  - [x] Verify it passes (`pytest tests/test_advisor_linkify.py -v`) — 37 passed
  - [x] Commit: `test(advisor): guard linkify against non-http schemes`

### Task 6: The citation cap

- **Files:** `scout/sub_agents/advisor/report.py`,
  `tests/test_advisor_linkify.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: `citation_cap` over a `RunListingDetail` returns
        3 for one gap with a tip, 1 for two, 1 for three, 1 for five, and 0
        for a detail with no tips. A detail whose tips include one matching no
        gap counts only the gaps that actually have a tip — five tips against
        one real gap still yields 3.
  - [x] Verify it fails (`pytest tests/test_advisor_linkify.py -v`)
  - [x] Implement minimal change: `_CITATION_BUDGET = 3` as a module constant,
        and `_citation_cap(detail)` returning `0` when no gap has a tip, else
        `max(1, _CITATION_BUDGET // tipped)` where `tipped` counts gaps in
        `detail.gaps` having at least one tip whose `gap_skill` equals
        `gap.skill`.
  - [x] Verify it passes (`pytest tests/test_advisor_linkify.py -v`) — 45 passed
  - [x] Commit: `feat(advisor): compute the per-gap citation cap`

### Task 7: Register both filters

- **Files:** `scout/sub_agents/advisor/report.py`,
  `tests/test_advisor_linkify.py`
- **Gate:** none
- **Steps:**
  - [x] Write failing test: rendering the string template
        `{{ text|linkify(1) }}` and `{{ detail|citation_cap }}` through
        `report._env` produces the expected output — i.e. both filters are
        reachable by the names the template will use.
  - [x] Verify it fails (`pytest tests/test_advisor_linkify.py -v`)
  - [x] Implement minimal change: add `env.filters["linkify"] = _linkify` and
        `env.filters["citation_cap"] = _citation_cap` in `_get_env()`,
        alongside the four existing registrations.
  - [x] Verify it passes (`pytest tests/test_advisor_linkify.py -v`) — 48 passed
  - [x] Commit: `feat(advisor): register linkify and citation_cap filters`

---

## Verification

- [x] All phase tests pass: `pytest tests/test_advisor_linkify.py -v` — 48 passed
- [x] No regression in the renderer suite: full `pytest` run green, 371
      passed (nothing rendered has changed yet — this phase adds capability
      the template does not call)

## Rollback

Revert the phase's commits. No template calls these filters yet, so removing
them changes no rendered output.

---

## Notes / Learnings

- **Reviewed against the merged P3 and found one real divergence
  (2026-07-28).** Phase 1 was built while P3's phases 2–3 were unbuilt, so the
  URL pattern was copied from P3's *phase doc*. The merged validator had since
  gained `re.IGNORECASE` — its comment explains why: "HTTPS:// is a real thing
  models write". Because the validator canonicalizes the scheme before
  comparing, it stores a tip citing `HTTPS://github.com/k/examples` intact,
  and this module's case-sensitive copy rendered that validated citation as
  dead text. Fixed, with the uppercase-scheme shapes added to the extraction
  cases and a cross-check confirming the two now agree on every shape tried.
  The lesson is about the *comment*, not the flag: it claimed the pattern was
  "deliberately identical" while it no longer was, which tells the next reader
  a check has been done that hasn't.
- **Acceptance criterion ticked prematurely.** "URL spans match what
  `grounding.py` finds" was ticked at the end of phase 1 on the strength of
  having copied the pattern, not of having compared against the merged module
  — which did not exist yet. It is now true and verified; it was not when
  first ticked. A criterion that depends on another branch's final code cannot
  be confirmed before that code lands.
- **The validator's truncation widening is deliberately not mirrored.** It
  widens a match to its whole non-whitespace token when the match stopped at a
  stop character that was not closing a wrap, so a fabricated deep link cannot
  keep an allowlisted prefix. That decides what may be *stored*; by the time
  text reaches the renderer every widened token has already been stripped, so
  there is nothing left for it to catch. Recorded in the code so its absence
  reads as a decision rather than an oversight.
- **Emphasis markup survives into stored tips.** `_tidy` clears only
  *orphaned* delimiters, so a deliberate `**bold**` reaches the template and
  renders as literal asterisks. Cosmetic, and not worth routing tips through
  the `markdown` filter to fix — that would fight `linkify` for the same text.
  Left as a known limit for P4's manual verification to judge against real
  tips.
- **Task 5 passed on write, as predicted.** The pattern copied from the
  validator is anchored to `https?://`, so no other scheme was ever eligible
  to become an anchor. The tests were kept as regression guards rather than
  the pattern being weakened to manufacture a failure — they are what stops a
  future "let's also linkify bare hostnames" change from quietly admitting
  `javascript:`.
- **An over-budget Markdown citation renders with its brackets.** Once the
  link budget is spent, the whole `[label](url)` construct is left exactly as
  stored. Deleting the URL would break advice written around it, and rewriting
  prose it is not linking is outside what this filter should do. Pinned by
  `test_linkify_over_limit_markdown_citation_stays_as_written` so the
  behaviour is deliberate rather than incidental. Worth revisiting if real
  tips turn out to cite in Markdown often *and* exceed the budget often —
  neither is observable until P3's phases 2–3 land.
