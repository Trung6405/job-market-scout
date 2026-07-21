# Azure VM CI/CD Deployment — Implementation Plan

> **Spec:** [`docs/specs/azure-vm-cicd-deploy/spec.md`](../../specs/azure-vm-cicd-deploy/spec.md) — this plan implements it.
> **Status:** ✅ All phases implemented (2026-07-21). Bicep compiles clean; workflow YAML validated; code-review passed (advisories applied).
> **CI system:** ⚠️ **Changed 2026-07-21** — GitHub Actions (was Azure DevOps; user reversed the spec's choice). Deploy via runner **rsync** to the VM; Azure auth via **OIDC**.
> **Deliverables:** `infra/` (Bicep IaC + draw.io diagram), `.github/workflows/{deploy,scheduled-run,infra-provision}.yml`, `deployment-setup.md`.

**Goal:** Stand up tracked infrastructure-as-code so the single Azure VM (that hosts the scout containers) can be created/recreated from source, not portal clicks. The `infra/` folder is the self-contained IaC deliverable; the GitHub Actions workflows and repo secrets build on top of it.

**Architecture (target layout):**

```
infra/                      ← IaC only (Bicep)
├── main.bicep              ← VM + VNet/subnet + NSG + public IP + NIC, one file
├── main.bicepparam         ← fill-in params (region, VM size, admin user, SSH pubkey…)
├── cloud-init.yaml         ← host prep (Docker + Compose + rsync + app dir), base64'd into the VM
├── azure-deployment.drawio ← 2-page diagram (deployment flow + network topology)
└── README.md               ← deploy steps + manual one-time Azure setup

.github/workflows/
├── deploy.yml              ← push to main: pytest → rsync to VM → render .env → compose up
├── scheduled-run.yml       ← daily cron: SSH docker compose run --rm app
└── infra-provision.yml     ← manual (workflow_dispatch): OIDC login → az deployment of main.bicep
```

**Decisions:** single `main.bicep` (no modules — one VM doesn't warrant it) · separate `cloud-init.yaml` referenced via `loadFileAsBase64()` · CI/CD in `.github/workflows/`, `infra/` is Bicep-only · `infra/` holds **zero secrets** · deploy = runner checkout + rsync (VM needs no GitHub access) · Azure auth = OIDC federated (no stored cloud secret).

## Global Constraints (from spec)

- **Bicep only** — not Terraform. Native ARM deploy.
- **Single VM, one environment.** No staging/prod split, no autoscaling, no blue-green.
- **No ACR.** Deploy = rsync source + local `docker compose build` on the VM, so the Bicep does **not** provision a registry.
- **Secrets never in the repo.** SSH *private* key + all `scout/.env` values live in **GitHub Actions secrets**. Only the SSH **public** key sits in `main.bicepparam` (safe to commit). `.env` is gitignored + rsync-excluded.
- **No changes** to `docker-compose.yaml`, `Dockerfile`, or `scout/` app code — deployment tooling only.
- Placeholders (not real values) for subscription/RG/region — resolved as manual setup.

**Tech stack:** Bicep (ARM), Azure CLI, cloud-init, Ubuntu 22.04 LTS, GitHub Actions (OIDC, rsync). No Python/app changes.

---

## Phase 1 — `infra/` folder (Bicep IaC) — **cook this now**

Deliverable: the four files in `infra/`, such that `az deployment group create -g <RG> --template-file infra/main.bicep --parameters infra/main.bicepparam` provisions a reachable, Docker-ready VM with the repo cloned onto it. No pipeline required to validate — `az` from a laptop is enough.

### 1.1 `infra/main.bicep`

- [ ] `targetScope = 'resourceGroup'` (RG created out-of-band; see README).
- [ ] **Params** (typed, with defaults where sensible), consumed from `main.bicepparam`:
  - `location string` — no default (forces explicit choice).
  - `vmName string = 'scout-vm'`
  - `vmSize string = 'Standard_B2s'`
  - `adminUsername string = 'azureuser'`
  - `adminSshPublicKey string` — no default (required, non-secret).
  - `sshSourceAddressPrefix string = '*'` — NSG SSH source. Default `*` + key-only auth; flagged as hardening follow-up (see Risks).
- [ ] **Resources** (minimal VM stack):
  - `virtualNetwork` `10.0.0.0/16` with one `subnet` `10.0.0.0/24`.
  - `networkSecurityGroup` — one inbound rule: TCP 22 from `sshSourceAddressPrefix`. Associated to the NIC.
  - `publicIPAddress` — **Standard SKU + Static** (Basic SKU is retiring; Standard requires Static allocation).
  - `networkInterface` — ipConfig binding subnet + public IP; NSG referenced here.
  - `virtualMachine`:
    - image: Canonical `0001-com-ubuntu-server-jammy` / `22_04-lts-gen2` / `latest`.
    - `osProfile.customData = loadFileAsBase64('cloud-init.yaml')`.
    - `linuxConfiguration`: `disablePasswordAuthentication: true`, SSH publicKey `adminSshPublicKey` → `/home/${adminUsername}/.ssh/authorized_keys`.
    - OS disk: managed, `StandardSSD_LRS`, from image.
    - hardwareProfile `vmSize`.
- [ ] **Outputs:** `publicIpAddress` (the IP the deploy pipeline SSHes to → feeds `VM_HOST` in Phase 4), `sshCommand` (convenience string).

> Bicep gotcha to verify at author time: `loadFileAsBase64` resolves relative to the `.bicep` file, so `cloud-init.yaml` sitting next to `main.bicep` is correct. Repo URL is baked into `cloud-init.yaml` (KISS) — no templating needed, so `customData` can be a static base64 load rather than a string-interpolated one.

### 1.2 `infra/main.bicepparam`

- [ ] `using './main.bicep'` header, then `param` assignments.
- [ ] Placeholders for the human to fill: `location` (e.g. `australiaeast` — user is AU), `adminSshPublicKey` (`ssh-rsa AAAA... REPLACE_ME`). Others default.
- [ ] Contains **no secrets** — public key only. Safe to commit.

### 1.3 `infra/cloud-init.yaml`

- [ ] `#cloud-config` one-time bootstrap:
  - `packages: [git]` (+ `package_update: true`).
  - `runcmd`: install Docker Engine + Compose plugin via `curl -fsSL https://get.docker.com | sh` (the convenience script ships `docker-compose-plugin`); enable + start `docker`; add `${adminUsername}` to the `docker` group.
  - `git clone --recurse-submodules <REPO_URL> /opt/job-market-scout` — repo vendors a submodule (`jobspy-mcp-server`), so `--recurse-submodules` is mandatory (matches README).
- [x] **Final (GitHub Actions + rsync):** cloud-init does NOT clone or install git. It installs Docker + Compose + rsync and creates `/opt/job-market-scout` (owned uid 1000). The `deploy.yml` workflow rsyncs the repo from the runner to the VM, so the VM needs no GitHub access — keeps IaC secret-free.

> Note: `jobspy-mcp` mounts `/var/run/docker.sock` and shells out to `docker run` per search (see `docker-compose.yaml`) — so a working host Docker daemon on the VM is a hard requirement, which this bootstrap satisfies. No extra nested-Docker setup needed.

### 1.4 `infra/README.md`

- [x] Manual one-time checklist (account/portal steps, not IaC): resource group (`az group create -n <RG> -l <REGION>`); GitHub Actions OIDC/secrets setup lives in `deployment-setup.md`.
- [x] Deploy commands: `az deployment group create -g <RG> --template-file main.bicep --parameters main.bicepparam`.
- [x] Which params to set before first run (`location`, `adminSshPublicKey`), how to generate the SSH keypair, and that the **private** key goes into a GitHub Actions secret (`VM_SSH_PRIVATE_KEY`), never here.
- [x] Placeholder legend: `<SUBSCRIPTION_ID>`, `<RESOURCE_GROUP>`, `<REGION>`.

### Phase 1 Success Criteria

- [ ] `infra/` contains exactly the four files above; no secrets committed.
- [ ] `az bicep build --file infra/main.bicep` compiles clean (lint pass) — the cheap local gate.
- [ ] (When a subscription exists) `az deployment group create ... --what-if` shows the VM + network resources with no errors; a real deploy yields a VM reachable over SSH with `docker`, `docker compose`, `rsync` present and `/opt/job-market-scout` ready for the workflow to rsync into.
- [ ] Spec success-criterion met: "VM + network resources can be created/recreated from tracked IaC."

---

## Phase 2 — `infra-provision.yml` (manual infra workflow) — ✅ done

`.github/workflows/infra-provision.yml`: `workflow_dispatch` only, `permissions: id-token: write`. Steps: `azure/login@v2` (OIDC, using `AZURE_CLIENT_ID/TENANT_ID/SUBSCRIPTION_ID`) → `az group create` + `az deployment group create --template-file infra/main.bicep --parameters infra/main.bicepparam`. Re-run to apply infra changes.

## Phase 3 — CI/CD workflows — ✅ done

- **`deploy.yml`** (push to `main` + `workflow_dispatch`): `test` job (pytest, Python 3.12) → `deploy` job: `actions/checkout` (submodules) → **rsync** repo to VM over SSH (`--delete`, excludes `.git`/`scout/.env`) → render `.env` from Actions secrets (heredoc, secrets via `env:`) → `docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d --build`. VM needs **no** GitHub access.
- **`scheduled-run.yml`** (`cron: "0 21 * * *"` + `workflow_dispatch`): SSH `docker compose -f docker-compose.yaml -f docker-compose.prod.yaml run --rm app`. Runs whatever `deploy` last synced.

**Production compose overlay + smoke-test page (added 2026-07-21).** The base `docker-compose.yaml` (local/dev) is left untouched; production adds `docker-compose.prod.yaml` (layered via `-f … -f …`) which brings up a `hello` nginx service serving `hello/index.html` on port 80 and sets `restart: unless-stopped` on the long-lived services. `main.bicep` gains an NSG `allow-http` rule (param `httpSourceAddressPrefix`, default `*`, empty = closed). Opening `http://<VM_IP>/` shows "Hello World" — an end-to-end reachability check (public IP → NSG:80 → nginx).
- `set -euo pipefail` throughout; SSH key `chmod 600` on the ephemeral runner; no `set -x`.

## Phase 4 — GitHub Actions secrets + manual setup — ✅ done

Documented in [`deployment-setup.md`](./deployment-setup.md): OIDC federated credential setup; **secrets** (18 `.env` keys + `VM_SSH_PRIVATE_KEY` + `AZURE_*` IDs) and **variables** (`VM_HOST`, `VM_USER`, `RESOURCE_GROUP`, `AZURE_LOCATION`); how secrets stay out of repo/logs. `.env` gitignored + rsync-excluded; rendered on the VM at deploy time only.

## Diagram — ✅ added

`infra/azure-deployment.drawio` (2 pages): CI/CD deployment flow (GitHub Actions) + network topology (VNet/subnet/NSG/public-IP/NIC/VM). Matches repo's existing `docs/diagrams/*.drawio` style.

## Applied code-review advisories (from the earlier ADO version, carried over)

- Deploy orders host-sync before `.env` render before `compose up` (config never leads code).
- `VM_HOST`/`VM_USER` are non-secret **variables** (not secrets).
- Noted compose `environment:` overrides `JOBSPY_MCP_URL`/`DATABASE_URL` from `.env` (inert-but-harmless).

---

## Risks & Unknowns

| Risk / Unknown | Handling |
|----------------|----------|
| **SSH open to `*`** (`sshSourceAddressPrefix` default) | Accept `*` + key-only auth (`disablePasswordAuthentication: true`) for now. Hardening follow-up: narrow to known IPs, or an "open→deploy→close" step. GitHub-hosted runners rotate IPs, so static allowlisting isn't practical yet. |
| Public IP SKU | Use **Standard + Static** — Basic SKU is being retired by Azure; Standard is the safe default. |
| Subscription/RG/region not chosen yet | Placeholders in `main.bicepparam` + README legend; does not block authoring or `bicep build` lint. |
| `az`/Bicep CLI not installed locally | `az bicep build` lint requires Azure CLI. If absent, Phase 1 ships with the compile gate deferred to first pipeline/CI run; note the limitation. |
| Cloud-init timing | First boot installs Docker before the app can run; the deploy pipeline (Phase 3) runs after provisioning, so no race — documented ordering. |

## Open Questions

- Region default — plan assumes `australiaeast` (user is AU). Confirm or override in `main.bicepparam`. Non-blocking.
- Daily schedule time (UTC) — deferred to Phase 3 (pipeline cron), not needed for the `infra/` folder.
