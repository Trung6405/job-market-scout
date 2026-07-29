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
