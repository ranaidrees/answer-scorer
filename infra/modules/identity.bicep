// User-assigned identity the Container App runs as. It is created on its own so the
// Foundry role assignment does not have to wait for the app.

@description('Identity name.')
param name string

@description('Region.')
param location string

@description('Tags for the identity.')
param tags object

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
  tags: tags
}

output id string = identity.id
output principalId string = identity.properties.principalId
output clientId string = identity.properties.clientId
