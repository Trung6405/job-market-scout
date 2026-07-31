# Phase 3: Seed and Verify in Production

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 1 complete and merged to `main` (the VM runs `main`'s
> code). Phase 2 is optional — it changes how fast this phase runs, not
> whether it works

---

## Goal

Turn the corpus into visible output. Done when a completed aggregation run has
added resources tagged with the most frequent gap skills, and a job-detail page
on the published dashboard renders a grounded tip with a citation that
resolves.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — this dispatches a real run: VM boot, GitHub API, LLM spend, and a
  Discord briefing push as a side effect of the scout cycle.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. Cost is bounded by the 120-minute step timeout and is recoverable.

---

## Tasks

### Task 1: Dispatch a run and read the summary

- **Files:** none — findings recorded in this doc's Notes
- **Gate:** none — bounded cost, no irreversible action
- **Steps:**
  - [ ] Confirm nothing is in flight and the workflow is enabled:
        `gh workflow list --all` (a disabled workflow reports as
        "could not find any workflows named …", which reads like a typo)
  - [ ] Dispatch: `gh workflow run "Scheduled run"` — a manual dispatch
        bypasses the Sunday-only gate by design
  - [ ] Watch to completion and record in Notes: the gather, filter and ingest
        phase timings, the completion summary's four counts, and the total
        step duration against the 120-minute bound
  - [ ] Confirm the step's conclusion is `success`, not `failure` — the whole
        point of phase 1
  - [ ] No commit

### Task 2: Check corpus coverage against the actual top gaps

- **Files:** none — findings recorded in Notes
- **Gate:** none — read-only queries
- **Steps:**
  - [ ] From the VM, query the two classes separately — they answer different
        questions (spec A2). Single-token gaps, which reordering alone should
        fix:

        ```sql
        SELECT s, count(*) FROM resources, unnest(skills) s
        WHERE s IN ('terraform','snowflake','eks','ecs','bedrock','cicd',
                    'azure','java','aws')
        GROUP BY s ORDER BY count(*) DESC;
        ```

  - [ ] Then the compound gaps observed uncovered in production, which
        reordering may *not* fix because no resource is likely to carry the
        same compound token:

        ```sql
        SELECT s, count(*) FROM resources, unnest(skills) s
        WHERE s IN ('awscloud','awssagemaker','semantickernel','huggingface')
        GROUP BY s ORDER BY count(*) DESC;
        ```

  - [ ] Record both results. Single-token misses mean reordering was necessary
        but not sufficient and the tagger is mislabelling. Compound misses are
        expected and scope a follow-on spec on retrieval matching or skill
        normalisation — they are a finding, not a failure of this plan
  - [ ] No commit

### Task 3: Confirm tips render on the dashboard

- **Files:** none — findings recorded in Notes
- **Gate:** none
- **Steps:**
  - [ ] Trigger the cycle that generates tips — either wait for the next 19:00
        UTC fire or dispatch again; tips are produced by the scout cycle, which
        runs *before* the aggregator in the same workflow, so the corpus must
        already be seeded when it runs
  - [ ] Confirm the run's log no longer reports
        `coach tips: no corpus coverage` for every listing, and record how many
        listings got tips out of how many were processed
  - [ ] Open the published dashboard
        (`https://trung6405scoutdash.z44.web.core.windows.net/`), follow a
        job-detail page for a listing with gaps, and confirm a grounded tip
        renders with a citation whose URL resolves
  - [ ] No commit

### Task 4: Record the real timings in the workflow comment

- **Files:** `.github/workflows/scheduled-run.yml`
- **Gate:** none
- **Steps:**
  - [ ] Update the `timeout-minutes: 120` comment with the measured
        end-to-end figures from Task 1, replacing the projections written
        before any run completed
  - [ ] Verify the workflow guards still pass
        (`python -m pytest tests/test_scheduled_run_workflow.py -q`)
  - [ ] Commit: `docs(ci): record the aggregator's real end-to-end timings`

---

## Verification

- [ ] The aggregation step's conclusion is `success` and it completed inside
      the 120-minute bound
- [ ] `resources` contains rows whose `skills` include `aws` and `terraform`
- [ ] At least one job-detail page renders a grounded tip with a resolving
      citation
- [ ] `python -m pytest -q` still passes after Task 4

## Observability

The signal that phase 1 worked is the step's conclusion plus the summary's
`failed` count: a run that previously died now completes and states how many
candidates it skipped. The signal that ordering worked is Task 2's query
returning rows for cloud/enterprise skills rather than only Python-ecosystem
ones. The signal the feature works is the absence of
`coach tips: no corpus coverage` for every listing.

## Rollback

Nothing to roll back — this phase dispatches runs and reads results. A bad run
costs VM time and LLM spend, both bounded by the step timeout. Task 4's commit
is comment-only and revertible in isolation.

---

## Notes / Learnings

<Filled in during execution — record the phase timings, the four summary
counts, the coverage query's result, and how many listings got tips.>
