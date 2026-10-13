// Log Analytics workspace and workspace-based Application Insights.

@description('Log Analytics workspace name.')
param workspaceName string

@description('Application Insights name.')
param applicationInsightsName string

@description('Region.')
param location string

@description('Tags for both resources.')
param tags object

@description('Days of retention. 30 is the shortest the pay-per-use tier offers and carries no retention charge.')
param retentionInDays int = 30

@description('Daily ingestion cap in GB, as a string because Bicep has no decimal literal. A spend control: ingestion stops for the day once the cap is reached.')
param dailyQuotaGb string = '0.1'

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
    workspaceCapping: {
      dailyQuotaGb: json(dailyQuotaGb)
    }
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: applicationInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
  }
}

output workspaceName string = workspace.name
output applicationInsightsName string = applicationInsights.name
output applicationInsightsConnectionString string = applicationInsights.properties.ConnectionString
