# Phase 1: Configuration Seam

> **Parent plan:** [plan.md](plan.md)
> **Status:** In progress
> **Depends on:** nothing

---

## Goal

Make the `DATABASE_URL` Actions secret the thing that actually decides where
the pipeline connects, and prove it while the answer is still the VM's own
database. Done when a full cycle runs on the VM with `DATABASE_URL` arriving
from `scout/.env`, with nothing pinned in a compose file, and a test that fails
if the pin ever comes back.

## Safety Checklist

- **Touches user input, auth, secrets, or external calls?**
  Yes — Task 1 writes the `DATABASE_URL` repository secret, and Task 4 deploys
  to production. The value written in Task 1 is the same DSN the compose file
  already pins, so the deployed behaviour is unchanged by design.
- **Contains a one-way door (schema, public API shape, new dependency)?**
  No. Every step here is revertible by restoring the removed line.

---

## Tasks

### Task 1: Point the deploy secret at the VM's own database

- **Files:** none — this is a GitHub repository secret.
- **Gate:** ⚠️ human sign-off required before this task — it writes a
  production deploy secret. Note that GitHub never reads a secret value back,
  so the current value cannot be recorded first; it is unused today (the
  compose file shadows it), so overwriting it changes nothing that runs.
- **Steps:**
  - [x] Confirm the secret exists and note its current `Updated` timestamp:

    ```bash
    gh secret list --repo Trung6405/job-market-scout | grep DATABASE_URL
    ```

  - [x] Set it to the VM's in-network DSN — the exact value
    `docker-compose.yaml` pins today, so the deploy in Task 4 is a no-op in
    behaviour:

    ```bash
    gh secret set DATABASE_URL --repo Trung6405/job-market-scout \
      --body 'postgresql://scout:scout@postgres:5432/scout'
    ```

  - [x] Verify the `Updated` timestamp moved (`2026-07-22T04:39:42Z` →
    `2026-07-29T04:32:49Z`):

    ```bash
    gh secret list --repo Trung6405/job-market-scout | grep DATABASE_URL
    ```

  - [x] No commit — nothing in the repo changed (these ticks ride with Task 2's
    commit, since Task 1 produces none of its own).

### Task 2: Remove the pin, move the local value to an override file

- **Files:**
  - Create: `tests/test_compose_database_url.py`
  - Create: `docker-compose.override.yaml`
  - Modify: `docker-compose.yaml` (delete the `DATABASE_URL` line from the
    `app` service's `environment:` block)
  - Modify: `.dockerignore`
- **Gate:** none
- **Steps:**

  - [x] **Step 1: Write the failing test**

    Create `tests/test_compose_database_url.py`:

    ```python
    """`DATABASE_URL` must reach the app container from `scout/.env`.

    The deploy already renders that secret onto the VM, but the base compose
    file used to pin the same variable in the `app` service's `environment:`
    block — and an inline value beats `env_file:`, so the rendered secret had
    no effect at all. Removing that line is the whole repoint mechanism for the
    managed instance (P6), and its absence is invisible in normal operation:
    anything that adds an environment block back silently pins the pipeline to
    the VM's own container again, and every test here would still pass without
    the first two.

    The in-network value local development needs lives in
    `docker-compose.override.yaml`, which Compose auto-loads only when no `-f`
    flag is given — so the production invocation never sees it. That makes the
    `-f` pair load-bearing too, which the last test pins.
    """

    from __future__ import annotations

    from pathlib import Path

    import pytest
    import yaml

    _ROOT = Path(__file__).resolve().parent.parent
    _WORKFLOWS_DIR = _ROOT / ".github" / "workflows"

    _LOCAL_DATABASE_URL = "postgresql://scout:scout@postgres:5432/scout"
    _PROD_COMPOSE_FLAGS = "-f docker-compose.yaml -f docker-compose.prod.yaml"


    def _app_environment(compose_file: str) -> dict[str, str]:
        compose = yaml.safe_load((_ROOT / compose_file).read_text(encoding="utf-8"))
        app = (compose.get("services") or {}).get("app") or {}
        environment = app.get("environment") or {}
        if isinstance(environment, list):
            # Compose accepts both the mapping form and a "KEY=value" list.
            return dict(item.split("=", 1) for item in environment)
        return environment


    def test_base_compose_does_not_pin_database_url():
        assert "DATABASE_URL" not in _app_environment("docker-compose.yaml")


    def test_prod_overlay_does_not_pin_database_url():
        assert "DATABASE_URL" not in _app_environment("docker-compose.prod.yaml")


    def test_app_still_reads_the_rendered_env_file():
        compose = yaml.safe_load(
            (_ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
        )
        assert "scout/.env" in compose["services"]["app"]["env_file"]


    def test_local_override_supplies_the_in_network_url():
        environment = _app_environment("docker-compose.override.yaml")
        assert environment["DATABASE_URL"] == _LOCAL_DATABASE_URL


    def _compose_run_scripts() -> dict[str, str]:
        """Map "<workflow>:<job id>:<step name>" -> script, for steps driving
        the compose stack on the VM."""
        found = {}
        for path in sorted(_WORKFLOWS_DIR.glob("*.yml")):
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            for job_id, job in (workflow.get("jobs") or {}).items():
                for step in job.get("steps") or []:
                    script = step.get("run", "")
                    if "docker compose" in script:
                        key = f"{path.name}:{job_id}:{step.get('name', '?')}"
                        found[key] = script
        return found


    def test_the_compose_driving_steps_are_discovered():
        """Guards the test below from silently passing on an empty set."""
        assert set(_compose_run_scripts()) == {
            "deploy.yml:deploy:Bring up containers",
            "scheduled-run.yml:run-job:Run scout cycle",
            "scheduled-run.yml:run-job:Run coach aggregator (weekly)",
            "scheduled-run.yml:run-job:Run coach link-health check (daily)",
        }


    @pytest.mark.parametrize("step_key", sorted(_compose_run_scripts()))
    def test_prod_compose_invocation_excludes_the_local_override(step_key):
        """Dropping either -f makes Compose auto-load
        docker-compose.override.yaml, which would silently point production
        back at the VM's own container."""
        assert _PROD_COMPOSE_FLAGS in _compose_run_scripts()[step_key]
    ```

  - [x] **Step 2: Run the test to verify it fails**

    Run: `pytest tests/test_compose_database_url.py -v`
    Expected: FAIL — `test_base_compose_does_not_pin_database_url` asserts
    against the pinned value, and `test_local_override_supplies_the_in_network_url`
    errors with `FileNotFoundError` for `docker-compose.override.yaml`.

  - [x] **Step 3: Make the change**

    In `docker-compose.yaml`, delete the `DATABASE_URL` line so the `app`
    service's environment block keeps only the MCP URL:

    ```yaml
      app:
        build: .
        env_file:
          - scout/.env
        depends_on:
          jobspy-mcp:
            condition: service_healthy
          postgres:
            condition: service_healthy
        environment:
          JOBSPY_MCP_URL: http://jobspy-mcp:9423
        volumes:
          - ./reports:/app/reports
          - ./scout/profile.json:/app/scout/profile.json:ro
    ```

    Create `docker-compose.override.yaml`:

    ```yaml
    # Local-development overlay. Compose auto-loads this file only when no -f
    # flag is given, so `docker compose up` picks it up and the production
    # invocation (-f docker-compose.yaml -f docker-compose.prod.yaml) does not.
    #
    # It exists because DATABASE_URL can no longer be pinned in the base file:
    # on the VM that variable has to come from scout/.env, which the deploy
    # renders from the DATABASE_URL secret, and an inline environment value
    # would beat the env_file and shadow it (that shadow is exactly what P6
    # removed). Locally scout/.env holds the host-side DSN (localhost:5433) so
    # pytest can reach Postgres from outside Docker, which is not reachable
    # from inside the app container — hence this in-network value.
    services:
      app:
        environment:
          DATABASE_URL: postgresql://scout:scout@postgres:5432/scout
    ```

    In `.dockerignore`, add the override file next to the compose file that is
    already excluded:

    ```
    # Docker itself
    Dockerfile
    docker-compose.yaml
    docker-compose.override.yaml
    .dockerignore
    ```

  - [x] **Step 4: Run the test to verify it passes**

    Run: `pytest tests/test_compose_database_url.py -v`
    Expected: PASS (9 tests — 4 file assertions, the discovery guard, and 4
    parametrized invocation checks)

  - [x] **Step 5: Verify both merges resolve the way they have to**

    As originally written this step was `docker compose up -d postgres app`,
    which is wrong: the `app` service's default command is `python -m
    scout.main`, so bringing it up would have run a full pipeline — a live
    scrape and the LLM spend that goes with it — to read one variable.
    `config` renders the same merge without starting anything.

    ```bash
    cp scout/.env.example scout/.env   # gitignored; the worktree had none
    docker compose config | grep DATABASE_URL
    docker compose -f docker-compose.yaml -f docker-compose.prod.yaml config | grep DATABASE_URL
    ```

    Expected, and observed: `postgresql://scout:scout@postgres:5432/scout` for
    the local merge (the override applies) and
    `postgresql://scout:scout@localhost:5433/scout` for the production merge —
    the value from `scout/.env`, proving the production path now reads the
    rendered file and nothing else. On the VM that file is rendered from the
    `DATABASE_URL` secret, which is the whole point.

  - [x] **Step 6: Commit**

    ```bash
    git add docker-compose.yaml docker-compose.override.yaml .dockerignore \
      tests/test_compose_database_url.py
    git commit -m "refactor(compose): let DATABASE_URL come from the deploy secret, not a pin

The deploy has always rendered a DATABASE_URL secret into scout/.env on the
VM, and it has always been dead: docker-compose.yaml pinned the same variable
in the app service's environment block, which beats env_file. Uncovering that
seam is what lets P6 repoint the pipeline at a managed instance by changing
one secret instead of editing the compose file on a production host.

The in-network DSN local development needs moves to docker-compose.override.yaml,
which Compose loads only when no -f flag is given — so the production
invocation never picks it up. Tests pin both halves, including the -f pair,
because a reintroduced environment block would be silent in normal operation."
    ```

### Task 3: Refuse to run the test suite against a non-local database

- **Files:**
  - Create: `tests/test_local_db_guard.py`
  - Modify: `tests/conftest.py`
- **Gate:** none
- **Steps:**

  - [x] **Step 1: Write the failing test**

    Create `tests/test_local_db_guard.py`:

    ```python
    """The db fixtures CREATE and TRUNCATE, so they must never reach the
    managed instance.

    `tests/conftest.py` derives the test database from `Settings().database_url`
    by swapping the last path segment — so a developer whose `scout/.env` points
    at the managed instance (P6) would have `pytest` create a `scout_test`
    database on the system of record and truncate tables next to the real ones.
    The allow-list fails closed: an unrecognised host is refused, not permitted.
    """

    from __future__ import annotations

    from tests.conftest import _is_local_dsn


    def test_host_side_dsn_is_local():
        assert _is_local_dsn("postgresql://scout:scout@localhost:5433/scout")


    def test_loopback_address_is_local():
        assert _is_local_dsn("postgresql://scout:scout@127.0.0.1:5433/scout")


    def test_compose_network_dsn_is_local():
        assert _is_local_dsn("postgresql://scout:scout@postgres:5432/scout")


    def test_managed_instance_dsn_is_not_local():
        assert not _is_local_dsn(
            "postgresql://scoutadmin:pw@trung6405-scout-pg.postgres.database.azure.com"
            ":5432/scout?sslmode=require"
        )


    def test_an_unrecognised_host_fails_closed():
        assert not _is_local_dsn("postgresql://scout:scout@db.example.net:5432/scout")
    ```

  - [x] **Step 2: Run the test to verify it fails**

    Run: `pytest tests/test_local_db_guard.py -v`
    Expected: FAIL at collection with
    `ImportError: cannot import name '_is_local_dsn' from 'tests.conftest'`

  - [x] **Step 3: Write minimal implementation**

    In `tests/conftest.py`, add the import and the helper below
    `_test_database_url`:

    ```python
    from urllib.parse import urlparse

    # Local Postgres hosts: the host-side published port, loopback, and the
    # compose service name reachable from inside the app container.
    _LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres"}


    def _is_local_dsn(dsn: str) -> bool:
        """True when `dsn` points at Postgres on this machine or the compose network.

        An allow-list rather than a deny-list of cloud hostnames: a host nobody
        thought about should be refused, not permitted.
        """
        return urlparse(dsn).hostname in _LOCAL_DB_HOSTS
    ```

    and make the fixture refuse anything else, before it connects:

    ```python
    @pytest_asyncio.fixture
    async def db_pool():
        dev_database_url = Settings().database_url
        if not _is_local_dsn(dev_database_url):
            pytest.fail(
                "DATABASE_URL points at "
                f"{urlparse(dev_database_url).hostname!r}; these fixtures create and "
                "truncate tables, so they refuse to run anywhere but a local Postgres."
            )
        try:
            await _ensure_test_database(dev_database_url)
    ```

  - [x] **Step 4: Run the test to verify it passes**

    Run: `pytest tests/test_local_db_guard.py -v`
    Expected: PASS (5 tests)

  - [x] **Step 5: Verify the fixture itself still works**

    ```bash
    docker compose up -d postgres
    pytest tests/test_db.py tests/test_coach_db.py -q
    ```

    Expected: PASS — the fixture still reaches the local Postgres unchanged.

  - [x] **Step 6: Commit**

    ```bash
    git add tests/conftest.py tests/test_local_db_guard.py
    git commit -m "test: refuse to run the db fixtures against a non-local Postgres

The db_pool fixture derives its database from Settings().database_url and then
CREATEs and TRUNCATEs. Once DATABASE_URL can point at the managed instance
(P6), a developer with a production DSN in scout/.env would have a stray
pytest run writing to the system of record. Allow-list the local hosts and
fail loudly on anything else."
    ```

### Task 4: Deploy the seam and prove one full cycle still runs

- **Files:** none — this is a production verification.
- **Gate:** ⚠️ human sign-off required before this task — merging to `main`
  triggers `Deploy`, which rewrites `scout/.env` on the VM and rebuilds the
  stack. Nothing about *where* the data lives changes here; that is the point.
- **Steps:**
  - [ ] Run the full suite locally first:

    ```bash
    docker compose up -d postgres
    pytest -q
    ```

    Expected: PASS, no new failures.

  - [ ] Open the PR and merge it to `main` once CI is green:

    ```bash
    gh pr create --fill
    gh pr merge --squash
    ```

  - [ ] Watch the deploy finish:

    ```bash
    gh run watch "$(gh run list --workflow=Deploy --limit 1 --json databaseId --jq '.[0].databaseId')"
    ```

  - [ ] Trigger one full cycle and watch it:

    ```bash
    gh workflow run "Scheduled run"
    gh run watch "$(gh run list --workflow='Scheduled run' --limit 1 --json databaseId --jq '.[0].databaseId')"
    ```

  - [ ] Confirm the cycle wrote a run row — the DSN now arrives from the
    secret, so a connect failure here means the seam is broken, not the data:

    ```bash
    ssh azureuser@"$VM_HOST" \
      "cd /opt/job-market-scout && docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
        exec -T postgres psql -U scout -d scout -c \
        'SELECT run_date, listings_scored, finished_at FROM runs ORDER BY run_date DESC LIMIT 3'"
    ```

    Expected: today's run present with a non-NULL `finished_at`.

  - [ ] Load the dashboard's history page and confirm the new run appears.
  - [ ] No commit — nothing in the repo changed.

---

## Verification

- [ ] Full suite passes: `pytest -q`
- [ ] The pin is gone and cannot come back unnoticed:
      `pytest tests/test_compose_database_url.py -v`
- [ ] `docker compose up -d postgres app` still connects locally (Task 2 Step 5)
- [ ] A production cycle completed with `DATABASE_URL` sourced from the secret,
      and today's run row is present in the VM database

## Rollback

Revert the Task 2 commit — restoring the `DATABASE_URL` line in
`docker-compose.yaml` re-shadows the secret and returns the stack to exactly
its previous behaviour. The Task 3 commit is independent and can stay. The
`DATABASE_URL` secret can be left as set; while the pin exists it has no effect.

---

## Notes / Learnings

- **Task 1:** the `DATABASE_URL` secret was last written `2026-07-22T04:39:42Z`
  and is now `2026-07-29T04:32:49Z`. Its previous value is unrecoverable, as
  expected — it was shadowed by the compose pin, so nothing depended on it.
- **Task 2 Step 5 was wrong as planned** and was corrected in place. It said
  `docker compose up -d postgres app`, but `app`'s default command is
  `python -m scout.main`: bringing the service up would have run a live scrape
  and a full LLM cycle to read one environment variable. `docker compose config`
  renders the identical merge and starts nothing. Worth carrying forward — any
  later step that reaches for `up`/`exec` on `app` to inspect configuration
  wants `config` or `run --rm` with an explicit command instead.
- The worktree had no `scout/.env` (gitignored, and it is a fresh checkout), so
  Compose refused to resolve `env_file` at all. Seeded it from
  `scout/.env.example`. That file is what stands in for the deploy-rendered one
  locally, which is why the production merge below reads `localhost:5433`.
- The two merges resolve as required: local (no `-f`) →
  `postgresql://scout:scout@postgres:5432/scout` from the override; production
  (`-f docker-compose.yaml -f docker-compose.prod.yaml`) →
  `postgresql://scout:scout@localhost:5433/scout`, i.e. straight from
  `scout/.env` with the override correctly ignored.
- **Task 3:** the helper is unit-tested, but the fixture wiring was checked
  separately by running `tests/test_db.py` with `DATABASE_URL` set to a managed
  host — it fails with the intended message, and does so before any connection
  is attempted, so a wrong DSN cannot even open a socket to the system of
  record. Against a real local Postgres the DB suites still pass unchanged
  (74 tests across `test_db`, `test_coach_db`, `test_coach_retrieval_db`,
  `test_coach_tips_db`, `test_coach_link_health_db`).
- Full suite before Postgres was running: 465 passed, 114 skipped — the skips
  are exactly the DB-touching tests, which then passed once the container was
  up. Worth knowing that a green local run means much less than it looks like
  when Docker is down; CI always has a live Postgres, so it does not have this
  blind spot.
