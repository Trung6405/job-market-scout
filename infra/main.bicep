targetScope = 'resourceGroup'

@description('Azure region for all resources, e.g. australiaeast.')
param location string

@description('Name of the virtual machine and prefix for its network resources.')
param vmName string = 'scout-vm'

@description('VM size. Standard_B2s (2 vCPU, 4 GiB) is enough to build and run the compose stack.')
param vmSize string = 'Standard_B2s'

@description('Admin (login) username for the VM.')
param adminUsername string = 'azureuser'

@description('SSH public key granted login access. Public key only, never the private key.')
param adminSshPublicKey string

@description('Source CIDR/IP allowed to reach SSH (port 22). Default * relies on key-only auth; narrow this to harden.')
param sshSourceAddressPrefix string = '*'

@description('Source CIDR/IP allowed to reach HTTP (port 80) — the hello smoke-test page. Set to a narrow range or "" to disable public web access.')
param httpSourceAddressPrefix string = '*'

@description('Globally-unique name for the Storage Account that hosts the dashboard via static website hosting.')
param dashboardStorageAccountName string = 'trung6405scoutdash'

@description('Object ID of the GitHub Actions service principal (job-market-scout-gha). Granted Storage Blob Data Contributor on the dashboard storage account so scheduled-run.yml can upload via its existing OIDC login instead of a stored account key.')
param ciServicePrincipalObjectId string = '93ac8a65-a658-4f39-90b3-538ebedba216'

var subnetName = 'default'

resource nsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: '${vmName}-nsg'
  location: location
  properties: {
    securityRules: concat([
      {
        name: 'allow-ssh'
        properties: {
          priority: 1000
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '22'
          sourceAddressPrefix: sshSourceAddressPrefix
          destinationAddressPrefix: '*'
        }
      }
    ], empty(httpSourceAddressPrefix) ? [] : [
      {
        name: 'allow-http'
        properties: {
          priority: 1010
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '80'
          sourceAddressPrefix: httpSourceAddressPrefix
          destinationAddressPrefix: '*'
        }
      }
    ])
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: '${vmName}-vnet'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: ['10.0.0.0/16']
    }
    subnets: [
      {
        name: subnetName
        properties: {
          addressPrefix: '10.0.0.0/24'
        }
      }
    ]
  }
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2023-11-01' = {
  name: '${vmName}-pip'
  location: location
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

resource nic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: '${vmName}-nic'
  location: location
  properties: {
    networkSecurityGroup: {
      id: nsg.id
    }
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: {
            id: '${vnet.id}/subnets/${subnetName}'
          }
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: {
            id: publicIp.id
          }
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-03-01' = {
  name: vmName
  location: location
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    osProfile: {
      computerName: vmName
      adminUsername: adminUsername
      customData: loadFileAsBase64('cloud-init.yaml')
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: adminSshPublicKey
            }
          ]
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: '0001-com-ubuntu-server-jammy'
        sku: '22_04-lts-gen2'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nic.id
        }
      ]
    }
  }
}

// Serves the reports dashboard (reports/ + hello/) independent of the VM's
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

resource dashboardStorageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(dashboardStorage.id, ciServicePrincipalObjectId, 'StorageBlobDataContributor')
  scope: dashboardStorage
  properties: {
    // Built-in "Storage Blob Data Contributor" role.
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: ciServicePrincipalObjectId
    principalType: 'ServicePrincipal'
  }
}

output publicIpAddress string = publicIp.properties.ipAddress
output sshCommand string = 'ssh ${adminUsername}@${publicIp.properties.ipAddress}'
output dashboardStorageAccountNameOut string = dashboardStorage.name
output dashboardWebEndpoint string = dashboardStorage.properties.primaryEndpoints.web
