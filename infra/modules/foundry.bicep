// Foundry resource, one project, one pinned model deployment, the Application
// Insights connection and the two inference role assignments.

@description('Foundry resource name. Also its custom subdomain, so it must be unique across Azure.')
param accountName string

@description('Foundry project name.')
param projectName string

@description('Region.')
param location string

@description('Tags for the resource, the project and the deployment.')
param tags object

@description('Model deployment name.')
param modelDeploymentName string

@description('Model name.')
param modelName string

@description('Pinned model version.')
param modelVersion string

@description('Deployment capacity, in thousands of tokens per minute.')
param modelCapacity int

@description('Application Insights resource in this resource group to connect to the project.')
param applicationInsightsName string

@description('Principal ID of the identity the Container App runs as.')
param appIdentityPrincipalId string

@description('Object ID of the signed-in user. Empty skips the assignment.')
param ownerPrincipalId string = ''

// Built-in role "Cognitive Services OpenAI User": the narrowest role that can call
// the /openai/v1 endpoint. This is a public role definition ID, the same in every tenant.
var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    // Keyless only: with local auth off there are no keys to leak.
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Answer scorer'
    description: 'AI answer scorer with a trust harness. Synthetic data only.'
  }
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: modelDeploymentName
  tags: tags
  sku: {
    name: 'GlobalStandard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
    // Pinned: the version never changes under the evals.
    versionUpgradeOption: 'NoAutoUpgrade'
    // The default guardrail, bound by name so it is visible as code.
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  // The resource accepts one child operation at a time: creating the project and
  // the deployment side by side fails with RequestConflict.
  dependsOn: [
    project
  ]
}

// One Application Insights connection per project. The "key" is the connection
// string, which Azure Monitor does not treat as a credential; it is resolved at
// deployment time and never written to a file.
resource applicationInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: applicationInsightsName
  properties: {
    category: 'AppInsights'
    target: applicationInsights.id
    authType: 'ApiKey'
    credentials: {
      key: applicationInsights.properties.ConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: applicationInsights.id
    }
  }
  dependsOn: [
    deployment
  ]
}

resource appIdentityOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, appIdentityPrincipalId, openAiUserRoleId)
  properties: {
    principalId: appIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRoleId)
  }
}

// An Owner role on the subscription carries no data actions, so the signed-in
// user needs the inference role as well for local runs and live evals.
resource ownerOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(ownerPrincipalId)) {
  scope: account
  name: guid(account.id, ownerPrincipalId, openAiUserRoleId)
  properties: {
    principalId: ownerPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRoleId)
  }
}

// The endpoint as scheme and host only (no trailing slash), so callers can
// append /openai/v1/.
output endpoint string = 'https://${split(account.properties.endpoint, '/')[2]}'
output accountName string = account.name
output projectName string = project.name
