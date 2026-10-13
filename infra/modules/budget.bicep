// Budget on the resource group. It warns by email; it does not cap spend.

@description('Budget name.')
param name string

@description('Amount for the whole period, in the billing currency.')
param amount int

@description('First day of the budget period. Must be the first day of a month.')
param startDate string

@description('Address that receives the notifications.')
param contactEmail string

var thresholds = [
  50
  80
  100
]

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: name
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Annually'
    timePeriod: {
      startDate: startDate
    }
    notifications: toObject(thresholds, threshold => 'actual${threshold}', threshold => {
      enabled: true
      operator: 'GreaterThanOrEqualTo'
      threshold: threshold
      thresholdType: 'Actual'
      contactEmails: [
        contactEmail
      ]
    })
  }
}
