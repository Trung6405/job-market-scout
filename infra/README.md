# infra/ — Azure infrastructure-as-code

Bicep templates that create the single Azure VM hosting the job-market-scout
containers. This folder is **IaC only** — no secrets, no CI/CD YAML (those live
in `.github/workflows/`: `deploy.yml`, `scheduled-run.yml`, `infra-provision.yml`).

Implements [`docs/specs/azure-vm-cicd-deploy/spec.md`](../docs/specs/azure-vm-cicd-deploy/spec.md).

## Files

| File | What it is |
|------|------------|
| `main.bicep` | VNet + subnet, NSG (SSH + optional HTTP), Standard/Static public IP, NIC, Ubuntu 22.04 VM. Bootstraps the VM via `cloud-init.yaml`. |
| `main.bicepparam` | Fill-in parameters. Public SSH key only — safe to commit. |
| `cloud-init.yaml` | First-boot script: installs Docker + Compose plugin + rsync and creates `/opt/job-market-scout` (the `deploy.yml` workflow rsyncs the code in later). |
| `azure-deployment.drawio` | 2-page diagram: deployment/CI-CD flow + network topology. |

## Prerequisites

- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) with the Bicep extension (`az bicep install`).
- An Azure subscription and a resource group (created below).
- An SSH keypair — the **public** key goes in `main.bicepparam`; keep the
  **private** key safe (it later goes into the `VM_SSH_PRIVATE_KEY` GitHub
  Actions secret, never into this repo).

## One-time manual setup

These are account/portal steps, outside the Bicep:

1. **GitHub Actions — Azure OIDC** (so `infra-provision.yml` can deploy without a
   stored cloud secret): create an Azure AD app + service principal, grant it
   Contributor on the RG, and add a federated credential for this repo:
   ```bash
   az ad app create --display-name "job-market-scout-gha"   # -> appId = AZURE_CLIENT_ID
   az ad sp create --id <appId>
   az role assignment create --assignee <appId> --role Contributor \
     --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>
   az ad app federated-credential create --id <appId> --parameters '{
     "name":"gha-main","issuer":"https://token.actions.githubusercontent.com",
     "subject":"repo:Trung6405/job-market-scout:ref:refs/heads/main",
     "audiences":["api://AzureADTokenExchange"]}'
   ```
2. **GitHub Actions — secrets & variables** (repo → Settings → Secrets and
   variables → Actions):
   - **Secrets:** the keys from [`scout/.env.example`](../scout/.env.example),
     plus `VM_SSH_PRIVATE_KEY` and
     `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID`.
     The candidate source is `scout/profile.json`, which is committed and
     reaches the VM via rsync — no resume secret is needed.
   - **Variables:** `VM_HOST` (VM public IP), `VM_USER` (default `azureuser`),
     `RESOURCE_GROUP`, `AZURE_LOCATION`.
3. **Resource group** — pick a subscription and region, then:
   ```bash
   az login
   az account set --subscription <SUBSCRIPTION_ID>
   az group create --name <RESOURCE_GROUP> --location <REGION>
   ```
4. **SSH keypair** (if you don't have one):
   ```bash
   ssh-keygen -t rsa -b 4096 -f ~/.ssh/scout_vm
   cat ~/.ssh/scout_vm.pub   # paste into main.bicepparam -> adminSshPublicKey
   ```

## Deploy

Fill in `main.bicepparam` (`location`, `adminSshPublicKey`; adjust `vmSize` /
`sshSourceAddressPrefix` if needed), then:

```bash
# Lint / compile check (cheap, no Azure needed)
az bicep build --file main.bicep

# Preview changes
az deployment group what-if \
  --resource-group <RESOURCE_GROUP> \
  --template-file main.bicep \
  --parameters main.bicepparam

# Deploy
az deployment group create \
  --resource-group <RESOURCE_GROUP> \
  --template-file main.bicep \
  --parameters main.bicepparam
```

The deployment outputs `publicIpAddress` (set this as the `VM_HOST` Actions
variable) and a ready-to-use `sshCommand`. To apply infra changes later (VM
size, NSG rules), edit the Bicep and re-run `az deployment group create`.

## Validate after provisioning

Confirm the VM came up correctly before wiring the deploy workflow. Grab the IP
from the deployment output, then:

```bash
IP=$(az deployment group show -g <RESOURCE_GROUP> -n main \
  --query properties.outputs.publicIpAddress.value -o tsv)

# 1. Port 22 reachable (NSG + public IP OK)
nc -vz "$IP" 22

# 2. cloud-init finished cleanly (bootstrap done)
ssh azureuser@"$IP" 'cloud-init status --wait'          # -> status: done

# 3. Tooling installed and Docker usable without sudo
ssh azureuser@"$IP" 'docker --version && docker compose version && rsync --version | head -1 && docker ps'

# 4. App dir exists and is owned by the admin user (rsync target)
ssh azureuser@"$IP" 'ls -ld /opt/job-market-scout'      # -> owner azureuser
```

Expected: `nc` succeeds, `cloud-init status` is `done`, all three tools print
versions, `docker ps` runs without permission error, and `/opt/job-market-scout`
is owned by `azureuser`. If `cloud-init status` shows `error`, inspect the
bootstrap log:

```bash
ssh azureuser@"$IP" 'sudo cat /var/log/cloud-init-output.log'
```

Optional Azure-side checks:

```bash
az vm show -g <RESOURCE_GROUP> -n scout-vm --query "provisioningState" -o tsv   # -> Succeeded
az network nsg rule list -g <RESOURCE_GROUP> --nsg-name scout-vm-nsg -o table   # allow-ssh present
```

> `docker ps` may fail on the very first SSH session if the login predates the
> `usermod -aG docker` from cloud-init — reconnect (or `newgrp docker`) and retry.

## Notes & caveats

- **`cloud-init.yaml` only preps the host** (Docker + Compose + rsync, and creates
  `/opt/job-market-scout`). It does **not** clone — the `deploy.yml` workflow
  rsyncs the repo from the GitHub runner to the VM over SSH, so the VM needs no
  GitHub access. Keeps all secrets out of the IaC (nothing sensitive in Bicep/customData).
- **SSH is open to `*`** by default (`sshSourceAddressPrefix`), relying on
  key-only auth (`disablePasswordAuthentication: true`). Narrow it to a known
  IP/CIDR to harden.
- **No secrets here.** Application secrets (`scout/.env` values) and the SSH
  private key belong in GitHub Actions secrets, rendered onto the VM at deploy
  time by `deploy.yml`.

## Placeholder legend

| Placeholder | Meaning |
|-------------|---------|
| `<SUBSCRIPTION_ID>` | Target Azure subscription |
| `<RESOURCE_GROUP>` | Resource group holding the VM |
| `<REGION>` | Azure region, e.g. `australiaeast` |
