# Plan: Static website hosting for the reports dashboard

> **Status:** Complete — verified reachable at https://trung6405scoutdash.z44.web.core.windows.net/ while `scout-vm` is deallocated
> **Created:** 2026-07-23 · **Last updated:** 2026-07-23
> **Spec:** none — small work, per plan-standards size threshold (single phase, ~4 files, low risk)
>
> **Amendment (2026-07-23):** Originally targeted Azure Static Web Apps. Provisioning failed with a
> policy violation — this subscription (Azure for Students) restricts deployments to
> `indonesiacentral`, `japanwest`, `japaneast`, `malaysiawest`, `newzealandnorth`, and Static Web
> Apps isn't offered in any of them. Switched to a Storage Account with static website hosting
> (available in `newzealandnorth`) instead — same ~$0 cost, and avoids the deploy-token secret
> entirely by reusing the existing OIDC login (via a `Storage Blob Data Contributor` role
> assignment) instead of `Azure/static-web-apps-deploy@v1`. All references to "Static Web App"
> below are updated to reflect this.
>
> **Amendment (2026-07-23):** `main.bicep` couldn't be redeployed against the existing VM (ARM
> rejects any `osProfile.customData` value on update — pre-existing issue, unrelated to this
> feature). Split the storage account into its own `infra/dashboard.bicep`, deployed as a separate
> step in `infra-provision.yml`. The RBAC role assignment also had to be granted out-of-band (the
> CI service principal only has `Contributor`, which can't grant roles) — see the note in
> `dashboard.bicep`. Also fixed: the static website's single global index-document setting meant
> `/hello/` 404'd looking for `hello/history.html` instead of the uploaded `hello/index.html`;
> standardized on `index.html` everywhere (`history.html` is also copied to `index.html` at the
> site root, and kept under its own name for direct links).

---

## Overview

Today the reports dashboard (`reports/history.html`, `reports/profile.html`,
and the `hello/` smoke-test page) is only served by nginx on `scout-vm`, so
it's unreachable whenever the VM is deallocated (i.e. ~23h/day). This plan
provisions an Azure Storage Account with static website hosting and adds a
publish step to `scheduled-run.yml` so the dashboard is reachable 24/7,
independent of the VM's start/deallocate cycle. The VM, its
docker-exec-dependent stack (`app` + `jobspy-mcp` + `jobspy-scraper` +
`postgres`), and GitHub Actions orchestration are unchanged. Done = after a
scheduled run completes and the VM deallocates, the dashboard is still
reachable at the storage account's static website endpoint with up-to-date
content.

## Acceptance Criteria

- [x] A `Microsoft.Storage/storageAccounts` resource with static website
      hosting enabled exists, provisioned via `infra/dashboard.bicep`/`infra-provision.yml`.
- [x] `scheduled-run.yml` copies `reports/` and `hello/` off the VM and
      uploads them to the storage account's `$web` container after each
      scout cycle, before the VM is deallocated.
- [x] The on-VM `hello` nginx service is removed from
      `docker-compose.prod.yaml`.
- [x] After a scheduled run, the dashboard (`/` → `history.html`/`index.html`, `/hello`)
      is reachable at the static website endpoint while `scout-vm` is deallocated.
      Verified 2026-07-23: `/`, `/hello/`, and `/history.html` all return 200
      with `scout-vm` in `VM deallocated` state.
- [x] A failed publish/upload step does not prevent the `Deallocate VM` step
      from running (unchanged `if: always()` on that step; also incidentally
      exercised when "Run scout cycle" itself failed mid-verification and
      `Deallocate VM` still ran).

---

## Risks & Unknowns

| Risk / unknown | Impact if wrong | Resolution |
|----------------|-----------------|------------|
| Static Web Apps' routing for a nested `hello/` subfolder under a non-root `app_location` may not map 1:1 to nginx's `/hello` alias behavior | `/hello` 404s or serves wrong content | Verify manually in the rollout step; adjust `staticwebapp.config.json` routes if needed |
| Deployment token secret naming/scoping unfamiliar (first Static Web Apps use in this repo) | Deploy step fails auth | Follow the token Bicep outputs; treat as accepted risk, fix forward if the first manual dispatch fails |

## Blast Radius

- **Code that will change:** `infra/main.bicep`, `infra/main.bicepparam` (if params needed), `.github/workflows/scheduled-run.yml`, `docker-compose.prod.yaml`.
- **Existing behaviour that could break:** the `/hello` and `/` dashboard URLs move from `http://<VM_PUBLIC_IP>/` to the new Static Web App hostname — anyone with the old URL bookmarked loses it. No change to the scout pipeline, Postgres, email delivery, or the VM's docker-exec stack.
- **Off-limits:** Do not modify `scout/` application code, `docker-compose.yaml` (base/dev file), or `deploy.yml` beyond what's needed here without flagging first.

---

## Tasks

1. **Provision the Static Web App**
   - Add a `Microsoft.Web/staticSites` resource to `infra/main.bicep` (Free SKU), output its default hostname and deployment token (`listSecrets` on the resource, or output the token via a Bicep `secure()` output).
   - Run `infra-provision.yml` (`workflow_dispatch`) to apply it.
   - Manually add the deployment token as a new GitHub secret, `AZURE_STATIC_WEB_APPS_API_TOKEN` (naming to match the standard `Azure/static-web-apps-deploy@v1` action convention).

2. **Wire the publish step into `scheduled-run.yml`**
   - After "Run scout cycle" and before "Deallocate VM": rsync `reports/` and `hello/` from the VM back to the runner (mirroring the existing rsync direction/exclude patterns already used in `deploy.yml`).
   - Add a step using `Azure/static-web-apps-deploy@v1` with `app_location` pointing at the synced folder, arranged so `reports/history.html` lands at the site root and `hello/index.html` lands under `/hello` (add a `staticwebapp.config.json` route/rewrite if the default folder-based routing doesn't already produce that layout).
   - Ensure the publish/deploy step's failure doesn't block the existing `if: always()` "Deallocate VM" step (it already runs regardless of prior step outcomes — just confirm the new step doesn't get inserted in a way that changes that).

3. **Remove the on-VM nginx `hello` service**
   - Delete the `hello` service block from `docker-compose.prod.yaml`.
   - Leave `docker-compose.yaml` (base/dev) untouched — nginx was only ever in the prod overlay.

4. **Manual rollout verification**
   - Trigger `scheduled-run.yml` via `workflow_dispatch`.
   - After it completes and the VM shows deallocated (`az vm list -d`), confirm both `/` and `/hello` resolve correctly on the Static Web App hostname.

---

## Testing Strategy

- **Unit:** none — this is infra/CI configuration, not application code.
- **Integration:** none beyond the manual rollout check below (no automated test harness for Bicep/GitHub Actions in this repo).
- **Manual:** Task 4 above — the definitive check is dashboard reachability *after* VM deallocation, since that's the entire point of the change.

## Rollout & Reversibility

- **Feature flag:** none.
- **Migrations:** none — no schema or stored-data changes.
- **Rollback plan:** revert the `scheduled-run.yml` and `docker-compose.prod.yaml` changes; the Static Web App resource can be left in place (Free tier, no cost) or deleted via `az staticwebapp delete`. The VM's `hello` nginx service can be restored from git history if needed.

## Key Decisions & Constraints

- Keep the VM, Postgres, and the docker-exec (jobspy-mcp → jobspy-scraper) pattern unchanged — decided during brainstorming as the lowest-risk option given the "cost + learning" goal and modest budget.
- Keep GitHub Actions as the sole orchestrator — no Azure-native scheduling service introduced.
- Static Web Apps (Free tier) was chosen first over a plain Storage static website: same ~$0 cost, but teaches a more distinct Azure service and needs less custom scripting. Reversed after provisioning failed — see amendment above — in favor of Storage static website, the only option this subscription's region policy actually allows.
- No one-way doors — the storage account is additive and free; nothing here is hard to reverse.

## Out of Scope

- Refactoring `jobspy-mcp` to remove its docker-exec dependency (considered during brainstorming, explicitly deferred).
- Moving Postgres to a managed Azure Database for PostgreSQL (considered, explicitly deferred to keep cost at $0 added).
- Moving orchestration off GitHub Actions to an Azure-native scheduler (considered, explicitly deferred).
- Resizing `scout-vm`'s SKU (discussed separately in this conversation; unrelated to this plan and not bundled in).

---
