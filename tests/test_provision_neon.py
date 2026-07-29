"""The parts of Neon provisioning that can silently do the wrong thing.

Two failures matter here and neither is loud: re-running the script could
create a second project rather than reusing the first (the script is meant
to be idempotent, and `infra-provision.yml` is dispatched by hand more than
once), and the connection string could omit TLS — which on Neon would fail
closed, but on any future provider might quietly not.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from infra.provision_neon import (
    build_connection_uri,
    check_project_shape,
    find_project,
    redact,
)

_ROOT = Path(__file__).resolve().parent.parent


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


def test_matching_project_shape_reports_nothing():
    project = {"region_id": "aws-ap-southeast-2", "pg_version": 16}
    assert check_project_shape(
        project, expected_region="aws-ap-southeast-2", expected_pg_version=16
    ) == []


def test_wrong_region_is_reported():
    """Region is fixed at creation, so catching it late means migrating twice."""
    project = {"region_id": "aws-us-east-2", "pg_version": 16}
    problems = check_project_shape(
        project, expected_region="aws-ap-southeast-2", expected_pg_version=16
    )
    assert len(problems) == 1
    assert "aws-us-east-2" in problems[0]


def test_wrong_major_version_is_reported():
    """The source is pgvector/pgvector:pg16 and CI runs pg16; a different major
    in production means the suite stops being a faithful regression net."""
    project = {"region_id": "aws-ap-southeast-2", "pg_version": 18}
    problems = check_project_shape(
        project, expected_region="aws-ap-southeast-2", expected_pg_version=16
    )
    assert len(problems) == 1
    assert "18" in problems[0]


def test_both_wrong_are_both_reported():
    project = {"region_id": "aws-us-east-2", "pg_version": 18}
    assert (
        len(
            check_project_shape(
                project, expected_region="aws-ap-southeast-2", expected_pg_version=16
            )
        )
        == 2
    )


def test_ci_step_does_not_print_the_connection_string():
    """`--print-connection-string` emits the role password on stdout.

    Actions logs are readable, and a DSN printed there is a leaked database.
    The flag is mentioned in the step's comment explaining why it is absent, so
    this has to check the executable lines rather than the whole script — a
    naive substring test over `run` passes the comment and fails the file.
    """
    workflow = yaml.safe_load(
        (_ROOT / ".github" / "workflows" / "infra-provision.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["provision"]["steps"]
    neon_steps = [s for s in steps if "provision_neon.py" in s.get("run", "")]
    assert neon_steps, "the provisioning workflow no longer runs provision_neon.py"
    for step in neon_steps:
        executable = [
            line
            for line in step["run"].splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert not any("--print-connection-string" in line for line in executable)
