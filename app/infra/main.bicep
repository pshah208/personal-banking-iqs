// =============================================================================
// Mortgage Renewal Concierge - frontend delivery app
// =============================================================================
// SYNTHETIC DEMO DATA. CFC Bank is a branding label only.
//
// Deploys into rg-scotia-iqs alongside the existing Foundry account/project:
//
//   * Container Registry
//   * Log Analytics + Application Insights
//   * Container Apps environment
//   * ca-<prefix>-bff   FastAPI, INTERNAL ingress, performs the OBO exchange
//   * ca-<prefix>-web   nginx + React SPA, EXTERNAL ingress, proxies /api -> bff
//
// The two Entra app registrations are NOT ARM resources - create them first with
//   python infra/provision_app_registrations.py
// and pass the resulting ids/secret in as parameters.
// =============================================================================

targetScope = 'resourceGroup'

@description('Base name used in resource names.')
param namePrefix string = 'mrc'

@description('Azure region.')
param location string = resourceGroup().location

@description('Extra tags merged onto every resource.')
param extraTags object = {}

@description('Container image for the SPA. Placeholder until the first build+push.')
param webImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Container image for the BFF.')
param bffImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

// --- Entra (from provision_app_registrations.py) ---
@description('Tenant id.')
param aadTenantId string = subscription().tenantId

@description('BFF app registration client id.')
param aadClientId string

@description('BFF client secret.')
@secure()
param aadClientSecret string

@description('API scope the SPA requests, e.g. api://<bff-client-id>/access_as_user')
param aadApiScope string

// --- Foundry ---
@description('Foundry project endpoint the agent lives in.')
param foundryProjectEndpoint string

@description('Foundry account name, for the role assignment. Blank to skip.')
param foundryAccountName string = ''

@description('Agent name to invoke.')
param foundryAgentName string = 'mortgage-renewal-concierge'

@description('Run the BFF without Azure calls. UI development only.')
param mockMode bool = false

@description('Display name of the bank this deployment is branded as (see tools/brand/fetch_brand.py).')
param bankName string = 'CFC Bank'

@description('Simulated card-processor profile shown in the Cards book (labels and API shape only).')
@allowed([ 'generic', 'tsys', 'fiserv', 'globalpayments' ])
param cardProcessor string = 'generic'

@description('Eventhouse query URI for the live card-processor stream (deploy_realtime.py). Empty = live panel off.')
param processorKqlUri string = ''

@description('KQL database holding the auth_stream table.')
param processorKqlDb string = ''

var tags = union({
  workload: namePrefix
  solution: 'mortgage-renewal-concierge'
  component: 'frontend'
  dataClassification: 'synthetic-demo-data'
  managedBy: 'bicep'
}, extraTags)

module observability 'modules/observability.bicep' = {
  name: 'observability'
  params: { namePrefix: namePrefix, location: location, tags: tags }
}

module registry 'modules/registry.bicep' = {
  name: 'registry'
  params: { namePrefix: namePrefix, location: location, tags: tags }
}

module apps 'modules/container-apps.bicep' = {
  name: 'container-apps'
  params: {
    namePrefix: namePrefix
    location: location
    tags: tags
    logAnalyticsCustomerId: observability.outputs.customerId
    logAnalyticsSharedKey: observability.outputs.sharedKey
    appInsightsConnectionString: observability.outputs.connectionString
    acrLoginServer: registry.outputs.loginServer
    acrName: registry.outputs.name
    webImage: webImage
    bffImage: bffImage
    aadTenantId: aadTenantId
    aadClientId: aadClientId
    aadClientSecret: aadClientSecret
    aadApiScope: aadApiScope
    foundryProjectEndpoint: foundryProjectEndpoint
    foundryAccountName: foundryAccountName
    foundryAgentName: foundryAgentName
    mockMode: mockMode
    bankName: bankName
    cardProcessor: cardProcessor
    processorKqlUri: processorKqlUri
    processorKqlDb: processorKqlDb
  }
}

output acrName string = registry.outputs.name
output acrLoginServer string = registry.outputs.loginServer
output webUrl string = apps.outputs.webUrl
output webFqdn string = apps.outputs.webFqdn
output bffFqdn string = apps.outputs.bffFqdn
output identityPrincipalId string = apps.outputs.identityPrincipalId

@description('Add this to the SPA app registration as a redirect URI.')
output redirectUriToAdd string = apps.outputs.webUrl
