"""The managed Postgres template must keep the shape P6 signed off on.

Four things about `infra/postgres.bicep` are load-bearing and none would fail
loudly if they drifted:

- **The admin password must never be committed** (NFR-CC-7).
- **The compute SKU must stay `Standard_B1ms`.** This was originally about
  preserving free-tier eligibility; that turned out not to exist on this
  subscription (spec A1), so the reason is now plainly cost — `Standard_B2s`
  is $0.10920/hr against B1ms's $0.02730/hr, four times the bill, and nothing
  else in the repo would notice the change.
- **pgvector must stay on the server's extension allow-list.** `CREATE
  EXTENSION vector` fails without it, and `scout/shared/schema.sql` runs that
  on every startup — so the failure lands at the point that looks like it
  should work, with no counterpart in the `pgvector/pgvector:pg16` container
  this data comes from.
- **Access must stay scoped to one address.** A widened firewall rule exposes
  the system of record and looks like nothing in a diff.

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


def test_instance_keeps_the_cheapest_shape():
    """B2s is 4x the hourly rate of B1ms; HA and geo-redundancy add more."""
    assert "param skuName string = 'Standard_B1ms'" in _BICEP
    assert "param storageSizeGB int = 32" in _BICEP
    assert "tier: 'Burstable'" in _BICEP
    assert "geoRedundantBackup: 'Disabled'" in _BICEP
    assert "highAvailability: {" in _BICEP
    assert "mode: 'Disabled'" in _BICEP


def test_major_version_matches_the_container_being_migrated_from():
    """pgvector/pgvector:pg16 is the source, so this is a same-major move —
    and CI runs pg16 too, so a different major in production would mean the
    suite stops being a faithful check."""
    assert "param postgresVersion string = '16'" in _BICEP


def test_pgvector_is_on_the_extension_allow_list():
    assert "'azure.extensions'" in _BICEP
    assert "VECTOR" in _BICEP


def test_access_is_restricted_to_a_single_allow_listed_address():
    assert "flexibleServers/firewallRules" in _BICEP
    assert "param allowedClientIp string" in _BICEP
    assert "startIpAddress: allowedClientIp" in _BICEP
    assert "endIpAddress: allowedClientIp" in _BICEP


def test_no_allow_all_azure_services_rule():
    """0.0.0.0 is Azure's "allow all Azure services" wildcard — it reads like a
    narrow rule and is not one."""
    assert "0.0.0.0" not in _BICEP


def _workflow(name: str) -> dict:
    return yaml.safe_load(
        (_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    )


def _job_scripts(workflow: dict, job_id: str) -> str:
    return "\n".join(step.get("run", "") for step in workflow["jobs"][job_id]["steps"])


def test_postgres_has_its_own_dispatch_only_workflow():
    workflow = _workflow("infra-postgres.yml")
    assert "infra/postgres.bicep" in _job_scripts(workflow, "provision")
    # `on: workflow_dispatch` parses to {True: {"workflow_dispatch": ...}} because
    # YAML 1.1 reads a bare `on` as the boolean true.
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_dispatch"}, (
        "provisioning a billable server must never be triggered by a push, "
        "a schedule, or another workflow"
    )


def test_provisioning_requires_confirming_the_standing_cost():
    """A dispatch that has not typed the confirmation must fail before the Azure
    login, so an accidental run costs nothing and changes nothing."""
    workflow = _workflow("infra-postgres.yml")
    steps = workflow["jobs"]["provision"]["steps"]
    guard, rest = steps[0], steps[1:]

    assert "inputs.confirm_cost" in guard.get("if", "")
    assert "exit 1" in guard.get("run", "")
    assert not any(
        "azure/login" in str(step.get("uses", "")) for step in [guard]
    ), "the guard must come before the login, not after it"
    assert any("azure/login" in str(step.get("uses", "")) for step in rest)


def test_shared_infra_workflow_cannot_recreate_the_server():
    """infra-provision.yml deploys the VM and the dashboard and is dispatched for
    routine changes to either. A postgres step there means a dashboard tweak
    re-creates a billable server -- including after Phase 3 deletes it, when
    nothing in the repo points at the charge. See spec Amendment A3."""
    scripts = _job_scripts(_workflow("infra-provision.yml"), "provision")
    assert "infra/postgres.bicep" not in scripts
