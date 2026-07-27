"""Every workflow job that drives scout-vm must hold the same VM lock.

Deploy and Scheduled run share one Azure VM: each `az vm start`s it, works
over SSH, then `az vm deallocate`s it. Without a shared concurrency group the
two can overlap, and whichever finishes first deallocates the VM out from
under the other — the platform sends a Hyper-V shutdown request, systemd
SIGTERMs sshd, and the surviving run's SSH dies with "Connection closed by
remote host" (exit 255) wherever it happened to be. That took out the
2026-07-27 and 2026-07-23 scheduled runs.

The lock is just a matching string in two files, so it is silently breakable:
rename one side and both workflows keep passing YAML validation while running
concurrently again. These tests discover VM-touching jobs by what their steps
actually do, so a new workflow that starts the VM is caught too.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"

_VM_LOCK_GROUP = "scout-vm"


def _vm_jobs() -> dict[str, dict]:
    """Map "<workflow file>:<job id>" -> job, for jobs that drive the VM."""
    found = {}
    for path in sorted(_WORKFLOWS_DIR.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in (workflow.get("jobs") or {}).items():
            run_script = "\n".join(
                step.get("run", "") for step in (job.get("steps") or [])
            )
            if "az vm start" in run_script or "az vm deallocate" in run_script:
                found[f"{path.name}:{job_id}"] = job
    return found


def test_the_vm_touching_jobs_are_discovered():
    """Guards the tests below from silently passing on an empty set."""
    assert set(_vm_jobs()) == {
        "deploy.yml:deploy",
        "scheduled-run.yml:run-job",
    }


@pytest.mark.parametrize("job_key", sorted(_vm_jobs()))
def test_vm_job_holds_the_shared_lock(job_key):
    concurrency = _vm_jobs()[job_key].get("concurrency")
    assert concurrency is not None, f"{job_key} can deallocate the VM unserialized"
    # A literal, identical string in both files — not `${{ github.workflow }}`
    # or anything else per-workflow, which would give each its own lock and
    # serialize nothing.
    assert concurrency["group"] == _VM_LOCK_GROUP


@pytest.mark.parametrize("job_key", sorted(_vm_jobs()))
def test_vm_job_queues_rather_than_cancels(job_key):
    """Cancelling skips the `if: always()` Deallocate VM step, leaving the VM
    running and billing — worse than the collision being fixed here."""
    assert _vm_jobs()[job_key]["concurrency"]["cancel-in-progress"] is False
