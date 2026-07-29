from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import asyncpg
import pytest
import pytest_asyncio
import requests

from scout.config import Settings
from scout.shared.db import apply_schema
from scout.shared.schemas import Listing, MatchResult

# Tests must never run against the dev/prod database (Settings().database_url) —
# a TRUNCATE here would wipe real run history. Use a dedicated database on the
# same Postgres server instead.
_TEST_DB_NAME = "scout_test"


def _test_database_url(dev_database_url: str) -> str:
    base = dev_database_url.rsplit("/", 1)[0]
    return f"{base}/{_TEST_DB_NAME}"


# Local Postgres hosts: the host-side published port, loopback, and the
# compose service name reachable from inside the app container.
_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres"}


def _is_local_dsn(dsn: str) -> bool:
    """True when `dsn` points at Postgres on this machine or the compose network.

    Since P6 the DATABASE_URL setting can name the managed instance, which is
    the system of record — and the fixture below CREATEs a database and
    TRUNCATEs tables on whatever it is handed. An allow-list rather than a
    deny-list of cloud hostnames: a host nobody thought about should be
    refused, not permitted.
    """
    return urlparse(dsn).hostname in _LOCAL_DB_HOSTS


async def _ensure_test_database(dev_database_url: str) -> None:
    conn = await asyncpg.connect(dsn=dev_database_url, timeout=2)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", _TEST_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch):
    """Turn an unstubbed HTTP call into a loud failure instead of a live request.

    The coach's HTTP callers (`link_health`, `github_search`) hold a
    module-level `requests.Session` and are stubbed per-test by patching
    `_session.head` / `_session.get`. When such a patch fails to apply, the
    call doesn't error — it silently reaches the real internet and the test
    then asserts on whatever the live host returned. That failure mode is
    actively misleading: `https://example.com/repo` answers 404, so
    `check_url` reports a perfectly plausible `gone` verdict and the test
    reads as a broken classifier rather than a missed stub.

    Patching `Session.request` (which every `head`/`get`/`post` helper funnels
    through) leaves the per-test instance-attribute stubs working untouched,
    while anything they miss names itself.
    """

    def _unstubbed_request(self, method, url, *args, **kwargs):
        raise AssertionError(
            f"unstubbed real network call: {method} {url} — stub the caller's "
            "session instead of letting the test reach the internet"
        )

    monkeypatch.setattr(requests.Session, "request", _unstubbed_request)


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
        pool = await asyncpg.create_pool(
            dsn=_test_database_url(dev_database_url), timeout=2
        )
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres unreachable: {exc}")
    await apply_schema(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE TABLE run_listings, runs, listings, resources CASCADE"
        )
    yield pool
    await pool.close()


@pytest.fixture
def listing_factory():
    def _make(**overrides) -> Listing:
        defaults = dict(
            source="indeed",
            external_id="ext-1",
            title="Backend Engineer",
            company="Acme Corp",
            location="Melbourne VIC",
            is_remote=False,
            url="https://example.com/job/1",
            description="We need Python and PostgreSQL.",
            salary_min=None,
            salary_max=None,
            date_posted=None,
            scraped_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
        )
        return Listing(**{**defaults, **overrides})

    return _make


@pytest.fixture
def match_factory(listing_factory):
    def _make(
        listing: Listing | None = None, score: int = 70, reasoning: str = "ok"
    ) -> MatchResult:
        return MatchResult(
            listing=listing if listing is not None else listing_factory(),
            score=score,
            reasoning=reasoning,
        )

    return _make
