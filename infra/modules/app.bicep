// Container Apps environment and the application, started on a placeholder image.
// The deploy workflow later swaps in the real image, port 8000 and the probes.

@description('Container Apps environment name.')
param environmentName string

@description('Container App name.')
param appName string

@description('Region.')
param location string

@description('Tags for both resources.')
param tags object

@description('Log Analytics workspace in this resource group that receives the container logs.')
param workspaceName string

@description('Resource ID of the user-assigned identity the app runs as.')
param identityId string

@description('Client ID of that identity, so DefaultAzureCredential picks it.')
param identityClientId string

@description('Container image.')
param image string

@description('Port the image listens on. The placeholder image serves on 80.')
param targetPort int = 80

@description('Foundry endpoint without a trailing slash.')
param foundryEndpoint string

@description('Model deployment name.')
param modelDeploymentName string

@description('Pinned model version.')
param modelVersion string

@description('Application Insights connection string. Azure Monitor does not treat it as a credential.')
param applicationInsightsConnectionString string

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

// Consumption profile only: pay per use, scale to zero, no fixed charge.
resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: targetPort
        transport: 'auto'
        // HTTPS only: plain HTTP requests are redirected.
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'app'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          // Non-secret settings only. The demo token and the hash salt are added
          // after provisioning as Container App secrets, by scripts/setup_env_local.py.
          env: [
            {
              name: 'FOUNDRY_ENDPOINT'
              value: foundryEndpoint
            }
            {
              name: 'MODEL_DEPLOYMENT'
              value: modelDeploymentName
            }
            {
              name: 'MODEL_VERSION'
              value: modelVersion
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: identityClientId
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: applicationInsightsConnectionString
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 2
      }
    }
  }
}

output name string = app.name
output fqdn string = app.properties.configuration.ingress.fqdn
