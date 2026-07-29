using './postgres.bicep'

param location = 'newzealandnorth'
param serverName = 'trung6405-scout-pg'
// Read from the environment, never committed. The password is a secret
// (NFR-CC-7); the client IP is already the VM_HOST Actions variable, so reading
// it here keeps the firewall rule from drifting out of sync with the address
// the deploy actually connects to. Neither has a default, so a missing value
// fails the deployment loudly rather than provisioning a server with an empty
// password or a wide-open rule.
param administratorLoginPassword = readEnvironmentVariable('POSTGRES_ADMIN_PASSWORD')
param allowedClientIp = readEnvironmentVariable('VM_HOST')
