# Phase 2: Provision the Instance

> **Parent plan:** [plan.md](plan.md)
> **Status:** In progress
> **Depends on:** Phase 1 complete (the secret is the seam, and it is proven)

---

## Goal

Stand up a Neon Postgres project from a committed provisioning script — pinned
to major 16, in the region closest to the VM — and prove the pipeline's own
client can reach it over TLS and run a vector query. Done when a probe from the
VM using asyncpg creates the pgvector extension and returns a cosine distance,
while the pipeline is still writing to the old database.

> **Rewritten 2026-07-29.** This phase originally provisioned an Azure Database
> for PostgreSQL Flexible Server from a Bicep template. The cost gate rejected
> it — see spec Amendments A1–A6. The provider, the provisioning mechanism, the
> access-control posture and the sizing constraints all changed; the shape of
> the phase (validate a fresh instance while the old one keeps serving) did not.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — a Neon API key and a generated database password, both stored as
  repository secrets and never committed. The provisioning script prints a
  connection string only when explicitly asked to, so it cannot land in a CI
  log by default.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No longer. Creating a Neon project on the Free plan starts no billing and
  fixes no irreversible setting, so Task 3's gate is about adding a second
  credential domain rather than about cost. Deleting the project undoes it.

---

## Tasks

### Task 1: Measure the database, and confirm a region

- **Files:** none — findings recorded in this doc's Notes.
- **Gate:** ⚠️ human sign-off required before proceeding past this task. The
  Free plan's ceiling is **0.5 GB per project** (spec A5), against 32 GiB on
  the rejected Azure shape. If the current database is already close to that,
  or growing fast enough to reach it soon, this plan does not work as written
  and the decision returns to the human.
- **Steps:**
  - [x] Start the VM and measure. The whole database, the per-table breakdown,
    and the growth rate all matter — a comfortable total with a `listings`
    table growing megabytes a day is not comfortable:

    ```bash
    RG=$(gh variable get RESOURCE_GROUP --repo Trung6405/job-market-scout)
    VM_HOST=$(gh variable get VM_HOST --repo Trung6405/job-market-scout)
    az vm start -g "$RG" -n scout-vm
    ssh -i ~/.ssh/scout_vm azureuser@"$VM_HOST" \
      "cd /opt/job-market-scout && docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
        exec -T postgres psql -U scout -d scout -c \
        \"SELECT pg_size_pretty(pg_database_size('scout')) AS total\" -c \
        \"SELECT relname, pg_size_pretty(pg_total_relation_size(c.oid)) AS size, n_live_tup AS rows
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY pg_total_relation_size(c.oid) DESC\""
    ```

  - [x] Estimate growth from the run history — bytes per run is the number that
    decides how long 0.5 GB lasts:

    ```bash
    ssh -i ~/.ssh/scout_vm azureuser@"$VM_HOST" \
      "cd /opt/job-market-scout && docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
        exec -T postgres psql -U scout -d scout -c \
        \"SELECT count(*) AS runs, min(run_date) AS first, max(run_date) AS last FROM runs\" -c \
        \"SELECT count(*) AS listings, pg_size_pretty(avg(length(description))::bigint) AS avg_description FROM listings\""
    ```

  - [x] Deallocate again immediately — the VM is not meant to be up:

    ```bash
    az vm deallocate -g "$RG" -n scout-vm
    ```

  - [x] Confirm Neon serves a region near `newzealandnorth`, from
    <https://neon.com/docs/introduction/regions> — no API key needed, so
    this runs before Task 3. It sets the per-query latency spec A6 flags.

  - [x] Record in Notes: total size, per-table sizes, row counts, run count and
    date span, implied growth per run, headroom against 0.5 GB, and the region.
  - [x] **STOP.** Do not proceed until the human has accepted the headroom.
  - [x] No commit.

### Task 2: The provisioning script

- **Files:**
  - Create: `infra/provision_neon.py`
  - Create: `tests/test_provision_neon.py`
  - No `infra/__init__.py` — `scripts/` already imports as a namespace package
    (`from scripts.audit_link_health import …`), so `infra/` does too.
  - Modify: `.github/workflows/infra-provision.yml`
  - Modify: `infra/README.md`
- **Gate:** none — committing the script provisions nothing.
- **Steps:**

  - [x] **Step 1: Write the failing test**

    Create `tests/test_provision_neon.py`. The API round-trip is not worth
    faking; what is worth testing is the idempotency decision and the
    connection-string construction, because the first decides whether a second
    run creates a duplicate project and the second decides whether TLS is
    actually requested:

    ```python
    """The parts of Neon provisioning that can silently do the wrong thing.

    Two failures matter here and neither is loud: re-running the script could
    create a second project rather than reusing the first (the script is meant
    to be idempotent, and `infra-provision.yml` is dispatched by hand more than
    once), and the connection string could omit TLS — which on Neon would fail
    closed, but on any future provider might quietly not.
    """

    from __future__ import annotations

    import pytest

    from infra.provision_neon import (
        build_connection_uri,
        find_project,
        redact,
    )


    def test_find_project_matches_by_name():
        projects = [
            {"id": "aa-1", "name": "other"},
            {"id": "bb-2", "name": "job-market-scout"},
        ]
        assert find_project(projects, "job-market-scout")["id"] == "bb-2"


    def test_find_project_returns_none_when_absent():
        assert find_project([{"id": "aa-1", "name": "other"}], "job-market-scout") is None


    def test_find_project_is_exact_not_substring():
        """"job-market-scout-old" must not be mistaken for the real project."""
        projects = [{"id": "aa-1", "name": "job-market-scout-old"}]
        assert find_project(projects, "job-market-scout") is None


    def test_connection_uri_requires_tls():
        uri = build_connection_uri(
            host="ep-x.ap-southeast-2.aws.neon.tech",
            role="scout",
            password="pw",
            database="scout",
        )
        assert uri.endswith("?sslmode=require")


    def test_connection_uri_percent_encodes_the_password():
        """A generated password containing @ or / would otherwise truncate the
        host or the database name."""
        uri = build_connection_uri(
            host="h", role="scout", password="p@ss/word", database="scout"
        )
        assert "p%40ss%2Fword" in uri
        assert "@h/scout" in uri


    def test_redact_hides_the_password():
        uri = "postgresql://scout:supersecret@h/scout?sslmode=require"
        assert "supersecret" not in redact(uri)
        assert "scout:***@h" in redact(uri)
    ```

  - [x] **Step 2: Run the test to verify it fails**

    Run: `pytest tests/test_provision_neon.py -v`
    Expected: FAIL at collection — `ModuleNotFoundError: No module named
    'infra.provision_neon'`

  - [x] **Step 3: Write the script**

    Create `infra/provision_neon.py`:

    ```python
    """Idempotently ensure the Neon project backing the pipeline exists.

    Infrastructure-as-code for a provider Bicep cannot express (spec A3). Run
    it twice and the second run changes nothing — `infra-provision.yml`
    dispatches it by hand, and a script that created a second project on the
    second dispatch would be worse than no script.

    It prints a connection string ONLY with --print-connection-string, which is
    for an operator running it locally. Without that flag it reports host,
    database and role and nothing secret, so it is safe in a CI log.
    """

    from __future__ import annotations

    import argparse
    import json
    import os
    import sys
    import urllib.error
    import urllib.parse
    import urllib.request

    _API = "https://console.neon.tech/api/v2"


    def find_project(projects: list[dict], name: str) -> dict | None:
        """Exact-name match. Substring matching would let "…-old" win."""
        for project in projects:
            if project.get("name") == name:
                return project
        return None


    def build_connection_uri(
        *, host: str, role: str, password: str, database: str
    ) -> str:
        """Assemble a DSN with TLS requested explicitly.

        Neon refuses non-TLS connections regardless, so `sslmode=require` is
        belt-and-braces there — but it is also what makes the DSN's intent
        readable, and what would carry the guarantee to any other provider.
        """
        quoted = urllib.parse.quote(password, safe="")
        return f"postgresql://{role}:{quoted}@{host}/{database}?sslmode=require"


    def redact(uri: str) -> str:
        """Mask the password so a DSN can be echoed in a status line."""
        scheme, _, rest = uri.partition("://")
        creds, _, tail = rest.partition("@")
        role, _, _password = creds.partition(":")
        return f"{scheme}://{role}:***@{tail}"


    def _request(method: str, path: str, token: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{_API}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # The body carries Neon's actual reason; without it every failure
            # reads as a bare status code.
            raise SystemExit(
                f"Neon API {method} {path} failed: {error.code} {error.read().decode()[:400]}"
            ) from error


    def main() -> int:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--project-name", default="job-market-scout")
        parser.add_argument("--region", default="aws-ap-southeast-2")
        parser.add_argument("--pg-version", type=int, default=16)
        parser.add_argument("--database", default="scout")
        parser.add_argument("--role", default="scout")
        parser.add_argument(
            "--print-connection-string",
            action="store_true",
            help="print the DSN including the password; for local use only",
        )
        args = parser.parse_args()

        token = os.environ.get("NEON_API_KEY")
        if not token:
            raise SystemExit("NEON_API_KEY is not set")

        existing = find_project(
            _request("GET", "/projects", token).get("projects", []), args.project_name
        )
        if existing is not None:
            print(f"project {args.project_name} already exists (id {existing['id']})")
            project_id = existing["id"]
            created = None
        else:
            created = _request(
                "POST",
                "/projects",
                token,
                {
                    "project": {
                        "name": args.project_name,
                        "region_id": args.region,
                        "pg_version": args.pg_version,
                    }
                },
            )
            project_id = created["project"]["id"]
            print(f"created project {args.project_name} (id {project_id})")

        endpoints = _request("GET", f"/projects/{project_id}/endpoints", token)
        host = endpoints["endpoints"][0]["host"]
        print(f"host     : {host}")
        print(f"database : {args.database}")
        print(f"role     : {args.role}")

        if args.print_connection_string:
            if created is None:
                print(
                    "\nThe password is shown only when the project is first created.\n"
                    "Retrieve or reset it in the Neon console: "
                    f"https://console.neon.tech/app/projects/{project_id}",
                    file=sys.stderr,
                )
                return 0
            role_password = created["roles"][0]["password"]
            print(
                "\n"
                + build_connection_uri(
                    host=host,
                    role=created["roles"][0]["name"],
                    password=role_password,
                    database=created["databases"][0]["name"],
                )
            )
        return 0


    if __name__ == "__main__":
        sys.exit(main())
    ```

    In `.github/workflows/infra-provision.yml`, add a step after the dashboard
    one. Note it deliberately omits `--print-connection-string`:

    ```yaml
          - name: Ensure Neon project (provision_neon.py)
            env:
              NEON_API_KEY: ${{ secrets.NEON_API_KEY }}
            run: |
              set -euo pipefail
              # No --print-connection-string: this must not put a DSN in the log.
              python infra/provision_neon.py
    ```

  - [x] **Step 4: Run the test to verify it passes**

    Run: `pytest tests/test_provision_neon.py -v`
    Expected: PASS (6 tests)

  - [x] **Step 5: Commit**

    ```bash
    git add infra/provision_neon.py infra/__init__.py tests/test_provision_neon.py \
      .github/workflows/infra-provision.yml infra/README.md
    git commit -m "feat(infra): provision the Neon project from a committed script

Bicep cannot express a non-Azure provider, so the IaC requirement is met by an
idempotent API script instead (spec A3). Terraform's Neon provider would give
drift detection at the cost of a toolchain the repo doesn't have and a remote
state backend to secure first - infrastructure work to enable infrastructure
work, for one project holding one database.

Idempotent because infra-provision.yml is dispatched by hand: a script that
created a second project on the second dispatch would be worse than none. The
connection string is printed only behind an explicit flag, so the CI step
cannot leak a DSN into a log."
    ```

### Task 3: Create the project

- **Files:** none.
- **Gate:** ⚠️ human sign-off required before this task. Not for cost — the Free
  plan bills nothing — but because it puts the system of record outside the
  Azure subscription and adds a second credential domain, which is the
  coherence objection the spec recorded and A1 accepted.
- **Steps:**
  - [ ] Create a Neon account and an API key at
    <https://console.neon.tech> → Account settings → API keys.
  - [ ] Store it:

    ```bash
    gh secret set NEON_API_KEY --repo Trung6405/job-market-scout
    ```

  - [ ] Run the script locally so the generated password reaches your terminal
    and not a CI log:

    ```bash
    export NEON_API_KEY=...   # paste, or read from your password manager
    python infra/provision_neon.py --region <region from Task 1> \
      --print-connection-string
    ```

  - [ ] Store the DSN it prints as the eventual cutover value — **not** in
    `DATABASE_URL` yet, which still points at the VM's database and must keep
    doing so until phase 4:

    ```bash
    gh secret set NEON_DATABASE_URL --repo Trung6405/job-market-scout
    ```

    Keeping the new DSN in a separate secret is what makes phase 4's cutover a
    single deliberate copy rather than an edit under time pressure, and what
    makes its rollback a copy back.

  - [ ] Confirm idempotency — run it again and check it reuses:

    ```bash
    python infra/provision_neon.py
    ```

    Expected: `project job-market-scout already exists (id …)`.

  - [ ] Record the project id, host and region in Notes.
  - [ ] No commit.

### Task 4: Prove the pipeline's own client can reach it

- **Files:** none — a one-off probe run from the VM.
- **Gate:** none — read-only against the new, empty project.
- **Steps:**
  - [ ] From the VM, using the app's own client and DSN. This settles asyncpg
    against Neon specifically — Neon routes by SNI, which older clients get
    wrong — and confirms pgvector needs no allow-list step here (spec A4):

    ```bash
    az vm start -g "$RG" -n scout-vm
    ssh -i ~/.ssh/scout_vm azureuser@"$VM_HOST"
    cd /opt/job-market-scout
    read -rs -p 'Neon DSN: ' TARGET_DSN && export TARGET_DSN
    docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
      run --rm -e TARGET_DSN app python -c "
    import asyncio, os, time, asyncpg

    async def main():
        start = time.monotonic()
        conn = await asyncpg.connect(dsn=os.environ['TARGET_DSN'])
        print(f'connect+wake: {time.monotonic()-start:.2f}s')
        print('server:', await conn.fetchval('SHOW server_version'))
        print('tls:', await conn.fetchval(
            'SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()'))
        await conn.execute('CREATE EXTENSION IF NOT EXISTS vector')
        print('pgvector:', await conn.fetchval(
            \"SELECT extversion FROM pg_extension WHERE extname = 'vector'\"))
        print('cosine:', await conn.fetchval(
            \"SELECT '[1,0,0]'::vector <=> '[0,1,0]'::vector\"))
        warm = time.monotonic()
        for _ in range(20):
            await conn.fetchval('SELECT 1')
        print(f'warm round-trip: {(time.monotonic()-warm)/20*1000:.1f}ms')
        await conn.close()

    asyncio.run(main())
    "
    az vm deallocate -g "$RG" -n scout-vm
    ```

    Expected: server version `16.x`, `tls: True`, a pgvector version, cosine
    `1.0`. Record `connect+wake` and `warm round-trip` — these are the numbers
    spec A6 says to measure rather than assume, and the warm figure is what
    NFR-CC-2's sub-100 ms budget actually has to accommodate.

  - [ ] If the warm round-trip is a large fraction of 100 ms, stop and raise it
    — the retriever issues a query per gap skill per run, so a per-query
    penalty multiplies.
  - [ ] Record all timings in Notes.
  - [ ] No commit.

---

## Verification

- [ ] Provisioning guards pass: `pytest tests/test_provision_neon.py -v`
- [ ] Full suite still passes: `pytest -q`
- [ ] Running the script twice reports "already exists" the second time
- [ ] The probe reports TLS on, pgvector created, and a cosine distance
- [ ] Measured warm round-trip recorded against NFR-CC-2's budget

## Rollback

The project is empty and nothing points at it:

```bash
# project id from Task 3's Notes
curl -s -X DELETE -H "Authorization: Bearer $NEON_API_KEY" \
  https://console.neon.tech/api/v2/projects/<project-id>
gh secret delete NEON_API_KEY --repo Trung6405/job-market-scout
gh secret delete NEON_DATABASE_URL --repo Trung6405/job-market-scout
```

Then revert the Task 2 commit. The pipeline is unaffected throughout this
phase — it is still writing to the VM's container, and `DATABASE_URL` still
names it.

---

## Notes / Learnings

- **Task 1 (cost, original phase):** the Azure shape priced at **$24.57
  USD/month** — `Standard_B1ms` compute $0.02730/hr × 730 h = $19.93, plus 32
  GiB storage at $0.14490/GB = $4.64, backup included. Region and SKU were
  fine: `newzealandnorth` serves `Standard_B1ms`, version 16, 32 GiB floor.
  The subscription is **Azure for Students** — a $100 credit, not the free
  account the 12-month B1ms allowance attaches to, giving roughly four months
  of runway shared with the VM. Human decision: take the spec's recorded
  fallback. See spec Amendments A1–A6.
- Neon Free is **0.5 GB storage / 100 CU-hours per month**, and **IP Allow is
  Scale-only** — no network restriction is possible on this plan, which is the
  one capability the rejected Azure design had and this one does not.

### Task 1 measurements *(2026-07-29)*

Total database: **12 MB** — 2.3% of the 512 MB ceiling.

| Table | Size | Rows |
|-------|------|------|
| `listings` | 3,544 kB | 880 (avg description 4,667 bytes) |
| `run_listings` | 384 kB | |
| `listing_gaps` | 312 kB | |
| `resources` | 48 kB | **0** (0 with embeddings) |
| `runs` | 40 kB | 8 (2026-07-22 → 2026-07-29) |
| `listing_tips` | 24 kB | |

Growth is ~1.5 MB/day over 8 days of history, so 0.5 GB is roughly **11 months**
of runway — a ceiling with a date on it, not headroom to ignore. `listings`
never deletes: a closed listing keeps its description forever, so the largest
table only grows. If this needs extending later, dropping descriptions from
long-closed listings is the obvious lever, and it is out of scope here.

Region: **`aws-ap-southeast-2`** (Sydney), the nearest Neon offers to the VM's
`newzealandnorth`. Neon's own Azure regions are deprecated to new projects, so
co-locating inside Azure was not available even in principle.

**`resources` is empty** — see spec Amendment A7. Human decision: carry on with
P6 regardless, since reachability is what this phase delivers and the
aggregator will populate whichever database is current.

*(remaining findings filled in during execution)*
