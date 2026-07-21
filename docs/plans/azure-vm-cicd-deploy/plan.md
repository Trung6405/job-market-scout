# Azure VM CI/CD Deployment — Implementation Plan

> **Spec:** [`docs/specs/azure-vm-cicd-deploy/spec.md`](../../specs/azure-vm-cicd-deploy/spec.md) — this plan implements it.
> **Status:** ✅ All phases implemented (2026-07-21). Bicep compiles clean; pipeline YAML validated; code-review passed (DONE_WITH_CONCERNS, advisories applied).
> **Deliverables:** `infra/` (Bicep IaC + draw.io diagram), root `azure-pipelines.yml` + `infra-provision.yml`, `deployment-setup.md`.

**Goal:** Stand up tracked infrastructure-as-code so the single Azure VM (that hosts the scout containers) can be created/recreated from source, not portal clicks. The `infra/` folder is the first, self-contained deliverable; the two Azure DevOps pipelines and the secret variable group build on top of it.

**Architecture (target layout):**

```
infra/                      ← IaC only (Bicep) — THIS PLAN, Phase 1
├── main.bicep              ← VM + VNet/subnet + NSG + public IP + NIC, one file
├── main.bicepparam         ← fill-in params (region, VM size, admin user, SSH pubkey…)
├── cloud-init.yaml         ← VM bootstrap (Docker + compose + git + clone), base64'd into the VM
└── README.md               ← deploy steps + manual one-time Azure/ADO setup checklist

azure-pipelines.yml         ← (repo root) CI/CD: pytest → SSH deploy + daily scheduled run — Phase 3
infra-provision.yml         ← (repo root) manual: az deployment of infra/main.bicep         — Phase 2
```

**Decisions carried from brainstorm (all confirmed):** single `main.bicep` (no modules — one VM doesn't warrant it) · separate `cloud-init.yaml` referenced via `loadFileAsBase64()` · pipeline YAMLs live at **repo root**, `infra/` is Bicep-only · `infra/` holds **zero secrets**.

## Global Constraints (from spec)

- **Bicep only** — not Terraform. Native ARM deploy, no extra tooling in the pipeline.
- **Single VM, one environment.** No staging/prod split, no autoscaling, no blue-green.
- **No ACR.** Deploy is git-pull + local `docker compose build` on the VM (Phase 3), so the Bicep does **not** provision a registry.
- **Secrets never in the repo.** SSH *private* key + all `scout/.env` values live in an ADO secret variable group (Phase 4). Only the SSH **public** key sits in `main.bicepparam` (safe to commit). `.env` is already gitignored.
- **No changes** to `docker-compose.yaml`, `Dockerfile`, or `scout/` app code — deployment tooling only.
- Placeholders (not real values) for subscription/RG/region/org — resolved as manual setup, per spec Open Questions.

**Tech stack:** Bicep (ARM), Azure CLI (`az deployment group create`), cloud-init, Ubuntu 22.04 LTS. No Python/app changes.

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
- [ ] `<REPO_URL>` hardcoded (fixed repo). Flag as the one edit needed if the repo moves.

> Note: `jobspy-mcp` mounts `/var/run/docker.sock` and shells out to `docker run` per search (see `docker-compose.yaml`) — so a working host Docker daemon on the VM is a hard requirement, which this bootstrap satisfies. No extra nested-Docker setup needed.

### 1.4 `infra/README.md`

- [ ] Manual one-time checklist (from spec — account/portal steps, not IaC): create Azure DevOps org/project, GitHub↔ADO service connection, Azure service connection, resource group (`az group create -n <RG> -l <REGION>`).
- [ ] Deploy commands: `az deployment group create -g <RG> --template-file main.bicep --parameters main.bicepparam`.
- [ ] Which params to set before first run (`location`, `adminSshPublicKey`), how to generate the SSH keypair, and that the **private** key goes into the ADO variable group (Phase 4), never here.
- [ ] Placeholder legend: `<SUBSCRIPTION_ID>`, `<RESOURCE_GROUP>`, `<REGION>`.

### Phase 1 Success Criteria

- [ ] `infra/` contains exactly the four files above; no secrets committed.
- [ ] `az bicep build --file infra/main.bicep` compiles clean (lint pass) — the cheap local gate.
- [ ] (When a subscription exists) `az deployment group create ... --what-if` shows the VM + network resources with no errors; a real deploy yields a VM reachable over SSH with `docker`, `docker compose`, `git` present and the repo cloned at `/opt/job-market-scout`.
- [ ] Spec success-criterion met: "VM + network resources can be created/recreated from tracked IaC."

---

## Phase 2 — `infra-provision.yml` (manual infra pipeline) — ✅ done

`infra-provision.yml` at repo root: `trigger: none` / `pr: none`, one `AzureCLI@2` step that `az group create` + `az deployment group create --template-file infra/main.bicep --parameters infra/main.bicepparam`, echoing outputs. Re-run to apply infra changes.

## Phase 3 — `azure-pipelines.yml` (CI/CD) — ✅ done

`azure-pipelines.yml` at repo root. Two paths gated by `Build.Reason`:
- **CI path** (push/manual): `Test` (pytest, Python 3.12) → `Deploy` (SSH: `git pull --ff-only` → render `.env` from `scout-secrets` → `docker compose up -d --build`).
- **Schedule path** (`cron: "0 21 * * *"`, `always: true`): `RunJob` (`dependsOn: []`, SSH `docker compose run --rm app`).
- `set -euo pipefail` throughout; deploy key `chmod 600` on the ephemeral agent; `.env` rendered via heredoc-over-stdin (no secret on command line, no `set -x`).

## Phase 4 — ADO secret variable group + manual setup — ✅ done

Documented in [`deployment-setup.md`](./deployment-setup.md): create the `scout-secrets` variable group (18 `.env` keys secret, `VM_SSH_PRIVATE_KEY` secret, `VM_HOST`/`VM_USER` non-secret), service connections, and how secrets stay out of repo/logs. `.env` gitignored; rendered on the VM at deploy time only.

## Diagram — ✅ added

`infra/azure-deployment.drawio` (2 pages): CI/CD deployment flow + network topology (VNet/subnet/NSG/public-IP/NIC/VM). Matches repo's existing `docs/diagrams/*.drawio` style.

## Applied code-review advisories

- Deploy reordered to `git pull` → render `.env` → `compose up` (config never leads code).
- `VM_HOST`/`VM_USER` documented as non-secret (used via `$(...)` on SSH command line).
- Noted compose `environment:` overrides `JOBSPY_MCP_URL`/`DATABASE_URL` from `.env` (inert-but-harmless).

---

## Risks & Unknowns

| Risk / Unknown | Handling |
|----------------|----------|
| **SSH open to `*`** (`sshSourceAddressPrefix` default) | Accept `*` + key-only auth (`disablePasswordAuthentication: true`) for now. Hardening follow-up: narrow to a jump-host/known IP, or an "open→deploy→close" step, once the deploy source IP is known. ADO Microsoft-hosted agents rotate IPs, so static allowlisting isn't practical yet. |
| Public IP SKU | Use **Standard + Static** — Basic SKU is being retired by Azure; Standard is the safe default. |
| Repo URL hardcoded in `cloud-init.yaml` | Documented as the single edit if the repo moves. Templating deferred (YAGNI). |
| Subscription/RG/region not chosen yet | Placeholders in `main.bicepparam` + README legend; does not block authoring or `bicep build` lint. |
| `az`/Bicep CLI not installed locally | `az bicep build` lint requires Azure CLI. If absent, Phase 1 ships with the compile gate deferred to first pipeline/CI run; note the limitation. |
| Cloud-init timing | First boot installs Docker before the app can run; the deploy pipeline (Phase 3) runs after provisioning, so no race — documented ordering. |

## Open Questions

- Region default — plan assumes `australiaeast` (user is AU). Confirm or override in `main.bicepparam`. Non-blocking.
- Daily schedule time (UTC) — deferred to Phase 3 (pipeline cron), not needed for the `infra/` folder.
