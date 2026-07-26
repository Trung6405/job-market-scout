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

@description('Set true only when first-creating the VM, or deliberately recreating it from scratch. Azure rejects any osProfile.customData value on an update to an already-existing VM (write-once, unconditionally — resending even an unchanged value fails), so this must stay false for routine redeploys of unrelated resources (NSG rules, VM size, etc.) once the VM exists.')
param recreateVm bool = false

var subnetName = 'default'

resource nsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: '${vmName}-nsg'
  location: location
  properties: {
    securityRules: [
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
    ]
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
    // customData is omitted (not set to an empty/placeholder value) unless
    // recreateVm is true — see its @description. Omitting the property
    // entirely, rather than resending it, is what avoids the update error.
    osProfile: union({
      computerName: vmName
      adminUsername: adminUsername
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
    }, recreateVm ? {
      customData: loadFileAsBase64('cloud-init.yaml')
    } : {})
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

output publicIpAddress string = publicIp.properties.ipAddress
output sshCommand string = 'ssh ${adminUsername}@${publicIp.properties.ipAddress}'
