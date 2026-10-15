// Container Apps environment + the web (SPA/nginx) and BFF apps.
//
// Ingress topology: the web app is external; the BFF is INTERNAL only and is
// reached via nginx inside the environment. That keeps the BFF and its client
// secret off the public internet, and removes CORS from the picture entirely.

param namePrefix string
param location string
param tags object

param logAnalyticsCustomerId string
@secure()
param logAnalyticsSharedKey string
param appInsightsConnectionString string

param acrLoginServer string
param acrName string
param webImage string
param bffImage string

// --- Entra / OBO ---
param aadTenantId string
param aadClientId string
@secure()
param aadClientSecret string
param aadApiScope string

// --- Foundry ---
param foundryProjectEndpoint string
param foundryAccountName string = ''
param foundryAgentName string = 'mortgage-renewal-concierge'
param mockMode bool = false
param bankName string = 'CFC Bank'

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${namePrefix}'
  location: location
  tags: tags
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

var acrPullRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, uami.id, acrPullRoleId)
  scope: acr
  properties: {
    principalId: uami.properties.principalId
    roleDefinitionId: acrPullRoleId
    principalType: 'ServicePrincipal'
  }
}

// Azure AI User on the Foundry account. Only used for the optional app-identity
// fallback and for health checks - user requests go through On-Behalf-Of.
resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = if (!empty(foundryAccountName)) {
  name: foundryAccountName
}
var azureAiUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
resource aiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(foundryAccountName)) {
  name: guid(foundryAccountName, uami.id, azureAiUserRoleId)
  scope: foundry
  properties: {
    principalId: uami.properties.principalId
    roleDefinitionId: azureAiUserRoleId
    principalType: 'ServicePrincipal'
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${namePrefix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsSharedKey
      }
    }
  }
}

// ---------------------------------------------------------------- BFF ----- //
resource bff 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${namePrefix}-bff'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uami.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        // Internal only. nginx in the web app proxies /api to it.
        external: false
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        { server: acrLoginServer, identity: uami.id }
      ]
      secrets: [
        { name: 'aad-client-secret', value: aadClientSecret }
      ]
    }
    template: {
      containers: [
        {
          name: 'bff'
          image: bffImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'AAD_TENANT_ID', value: aadTenantId }
            { name: 'AAD_CLIENT_ID', value: aadClientId }
            { name: 'AAD_CLIENT_SECRET', secretRef: 'aad-client-secret' }
            { name: 'AAD_API_SCOPE', value: aadApiScope }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
            { name: 'FOUNDRY_AGENT_NAME', value: foundryAgentName }
            { name: 'MOCK_MODE', value: string(mockMode) }
            { name: 'BANK_NAME', value: bankName }
            { name: 'AZURE_CLIENT_ID', value: uami.properties.clientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8000 }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}

// ---------------------------------------------------------------- web ----- //
resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${namePrefix}-web'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uami.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
        corsPolicy: {
          allowedOrigins: [ '*' ]
          allowedMethods: [ 'GET', 'POST', 'OPTIONS' ]
          allowedHeaders: [ '*' ]
        }
      }
      registries: [
        { server: acrLoginServer, identity: uami.id }
      ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: webImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            // Intra-environment call by app name over plain HTTP. Using the
            // internal HTTPS FQDN instead requires SNI configuration in nginx
            // (proxy_ssl_server_name) and otherwise fails the TLS handshake,
            // which surfaces as a 502 on every /api request.
            { name: 'BFF_URL', value: 'http://${bff.name}' }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}

output webFqdn string = web.properties.configuration.ingress.fqdn
output webUrl string = 'https://${web.properties.configuration.ingress.fqdn}'
output bffFqdn string = bff.properties.configuration.ingress.fqdn
output identityPrincipalId string = uami.properties.principalId
output identityClientId string = uami.properties.clientId
output environmentName string = env.name
