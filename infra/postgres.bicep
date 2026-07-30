targetScope = 'resourceGroup'

// Deliberately separate from main.bicep (the VM template), for the same reason
// dashboard.bicep is: redeploying main.bicep against an existing VM fails ARM's
// authorization check on osProfile.customData and aborts the whole deployment,
// including unrelated resources in the same template.
//
// This server is the always-on system of record for P6. It exists because the
// scout VM is deallocated ~23h/day, which made the data unreachable whenever
// anyone wanted to ask the system something (FR-CC-13).
//
// Cost, measured rather than assumed (spec Amendment A1): $24.57/month —
// $19.93 compute + $4.64 storage. The free B1ms allowance does NOT apply to
// this subscription, which is Azure for Students ($100 credit, not the Azure
// free account). The current pass runs this as a days-long evaluation and
// deletes it afterwards; the template stays committed so re-provisioning is a
// workflow dispatch rather than a redesign.

@description('Azure region. Must match the VM\'s region so per-query latency stays local, and must be one of this subscription\'s policy-allowed regions.')
param location string

@description('Globally-unique name for the PostgreSQL Flexible Server.')
param serverName string

@description('Compute SKU. Standard_B1ms at $0.02730/hr is the smallest Burstable shape; Standard_B2s is $0.10920/hr — four times the bill for a workload that runs a few minutes a day.')
param skuName string = 'Standard_B1ms'

@description('Provisioned storage in GiB. 32 is the minimum Flexible Server offers, and the whole database measured 12 MB, so this is floor-constrained rather than workload-constrained.')
param storageSizeGB int = 32

@description('PostgreSQL major version, pinned to match the pgvector/pgvector:pg16 container the data comes from so the migration is a copy rather than an upgrade. CI runs pg16 too.')
param postgresVersion string = '16'

@description('Administrator login name.')
param administratorLogin string = 'scoutadmin'

@secure()
@description('Administrator password, supplied at deploy time from the POSTGRES_ADMIN_PASSWORD environment variable (NFR-CC-7). Never stored in the .bicepparam file.')
param administratorLoginPassword string

@description('The scout VM\'s static public IP — the only address granted access in this phase. P7 decides its own connectivity.')
param allowedClientIp string

@description('Application database name. Matches the container\'s so the connection string differs only in host and credentials.')
param databaseName string = 'scout'

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: serverName
  location: location
  sku: {
    name: skuName
    tier: 'Burstable'
  }
  properties: {
    version: postgresVersion
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorLoginPassword
    storage: {
      storageSizeGB: storageSizeGB
      autoGrow: 'Disabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    // Public endpoint restricted by the firewall rule below. Networking mode is
    // fixed at creation time on Flexible Server, so choosing VNet integration
    // here would be irreversible for no present benefit: one VM today, one
    // Function later.
    network: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: server
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// pgvector is not available by default the way it is in the container image:
// it must be on the server's extension allow-list before `CREATE EXTENSION
// vector` — which scout/shared/schema.sql runs on every startup — can succeed.
// This is the step with no counterpart in the current setup, and it fails at
// exactly the point that looks like it should work.
resource vectorAllowList 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: server
  name: 'azure.extensions'
  properties: {
    value: 'VECTOR'
    source: 'user-override'
  }
  // The children are chained rather than deployed in parallel: Flexible Server
  // rejects concurrent writes to a server still settling a previous one.
  dependsOn: [database]
}

resource allowScoutVm 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: server
  name: 'allow-scout-vm'
  properties: {
    startIpAddress: allowedClientIp
    endIpAddress: allowedClientIp
  }
  dependsOn: [vectorAllowList]
}

output serverFqdn string = server.properties.fullyQualifiedDomainName
output databaseNameOut string = databaseName
output administratorLoginOut string = administratorLogin
