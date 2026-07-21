# Deployment setup — Azure DevOps (manual, one-time)

Companion to [`plan.md`](./plan.md). Covers the account/portal steps that live
**outside** the pipeline YAML: the ADO project, service connections, and the
secret variable group the pipelines read from.

Pipelines (repo root):
- `infra-provision.yml` — manual: deploys `infra/main.bicep`.
- `azure-pipelines.yml` — CI/CD: `main` push → test + deploy; daily cron → scout run.

## 1. Provision the VM first

Run `infra-provision.yml` (or `az deployment` locally per [`infra/README.md`](../../../infra/README.md)).
Note the deployment output `publicIpAddress` — it becomes `VM_HOST` below.

## 2. Azure DevOps project + connections

1. Create the ADO organization/project.
2. Connect this GitHub repo (**Project settings → Service connections → GitHub**).
3. Create an **Azure Resource Manager** service connection scoped to the target
   subscription/resource group. Its name goes into `infra-provision.yml`
   (`azureServiceConnection`, currently `<AZURE_SERVICE_CONNECTION>`).
4. Register both pipelines: **Pipelines → New → existing YAML** →
   `azure-pipelines.yml` and `infra-provision.yml`.

## 3. Secret variable group: `scout-secrets`

**Pipelines → Library → + Variable group**, name it exactly `scout-secrets`
(matches `variables: - group: scout-secrets` in `azure-pipelines.yml`). Mark
the credential values as **secret** (lock icon); leave the connection targets
`VM_HOST`/`VM_USER` **non-secret** (they are used as `$(...)` on the SSH command
line, and Azure recommends secrets never appear there). Keys:

| Key | Secret? | Source |
|-----|---------|--------|
| `JOBSPY_MCP_URL` | yes | `http://jobspy-mcp:9423` (compose-internal) |
| `DEEPSEEK_API_KEY` | yes | DeepSeek |
| `DEEPSEEK_MODEL` | yes | e.g. `deepseek/deepseek-chat` |
| `SEARCH_ROLES`, `SEARCH_LOCATIONS`, `RESULTS_WANTED`, `HOURS_OLD` | yes | search config |
| `RESUME_PATH`, `PREFERRED_LOCATIONS`, `REMOTE_ONLY`, `MIN_SALARY`, `MIN_MATCH_SCORE` | yes | scoring config |
| `DESCRIPTION_CHAR_LIMIT`, `BRIEFING_MAX_MATCHES` | yes | limits |
| `DATABASE_URL` | yes | `postgresql://scout:scout@postgres:5432/scout` (compose-internal) |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `GMAIL_RECIPIENT` | yes | email |
| `VM_HOST` | no | VM public IP (step 1 output) |
| `VM_USER` | no | VM admin username (default `azureuser`) |
| `VM_SSH_PRIVATE_KEY` | yes | private half of the keypair whose public key is in `main.bicepparam` |

The full-file key set mirrors [`scout/.env.example`](../../../scout/.env.example)
plus the three `VM_*` deploy keys.

> Note: `docker-compose.yaml` sets `JOBSPY_MCP_URL` and `DATABASE_URL` in the
> `app` service's `environment:` block, which overrides `env_file`. Those two
> rendered `.env` lines are therefore inert for the `app` service — kept for
> completeness, harmless.

## 4. How secrets stay out of the repo and logs

- The `.env` file is **never committed** (`.gitignore` covers it). The deploy
  stage renders it on the VM at `/opt/job-market-scout/scout/.env` over SSH,
  from the variable group values.
- ADO auto-masks secret variable values in pipeline logs; the deploy script
  never runs with `set -x`, so rendered `.env` contents are not echoed.
- `VM_SSH_PRIVATE_KEY` is written to `~/.ssh/deploy_key` (`chmod 600`) on the
  ephemeral pipeline agent only.

## 5. Schedule

`azure-pipelines.yml` runs the scout cycle daily at **21:00 UTC** (`cron: "0 21 * * *"`).
Change the cron line to adjust. `always: true` runs it even without new commits.
