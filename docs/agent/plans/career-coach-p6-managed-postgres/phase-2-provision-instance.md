# Phase 2: Provision the Instance

> **Parent plan:** [plan.md](plan.md)
> **Status:** Complete — all four tasks done, all verification passing. The
> server is provisioned and billing; Phase 3 ends by deleting it.
> **Depends on:** Phase 1 complete (the secret is the seam, and it is proven)

---

## Goal

Stand up an Azure Database for PostgreSQL Flexible Server from committed Bicep
— smallest Burstable shape, pgvector allow-listed, reachable only from the
scout VM — and prove the pipeline's own client can connect to it over TLS and
run a vector query. Done when a probe from the VM using asyncpg and a
`sslmode=require` DSN creates the extension and returns a cosine distance,
while the pipeline is still writing to the old database.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — a new administrator password is generated and stored as a repository
  secret, and the server takes a public endpoint restricted by IP allow-list.
  The password is never written to a committed file: `postgres.bicepparam`
  reads it from the environment at deploy time.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  Yes — Task 3 creates the instance, which begins standing cost and fixes the
  networking mode permanently. It is gated on the price established in Task 1.

---

## Tasks

### Task 1: Price the instance and confirm the region serves it

- **Files:** none — findings are recorded in this doc's Notes section.
- **Gate:** ⚠️ human sign-off required before proceeding past this task. This
  is the spec's "no standing cost begins without it having been explicitly
  confirmed and accepted first". If the shape carries an unacceptable charge,
  stop and return to the human — the spec's recorded fallback is a free managed
  Postgres outside Azure (Neon/Supabase), which is a different plan.
- **Steps:**
  - [x] Log in and select the subscription the rest of the infra lives in:

    ```bash
    az login
    az account show --query "{name:name, id:id, state:state}" -o json
    ```

  - [x] Confirm the VM's region serves Flexible Server at the smallest
    Burstable shape. `newzealandnorth` is the region `infra/main.bicepparam`
    pins, and this subscription's policy already blocked Static Web Apps
    outright, so availability is not assumed:

    ```bash
    az postgres flexible-server list-skus --location newzealandnorth -o table | grep -i b1ms
    ```

    Expected: a `Standard_B1ms` row under the `Burstable` tier. If the region
    serves nothing, re-run against the other policy-allowed regions
    (`indonesiacentral`, `japanwest`, `japaneast`, `malaysiawest`) and record
    which serve it — a non-co-located instance changes the latency note in the
    spec and is a decision to bring back, not absorb.

  - [x] Price the compute and the storage on this subscription's currency:

    ```bash
    curl -s "https://prices.azure.com/api/retail/prices?\$filter=serviceName%20eq%20'Azure%20Database%20for%20PostgreSQL'%20and%20armRegionName%20eq%20'newzealandnorth'%20and%20skuName%20eq%20'B1ms'" \
      | python -m json.tool
    curl -s "https://prices.azure.com/api/retail/prices?\$filter=serviceName%20eq%20'Azure%20Database%20for%20PostgreSQL'%20and%20armRegionName%20eq%20'newzealandnorth'%20and%20contains(meterName,%20'Storage')" \
      | python -m json.tool
    ```

  - [x] Check whether this subscription's free allowance covers the shape
    (12 months of `Standard_B1ms` at 750 h/month plus 32 GiB storage is
    documented for the Azure free account, and this subscription's offer type
    is exactly what is unverified). In the portal: **Subscriptions → this
    subscription → Overview** for the offer, then **Cost Management → Free
    services** for what remains of any allowance.
  - [x] Record in Notes below: region, SKU availability, monthly compute price,
    monthly storage price, whether the free allowance applies, and the human's
    decision.
  - [x] **STOP.** Do not proceed to Task 2 until the human has accepted the
    cost in conversation.
  - [x] No commit.

### Task 2: Add the Bicep template and its guards

- **Files:**
  - Create: `infra/postgres.bicep`
  - Create: `infra/postgres.bicepparam`
  - Create: `tests/test_infra_postgres_template.py`
  - Modify: `.github/workflows/infra-provision.yml`
- **Gate:** none — committing a template provisions nothing.
- **Steps:**

  - [x] **Step 1: Write the failing test**

    Create `tests/test_infra_postgres_template.py`:

    ```python
    """The managed Postgres template must keep the shape P6 signed off on.

    Three things about `infra/postgres.bicep` are load-bearing and none would
    fail loudly if they drifted: the admin password must never be committed
    (NFR-CC-7); the instance must stay the smallest Burstable shape, because
    anything larger forfeits free-allowance eligibility rather than merely
    costing more; and pgvector must stay on the server's extension allow-list,
    without which `CREATE EXTENSION vector` fails and the corpus has nowhere to
    land — a step with no counterpart in the container this data comes from.

    Assertions run against the Bicep source text rather than a compiled ARM
    template so the suite needs no Azure CLI.
    """

    from __future__ import annotations

    import re
    from pathlib import Path

    import yaml

    _ROOT = Path(__file__).resolve().parent.parent
    _BICEP = (_ROOT / "infra" / "postgres.bicep").read_text(encoding="utf-8")
    _BICEPPARAM = (_ROOT / "infra" / "postgres.bicepparam").read_text(encoding="utf-8")


    def test_admin_password_parameter_is_marked_secure():
        assert "@secure()" in _BICEP
        assert "param administratorLoginPassword string" in _BICEP


    def test_admin_password_is_never_committed():
        assignment = re.search(
            r"param administratorLoginPassword\s*=\s*(.+)", _BICEPPARAM
        )
        assert assignment is not None, "the param file must supply the password"
        assert assignment.group(1).strip().startswith("readEnvironmentVariable("), (
            "supply the password from POSTGRES_ADMIN_PASSWORD at deploy time, "
            "never as a literal in a committed file"
        )


    def test_instance_keeps_the_smallest_free_tier_shape():
        assert "param skuName string = 'Standard_B1ms'" in _BICEP
        assert "param storageSizeGB int = 32" in _BICEP
        assert "tier: 'Burstable'" in _BICEP
        assert "geoRedundantBackup: 'Disabled'" in _BICEP
        assert "highAvailability: {" in _BICEP
        assert "mode: 'Disabled'" in _BICEP


    def test_major_version_matches_the_container_being_migrated_from():
        """pgvector/pgvector:pg16 is the source, so this is a same-major move."""
        assert "param postgresVersion string = '16'" in _BICEP


    def test_pgvector_is_on_the_extension_allow_list():
        assert "'azure.extensions'" in _BICEP
        assert "VECTOR" in _BICEP


    def test_access_is_restricted_to_a_single_allow_listed_address():
        assert "flexibleServers/firewallRules" in _BICEP
        assert "param allowedClientIp string" in _BICEP
        assert "startIpAddress: allowedClientIp" in _BICEP
        assert "endIpAddress: allowedClientIp" in _BICEP


    def test_provision_workflow_deploys_the_postgres_template():
        workflow = yaml.safe_load(
            (_ROOT / ".github" / "workflows" / "infra-provision.yml").read_text(
                encoding="utf-8"
            )
        )
        scripts = "\n".join(
            step.get("run", "") for step in workflow["jobs"]["provision"]["steps"]
        )
        assert "infra/postgres.bicep" in scripts
    ```

  - [x] **Step 2: Run the test to verify it fails**

    Run: `pytest tests/test_infra_postgres_template.py -v`
    Expected: FAIL at collection with `FileNotFoundError` for
    `infra/postgres.bicep`.

  - [x] **Step 3: Write the template**

    Create `infra/postgres.bicep`:

    ```bicep
    targetScope = 'resourceGroup'

    // Deliberately separate from main.bicep (the VM template), for the same
    // reason dashboard.bicep is: redeploying main.bicep against an existing VM
    // fails ARM's authorization check on osProfile.customData and aborts the
    // whole deployment, including unrelated resources in the same template.
    //
    // This server is the system of record from P6 onward. It exists because the
    // scout VM is deallocated ~23h/day, which made the data unreachable
    // whenever anyone wanted to ask the system something (FR-CC-13).

    @description('Azure region. Must match the VM\'s region so per-query latency stays local, and must be one of this subscription\'s policy-allowed regions.')
    param location string

    @description('Globally-unique name for the PostgreSQL Flexible Server.')
    param serverName string

    @description('Compute SKU. Standard_B1ms is the smallest Burstable shape and the one a free allowance covers — a larger shape does not merely cost more, it forfeits eligibility.')
    param skuName string = 'Standard_B1ms'

    @description('Provisioned storage in GiB. 32 is the minimum Flexible Server offers and the amount the free allowance covers; the whole corpus and run history is a few MB.')
    param storageSizeGB int = 32

    @description('PostgreSQL major version, pinned to match the pgvector/pgvector:pg16 container the data comes from so the migration is a copy, not an upgrade.')
    param postgresVersion string = '16'

    @description('Administrator login name.')
    param administratorLogin string = 'scoutadmin'

    @secure()
    @description('Administrator password, supplied at deploy time from the POSTGRES_ADMIN_PASSWORD environment variable (NFR-CC-7). Never stored in the .bicepparam file.')
    param administratorLoginPassword string

    @description('The scout VM\'s static public IP — the only address granted access in this phase. P7 decides its own connectivity.')
    param allowedClientIp string

    @description('Application database name. Matches the container\'s so the connection string differs only in host and credentials.')
    param databaseName string = 'scout'

    resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
      name: serverName
      location: location
      sku: {
        name: skuName
        tier: 'Burstable'
      }
      properties: {
        version: postgresVersion
        administratorLogin: administratorLogin
        administratorLoginPassword: administratorLoginPassword
        storage: {
          storageSizeGB: storageSizeGB
          autoGrow: 'Disabled'
        }
        backup: {
          backupRetentionDays: 7
          geoRedundantBackup: 'Disabled'
        }
        highAvailability: {
          mode: 'Disabled'
        }
        // Public endpoint restricted by the firewall rule below. Networking
        // mode is fixed at creation time on Flexible Server, so choosing VNet
        // integration here would be irreversible for no present benefit: one
        // VM today, one Function later.
        network: {
          publicNetworkAccess: 'Enabled'
        }
      }
    }

    resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
      parent: server
      name: databaseName
      properties: {
        charset: 'UTF8'
        collation: 'en_US.utf8'
      }
    }

    // pgvector is not available by default the way it is in the container
    // image: it must be on the server's extension allow-list before
    // `CREATE EXTENSION vector` — which scout/shared/schema.sql runs on every
    // startup — can succeed.
    resource vectorAllowList 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
      parent: server
      name: 'azure.extensions'
      properties: {
        value: 'VECTOR'
        source: 'user-override'
      }
      // The children are chained rather than deployed in parallel: Flexible
      // Server rejects concurrent writes to a server that is still settling a
      // previous one.
      dependsOn: [database]
    }

    resource allowScoutVm 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
      parent: server
      name: 'allow-scout-vm'
      properties: {
        startIpAddress: allowedClientIp
        endIpAddress: allowedClientIp
      }
      dependsOn: [vectorAllowList]
    }

    output serverFqdn string = server.properties.fullyQualifiedDomainName
    output databaseNameOut string = databaseName
    output administratorLoginOut string = administratorLogin
    ```

    Create `infra/postgres.bicepparam`:

    ```bicep
    using './postgres.bicep'

    param location = 'newzealandnorth'
    param serverName = 'trung6405-scout-pg'
    // Read from the environment, never committed: the password is a secret
    // (NFR-CC-7) and the client IP is already the VM_HOST Actions variable, so
    // reading it here keeps the firewall rule from drifting out of sync with
    // the address the deploy actually uses.
    param administratorLoginPassword = readEnvironmentVariable('POSTGRES_ADMIN_PASSWORD')
    param allowedClientIp = readEnvironmentVariable('VM_HOST')
    ```

    In `.github/workflows/infra-provision.yml`, add a step after the dashboard
    deployment (deployment name defaults to the template's base name, matching
    how the `dashboard` deployment is looked up later in the same file):

    ```yaml
          - name: Deploy managed Postgres Bicep (postgres.bicep)
            env:
              # readEnvironmentVariable() in postgres.bicepparam reads both of
              # these at compile time. Neither has a default, so a missing
              # secret fails the deployment loudly rather than provisioning a
              # server with an empty password or a wide-open firewall rule.
              POSTGRES_ADMIN_PASSWORD: ${{ secrets.POSTGRES_ADMIN_PASSWORD }}
              VM_HOST: ${{ vars.VM_HOST }}
            run: |
              set -euo pipefail
              az deployment group create \
                --resource-group "$RESOURCE_GROUP" \
                --template-file infra/postgres.bicep \
                --parameters infra/postgres.bicepparam \
                --query "properties.outputs" -o json
    ```

  - [x] **Step 4: Run the test to verify it passes**

    Run: `pytest tests/test_infra_postgres_template.py -v`
    Expected: PASS (7 tests)

  - [x] **Step 5: Compile the template**

    ```bash
    az bicep build --file infra/postgres.bicep --stdout > /dev/null
    ```

    Expected: no output and exit 0. A warning about an unknown API version
    means the pinned `2024-08-01` is not in the local Bicep type index — run
    `az bicep upgrade` and re-check before changing the API version.

  - [x] **Step 6: Commit**

    ```bash
    git add infra/postgres.bicep infra/postgres.bicepparam \
      .github/workflows/infra-provision.yml tests/test_infra_postgres_template.py
    git commit -m "feat(infra): template the always-on managed Postgres (P6)

Smallest Burstable shape, no HA, locally-redundant backups, major version
pinned to 16 to match the pgvector/pgvector:pg16 container the data will be
copied from. Public endpoint restricted to the VM's static IP — networking
mode is fixed at creation on Flexible Server, so VNet integration would be an
irreversible choice for no present benefit.

pgvector needs the azure.extensions allow-list before CREATE EXTENSION can
succeed, which is a step with no counterpart in the container image and is
easy to miss: schema.sql would simply fail. The password is read from the
environment at deploy time so nothing sensitive is committed (NFR-CC-7).

Provisions nothing on its own — infra-provision.yml is manual dispatch."
    ```

### Task 3: Provision the server

- **Files:** none — this runs the committed template.
- **Gate:** ⚠️ human sign-off required before this task — it creates the
  billable resource and permanently fixes the networking mode. Do not run it
  until the human has accepted the price recorded in Task 1's Notes.
- **Steps:**
  - [x] Generate an administrator password and store it as a repository secret.
    Azure rejects passwords containing the login name and requires 8–128 chars
    from three of the four character classes:

    ```bash
    PGPW="$(python -c "import secrets, string; alphabet = string.ascii_letters + string.digits + '-_.~'; print(''.join(secrets.choice(alphabet) for _ in range(32)))")"
    gh secret set POSTGRES_ADMIN_PASSWORD --repo Trung6405/job-market-scout --body "$PGPW"
    ```

    Keep `$PGPW` in this shell — Tasks 4 and Phase 3 need it, and GitHub will
    not read it back. Store it in the password manager before closing the shell.

  - [x] Confirm `VM_HOST` is the VM's current static public IP, since it becomes
    the firewall rule:

    ```bash
    gh variable list --repo Trung6405/job-market-scout | grep VM_HOST
    az network public-ip show -g "$RESOURCE_GROUP" -n scout-vm-pip --query ipAddress -o tsv
    ```

    Expected: the two match. If not, fix `VM_HOST` first — the deploy and
    scheduled-run workflows use it to reach the VM as well.

  - [x] Preflight with `what-if` first — it validates against ARM and creates
    nothing, so a policy denial or a bad SKU surfaces before any billing
    starts. The dummy password is never used to create anything:

    ```bash
    POSTGRES_ADMIN_PASSWORD='Dummy-WhatIf-Only' VM_HOST="$VM_HOST"       az deployment group what-if --resource-group "$RESOURCE_GROUP"       --template-file infra/postgres.bicep --parameters infra/postgres.bicepparam
    ```

    Expected: `Succeeded`, with `Create` for the server, its `scout` database,
    the `azure.extensions` configuration and the `allow-scout-vm` firewall
    rule — and nothing else changing.

  - [x] Dispatch the provisioning workflow and watch it:

    ```bash
    gh workflow run "Provision infra"
    gh run watch "$(gh run list --workflow='Provision infra' --limit 1 --json databaseId --jq '.[0].databaseId')"
    ```

    ⚠️ **This does not work from a feature branch, and that is not a transient
    failure** — the Azure OIDC federated credential is subject-scoped to
    `refs/heads/main` alone, so the dispatch dies at `azure/login` before any
    `az deployment` runs. Provisioned instead by running the same committed
    template and `.bicepparam` from the local `az` CLI, deployment named
    `postgres` to match what the workflow step would have produced. See Notes.

    ```bash
    POSTGRES_ADMIN_PASSWORD="$PGPW" VM_HOST="$VM_HOST" \
      az deployment group create --resource-group "$RESOURCE_GROUP" --name postgres \
      --template-file infra/postgres.bicep --parameters infra/postgres.bicepparam \
      --query "properties.outputs" -o json
    ```

  - [x] Read the outputs and record the FQDN in Notes:

    ```bash
    az deployment group show -g "$RESOURCE_GROUP" -n postgres \
      --query properties.outputs -o json
    ```

  - [x] Confirm the shape actually created matches what was priced:

    ```bash
    az postgres flexible-server show -g "$RESOURCE_GROUP" -n trung6405-scout-pg \
      --query "{sku:sku.name, tier:sku.tier, version:version, storage:storage.storageSizeGb, ha:highAvailability.mode, backup:backup.geoRedundantBackup}" -o json
    ```

    Expected: `Standard_B1ms`, `Burstable`, `16`, `32`, `Disabled`, `Disabled`.

  - [x] No commit — no code changed. *(But the Notes below record measurements
    that cannot be re-derived without paying to provision again, and Phase 3's
    teardown is gated on them being captured, so they should not be left
    sitting in a working tree.)*

### Task 4: Prove the pipeline's own client can reach it over TLS with pgvector

- **Files:** none — a one-off probe run from the VM.
- **Gate:** none — read-only against the new, still-empty instance. Nothing
  touches the old database.
- **Steps:**
  - [x] From the VM, connect with the app's own client library and DSN form.
    This is the step that settles whether asyncpg honours `sslmode=require`
    supplied in the DSN, and whether the allow-listed extension can actually be
    created — both assumed, neither previously exercised here:

    ```bash
    ssh azureuser@"$VM_HOST"
    cd /opt/job-market-scout
    read -rs -p 'managed DSN: ' TARGET_DSN && export TARGET_DSN
    docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
      run --rm -e TARGET_DSN app python -c "
    import asyncio, os, asyncpg

    async def main():
        conn = await asyncpg.connect(dsn=os.environ['TARGET_DSN'])
        print('server:', await conn.fetchval('SHOW server_version'))
        print('tls:', await conn.fetchval(
            'SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()'))
        await conn.execute('CREATE EXTENSION IF NOT EXISTS vector')
        print('pgvector:', await conn.fetchval(
            \"SELECT extversion FROM pg_extension WHERE extname = 'vector'\"))
        print('cosine:', await conn.fetchval(
            \"SELECT '[1,0,0]'::vector <=> '[0,1,0]'::vector\"))
        await conn.close()

    asyncio.run(main())
    "
    ```

    The DSN is
    `postgresql://scoutadmin:<password>@trung6405-scout-pg.postgres.database.azure.com:5432/scout?sslmode=require`
    — typed at the `read -rs` prompt so it never lands in shell history.

    Expected: server version `16.x`, `tls: True`, a pgvector version, and
    cosine distance `1.0`. If `tls` is False or the connect fails on the
    `sslmode` parameter, stop — TLS in transit is a must-have, and the fix
    belongs here rather than after data has moved.

  - [x] Confirm the firewall genuinely restricts access — the same connect from
    somewhere that is not the VM should be refused:

    ```bash
    # from your laptop, not the VM
    az postgres flexible-server firewall-rule list -g "$RESOURCE_GROUP" \
      --server-name trung6405-scout-pg -o table
    ```

    Expected: exactly one rule, `allow-scout-vm`, start and end both equal to
    `VM_HOST`. No `AllowAllAzureIps` / `0.0.0.0` rule.

    Listing the rules only reads the intent, so the refusal was also exercised
    directly — a TCP connect to the server from the laptop, which is not
    allow-listed:

    ```bash
    python -c "
    import socket
    s = socket.socket(); s.settimeout(15)
    s.connect(('trung6405-scout-pg.postgres.database.azure.com', 5432))
    "
    ```

    Expected: it does not connect.

  - [x] Record the observed server version, pgvector version, and TLS result in
    Notes.
  - [x] No commit — no code changed.

---

## Verification

- [x] Template guards pass: `pytest tests/test_infra_postgres_template.py -v`
      — 8 passed
- [x] Template compiles: `az bicep build --file infra/postgres.bicep --stdout > /dev/null`
      — clean, no warnings
- [x] Full suite still passes: `pytest -q` — 590 passed in 4m16s
- [x] `az postgres flexible-server show` reports the priced shape (Task 3)
- [x] The probe from the VM reports TLS on, pgvector created, and a cosine
      distance (Task 4) — `TLSv1.3`, pgvector `0.8.2`, cosine `1.0`
- [x] Exactly one firewall rule exists, scoped to the VM's IP — and a connect
      from a non-allow-listed address was confirmed to time out

## Rollback

The instance is empty and nothing points at it, so rollback is deletion:

```bash
az postgres flexible-server delete -g "$RESOURCE_GROUP" -n trung6405-scout-pg --yes
gh secret delete POSTGRES_ADMIN_PASSWORD --repo Trung6405/job-market-scout
```

Then revert the Task 2 commit to take the template and its provisioning step
back out. The pipeline is unaffected either way — it is still writing to the
VM's container throughout this phase.

---

## Notes / Learnings

### Task 1 — cost and region *(2026-07-29)*

- **Region and SKU: available.** `newzealandnorth` serves `Standard_B1ms`
  (and `Standard_B2s`) under the Burstable tier; supported majors are 11–18, so
  16 is pinnable; the storage floor is 32768 MB = 32 GiB. The shape this phase
  describes is buildable exactly as written.
- **Price: $24.57 USD/month**, about **$0.81/day** — `B1MS` compute at
  $0.02730/hr × 730 h = $19.93, plus 32 GiB at $0.14490/GB = $4.64. Backup up
  to provisioned size is included. Note the retail-price meter is named
  `B1MS` (uppercase) under "Burstable BS Series Compute", not `B1ms`.
- **The free allowance does not apply.** The subscription is *Azure for
  Students* — a $100 credit, not the Azure free account the 12-month free
  B1ms offer attaches to. Decision: proceed on a short-lived basis (spec A1).
- **Neon was explored and rejected** in between. Its Free plan has no IP
  allow-list (Scale-plan feature), which would have traded this design's
  single-IP restriction for a database guarded by its password alone. That
  work is parked on the `feat/career-coach-p6-neon` branch if the cost
  question is ever revisited.

### Task 2 — the template *(2026-07-29)*

- `az bicep build` compiles clean, no warnings — the pinned `2024-08-01` API
  version is recognised by the local Bicep type index.
- `az bicep build-params` was run **both ways** to check the fail-closed
  intent, not just the happy path. With `POSTGRES_ADMIN_PASSWORD` and
  `VM_HOST` set it resolves and renders the password as `securestring`;
  without them it fails with `BCP427 — Environment variable … does not exist
  and there's no default value set`. That is the desired behaviour: a missing
  secret stops the deployment rather than creating a server with an empty
  password or a firewall rule open to everything.
- The compiled ARM confirms the `dependsOn` chain came out as intended —
  database → `azure.extensions` → firewall rule — which is what keeps Flexible
  Server from rejecting concurrent child writes.
- **ARM `what-if` was run as a preflight, and it creates nothing.** It reported
  `status: Succeeded, error: None` with exactly four `Create` operations —
  the server, `databases/scout`, `configurations/azure.extensions` and
  `firewallRules/allow-scout-vm` — and `Ignore` for every existing resource
  (VM, NIC, NSG, public IP, VNet, disk, storage account, managed identity).
  Worth doing before the gate specifically because this subscription's region
  policy has silently refused a resource type before (Static Web Apps, see
  `infra/dashboard.bicep`); a policy denial would have surfaced here rather
  than half-way through a real deployment.
- The shape guards were rewritten before use. They originally justified
  pinning `Standard_B1ms` by free-tier eligibility, which A1 disproved; the
  reason now stated is cost, since `Standard_B2s` is $0.10920/hr against
  B1ms's $0.02730/hr and nothing else in the repo would catch that drift.

### Database measurements *(2026-07-29)*

Total **12 MB**, so 32 GiB is not a constraint at any horizon that matters.

| Table | Size | Rows |
|-------|------|------|
| `listings` | 3,544 kB | 880 (avg description 4,667 bytes) |
| `run_listings` | 384 kB | |
| `listing_gaps` | 312 kB | |
| `resources` | 48 kB | **0** (0 with embeddings) |
| `runs` | 40 kB | 8 (2026-07-22 → 2026-07-29) |
| `listing_tips` | 24 kB | |

Growth is ~1.5 MB/day across 8 days of history. `listings` never deletes — a
closed listing keeps its description — so the largest table only grows.

`resources` being empty is spec Amendment A2, and it makes this phase's
embedding verification vacuous for now.

### Task 3 — provisioning *(2026-07-30)*

The server exists and is `Ready`. The deployment reports `Succeeded` at
**2026-07-29T23:38:09Z** (2026-07-30 09:38 Sydney) after `PT6M52.8S`, so the
server was created around 23:31Z. **That is the clock the evaluation window
runs against** — roughly $0.81/day from then — and Phase 3 ends by deleting the
server.

| | |
|---|---|
| FQDN | `trung6405-scout-pg.postgres.database.azure.com` |
| Admin login | `scoutadmin` |
| Database | `scout` |
| Region | New Zealand North — co-located with `scout-vm`, confirmed from `az vm show`, not assumed from the param file |

Shape verified against Task 1's prices, all six pins as written:
`Standard_B1ms` / `Burstable` / `16` / `32` GiB / HA `Disabled` / geo-redundant
backup `Disabled`, with `publicNetworkAccess: Enabled`.
`azure.extensions` reads `VECTOR`, source `user-override` — so the allow-list
step landed, and Task 4's `CREATE EXTENSION` has what it needs. Exactly one
firewall rule, `allow-scout-vm`, `172.204.26.218`–`172.204.26.218`; no
`AllowAllAzureIps` and no `0.0.0.0`. `VM_HOST` was checked against
`scout-vm-pip` first and already matched.

**The workflow route does not work from a feature branch, and this is
structural rather than transient.** `az identity federated-credential list`
shows the `job-market-scout-gha` identity carries exactly one credential,
`gha-main`, subject `repo:Trung6405/job-market-scout:ref:refs/heads/main`.
Dispatching `Provision infra` on `feat/career-coach-p6-azure` failed at
`azure/login` with `AADSTS700213 — No matching federated identity record found
for presented assertion subject … refs/heads/feat/career-coach-p6-azure`. It
failed *before* the `az group create` step, so nothing was created and nothing
billed. Three routes were available — add a branch-scoped credential, merge to
`main` first, or run the deployment locally — and the local `az` CLI was chosen:
it runs the identical committed template and `.bicepparam`, so the artifact
under test is unchanged and only the credential path differs, and it avoids both
granting a throwaway branch main's infra rights and merging a provisioning step
that had never deployed successfully. The local ARM `what-if` had already
succeeded under the same credentials, so authorization was proven beforehand.

Two consequences the rest of this plan has to carry:

1. **The workflow's postgres step is unexercised.** Everything except that
   step's own `az deployment group create` invocation is proven; the step itself
   has never run green. Whoever eventually merges this to `main` is the first to
   exercise it.
2. **`infra-provision.yml` deploys all four templates in one job, so once the
   postgres step is on `main`, any later dispatch re-creates this billable
   server** — including after Phase 3 deletes it, and including dispatches made
   for an unrelated VM or dashboard change. That is the same silent-cost drift
   the Task 2 guards were written to prevent, and neither Phase 3 nor the
   deferred Phase 4 accounts for it. It needs resolving before the merge, not
   after. **Resolved — spec A3:** the deployment moved to a dedicated,
   confirmation-gated `infra-postgres.yml`.

### Task 4 — the probe *(2026-07-30)*

Run from the VM through the app's own container and client library, with the
explicit `-f docker-compose.yaml -f docker-compose.prod.yaml` pair. **Every
assumption the plan's risk table flagged came back good.**

| | Observed | Was assumed because |
|---|---|---|
| `server_version` | `16.14` | major pinned to 16 to match `pgvector/pgvector:pg16` |
| `ssl` | `True`, `TLSv1.3`, `TLS_AES_256_GCM_SHA384` | **asyncpg does honour `sslmode=require` given in the DSN** — never previously exercised here, and the acceptance criterion for encryption in transit |
| `pgvector` | `0.8.2`, created from `CREATE EXTENSION IF NOT EXISTS vector` | the `azure.extensions` allow-list actually admits `VECTOR`; this is the step with no counterpart in the container image |
| `<=>` on `vector(384)` | `0.0` for two parallel 384-dim vectors, `1.0` for orthogonal 3-dim | the operator and the exact column width `resources.embedding` declares both work, not just 3-dim toys |
| connect | 137 ms cold (TLS handshake included) | — |
| warm round-trip | median **0.67 ms** (min 0.65, max 1.43) over 10 `SELECT 1` on an open connection | NFR-CC-2 budgets <100 ms for retrieval, so the network is ~1% of it. Co-location in New Zealand North is what buys this |

**The probe was proved to have hit the managed instance, not the local
container** — worth doing explicitly, because a DSN that silently fell back
would have produced a confident-looking pass:

| | host | user | ssl | public tables |
|---|---|---|---|---|
| managed | `10.60.0.4` | `scoutadmin` | `True` | **0** — fresh, and the extension adds no tables |
| VM container | `172.18.0.3` | `scout` | `False` | **6** — untouched, still the system of record |

**The firewall was tested by refusal, not just by reading the rule list.** A TCP
connect from the laptop, which is not allow-listed, timed out after 15 s, while
the VM connects in 137 ms. Note the CLI flag in the step above was wrong as
written: `firewall-rule list` rejects `-s` with `unrecognized arguments` and
needs `--server-name`.

Two incidental findings, neither caused by this phase but both bearing on it:

1. **`docker-compose.override.yaml` *is* present on the VM**, contradicting
   Phase 1's note that "the VM never sees the file". `deploy.yml` rsyncs with
   `--exclude '.git' --exclude 'scout/.env' --exclude 'reports'` and nothing
   else, so the override ships. Production is still safe *today* for the reason
   Phase 1 gave — every production invocation passes the `-f` pair, so the
   override is never auto-loaded — but the safety now rests entirely on that,
   with a live in-network `DATABASE_URL` pin sitting on the VM's disk. After
   cutover, any bare `docker compose run/up` on the VM, the natural thing to
   type when debugging by hand, would silently talk to the old container
   database instead of the system of record. **Resolved — spec A4:** the rsync
   now excludes the file *and* removes it explicitly, since `--delete` leaves
   excluded files on the receiver alone, and both halves are pinned by tests.
2. The probe needed the VM booted (`az vm start`), since the VM is the only
   allow-listed address. That makes every future manual interaction with the
   managed instance cost a VM boot — a wrinkle for P7, whose Function will need
   its own firewall entry rather than borrowing the VM's.
