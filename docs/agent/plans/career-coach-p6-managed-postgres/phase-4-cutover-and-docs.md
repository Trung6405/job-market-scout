# Phase 4: Cutover and Documentation

> **Parent plan:** [plan.md](plan.md)
> **Status:** Not started
> **Depends on:** Phase 3 complete (counts verified and read by the human)

---

## Goal

Repoint the pipeline at the managed instance by changing one secret, prove a
full cycle runs against it with unchanged output, and leave behind a rollback
runbook plus the corrections this phase owes the umbrella PRS. Done when the
day's run is recorded on the managed instance, the dashboard renders from it,
and the VM's container is still sitting there holding its data.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — Task 1 rewrites the `DATABASE_URL` deploy secret to a DSN carrying the
  administrator password, and the whole pipeline follows it.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  Yes — Task 1 moves the system of record. It is reversible by the same secret
  change for as long as the VM's container keeps its data, which is what makes
  the grace period load-bearing rather than ceremonial. It is gated on the
  human having read Phase 3's verification output.

---

## Tasks

### Task 1: Repoint the pipeline

- **Files:** none — this is the `DATABASE_URL` repository secret.
- **Gate:** ⚠️ human sign-off required before this task. Do not run it until
  the human has read Phase 3's verification report in conversation and said to
  proceed. This is the one-way door the umbrella PRS's sign-off gate exists
  for: an automated verification that passes for the wrong reason would
  repoint the system of record with nobody having looked.
- **Steps:**
  - [ ] Confirm nothing is mid-run — a cutover between the scrape and the
    persist would split one cycle across two databases:

    ```bash
    gh run list --workflow='Scheduled run' --limit 1
    gh run list --workflow=Deploy --limit 1
    ```

    Expected: both `completed`.

  - [ ] Set the secret to the managed DSN. `sslmode=require` is what makes the
    connection encrypted in transit, and Phase 2 Task 4 already proved asyncpg
    honours it:

    ```bash
    read -rs -p 'managed DSN: ' MANAGED_DSN
    gh secret set DATABASE_URL --repo Trung6405/job-market-scout --body "$MANAGED_DSN"
    unset MANAGED_DSN
    ```

    The value is
    `postgresql://scoutadmin:<password>@trung6405-scout-pg.postgres.database.azure.com:5432/scout?sslmode=require`.

  - [ ] Redeploy so the VM's `scout/.env` is re-rendered from it:

    ```bash
    gh workflow run Deploy
    gh run watch "$(gh run list --workflow=Deploy --limit 1 --json databaseId --jq '.[0].databaseId')"
    ```

  - [ ] Confirm the container now resolves the managed host, without printing
    the password:

    ```bash
    ssh azureuser@"$VM_HOST" \
      "cd /opt/job-market-scout && docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
        run --rm app python -c \"
    from urllib.parse import urlparse
    from scout.config import Settings
    print(urlparse(Settings().database_url).hostname)\""
    ```

    Expected: `trung6405-scout-pg.postgres.database.azure.com`

  - [ ] No commit.

### Task 2: Prove a full cycle on the managed instance

- **Files:** none — this is the manual verification the plan's Definition of
  Done requires.
- **Gate:** none — the gate was Task 1.
- **Steps:**
  - [ ] Note the managed instance's current run count, so the new run is
    unambiguous:

    ```bash
    export SOURCE_DSN='postgresql://scout:scout@postgres:5432/scout'
    read -rs -p 'managed DSN: ' TARGET_DSN && export TARGET_DSN
    ssh azureuser@"$VM_HOST"  # then, on the VM, in /opt/job-market-scout:
    docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
      run --rm -e SOURCE_DSN -e TARGET_DSN app python -m scripts.verify_migration
    ```

    Expected: still all matching — nothing has written anywhere yet.

  - [ ] Run one full cycle:

    ```bash
    gh workflow run "Scheduled run"
    gh run watch "$(gh run list --workflow='Scheduled run' --limit 1 --json databaseId --jq '.[0].databaseId')"
    ```

  - [ ] Confirm the run landed on the managed instance and *not* on the VM's
    container — re-running the comparison is the sharpest form of this, because
    the target should now be ahead of the source:

    ```bash
    docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
      run --rm -e SOURCE_DSN -e TARGET_DSN app python -m scripts.verify_migration
    ```

    Expected: `runs`, `run_listings` and friends higher on the target than the
    source, and the closing line reporting a mismatch. That "failure" is the
    proof: the old database stopped receiving writes.

  - [ ] Confirm the history page still shows the pre-move runs alongside
    today's — the whole point of copying rather than starting fresh. Load the
    dashboard's history page and check that a run from before the migration
    still renders, along with its job-detail page, gaps and tips.
  - [ ] Confirm grounded tips still cite resources, which exercises the vector
    retrieval path against the managed instance end to end. Open any
    job-detail page with a skill gap and check the tip's citations resolve.
  - [ ] Record in Notes: the cutover date (the grace period starts here), the
    post-cycle counts, and anything that looked different.
  - [ ] No commit.

### Task 3: Document the new topology, the rollback, and the PRS corrections

- **Files:**
  - Modify: `infra/README.md`
  - Modify: `docs/commands.md`
  - Modify: `README.md`
  - Modify: `docs/project/specification/career-coach-agent-prs.md`
  - Modify: `docs/agent/plans/career-coach-p6-managed-postgres/plan.md` (phase
    statuses and Definition of Done)
- **Gate:** none
- **Steps:**

  - [ ] **Step 1: `infra/README.md`**

    Add `postgres.bicep` and `postgres.bicepparam` to the Files table:

    | File | What it is |
    |------|------------|
    | `postgres.bicep` | Azure Database for PostgreSQL Flexible Server (Burstable `Standard_B1ms`, 32 GiB, no HA, locally-redundant backup), the `scout` database, the `azure.extensions` allow-list entry pgvector needs, and a firewall rule admitting only the VM's static IP. |
    | `postgres.bicepparam` | Server name and region. The admin password and the allowed client IP are read from the environment at deploy time (`POSTGRES_ADMIN_PASSWORD`, `VM_HOST`) — never committed. |

    Add `POSTGRES_ADMIN_PASSWORD` to the secrets list in the one-time setup
    section, and add a subsection recording the topology and the rollback:

    ````markdown
    ## The database lives on managed Postgres (P6)

    Since the P6 cutover the pipeline's system of record is the Flexible Server
    in `postgres.bicep`, not the `postgres` container on the VM. The container
    is still running and still holds its pre-cutover data: it is the rollback
    target for the grace period, and it is deliberately not retired here.

    - **Do not run `docker compose down -v` on the VM.** That drops the volume
      and with it the only thing rollback depends on.
    - **Rollback** is a secret change and a redeploy, not a restore:

      ```bash
      gh secret set DATABASE_URL --repo Trung6405/job-market-scout \
        --body 'postgresql://scout:scout@postgres:5432/scout'
      gh workflow run Deploy
      ```

      Runs recorded on the managed instance after the cutover are not carried
      back. The pipeline is idempotent per run date, so the cost is at most one
      re-run.

    - **Access** is one firewall rule for the VM's static IP. `VM_HOST` feeds
      both that rule and the deploy's SSH target, so changing the VM's public
      IP means re-running `Provision infra` as well as updating the variable.
    - **Local development and CI never touch it:** `docker-compose.override.yaml`
      supplies the in-network DSN for local runs, `deploy.yml`'s test job sets
      `DATABASE_URL` to its own service container, and `tests/conftest.py`
      refuses to run against a non-local host.
    ````

  - [ ] **Step 2: `docs/commands.md`**

    Under the stack-management section, note that `docker compose down -v` now
    wipes only the rollback copy rather than the live history, and add the
    verification command:

    ````markdown
    ### Compare the VM database against the managed instance
    Read-only on both sides — the row counts the P6 cutover was decided from,
    and the way to check the two have diverged as expected since:
    ```bash
    export SOURCE_DSN='postgresql://scout:scout@postgres:5432/scout'
    read -rs -p 'managed DSN: ' TARGET_DSN && export TARGET_DSN
    docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
      run --rm -e SOURCE_DSN -e TARGET_DSN app python -m scripts.verify_migration
    ```
    ````

  - [ ] **Step 3: `README.md`**

    Where the README describes the deployed stack, record that Postgres is now
    a managed instance reachable independently of the VM's power state, and
    that the VM's container remains as the rollback target. Where it explains
    local setup, note that `docker compose up` picks up
    `docker-compose.override.yaml` automatically and that `scout/.env` supplies
    the host-side DSN for `pytest`.

  - [ ] **Step 4: `docs/project/specification/career-coach-agent-prs.md`**

    Correct the three points in place and record the reasoning in a new
    `## 11. Amendments` section at the end of the file:

    - §4.2 P6 row and D-CC-8 both name `resources` / `listing_gaps` /
      `run_listings` / `runs` — replace with all six of `listings`, `runs`,
      `run_listings`, `listing_gaps`, `listing_tips`, `resources`.
    - D-CC-8 gains the pgvector allow-list step: the extension must be added to
      the server's `azure.extensions` parameter before `CREATE EXTENSION` can
      succeed, which has no counterpart in the container image.
    - NFR-CC-2's sub-100 ms retrieval budget was written against a same-host
      database; after P6 every query crosses a network with TLS. The budget
      still holds — small corpus, selective pre-filter, same region — but the
      assumption it was written under no longer does.

    ```markdown
    ## 11. Amendments

    Corrections made while implementing P6
    (`docs/agent/specs/career-coach-p6-managed-postgres/spec.md`). The sections
    above are updated in place; this table keeps the reasoning.

    | PRS said | Now | Why |
    |---|---|---|
    | §4.2 / D-CC-8: migrate `resources` / `listing_gaps` / `run_listings` / `runs` — four tables. | Six tables: adds `listings` and `listing_tips`. | The four named are not a closed set under their foreign keys: `run_listings` references `listings`, and `listing_tips` references `run_listings`. Migrating four would have restored a database whose gap rows point at listings that aren't there. |
    | D-CC-8 describes provisioning a Flexible Server with pgvector, as though the extension is available the way it is in the container image. | pgvector must first be added to the server's `azure.extensions` parameter; only then can `CREATE EXTENSION vector` run. | The allow-list is a managed-service step with no counterpart in `pgvector/pgvector:pg16`, and it fails at exactly the point that looks like it should work: `scout/shared/schema.sql` runs `CREATE EXTENSION IF NOT EXISTS vector` on every startup and would simply error. |
    | NFR-CC-2: typical top-k retrieval < 100 ms, written when Postgres was a container on the same host as the pipeline. | Budget unchanged, assumption recorded: retrieval now crosses a network and does TLS on every query, and a run issues many queries. | Still comfortably met — the corpus is small, the `skills @>` pre-filter is selective, and the instance is in the VM's region — but a future latency surprise should be diagnosed against the real topology rather than rediscovered. |
    ```

  - [ ] **Step 5: Update this plan's status**

    In `plan.md`, set every phase row to `Complete`, set the header `Status` to
    `Complete`, and tick the Definition of Done checkboxes — in this same
    commit, not a follow-up one.

  - [ ] **Step 6: Verify and commit**

    ```bash
    pytest -q
    git add infra/README.md docs/commands.md README.md \
      docs/project/specification/career-coach-agent-prs.md \
      docs/agent/plans/career-coach-p6-managed-postgres/
    git commit -m "docs: record the managed Postgres topology and its rollback (P6)

The pipeline's system of record is now the Flexible Server, and the VM's
postgres container is the rollback target rather than dead weight — which
makes 'docker compose down -v on the VM' a destructive command it wasn't
before, so it is called out where someone would reach for it.

Also carries three corrections into the career-coach PRS rather than diverging
from it silently: the foreign-key-connected set is six tables, not the four it
names; pgvector needs an azure.extensions allow-list entry before CREATE
EXTENSION can succeed; and NFR-CC-2's latency budget was written against a
same-host database that no longer exists."
    ```

---

## Verification

- [ ] Full suite passes: `pytest -q`
- [ ] `Settings().database_url` on the VM resolves to the managed host (Task 1)
- [ ] A full `Scheduled run` completed after the cutover
- [ ] `python -m scripts.verify_migration` shows the target ahead of the source
      afterwards — writes stopped reaching the VM's container
- [ ] A pre-migration run still renders on the history page, with its
      job-detail page, gaps, and cited tips
- [ ] The VM's `postgres` container is still running with its volume intact:
      `ssh azureuser@"$VM_HOST" 'docker ps --filter name=postgres'`

## Observability

- The pipeline emits no connection-string log line by design, so the signal
  that the cutover took is behavioural: after cutover, `runs` on the managed
  instance gains a row each day and the VM's copy stops growing. The
  `verify_migration` report is the readout for that.
- A failed cutover is loud, not silent: `asyncpg` raises at pool creation and
  the `Run scout cycle` step fails before any stage runs, so a half-written
  day is not a failure mode here.
- A firewall or TLS regression surfaces the same way — `Run scout cycle` fails
  at connect. If the VM's public IP ever changes, that is what it looks like.

## Rollback

Set the secret back and redeploy:

```bash
gh secret set DATABASE_URL --repo Trung6405/job-market-scout \
  --body 'postgresql://scout:scout@postgres:5432/scout'
gh workflow run Deploy
```

The VM's container has been running and holding its data throughout, so this
is a configuration change and not a restore — for as long as the grace period
lasts and the volume is intact. Runs recorded on the managed instance after
cutover do not come back with it; the pipeline is idempotent per run date, so
re-running the day covers it. The Task 3 documentation commit can be reverted
separately, or amended to describe the reverted state.

---

## Notes / Learnings

*(filled in during execution — record the cutover date, since the grace period
runs from it, and the post-cycle verification output)*
