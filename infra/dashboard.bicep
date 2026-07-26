targetScope = 'resourceGroup'

// Deliberately separate from main.bicep (the VM template): redeploying
// main.bicep against an already-existing VM fails ARM's authorization check
// on osProfile.customData (immutable once the VM exists), which aborts the
// *entire* deployment — including unrelated resources in the same template.
// Splitting this out means dashboard changes never depend on the VM
// template being redeployable.

@description('Azure region for the dashboard storage account. Must be one of this subscription\'s policy-allowed regions.')
param location string

@description('Globally-unique name for the Storage Account that hosts the dashboard via static website hosting.')
param dashboardStorageAccountName string = 'trung6405scoutdash'

// Serves the reports dashboard (reports/) independent of the VM's
// start/deallocate cycle, so it's reachable even while scout-vm is off.
// Static website hosting itself (the $web container, index/error docs) is a
// data-plane setting with no ARM property, so it's enabled by an `az
// storage blob service-properties update --static-website` call in
// infra-provision.yml after this deploys. Content is pushed by
// scheduled-run.yml via `az storage blob upload-batch` using the same OIDC
// login already set up there — no separate deploy-token secret needed.
//
// Azure Static Web Apps was tried first but isn't available in any region
// this subscription's policy allows (indonesiacentral, japanwest, japaneast,
// malaysiawest, newzealandnorth) — Storage Accounts are, so this uses plain
// blob static-website hosting instead.
resource dashboardStorage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: dashboardStorageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: true
    minimumTlsVersion: 'TLS1_2'
  }
}

// NOT provisioned here: the CI service principal only holds Contributor on
// this resource group, which can't grant RBAC roles (needs User Access
// Administrator/Owner) — and ARM authorization-checks every resource in a
// template upfront, so including a roleAssignment resource the deployer
// can't authorize aborts the *entire* deployment, not just that resource.
// Granted once, out of band, by an account with elevated rights:
//   az role assignment create --assignee-object-id 93ac8a65-a658-4f39-90b3-538ebedba216 \
//     --assignee-principal-type ServicePrincipal \
//     --role "Storage Blob Data Contributor" --scope <dashboardStorage resource ID>

output dashboardStorageAccountNameOut string = dashboardStorage.name
output dashboardWebEndpoint string = dashboardStorage.properties.primaryEndpoints.web
