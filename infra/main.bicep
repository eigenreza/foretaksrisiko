// privacy-scan: allow-dates: the dates below are Azure API versions, not calendar dates.
// Azure App Service (Linux) running the demo container on the free F1 plan.
// The image is public on Docker Hub, so the app pulls it without a login and without a registry.
// Deploy only after approval:
//   az group create --name <group> --location norwayeast
//   az deployment group create --resource-group <group> --template-file infra/main.bicep \
//     --parameters appName=<name> containerImage=docker.io/<user>/foretaksrisiko-demo:<tag>
// The command asks for groqApiKey, the key for the assistant page. Leave it empty to run the
// demo with the assistant switched off. The key is stored only as an app setting.

@description('Name of the web app, also used for the plan')
param appName string

@description('Public container image with the demo, including registry and tag')
param containerImage string

@description('Azure region')
param location string = resourceGroup().location

@description('App Service plan SKU. F1 is free and sleeps when idle; B1 is the cheapest tier with always-on.')
param skuName string = 'F1'

@secure()
@description('Key for the assistant page at Groq. Empty switches the assistant off.')
param groqApiKey string = ''

var baseSettings = [
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
var keySettings = empty(groqApiKey) ? [] : [
  {
    name: 'GROQ_API_KEY'
    value: groqApiKey
  }
]

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
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'DOCKER|${containerImage}'
      alwaysOn: skuName != 'F1'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: concat(baseSettings, keySettings)
    }
  }
}

output url string = 'https://${site.properties.defaultHostName}'
