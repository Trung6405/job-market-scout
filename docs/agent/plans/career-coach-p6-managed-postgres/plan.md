# Plan: Career Coach P6 — Always-On Managed Postgres

> **Status:** Evaluation complete, cutover deferred — phases 1–3 executed and the
> instance was torn down at the end of phase 3 (spec A1). Phase 4 is written,
> including the migrate-back exit path (spec A5), and waits on a funded decision
> to carry the standing cost.
> **Created:** 2026-07-29 · **Last updated:** 2026-07-30
> **Spec:** [spec.md](../../specs/career-coach-p6-managed-postgres/spec.md)

---

## Overview

Move the system of record off the scout VM's Postgres container and onto an
Azure Database for PostgreSQL Flexible Server, so the gap and resource data
stays queryable during the ~23h/day the VM is deallocated. A fresh instance is
provisioned and validated while the old database keeps serving; the data is
copied and row-count-verified; and only then, as a deliberate human step, is
the stored `DATABASE_URL` secret repointed.

**Scope of the current pass: evaluation only (spec A1).** Phases 1–3 run and
the instance is torn down afterwards; phase 4's cutover is deferred until the
standing cost is funded. Done, for this pass, means the instance was proven
to work — TLS, pgvector, a faithful restore with matching row counts, and
measured latency — without the system of record ever moving.

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
| ~~Free allowance covering a `Standard_B1ms` Flexible Server~~ | — | **Resolved 2026-07-29 (spec A1):** it does not apply. Azure for Students is a $100 credit, not the free account. Measured $24.57/month ($0.81/day); accepted for a short-lived trial |
| ~~How long the instance lives~~ | — | **Resolved 2026-07-29 (spec A1):** evaluation only. Phases 1–3 run, then teardown; phase 4 is deferred, so nothing is cut over and no data can be stranded |
| **The `resources` corpus is empty** (0 rows, 0 embeddings) | Phase 3's embedding check compares 0 to 0 and proves nothing; the resource half of FR-CC-13 stays unanswerable | Accepted (spec A2). The check is kept — it costs nothing and becomes meaningful once aggregation works |
| Flexible Server availability in `newzealandnorth` — this subscription's region policy already blocked Static Web Apps everywhere (`infra/dashboard.bicep`) | Instance cannot be co-located with the VM; either a policy-allowed but distant region (worse per-query latency) or the non-Azure fallback | Spike: Phase 2 Task 1 runs `az postgres flexible-server list-skus` against the region before provisioning |
| asyncpg honouring `sslmode=require` supplied in the DSN — assumed from libpq-style parsing, never exercised here | Cutover fails at connect time, or connects unencrypted | Spike: Phase 2 Task 4 connects from the VM using the app's own client and DSN form, before any data moves |
| `azure.extensions` accepting `VECTOR`, and the server's pgvector supporting `VECTOR(384)` and `<=>` | `CREATE EXTENSION vector` fails, so the `resources` restore fails and the corpus has nowhere to land | Spike: Phase 2 Task 4 creates the extension and runs a probe cosine query before the migration runs |
| Flexible Server rejecting parallel child-resource writes (database / configurations / firewall rule deployed together) | Provisioning deployment fails part-way | Accepted risk, mitigated: `postgres.bicep` chains the children with explicit `dependsOn`, and re-running the deployment is idempotent |
| The current value of the `DATABASE_URL` Actions secret is unknowable (GitHub does not read secrets back) and it is shadowed today, so it may be empty or stale | Removing the compose pin renders an empty DSN onto the VM and the next scheduled run dies at connect time | Ordering: Phase 1 Task 1 sets the secret to the VM-local DSN *before* Task 2 removes the pin, and Task 4 proves the seam on the unchanged database |
| `pg_dump` / `psql` client version skew against the managed server | Restore fails or silently drops objects | Accepted risk, mitigated: both run inside the VM's own `pgvector/pgvector:pg16` container, and the server's major version is pinned to 16 to match |

## Blast Radius

- **Code that will change:** `docker-compose.yaml`, `docker-compose.override.yaml`
  (new), `.dockerignore`, `infra/`, `.github/workflows/infra-provision.yml`,
  `scripts/verify_migration.py` (new), `tests/`, `docs/commands.md`,
  `README.md`, `docs/project/specification/career-coach-agent-prs.md`.
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
| 2 | Provision the instance | [phase-2-provision-instance.md](phase-2-provision-instance.md) | **Complete** |
| 3 | Migrate and verify | [phase-3-migrate-and-verify.md](phase-3-migrate-and-verify.md) | **Complete** — instance migrated onto, verified, then deleted (evaluation cost $0.07) |
| 4 | Cutover, documentation, and the exit | [phase-4-cutover-and-docs.md](phase-4-cutover-and-docs.md) | **Deferred** — needs funded standing cost (spec A1). Now also carries Task 4, the migrate-back and retirement path (spec A5) |

> All phases are planned in advance — every row above has a written,
> human-approved phase doc before phase 1 execution starts. If executing
> an earlier phase surfaces a needed change to a later phase doc, update
> that doc explicitly and record the change in its Notes / Learnings
> section; don't leave later phases undocumented.

---

## Testing Strategy

- **Unit:** per-task TDD in the phase docs covers the compose/workflow guards
  (`tests/test_compose_database_url.py`), the non-local-database refusal in the
  test fixtures (`tests/test_local_db_guard.py`), the template shape and
  secret-handling guards (`tests/test_infra_postgres_template.py`), and the
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

  That cheap rollback is a **discard**, and it stays acceptable only while the
  grace period does. To unwind without losing anything — or to retire the
  managed instance at all once it is the system of record — use **phase 4
  Task 4**, which copies the data back before touching the secret and deletes
  the server last. Flipping the secret first would point the pipeline at a
  stale database while the good copy sat in a resource queued for deletion.

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
- **Provisioning is priced before it exists.** The free allowance is documented
  for one class of subscription and this one's status is not assumed.
- **The migration runs from the VM, not CI.** The VM's public IP is static and
  already the only allow-listed address; CI runners rotate across a range far
  too wide to allow-list for one dump.
- ⚠️ **One-way doors:**
  - **Provisioning the instance** (Phase 2 Task 3) — begins standing cost, and
    networking mode is fixed at creation. Requires human sign-off on the price
    established in Task 1.
  - **The cutover** (Phase 4 Task 1) — repoints the system of record. Requires
    the human to read the Phase 3 verification output and explicitly approve.

## Out of Scope

- Removing or retiring the VM's `postgres` container — it *is* the rollback
  target; teardown is a separate change after the grace period.
- The Discord bot and any networking on its behalf (P7), including how a
  Consumption-plan Function will be granted access.
- Any schema or query change; any migration tooling.
- Private networking (VNet integration / private endpoints), Entra
  authentication, high availability, geo-redundant backup, read replicas, and
  connection-pooling changes.

---

## Definition of Done

> **This pass is phases 1–3 only.** The criteria below that depend on cutover
> — a full cycle on the managed instance, querying while the VM is
> deallocated, rollback-by-secret — are deferred with phase 4, not abandoned.

- [ ] All acceptance criteria met *(minus the cutover-dependent ones)*
- [ ] All phase 1–3 verification steps pass
- [ ] The instance is proven manually: TLS on, pgvector working, row counts
      matching, latency measured
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
