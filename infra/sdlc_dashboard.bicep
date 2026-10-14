// Answer scorer: the delivery evidence workbook (S9, spec section 2 in
// intent/s9-delivery-evidence/).
//
// Deployed on its own into the existing resource group, never through main.bicep and
// never with azd:
//
//   az deployment group create --resource-group <group> --template-file infra/sdlc_dashboard.bicep
//     --parameters applicationInsightsName=<name>
//
// It creates one workbook and nothing else. Application Insights is only referenced, so
// that the live tiles can read it. The layout and the queries are in sdlc_workbook.json,
// which scripts/build_sdlc_workbook.py makes from dashboards/sdlc_snapshot.json and
// dashboards/queries.kql; a unit test keeps the three in step.
targetScope = 'resourceGroup'

@description('Name of the existing Application Insights resource in this resource group. The workbook is bound to it here, so no resource ID is written in any file.')
@minLength(1)
param applicationInsightsName string

@description('Region for the workbook.')
param location string = resourceGroup().location

@description('Value of the owner tag: the public GitHub handle, never an email address.')
param ownerTag string = 'ranaidrees'

@description('Title of the workbook in the portal.')
param workbookDisplayName string = 'Answer scorer: delivery evidence'

var tags = {
  project: 'answer-scorer'
  env: 'demo'
  owner: ownerTag
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

// The file holds the layout and the queries only. The resource it reads from is added
// here, at deployment time.
var workbookContent = union(json(loadTextContent('sdlc_workbook.json')), {
  fallbackResourceIds: [
    applicationInsights.id
  ]
})

resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  // A workbook's resource name must be a GUID. This one is stable for the resource group
  // and differs from the operational dashboard's.
  name: guid(resourceGroup().id, 'answer-scorer-delivery-evidence')
  location: location
  tags: tags
  kind: 'shared'
  properties: {
    displayName: workbookDisplayName
    description: 'Trust scorecard of the answer scorer (guards, offline and online evaluation, golden dataset), then how it was delivered: gates before production, deploys and the live service, and the AI-native SDLC. GitHub figures are a snapshot refreshed by a pull request.'
    category: 'workbook'
    sourceId: applicationInsights.id
    version: 'Notebook/1.0'
    serializedData: string(workbookContent)
  }
}

// The name only: no resource ID leaves this file.
output workbookDisplayName string = workbook.properties.displayName
