// Answer scorer: everything the demo needs, in one resource group.
//
// Provisioned once with `azd provision` in slice S1. After the first application
// deploy this file is never provisioned again, because it would put the placeholder
// image and port back on the Container App. The workbook, action group and alert
// rules live in a separate file that a later slice deploys on its own.
targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('azd environment name. The resource group is named rg-<environmentName>.')
param environmentName string

@minLength(1)
@description('Region for every resource.')
param location string

@description('Object ID of the signed-in user, who gets the inference role for local runs and live evals. azd fills it in.')
param principalId string = ''

@description('Address for the budget notifications. Comes from the azd environment and is never written to a tracked file.')
param alertEmail string

@description('Value of the owner tag: the public GitHub handle, never an email address.')
param ownerTag string = 'ranaidrees'

@description('Model deployment name. The application refers to the model by this name.')
param modelDeploymentName string = 'scorer-mini'

@description('Model name.')
param modelName string = 'gpt-5.4-mini'

@description('Pinned model version.')
param modelVersion string = '2026-03-17'

@minValue(1)
@description('Deployment capacity, in thousands of tokens per minute.')
param modelCapacity int = 100

@minValue(1)
@description('Budget for the resource group, in the billing currency.')
param budgetAmount int = 10

@description('First day of the budget period. Must be the first day of a month.')
param budgetStartDate string = '2026-10-01'

@description('Image the Container App starts with. The deploy workflow replaces it.')
param placeholderImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

var tags = {
  project: 'answer-scorer'
  env: 'demo'
  owner: ownerTag
  'azd-env-name': environmentName
}

// Short, stable suffix for the names that must be unique across Azure.
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module identity 'modules/identity.bicep' = {
  name: 'identity'
  scope: resourceGroup
  params: {
    name: 'id-app'
    location: location
    tags: tags
  }
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: resourceGroup
  params: {
    workspaceName: 'log-answer-scorer-${resourceToken}'
    applicationInsightsName: 'appi-answer-scorer-${resourceToken}'
    location: location
    tags: tags
  }
}

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  scope: resourceGroup
  params: {
    accountName: 'aif-answer-scorer-${resourceToken}'
    projectName: 'proj-answer-scorer'
    location: location
    tags: tags
    modelDeploymentName: modelDeploymentName
    modelName: modelName
    modelVersion: modelVersion
    modelCapacity: modelCapacity
    applicationInsightsName: monitoring.outputs.applicationInsightsName
    appIdentityPrincipalId: identity.outputs.principalId
    ownerPrincipalId: principalId
  }
}

module app 'modules/app.bicep' = {
  name: 'app'
  scope: resourceGroup
  params: {
    environmentName: 'cae-answer-scorer-${resourceToken}'
    appName: 'ca-answer-scorer'
    location: location
    tags: tags
    workspaceName: monitoring.outputs.workspaceName
    identityId: identity.outputs.id
    identityClientId: identity.outputs.clientId
    image: placeholderImage
    foundryEndpoint: foundry.outputs.endpoint
    modelDeploymentName: modelDeploymentName
    modelVersion: modelVersion
    applicationInsightsConnectionString: monitoring.outputs.applicationInsightsConnectionString
  }
}

module budget 'modules/budget.bicep' = {
  name: 'budget'
  scope: resourceGroup
  params: {
    name: 'budget-${environmentName}'
    amount: budgetAmount
    startDate: budgetStartDate
    contactEmail: alertEmail
  }
}

// azd writes these to its environment. None of them is a credential, but the
// identifiers still stay out of tracked files.
output AZURE_RESOURCE_GROUP string = resourceGroup.name
output FOUNDRY_ENDPOINT string = foundry.outputs.endpoint
output FOUNDRY_ACCOUNT_NAME string = foundry.outputs.accountName
output FOUNDRY_PROJECT_NAME string = foundry.outputs.projectName
output MODEL_DEPLOYMENT string = modelDeploymentName
output MODEL_VERSION string = modelVersion
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.applicationInsightsConnectionString
output APPLICATIONINSIGHTS_NAME string = monitoring.outputs.applicationInsightsName
output LOG_ANALYTICS_WORKSPACE_NAME string = monitoring.outputs.workspaceName
output CONTAINER_APP_NAME string = app.outputs.name
output CONTAINER_APP_FQDN string = app.outputs.fqdn
output APP_IDENTITY_CLIENT_ID string = identity.outputs.clientId
