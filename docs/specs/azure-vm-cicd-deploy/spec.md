# Spec: CI/CD Pipeline for Azure VM Deployment

> **Status:** Draft
> **Created:** 2026-07-20 · **Approved:** —
> **Implementation plan:** [plan.md](../../plans/azure-vm-cicd-deploy/plan.md) *(created after approval)*

---

## Problem

The `job-market-scout` pipeline (scraper → scorer → briefing, driven by `scout/main.py`) currently only runs locally via `docker compose up`. There is no automated way to get code changes onto a real server, and no scheduled execution — someone has to manually run the pipeline. There's also no target infrastructure yet: no Azure VM exists to host the containers. The team wants pushes to `main` to automatically deploy to a live Azure VM, and wants the scout job itself to run daily without manual intervention.

## Success Criteria

- A push to `main` that passes tests automatically updates the running containers on the Azure VM with no manual SSH steps.
- The scout pipeline job (`docker compose run --rm app`) executes once daily on the VM without anyone triggering it by hand.
- Secrets (API keys, DB credentials, SSH key) never appear in the git repo or in pipeline logs.
- The Azure VM and its network resources (NSG, public IP, disk) can be created or recreated from tracked infrastructure-as-code, not manual portal clicks.

---

## Requirements

### Must have

- An Azure DevOps pipeline (`azure-pipelines.yml`) that: runs `pytest` on push to `main`; on success, deploys via SSH (`git pull` + `docker compose up -d --build`) to the VM.
- A daily scheduled trigger on the same pipeline (or a stage within it) that runs the scout job once via `docker compose run --rm app` on the VM.
- A Bicep template defining the VM, NSG, public IP, and disk, deployable via a separate, manually-triggered pipeline (`infra-provision.yml`).
- A one-time VM bootstrap mechanism (cloud-init or provisioning script) that installs Docker, Docker Compose, and git, and clones the repo.
- Secrets (the values currently in `scout/.env`, plus the deploy SSH private key) stored in an Azure DevOps secret variable group, written to the VM's `scout/.env` only at deploy time over SSH.
- A documented, manual, one-time checklist for creating the Azure DevOps project/repo connection and the Azure service connection (account/portal-level steps outside pipeline YAML).

### Should have

- Deploy stage fails loudly (and does not leave the VM mid-update) if `git pull` or `docker compose up` fails.
- Pipeline run logs make clear which stage (test / deploy / scheduled-run) executed and its outcome.

### Won't have

- Container registry (ACR) usage — deploy is git-pull + local build on the VM, not registry push/pull, per chosen approach.
- Changes to `docker-compose.yaml`, `Dockerfile`, or any `scout/` application code — this is deployment tooling only.
- Monitoring/alerting, autoscaling, or blue-green/zero-downtime deploy — single VM, in-place restart is acceptable.
- Multi-environment (staging/prod) support — one VM, one environment.

---

## Proposed Approach

Two independent Azure DevOps pipelines, reflecting that infrastructure changes rarely and code changes often:

1. **`infra-provision.yml`** (manual trigger only) deploys `infra/main.bicep` — a VM, NSG (allowing SSH), public IP, and OS disk — and runs a bootstrap step (cloud-init embedded in the Bicep, or a `customScript` extension) that installs Docker Engine, the Docker Compose plugin, and git, then clones this repository onto the VM. Re-running this pipeline is how infra changes (VM size, NSG rules, etc.) get applied.

2. **`azure-pipelines.yml`** (the CI/CD pipeline) has two trigger paths into shared stages:
   - **CI path** — push to `main` → `Test` stage (`pytest`) → `Deploy` stage: SSH into the VM, write `.env` from the ADO secret variable group, `git pull`, `docker compose up -d --build`.
   - **Schedule path** — daily cron trigger → `RunJob` stage: SSH into the VM, `docker compose run --rm app` (one-shot pipeline execution, separate from the long-lived `postgres`/`jobspy-mcp` services).

   Both paths reuse the same SSH connection details and secret variable group, defined once in the pipeline file.

Secrets live in an Azure DevOps Library variable group (secret-masked), containing the same keys as `scout/.env.example` plus `VM_SSH_PRIVATE_KEY` and `VM_HOST`. The deploy stage renders these into a `.env` file on the VM via an SSH task (e.g. `Bash@3` over an SSH connection, or the `SSH` deploy task) — the file never passes through a git commit or an unmasked log line.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| GitHub Actions | User specified Azure DevOps Pipelines as the CI/CD system to use. |
| Build & push to Azure Container Registry, pull on VM | User chose the simpler SSH + git pull + `docker compose up --build` approach; no registry to provision or authenticate against. |
| Terraform for infra | User chose Bicep — no extra tooling to install in the pipeline, native ARM deployment task available. |
| Single pipeline with a conditional infra stage | User chose two separate pipelines so infra provisioning is fully isolated from the code deploy path and can't be triggered accidentally by a push. |
| Do nothing (keep manual local `docker compose up`) | Doesn't meet the stated goal of automated deploy + unattended daily runs. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Azure DevOps org/project name and repo connection (GitHub service connection vs. Azure Repos mirror) — org doesn't exist yet, user will create it later | human | no — documented as a manual setup checklist step; pipeline YAML uses placeholder service-connection/org names |
| Target Azure subscription, resource group name, and region for the VM | human | no — Bicep params and pipeline variables use clearly-named placeholders (`<SUBSCRIPTION_ID>`, `<RESOURCE_GROUP>`, `<REGION>`) for the user to fill in before first run |
| VM size and OS image (e.g. `Standard_B2s`, Ubuntu 22.04 LTS) — no strong constraint given, will default and confirm | human | no |
| Exact daily schedule time (UTC) for the job run — "daily" given, specific time not yet chosen | human | no |

> None of these block writing plan.md — all resolved as "use placeholders / defaults, document as manual setup," carried into the plan's Risks & Unknowns and into a manual setup checklist.

---

## Amendments *(only after approval — never silently edit approved content)*

- **2026-07-21 — CI system changed to GitHub Actions.** User reversed the original "Azure DevOps Pipelines" choice (see Alternatives Considered). Implementation now uses `.github/workflows/` instead of `azure-pipelines.yml`/`infra-provision.yml`. Two further consequences of the switch: (1) deploy is **runner checkout + rsync** to the VM rather than VM-side `git pull` — the VM needs no GitHub access, which also resolves the private-repo clone problem; (2) Azure auth for infra provisioning uses **OIDC federated credentials** (no stored service-principal secret) instead of an ADO service connection. The Bicep/IaC (`infra/`) is unchanged by this. See `docs/plans/azure-vm-cicd-deploy/{plan,deployment-setup}.md`.
