// privacy-scan: allow-dates: the dates below are Azure API versions, not calendar dates.
// Azure App Service (Linux) running the demo container on the cheapest tier that works.
// Deploy only after approval:
//   az group create --name <group> --location norwayeast
//   az deployment group create --resource-group <group> --template-file infra/main.bicep \
//     --parameters appName=<name> containerImage=<registry>/foretaksrisiko-demo:<tag>
// The app pulls the image with its own identity. Give that identity read access to the registry:
//   az role assignment create --assignee <principalId output> --role AcrPull --scope <registry id>

@description('Name of the web app, also used for the plan')
param appName string

@description('Container image with the demo, including registry and tag')
param containerImage string

@description('Azure region')
param location string = resourceGroup().location

@description('App Service plan SKU. F1 is free and sleeps when idle; B1 is the cheapest tier with always-on.')
param skuName string = 'F1'

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${appName}-plan'
  location: location
  kind: 'linux'
  sku: {
    name: skuName
  }
  properties: {
    reserved: true
  }
}

resource site 'Microsoft.Web/sites@2023-12-01' = {
  name: appName
  location: location
  kind: 'app,linux,container'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'DOCKER|${containerImage}'
      acrUseManagedIdentityCreds: true
      alwaysOn: skuName != 'F1'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        {
          name: 'WEBSITES_PORT'
          value: '8000'
        }
        {
          name: 'STREAMLIT_SERVER_HEADLESS'
          value: 'true'
        }
        {
          name: 'STREAMLIT_BROWSER_GATHER_USAGE_STATS'
          value: 'false'
        }
      ]
    }
  }
}

output url string = 'https://${site.properties.defaultHostName}'
output principalId string = site.identity.principalId
