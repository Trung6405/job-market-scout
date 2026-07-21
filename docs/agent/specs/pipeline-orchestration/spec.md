# Spec: Pipeline Orchestration

> **Status:** Approved
> **Created:** 2026-07-19 · **Approved:** 2026-07-20
> **Implementation plan:** [plan.md](../../plans/pipeline-orchestration/plan.md) *(created after approval)*

---

## Problem

`job-market-scout`'s four stages — Scraper, Tracker, Scorer, Briefing — each work and are tested in isolation, but nothing runs them end-to-end. `scout/agent.py`, the intended root wiring point, is an empty stub; every prior spec (tracker-orchestration, scorer-agent) explicitly deferred "root `SequentialAgent` wiring" to a later session. Two of the four stages (Scraper, Scorer) also have no code that actually invokes their `LlmAgent` and parses its structured output — only the Briefing stage has that runner glue today. Separately, the container's `Dockerfile` `CMD` starts `adk api_server`, a long-running interactive chat server, which cannot execute a one-shot daily batch run even if the wiring existed. Without this work, the pipeline described in the PRS (§3.1: Scraper → Tracker → Scorer → Briefing, once per day) cannot actually execute; it only exists as four disconnected, individually-testable pieces. There is also no way to exercise the whole pipeline interactively during development — each sub-agent can already be pointed at individually via `adk web` (each exports a module-level `root_agent`), but there is no equivalent top-level entry point to watch the full Scraper → Tracker → Scorer → Briefing run happen stage by stage while developing or debugging it.

## Success Criteria

- A single call runs the full pipeline: scraped listings are tracked, relevant (new/changed) listings are scored, and a briefing email is sent for them — with no manual gluing of stage outputs to inputs.
- When the Tracker finds no new/changed listings, the Scorer and Briefing stages are not invoked (no wasted LLM calls).
- The container's default startup command actually executes one pipeline run to completion and exits, rather than starting a chat server that never triggers the pipeline.
- A stage failure aborts the run visibly (raises), with no partial-success masking.
- A developer can run `adk web`, send one message to the root agent, and watch the pipeline progress stage by stage (listing count, new/changed count, scores computed, email sent) in the ADK web UI — without needing the Docker/batch path to inspect behavior.

---

## Requirements

### Must have

- A `run_scraper` function that runs the existing Scraper `LlmAgent` via an ADK runner and returns parsed `list[Listing]`, following the invocation pattern `briefing/summarize.py` already uses.
- A `run_scorer` function with the same shape for the Scorer `LlmAgent`, returning parsed `list[ListingScore]`.
- A custom (non-LLM) `BaseAgent` in `scout/agent.py` — `ScoutPipelineAgent` — whose `_run_async_impl` calls, in order: `run_scraper` → `track_listings` → (short-circuit if empty) → `run_scorer` → `run_briefing`, threading a single `Settings` instance through every call, and yields an ADK `Event` after each stage completes (listing count after Scraper, new/changed count after Tracker, score count after Scorer, "email sent" after Briefing). This is the one place the full stage sequence is implemented — calling the stage functions directly (not through a separate `run_scout` wrapper) is what makes the per-stage events possible. `scout/agent.py` exports `root_agent = ScoutPipelineAgent()`, so `adk web` (pointed at the repo root) discovers it and a developer can send it one message to trigger a full run and watch stage-by-stage progress in the UI, the same way each sub-agent's own `root_agent` already works standalone today.
- A batch entrypoint (`scout/main.py`) that drives `ScoutPipelineAgent` through an `InMemoryRunner` once via `asyncio.run`, consuming its events (e.g. logging them) and exiting non-zero if the run raises, so the same single implementation of the stage sequence serves both `adk web` and the batch/Docker path.
- `Dockerfile`'s `CMD` updated to invoke that batch entrypoint instead of `adk api_server`.

### Should have

- A shared parsing helper (`scout/shared/parsing.py`) extracted from `briefing/summarize.py`'s existing code-fence-stripping logic, reused by the three LLM-output parsers (briefing prose, scraper listings, scorer scores) instead of duplicating it a third time.

### Won't have

- A literal ADK `SequentialAgent` chaining the four stages as agent instances — infeasible given Decision D3 (listing data never round-trips through the LLM), which requires the Scorer and Briefing agents to be *constructed* with the previous stage's typed Python output already known, not received via ADK session state at runtime. `ScoutPipelineAgent` does not change this: it is a thin custom wrapper that calls the same typed Python functions internally and only uses ADK `Event`s to report progress, not to pass stage data between sub-agents.
- A scheduler / cron trigger for daily runs — planned separately per PRS §7 (Azure VM instance), out of scope here.
- Persisting match scores (`matches` table) — deferred per PRS Decision D4, unrelated to this wiring.
- Retry or partial-failure recovery across stages — fail-fast matches the existing project-wide convention (Tracker and Briefing already raise on failure with no retry).

---

## Proposed Approach

`run_scraper` and `run_scorer` are plain async Python functions, not ADK agent constructs: each builds its stage's `LlmAgent` (via the existing `build_scraper_agent`/`build_scorer_agent`), runs it through an `InMemoryRunner` exactly as `briefing/summarize.py`'s `_run_briefing_agent` does, and parses the final response text into the stage's Pydantic output type using `TypeAdapter(list[X]).validate_json(...)` after stripping any markdown code fence.

`ScoutPipelineAgent` (in `scout/agent.py`) is a thin `BaseAgent` subclass that is the pipeline's single orchestrator — it is what `run_scraper` → `track_listings` → `run_scorer` → `run_briefing` are wired together *in*, rather than a separate plain-function orchestrator. Its `_run_async_impl` calls each stage in order, passing typed Python values (`list[Listing]`, `list[ListingScore]`) from one stage's return value into the next stage's arguments — the same style `briefing/briefing.py`'s `run_briefing` already uses internally to join `Listing`s and `ListingScore`s by key — and after each stage yields an `Event` carrying a short human-readable status (e.g. `"Scraper: 18 listings found"`, `"Tracker: 5 new, 13 existing"`, `"Scorer: 5 scored"`, `"Briefing: email sent"`). Run through `adk web`, sending it any message triggers this sequence and the developer watches the whole pipeline's behavior unfold turn by turn instead of only seeing a final result. `scout/agent.py` exports `root_agent = ScoutPipelineAgent()` for ADK's agent discovery, mirroring the `root_agent = build_scraper_agent()` pattern each sub-agent module already uses standalone.

The batch entrypoint (`scout/main.py`) drives the same `ScoutPipelineAgent` through an `InMemoryRunner`, so the container path and the `adk web` path share one implementation of the stage sequence rather than two. `main.py` consumes the runner's events (logging each), and raises/exits non-zero if the run fails, satisfying the "stage failure aborts visibly" success criterion. The `Dockerfile`'s `CMD` is changed to run `scout/main.py`, so a scheduled container invocation actually executes the pipeline instead of starting an idle API server.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Literal ADK `SequentialAgent` wiring the four stages as agent instances | Scorer/Briefing agents must be built with the prior stage's data already baked into their instructions (D3); `SequentialAgent` shares state at runtime between pre-built agent instances, which doesn't fit that construction-time dependency. |
| Leave `Dockerfile`'s `CMD` as `adk api_server` | The new orchestrator would have no caller in the running container — a scheduler hitting this image would start a chat server, not execute the batch pipeline; the PRS's "one run per day" behavior would remain unreachable in production. |
| Keep the code-fence-stripping parsing helper duplicated per stage | Three near-identical copies of the same small regex helper; low cost to extract once, reused by briefing, scraper, and scorer parsers. |
| A plain `run_scout` async function as the only orchestrator, with no ADK-discoverable agent | Simpler, but leaves no way to exercise the full pipeline through `adk web` for interactive dev/debug visibility — every sub-agent can already be run standalone that way, and the top-level pipeline was the one gap. |
| Reuse `LlmAgent`/`SequentialAgent` itself to get `adk web` support "for free" | Same problem as the rejected literal `SequentialAgent` above: those constructs pass data via ADK session state, which doesn't fit D3's construction-time dependency between stages. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Whether `ScoutPipelineAgent`'s zero-relevant-listings short circuit should yield an `Event` distinguishing "pipeline ran but nothing to brief" from "pipeline errored" | Implementation-time judgment | No |
| Exact `Event` content/format for progress reporting (plain text vs. structured `actions`/`state_delta`) — affects only how readable the `adk web` transcript is, not pipeline behavior | Implementation-time judgment | No |

---

## Amendments *(only after approval — never silently edit approved content)*

- (none yet)
