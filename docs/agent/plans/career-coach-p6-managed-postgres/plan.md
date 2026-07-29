# Plan: Career Coach P6 — Always-On Managed Postgres

> **Status:** Not started
> **Created:** 2026-07-29 · **Last updated:** 2026-07-29
> **Spec:** [spec.md](../../specs/career-coach-p6-managed-postgres/spec.md)

---

## Overview

Move the system of record off the scout VM's Postgres container and onto a
managed Neon Postgres project, so the gap and resource data stays queryable
during the ~23h/day the VM is deallocated. A fresh instance is
provisioned and validated while the old database keeps serving; the data is
copied and row-count-verified; and only then, as a deliberate human step, is
the stored `DATABASE_URL` secret repointed. Done means a full pipeline cycle
runs against the managed instance with unchanged behaviour, the pre-move run
history and corpus are intact on it, and reverting is a one-line secret change.

## Acceptance Criteria

- [ ] `listing_gaps` and `resources` can be queried while `scout-vm` is deallocated.
- [ ] A full pipeline cycle completes against the managed instance and renders
      the dashboard, history, and job-detail pages with no observable change.
- [ ] Row counts for all six tables match between the VM database and the
      managed instance, and the count of `resources` carrying a non-NULL
      `embedding` matches.
- [ ] Connections to the managed instance are encrypted in transit
      (`sslmode=require` in the DSN, honoured by asyncpg).
- [ ] No application code or SQL under `scout/` changes — the repoint is
      configuration only.
- [ ] Reverting to the VM database is a single `DATABASE_URL` secret change
      plus a redeploy, with the VM's container still holding its data.
- [ ] The pipeline's local and CI test paths cannot reach the managed instance.
- [ ] The actual cost was confirmed and accepted before the instance existed.

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| **Neon Free's 0.5 GB storage ceiling** against a `listings` table holding a description per row and growing daily | The database fills and writes start failing, on the system of record, with no headroom to buy back except by paying or pruning | **Open.** Spike + gate: Phase 2 Task 1 measures current size, per-table breakdown and growth per run before anything is provisioned (spec A5) |
| ~~Free allowance covering `Standard_B1ms`~~ | — | **Resolved 2026-07-29:** it does not. Azure for Students is a $100 credit; measured $24.57/month, ~4 months runway. Provider changed to Neon (spec A1) |
| **No IP allow-list is possible on Neon Free** (Scale-plan feature) | The system of record is reachable by anyone holding the connection string, where the Azure design admitted exactly one IP | **Accepted risk** (spec A2), mitigated only by mandatory TLS, a high-entropy secret-managed password, and rotation on suspicion |
| asyncpg reaching Neon specifically — Neon routes by SNI, and `sslmode=require` in the DSN has never been exercised here | Cutover fails at connect time, or connects unencrypted | Spike: Phase 2 Task 4 connects from the VM using the app's own client and DSN form, before any data moves |
| Per-query latency now crosses clouds, plus a scale-to-zero cold start on the first query after idle | NFR-CC-2's sub-100 ms retrieval budget was written for a same-host database and is now asserted against much weaker premises | Spike: Phase 2 Task 4 measures cold connect and warm round-trip and records both (spec A6); raise if the warm figure is a large fraction of the budget |
| A second `gh workflow run` entering the `scout-vm` concurrency group while another is queued **cancels the pending one** | A deploy or cutover appears to have been triggered but silently never runs — observed 2026-07-29, when the phase-1 deploy was evicted this way | Procedural: dispatch one VM-touching workflow at a time and confirm completion before the next. `cancel-in-progress: false` protects a *running* job, not a queued one |
| The current value of the `DATABASE_URL` Actions secret is unknowable (GitHub does not read secrets back) and it is shadowed today, so it may be empty or stale | Removing the compose pin renders an empty DSN onto the VM and the next scheduled run dies at connect time | Ordering: Phase 1 Task 1 sets the secret to the VM-local DSN *before* Task 2 removes the pin, and Task 4 proves the seam on the unchanged database |
| `pg_dump` / `psql` client version skew against the managed server | Restore fails or silently drops objects | Accepted risk, mitigated: both run inside the VM's own `pgvector/pgvector:pg16` container, and the server's major version is pinned to 16 to match |

## Blast Radius

- **Code that will change:** `docker-compose.yaml`, `docker-compose.override.yaml`
  (new), `.dockerignore`, `infra/provision_neon.py` (new), `infra/__init__.py`
  (new), `infra/README.md`, `.github/workflows/infra-provision.yml`,
  `scripts/verify_migration.py` (new), `tests/`, `docs/commands.md`,
  `README.md`, `docs/project/specification/career-coach-agent-prs.md`.
  No Bicep template is added — the provider is not Azure (spec A3).
- **Existing behaviour that could break:** the daily `Scheduled run` and the
  `Deploy` workflow (both drive the compose stack over SSH); local
  `docker compose up`; the pytest fixtures in `tests/conftest.py`.
- **Off-limits:** everything under `scout/` — including `scout/shared/db.py`
  and `scout/shared/schema.sql`. This phase moves data and changes
  configuration; an edit under `scout/` means the approach has gone wrong.
  Do not modify anything outside the directories above without flagging it to
  the human first.

---

## Phases

| # | Phase | Document | Status |
|---|-------|----------|--------|
| 1 | Configuration seam | [phase-1-configuration-seam.md](phase-1-configuration-seam.md) | In progress |
| 2 | Provision the instance | [phase-2-provision-instance.md](phase-2-provision-instance.md) | In progress |
| 3 | Migrate and verify | [phase-3-migrate-and-verify.md](phase-3-migrate-and-verify.md) | Not started |
| 4 | Cutover and documentation | [phase-4-cutover-and-docs.md](phase-4-cutover-and-docs.md) | Not started |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing
> an earlier phase surfaces a needed change to a later phase doc, update
> that doc explicitly and record the change in its Notes / Learnings
> section; don't leave later phases undocumented.

---

## Testing Strategy

- **Unit:** per-task TDD in the phase docs covers the compose/workflow guards
  (`tests/test_compose_database_url.py`), the non-local-database refusal in the
  test fixtures (`tests/test_local_db_guard.py`), the provisioning script's
  idempotency and DSN construction (`tests/test_provision_neon.py`), and the
  count-comparison logic (`tests/test_verify_migration.py`).
- **Integration:** the existing suite is the regression net. It runs against a
  local Postgres in `deploy.yml`'s `test` job on every push, and staying green
  is the evidence that no application behaviour changed — this phase touches no
  code the suite covers, so any new failure means the blast radius was exceeded.
- **Manual:** the cost/region check, provisioning, the connectivity and pgvector
  probe from the VM, the dump/restore, the row-count verification read at the
  gate, and one full pipeline cycle after cutover with the dashboard checked.

## Rollout & Reversibility

- **Feature flag:** no. The `DATABASE_URL` Actions secret *is* the switch —
  which is why Phase 1 makes it load-bearing before it is repointed.
- **Migrations:** no schema change. The data move is a logical dump restored
  into a fresh, empty instance; the source database is read-only throughout and
  is never dropped, truncated, or altered.
- **Rollback plan:** set the `DATABASE_URL` Actions secret back to
  `postgresql://scout:scout@postgres:5432/scout` and re-run `Deploy`. The VM's
  `postgres` container keeps running with its data for the whole grace period —
  so do not run `docker compose down -v` on the VM, and do not retire the
  container as part of this work. Writes made to the managed instance after
  cutover are lost on rollback; the pipeline is idempotent per run date, so the
  cost of that is at most one re-run.

---

## Key Decisions & Constraints

- **The repoint is a deletion.** `docker-compose.yaml` pinned `DATABASE_URL` in
  the `app` service's `environment:` block, and an inline value beats
  `env_file:` — which is why the secret the deploy already renders to
  `scout/.env` had no effect. Removing that one line is the entire mechanism.
- **The in-network value moves to `docker-compose.override.yaml`.** Compose
  auto-loads an override file only when no `-f` flag is given, and every
  production invocation passes `-f docker-compose.yaml -f
  docker-compose.prod.yaml`. Local development keeps working unchanged; the
  VM never sees the file. This makes the `-f` pair load-bearing, so a test
  pins it.
- **The secret is proven before it is repointed.** Phase 1 sets `DATABASE_URL`
  to the VM's *own* database and deploys. If the seam is broken, it fails while
  the system of record is still the old one and nothing has been migrated.
- **Provisioning is priced before it exists.** This is what the gate caught:
  the subscription is Azure for Students, the free allowance does not apply,
  and $24.57/month against a $100 credit is four months of runway. The provider
  is Neon instead (spec A1–A6). Had provisioning been automated end to end, the
  instance would already exist and be billing.
- **Provisioning is a committed script, not a Bicep template.** Bicep cannot
  express a non-Azure provider; Terraform would cost a new toolchain and a
  remote state backend to secure first. An idempotent API script keeps the
  requirement's intent — reviewable, re-runnable, not clicked together.
- **Access control is weaker than the Azure design, deliberately.** Neon Free
  has no IP allow-list, so the database is reachable by anyone holding the
  connection string. Accepted, not solved; the thing that solves it is paying.
- **The migration still runs from the VM, for a different reason.** The
  original rationale — the VM was the only allow-listed address — is void now
  that no allow-list exists. It remains right because the source data is on the
  VM: dumping and restoring there keeps the whole copy local to one host
  instead of pulling the entire listings corpus down to a CI runner and pushing
  it back out.
- ⚠️ **One-way doors:**
  - **Creating the Neon project** (Phase 2 Task 3) — no longer a cost
    commitment on the Free plan, but it puts the system of record outside the
    subscription holding everything else and adds a second credential domain.
    Requires human sign-off; reversible by deleting the project.
  - **The cutover** (Phase 4 Task 1) — repoints the system of record. Requires
    the human to read the Phase 3 verification output and explicitly approve.

## Out of Scope

- Removing or retiring the VM's `postgres` container — it *is* the rollback
  target; teardown is a separate change after the grace period.
- The Discord bot and any networking on its behalf (P7), including how a
  Consumption-plan Function will be granted access.
- Any schema or query change; any migration tooling.
- Private networking, high availability, geo-redundant backup, read replicas,
  and connection-pooling changes. On the Neon Free plan these are moot rather
  than declined — the plan does not offer them (spec A5).
- Paying for Neon's Scale plan to recover IP allow-listing (spec A2).

---

## Definition of Done

- [ ] All acceptance criteria met
- [ ] All phase verification steps pass
- [ ] Feature verified manually in a running environment (one full cycle post-cutover)
- [ ] Docs / README updated where behaviour changed (`infra/README.md`,
      `docs/commands.md`, `README.md`)
- [ ] The three corrections this phase makes to the umbrella PRS are recorded
      in `docs/project/specification/career-coach-agent-prs.md`
- [ ] No new lint or type-check warnings

## Update Rules

- Phase docs hold task-level detail; this file holds phase-level status only.
- When a phase's scope changes, update its row here **in the same commit**.
- On conflict, this file wins for *what* the phases are; the phase doc
  wins for *how* its tasks are done.
