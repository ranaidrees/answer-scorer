// Answer scorer: the dashboard and the alerts (spec section 8).
//
// Deployed on its own into the existing resource group, never through main.bicep and
// never with azd:
//
//   az deployment group create --resource-group <group> --template-file infra/observability.bicep
//     --parameters applicationInsightsName=<name> alertEmail=<address>
//
// It creates a workbook, an action group with one email receiver and two log alert
// rules. It changes nothing that main.bicep created: Application Insights is only
// referenced. The queries are kept in dashboards/queries.kql; the workbook file and the
// two alert queries below hold the same text, and a unit test keeps them in step.
targetScope = 'resourceGroup'

@description('Name of the existing Application Insights resource in this resource group. The workbook and both alert rules are bound to it here, so no resource ID is written in any file.')
@minLength(1)
param applicationInsightsName string

@minLength(1)
@secure()
@description('Address that receives the alert emails. Given at deployment time and never written to a tracked file. Marked secure so that it is not kept in the deployment history.')
param alertEmail string

@description('Region for the workbook and the alert rules.')
param location string = resourceGroup().location

@description('Value of the owner tag: the public GitHub handle, never an email address.')
param ownerTag string = 'ranaidrees'

@description('Title of the workbook in the portal.')
param workbookDisplayName string = 'Answer scorer dashboard'

var tags = {
  project: 'answer-scorer'
  env: 'demo'
  owner: ownerTag
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

// --- Workbook ------------------------------------------------------------------------------

// The file holds the layout and the queries only. The resource it reads from is added
// here, at deployment time.
var workbookContent = union(json(loadTextContent('workbook.json')), {
  fallbackResourceIds: [
    applicationInsights.id
  ]
})

resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  // A workbook's resource name must be a GUID. This one is stable for the resource group.
  name: guid(resourceGroup().id, 'answer-scorer-dashboard')
  location: location
  tags: tags
  kind: 'shared'
  properties: {
    displayName: workbookDisplayName
    description: 'Requests and latency, human-review rate by reason, tokens and estimated cost, and eval results per run. Metadata only: no candidate text.'
    category: 'workbook'
    sourceId: applicationInsights.id
    version: 'Notebook/1.0'
    serializedData: string(workbookContent)
  }
}

// --- Action group --------------------------------------------------------------------------

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-answer-scorer-email'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'scorer-demo'
    enabled: true
    emailReceivers: [
      {
        name: 'owner'
        emailAddress: alertEmail
        useCommonAlertSchema: true
      }
    ]
  }
}

// --- Alert rules ---------------------------------------------------------------------------

// Both rules fire when their query returns a row, and each query returns a row only when
// the SLO is breached. A window with no requests returns no row, so neither rule can fire
// on no data. Both run at the cheapest evaluation frequency that still matches the window
// in the spec, because a log alert rule is charged per month by how often it runs.

// Same text as `alert_latency_p95` in dashboards/queries.kql.
var latencyQuery = '''
requests
| where name == "POST /api/score" and toint(resultCode) == 200
| summarize completed_requests = count(), p95_ms = percentile(duration, 95)
| where completed_requests >= 5 and p95_ms > 6000
'''

// Same text as `alert_availability` in dashboards/queries.kql.
var availabilityQuery = '''
requests
| where name == "POST /api/score"
| extend status = toint(resultCode)
| where status < 400 or status >= 500
| summarize counted_requests = count(), failures_5xx = countif(status >= 500)
| where counted_requests > 0
| extend availability = 100.0 * (counted_requests - failures_5xx) / counted_requests
| where availability < 99.0
| project counted_requests, failures_5xx, availability_pct = round(availability, 2)
'''

resource latencyAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: 'alert-answer-scorer-latency-p95'
  location: location
  tags: tags
  kind: 'LogAlert'
  properties: {
    displayName: 'Answer scorer: p95 latency over 6 s for 15 minutes'
    description: 'SLO: p95 latency at or under 6 s. Fires when the p95 of completed requests to POST /api/score over 15 minutes is over 6 s, with at least five completed requests in the window. Never fires on no data.'
    enabled: true
    severity: 2
    scopes: [
      applicationInsights.id
    ]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT15M'
    criteria: {
      allOf: [
        {
          query: latencyQuery
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: true
    actions: {
      actionGroups: [
        actionGroup.id
      ]
    }
  }
}

resource availabilityAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: 'alert-answer-scorer-availability'
  location: location
  tags: tags
  kind: 'LogAlert'
  properties: {
    displayName: 'Answer scorer: availability under 99% over 1 hour'
    description: 'SLO: 99% of non-4xx requests succeed. Fires when fewer than 99% of the non-4xx requests to POST /api/score over 1 hour succeeded. Never fires on no data.'
    enabled: true
    severity: 1
    scopes: [
      applicationInsights.id
    ]
    evaluationFrequency: 'PT1H'
    windowSize: 'PT1H'
    criteria: {
      allOf: [
        {
          query: availabilityQuery
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    autoMitigate: true
    actions: {
      actionGroups: [
        actionGroup.id
      ]
    }
  }
}

// Names only: no resource ID and no address leaves this file.
output workbookDisplayName string = workbook.properties.displayName
output actionGroupName string = actionGroup.name
output latencyAlertName string = latencyAlert.name
output availabilityAlertName string = availabilityAlert.name
