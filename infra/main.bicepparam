using './main.bicep'

param location = 'australiaeast'
param vmName = 'scout-vm'
param vmSize = 'Standard_B2s'
param adminUsername = 'azureuser'
param adminSshPublicKey = 'ssh-rsa AAAA...REPLACE_WITH_YOUR_PUBLIC_KEY'
param sshSourceAddressPrefix = '*'
