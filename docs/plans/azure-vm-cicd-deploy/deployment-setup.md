# Deployment setup — GitHub Actions (manual, one-time)

Companion to [`plan.md`](./plan.md). Covers the account/portal steps that live
**outside** the workflow YAML: the Azure OIDC identity, the resource group, and
the GitHub Actions secrets/variables the workflows read.

Workflows (`.github/workflows/`):
- `infra-provision.yml` — manual (`workflow_dispatch`): deploys `infra/main.bicep` via OIDC.
- `deploy.yml` — push to `main`: `test` (pytest) → `deploy` (rsync repo to VM, render `.env`, `docker compose up -d --build`).
- `scheduled-run.yml` — daily cron 21:00 UTC (+ manual): SSH `docker compose run --rm app`.

Deploy model: the runner checks out the repo and **rsyncs** it to the VM over
SSH — the VM needs no GitHub access (no deploy key).

## 1. Provision the VM first

Run **Actions → Provision infra → Run workflow** (or `az deployment` locally per
[`infra/README.md`](../../../infra/README.md)). Note the output `publicIpAddress`
— it becomes the `VM_HOST` variable below.

## 2. Azure OIDC (federated) for infra-provision

Create an Azure AD app + service principal, grant it Contributor on the target
subscription/RG, and add a **federated credential** for this repo so no cloud
secret is stored:

```bash
az ad app create --display-name "job-market-scout-gha"
# capture appId (-> AZURE_CLIENT_ID) and the tenant/subscription IDs
az ad sp create --id <appId>
az role assignment create --assignee <appId> --role Contributor \
  --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/<RESOURCE_GROUP>
az ad app federated-credential create --id <appId> --parameters '{
  "name": "gha-main",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:Trung6405/job-market-scout:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'
```

For manual `workflow_dispatch` runs the token subject is the branch ref above.
If you provision from a non-`main` branch, add a matching federated credential.

## 3. GitHub Actions secrets & variables

**Repo → Settings → Secrets and variables → Actions.**

**Secrets** (encrypted):

| Secret | Source |
|--------|--------|
| `JOBSPY_MCP_URL`, `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` | app config / DeepSeek |
| `SEARCH_ROLES`, `SEARCH_LOCATIONS`, `RESULTS_WANTED`, `HOURS_OLD` | search config |
| `RESUME_PATH`, `PREFERRED_LOCATIONS`, `REMOTE_ONLY`, `MIN_SALARY`, `MIN_MATCH_SCORE` | scoring config |
| `DESCRIPTION_CHAR_LIMIT`, `BRIEFING_MAX_MATCHES` | limits |
| `DATABASE_URL` | `postgresql://scout:scout@postgres:5432/scout` (compose-internal) |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `GMAIL_RECIPIENT` | email |
| `VM_SSH_PRIVATE_KEY` | private half of the keypair whose public key is in `main.bicepparam` |
| `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` | OIDC (step 2) |

The 18 app keys mirror [`scout/.env.example`](../../../scout/.env.example).

**Variables** (non-secret):

| Variable | Value |
|----------|-------|
| `VM_HOST` | VM public IP (step 1 output) |
| `VM_USER` | VM admin username (default `azureuser`) |
| `RESOURCE_GROUP` | resource group name |
| `AZURE_LOCATION` | e.g. `australiaeast` |

## 4. How secrets stay out of the repo and logs

- `.env` is **never committed** (`.gitignore` covers it) and is excluded from the
  rsync. The `deploy` job renders it on the VM from the mapped secrets.
- GitHub Actions auto-masks secret values in logs; secrets are consumed via
  `env:` (not inline `${{ }}` in `run:`), and no step uses `set -x`.
- `VM_SSH_PRIVATE_KEY` is written to `~/.ssh/deploy_key` (`chmod 600`) on the
  ephemeral runner only. No cloud credential is stored (OIDC).

## 5. Schedule

`scheduled-run.yml` runs daily at **21:00 UTC** (`cron: "0 21 * * *"`). Change the
cron to adjust. A `deploy` must run once (push to `main`) before the first
scheduled run, so the code + `.env` exist on the VM.

> Note: `docker-compose.yaml` sets `JOBSPY_MCP_URL` and `DATABASE_URL` in the
> `app` service's `environment:` block, which overrides `env_file` — those two
> rendered `.env` lines are inert for `app`, kept for completeness.
