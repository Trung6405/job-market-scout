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
`-f` pair load-bearing too, which the last tests pin.

The `-f` pair was carrying that weight alone, though. P6 Phase 2 found the
override sitting on the VM: the deploy's rsync excluded `.git`, `scout/.env`
and `reports`, and nothing else. After the cutover a bare `docker compose`
there would auto-load an in-network `DATABASE_URL` and silently use the old
container database, so the last two tests pin both halves of the fix — the
exclusion, and the explicit removal that the exclusion alone does not give
you.
"""

from __future__ import annotations

import re
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


def _commands(script: str) -> str:
    """The script with comment lines dropped.

    Every guard here keys off what a step actually runs, never off prose that
    happens to mention it. Without this, a step whose *comment* says "before
    rsync" or "a bare `docker compose` would..." gets picked up as if it ran
    those commands -- and a guard that matches a comment can be satisfied by
    editing one.
    """
    return "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )


def _compose_run_scripts() -> dict[str, str]:
    """Map "<workflow>:<job id>:<step name>" -> commands, for steps driving
    the compose stack on the VM."""
    found = {}
    for path in sorted(_WORKFLOWS_DIR.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                script = _commands(step.get("run", ""))
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


def _deploy_rsync_script() -> str:
    workflow = yaml.safe_load(
        (_WORKFLOWS_DIR / "deploy.yml").read_text(encoding="utf-8")
    )
    for step in workflow["jobs"]["deploy"]["steps"]:
        script = _commands(step.get("run", ""))
        # An invocation, not a mention: another step's comment says "before rsync".
        if re.search(r"(?m)^\s*rsync\s", script):
            return script
    raise AssertionError("deploy.yml no longer has an rsync step to check")


def test_deploy_does_not_ship_the_local_override_to_the_vm():
    """The -f pair above is the only thing keeping production off the
    override, and it was carrying that weight alone: the file was found on the
    VM, because the rsync excluded only .git, scout/.env and reports."""
    assert "--exclude 'docker-compose.override.yaml'" in _deploy_rsync_script()


def test_deploy_removes_an_override_already_on_the_vm():
    """Excluding a path is not the same as deleting it. rsync --delete leaves
    excluded files on the receiver untouched, so any copy shipped before the
    exclusion existed would stay there indefinitely -- which is exactly the
    state the VM was found in."""
    assert re.search(
        r"rm -f\s+'?[^'\s]*docker-compose\.override\.yaml", _deploy_rsync_script()
    ), "the deploy must explicitly remove a pre-existing override from the VM"
