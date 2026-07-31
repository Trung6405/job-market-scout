# Spec: Skill Alias Normalisation

> **Status:** Draft
> **Created:** 2026-07-30 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/skill-alias-normalisation/plan.md) *(created after approval)*

---

## Problem

Retrieval matches a gap to a resource only when both sides reduce to the same
normalised token, and common spellings of one technology do not. `GCP` and
`Google Cloud Platform` reduce to different tokens, as do `Node.js` and
`NodeJS`, `REST API` and `RESTful APIs`, `.NET` and `.NET Core`, `CI/CD` and
`CI/CD pipelines`. A resource tagged one way is invisible to a gap written the
other way, and the failure is silent — the gap simply reports no coverage,
indistinguishable from a corpus that genuinely lacks the material.

Measured across the current gap data, 51 technologies appear under more than
one spelling, spanning 119 distinct strings and covering the most frequent
skills in the set: CI/CD (48 gap rows), TypeScript (40), Node.js (30), .NET
(29), REST (27), Google Cloud (21). Every one of those is a chance for a
correct resource to be passed over.

This compounds with corpus growth rather than washing out. Tokens are stored
normalised on write, so every resource added under today's rules is another row
whose spelling is frozen, and a later rule change leaves them stale unless they
are remapped.

## Success Criteria

- A gap written `GCP` retrieves resources tagged `Google Cloud Platform`, and
  the reverse.
- The same holds for the other measured variant families: Node.js, REST APIs,
  .NET, CI/CD, Infrastructure as Code, Vue.js, full-stack development.
- Technologies that merely look similar stay separate — `C`, `C++`, `C#`,
  `Java` and `JavaScript` each retrieve only their own resources.
- Every resource row already stored carries the same token it would get if it
  were tagged fresh under the new rules.
- Re-running the remap changes nothing the second time.

---

## Requirements

### Must have

- A curated alias table mapping known equivalent spellings onto one canonical
  normalised token, extending the existing `_SKILL_ALIASES`.
- Aliases keyed and valued in **normalised form**, so the same table can be
  applied to already-stored tokens without re-tagging anything.
- A backfill that rewrites `resources.skills` through the new rules, idempotent
  and safe to re-run.
- Guard tests pinning the known-dangerous separations — `c` / `cpp` / `csharp`,
  `java` / `javascript` — so a future alias entry cannot silently merge them.
- Every alias entry justified by an observed variant in real gap or resource
  data, not by imagination.

### Should have

- A one-off report of which gap skills gain corpus coverage as a result, to
  confirm the change did something measurable rather than merely passing tests.
- Coverage of the multi-word cases the current pipeline mangles, where
  punctuation stripping runs before any alias lookup (`.NET Core` reaching
  `netcore` rather than `dotnet`).

### Won't have

- **Algorithmic stemming or fuzzy matching.** A crude stem over this data
  merged `C`, `C++` and `C#` into one bucket — the exact failure
  `_PUNCTUATED_SKILLS` was written to prevent, and which once marked a C++
  requirement met against plain C. Equivalences are asserted by hand or not at
  all.
- **Rejecting prose, generic or multi-skill gap strings** (~231 of 852). That
  saves aggregation work rather than fixing matching, has no backfill
  implication, and belongs in its own change.
- **Re-tagging resources with the LLM.** The backfill is a token remap; the
  tagger's judgement is not in question.
- **Changing the exact-match retrieval strategy itself** (D-CC-3). Making the
  tokens correct is this spec; whether exact matching is the right strategy is
  a separate question, and one the compound-skill finding may reopen.
- Semantic grouping of related-but-distinct skills (`Security` vs
  `Cloud Security`, `Java` vs `Spring Boot`) — these are different things and
  merging them would degrade retrieval precision.

---

## Proposed Approach

Extend the existing normalisation rather than replace it. `normalize_skill`
already has the right shape: fold punctuation-load-bearing names first, strip
version suffixes, remove remaining punctuation, then apply an alias table. The
alias table is simply too small — six entries against 51 observed variant
families.

The work is therefore in three parts. First, derive the alias entries from
data: group the observed gap and resource spellings, inspect each group by
hand, and record only the ones that are genuinely the same technology.
Second, handle the cases the current ordering mangles — multi-word names whose
punctuation is stripped before any alias can be consulted, of which `.NET Core`
is the clearest example. Third, because tokens are stored normalised, apply the
same table to `resources.skills` so existing rows agree with new ones.

The backfill is cheap precisely because aliases are normalised-to-normalised: a
stored token `gcp` becomes `googlecloudplatform` by table lookup, with no
network call, no LLM, and no need for the original string. It is a pure
rewrite, idempotent by construction — applying the table to an
already-canonical token is a no-op.

Canonical direction is chosen per family by which spelling the resource tagger
is more likely to emit, since the corpus side is the one that cannot be
re-asked cheaply.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Algorithmic stemming / suffix stripping | Demonstrably unsafe on this data: it merged C, C++ and C# into one token. The codebase already rejected this once and documented why. |
| Fuzzy or embedding-based skill matching | Retrieval already ranks by embedding *within* an exact-token pre-filter (D-CC-3); loosening the pre-filter reopens the Java/JavaScript false-match the design chose to prevent. A different spec if ever wanted. |
| Leave existing rows on old tokens | Knowingly leaves rows that silently never match — the same invisible-failure class this project spent the week removing. |
| Re-tag every resource with the LLM | Costs thousands of calls to recover information a lookup table already has. |
| Do nothing, rely on corpus breadth | More resources under fragmented spellings does not fix fragmentation; it multiplies it. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Canonical direction per family — is the corpus more often tagged `GCP` or `Google Cloud Platform`? | spike: read `resources.skills` distribution before fixing directions | no |
| Whether `.NET` and `.NET Core` should merge at all, or are distinct enough that a .NET Core resource is wrong for a .NET gap | human, informed by the spike's data | no |
| How many gap skills actually gain coverage — the change may be correct yet immaterial until the corpus holds cloud resources | measured after the coach-aggregator-completion plan lands | no |

---

## Amendments *(only after approval — never silently edit approved content)*

### A1 — Merging is a matching concern, not a display one *(2026-07-30)*

The open question on `.NET` vs `.NET Core` is resolved, and the answer
generalises: **the families are the same technology for sourcing purposes, so
their resource tokens merge, while the gaps stay separate as written.**

This is less of a change than it sounds, because the split already exists in the
data model. `listing_gaps.skill` stores the raw extracted string and the report
renders that; `normalize_skill` runs only when matching. So a gap displayed as
`.NET Core` looks up the merged token and finds a `.NET` resource, while still
appearing as `.NET Core` on the page. Two consequences worth stating so they are
not "improved" later:

- **No gap-row deduplication.** The same page listing `HuggingFace` and
  `Hugging Face` as two rows stays that way. They already resolve to one token
  for retrieval, so the duplication is cosmetic, and collapsing rows would
  discard the requirement levels the extractor assigned to each.
- **Merging is deliberately asymmetric in effect.** It widens what a gap can
  find without narrowing what a gap *is*. That is why the aggressive direction
  is safe here and would not be safe if gaps were being merged.

The families merged on that basis: `.NET`/`.NET Core`, `REST`/`REST API`/
`RESTful APIs`, `GCP`/`Google Cloud`/`Google Cloud Platform`, `CI/CD`/`CI/CD
pipelines`, `Node.js`/`NodeJS`, `Vue.js`/`VueJS`, `Infrastructure as
Code`/hyphenated variants, and case-only variants.

`Security` vs `Cloud Security` is **not** merged — see the plan's Key Decisions
for the reasoning. It was listed alongside the others in phase 1 Task 2 but is a
different case: a generic parent term and a specialisation, where merging would
pull general security material into cloud-security gaps rather than reconcile
two spellings of one thing.
