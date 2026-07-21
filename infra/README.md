# infra/ — Azure infrastructure-as-code

Bicep templates that create the single Azure VM hosting the job-market-scout
containers. This folder is **IaC only** — no secrets, no CI/CD YAML (those live
in `.github/workflows/`: `deploy.yml`, `scheduled-run.yml`, `infra-provision.yml`).

Implements [`docs/specs/azure-vm-cicd-deploy/spec.md`](../docs/specs/azure-vm-cicd-deploy/spec.md).

## Files

| File | What it is |
|------|------------|
| `main.bicep` | VNet + subnet, NSG (SSH), Standard/Static public IP, NIC, Ubuntu 22.04 VM. Bootstraps the VM via `cloud-init.yaml`. |
| `main.bicepparam` | Fill-in parameters. Public SSH key only — safe to commit. |
| `cloud-init.yaml` | First-boot script: installs Docker + Compose plugin + git, clones this repo to `/opt/job-market-scout`. |

## Prerequisites

- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) with the Bicep extension (`az bicep install`).
- An Azure subscription and a resource group (created below).
- An SSH keypair — the **public** key goes in `main.bicepparam`; keep the
  **private** key safe (it later goes into the Azure DevOps secret variable
  group, never into this repo).

## One-time manual setup

These are account/portal steps, outside the Bicep (per spec):

1. **Azure DevOps** — create the org/project, connect this GitHub repo
   (GitHub service connection), and create an Azure Resource Manager service
   connection for the pipeline to deploy with. (Used by later phases.)
2. **Resource group** — pick a subscription and region, then:
   ```bash
   az login
   az account set --subscription <SUBSCRIPTION_ID>
   az group create --name <RESOURCE_GROUP> --location <REGION>
   ```
3. **SSH keypair** (if you don't have one):
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

The deployment outputs `publicIpAddress` (feeds the pipeline's `VM_HOST`) and a
ready-to-use `sshCommand`. To apply infra changes later (VM size, NSG rules),
edit the Bicep and re-run `az deployment group create`.

## Notes & caveats

- **`cloud-init.yaml` only preps the host** (Docker + Compose + rsync, and creates
  `/opt/job-market-scout`). It does **not** clone — the `deploy.yml` workflow
  rsyncs the repo from the GitHub runner to the VM over SSH, so the VM needs no
  GitHub access. Keeps all secrets out of the IaC (nothing sensitive in Bicep/customData).
- **SSH is open to `*`** by default (`sshSourceAddressPrefix`), relying on
  key-only auth (`disablePasswordAuthentication: true`). Narrow it to a known
  IP/CIDR to harden.
- **No secrets here.** Application secrets (`scout/.env` values) and the SSH
  private key belong in the Azure DevOps secret variable group, written to the
  VM at deploy time.

## Placeholder legend

| Placeholder | Meaning |
|-------------|---------|
| `<SUBSCRIPTION_ID>` | Target Azure subscription |
| `<RESOURCE_GROUP>` | Resource group holding the VM |
| `<REGION>` | Azure region, e.g. `australiaeast` |
