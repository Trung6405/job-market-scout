# Spec: Career Coach P2 — Retriever

> **Status:** Approved
> **Created:** 2026-07-27 · **Approved:** 2026-07-27
> **Implementation plan:** [plan.md](../../plans/career-coach-p2-retriever/plan.md) *(created after approval)*
> **Umbrella PRS:** `docs/project/specification/career-coach-agent-prs.md` (v1.1) — this is phase **P2** of Stage 1.
> **Depends on:** P0 (`resources` table + pgvector, merged). Testable on seeded
> rows independently of P1, but shares P1's `embed()` and its normalized
> `resources.skills[]` guarantee.

---

## Problem

Gap detection already tells the job seeker which skills a listing wants that
they don't have, and P1 fills a corpus of vetted learning resources tagged with
those same skill names. Nothing connects the two. A gap is still just a word on
a report — the seeker is told they're missing Kubernetes and left to find their
own way to learn it, which is exactly the work the corpus was built to save.

Every downstream phase is blocked on that connection. The grounded-tip stage
(P3) can only write advice that cites real resources if something hands it the
right handful of resources per gap, and the report surfacing (P4) has nothing
new to show until it does. Selecting resources for a gap is also the one step
where being *wrong* is worse than being silent: advice pointing at a resource
for a different technology is worse than no advice, because it costs the seeker
time before they discover it was irrelevant.

## Success Criteria

- Given a detected gap whose skill has matching resources in the corpus, the
  retriever returns the 2–3 most semantically relevant of them, each with the
  URL, title, and summary a grounded tip needs to cite it.
- A gap for one technology never returns a resource tagged only with a
  different one — a "Java" gap does not surface JavaScript resources, and a
  gap written as `"K8s"` or `"React.js"` still finds resources tagged
  `kubernetes` / `react`.
- A gap with no matching resources yields nothing rather than a loose match,
  so a caller can tell "no resource for this" apart from "here is a weak one".
- Retrieving for a whole run's gaps costs one embedding pass and does not grow
  more expensive when the same skill is a gap on many listings.
- Resources that have failed link-health verification stop being returned
  without the retriever needing to change when P5 lands.

---

## Requirements

### Must have

- Per gap, pre-filter candidate resources by **exact match** on the normalized
  skill against `resources.skills[]`, then rank only that pre-filtered set by
  pgvector cosine similarity, returning the top `k` (FR-CC-7).
- Normalize incoming gap skill names with the shared `normalize_skill` before
  the pre-filter — `listing_gaps.skill` stores the raw extracted wording, so
  the read side must canonicalize to match the corpus.
- Return results keyed by the caller's original skill string, so a caller
  holding a `SkillGap` can look up its resources without re-normalizing.
- Return an empty result for a skill whose pre-filter matches nothing — no
  relaxed or unfiltered fallback.
- Deduplicate skills before embedding and querying, so a skill appearing as a
  gap on many listings is embedded and looked up once per run.
- Exclude resources that cannot be ranked or are no longer known-good: rows
  with no stored embedding, and rows whose `last_verified` is older than a
  staleness window. A `NULL` `last_verified` counts as live.
- Expose each result's similarity score alongside its fields, so callers and
  logs can tell a strong match from a marginal one.

### Should have

- Configurable top-`k` and staleness window, following the existing `Settings`
  dataclass / env-var convention.
- A single set-based database round trip for a whole run's skills, rather than
  one query per skill.

### Won't have

- Any change to gap detection or to how `listing_gaps.skill` is stored — the
  umbrella puts gap-detection changes out of scope (§2.2); the retriever
  normalizes on read instead.
- The Advisor grounded-tip stage, its prompt, or its URL validator (P3) — this
  phase only returns resources; nothing consumes them yet.
- Report or dashboard changes (P4).
- Writing, updating, or verifying resources — the retriever is read-only. Link
  health is P5; the staleness filter here only *honours* a verification result,
  it never produces one.
- A pgvector index (`ivfflat`/`hnsw`) — see Alternatives.
- A relevance threshold or score floor — see Alternatives.

---

## Proposed Approach

A single new module, `scout/sub_agents/coach/retriever.py`, exposing one
function that takes a run's gap skill names and returns the resources for each:

```python
async def retrieve_for_skills(
    conn, skills: list[str], k: int = 3
) -> dict[str, list[RetrievedResource]]
```

The pipeline inside it is four steps: **normalize** each incoming skill and
drop duplicates; **embed** the distinct normalized names in one batched call
through P1's existing `embed()` singleton; **query** for all of them; **map**
the results back onto the caller's original strings so `SkillGap.skill` remains
a valid key.

**Hybrid retrieval (D-CC-3).** The exact `skills[]` pre-filter runs first and
the vector ranking only orders what survives it. The pre-filter is what makes
the result trustworthy — it guarantees topical correctness, which pure semantic
similarity cannot ("Java" and "JavaScript" embed close together). The vector
ranking is what makes it *useful*, choosing the most on-topic resource among
several that all legitimately teach the skill. Neither half is sufficient
alone, which is why an empty pre-filter returns nothing rather than falling
back to unfiltered similarity: the fallback would return precisely the matches
the pre-filter exists to reject.

**Where the query lives.** The SQL sits in `scout/shared/db.py` alongside the
other query helpers, keeping the retriever module free of SQL and letting the
database layer be tested directly against seeded rows. The intended form is one
set-based statement — the skills and their query vectors unnested into a
two-column relation, `CROSS JOIN LATERAL` a top-`k` subquery per row — so a
whole run costs one round trip.

**Liveness.** `last_verified` means "last confirmed reachable". Rows are
retrievable when it is `NULL` (never checked — everything P1 writes) or within
a configurable window. This needs no schema change and no coupling to P5: once
P5 begins stamping successful checks, a URL that fails re-verification simply
stops receiving a fresh stamp and ages out of retrieval on its own, satisfying
FR-CC-10's "drops out of retrieval until re-verified" without the retriever
changing at all.

**Shared additions:** a `RetrievedResource` model in `scout/shared/schemas.py`
(the resource's display fields plus `similarity`) and the query helper in
`scout/shared/db.py`.

**Config** (`scout/config.py`, following the existing `_env_*` helpers):
`coach_top_k: int = 3` — the PRS specifies "top 2–3"; 3 gives P3 the widest
choice and P3 can present fewer. `coach_resource_max_age_days: int = 90` — a
quarter, long enough that P5's eventual cadence re-stamps well before anything
ages out.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Pure vector search, no `skills[]` pre-filter | Reintroduces exactly the cross-technology false positives D-CC-3 exists to prevent; short skill phrases embed too close together to separate "Java" from "JavaScript". |
| Vector fallback when the pre-filter is empty | Only fires in precisely the case the pre-filter was protecting — a skill with no real coverage — so it converts "no resource" into "a wrong resource", the outcome most costly to the seeker. |
| Vector fallback gated by a cosine similarity floor | Needs a tuned threshold, and there is no populated corpus to tune it against; an untuned magic number is a guess wearing a number's clothes. Revisit only if empty results prove common in practice. |
| One query per skill, looped behind the same API | Identical API and identical results, just N round trips instead of 1. Kept as the fallback if the set-based form proves unworkable in pgvector — not a different design, so nothing downstream depends on which one ships. |
| Fetch pre-filtered rows and rank in Python/numpy | Moves ranking out of the database when pgvector is already installed for this purpose, and pulls every candidate's 384-dim embedding over the wire to do it. |
| Add an `ivfflat`/`hnsw` index on `resources.embedding` now | The pre-filter reduces each ranking to the rows for one skill — tens at most; a sequential scan over that is faster than an approximate index, and `ivfflat` needs a populated table to build meaningful lists. Premature, and it trades exact results for approximate ones to solve a problem the corpus is too small to have. |
| Normalize `listing_gaps.skill` at write time instead of on read | Changes gap detection, which the umbrella puts out of scope (§2.2), and would need a backfill of existing gap rows. Normalizing on read is free and touches nothing else. |
| Do nothing | P3 and P4 cannot be built; the corpus P1 fills stays unread, and gaps remain a list of words with no path from them to a resource. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Does pgvector accept a per-row `text::vector` cast inside a `CROSS JOIN LATERAL`, as the set-based query requires? | spike | No — resolved by the first task of phase 1, against real Postgres. If it fails, the looped-per-skill form ships behind an identical API and no other phase is affected. |

> No question blocks planning.

---

## Amendments *(only after approval — never silently edit approved content)*

- —
