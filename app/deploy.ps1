<#
.SYNOPSIS
    Build, push and deploy the Mortgage Renewal Concierge web app.

.DESCRIPTION
    Order matters here:

      1. Bicep      registry, observability, Container Apps env, both apps
                    (first pass uses placeholder images)
      2. Build+push web and BFF images to the new ACR
      3. Update both container apps to the real images
      4. Print the SPA redirect URI to register

    The Entra app registrations are NOT created here - run
    infra/provision_app_registrations.py first and pass the values in.

.EXAMPLE
    # one-time
    python infra\provision_app_registrations.py --spa-redirect http://localhost:5173

    .\deploy.ps1 -ResourceGroup rg-mtgrenewal-dev-eastus-001 `
                 -AadClientId <bff-client-id> `
                 -AadClientSecret <secret> `
                 -AadApiScope api://<bff-client-id>/access_as_user

    .\deploy.ps1 -ResourceGroup rg-mtgrenewal-dev-eastus-001 -Only images   # rebuild + redeploy code only

    The Foundry endpoint and account default to the outputs of the root
    deploy.ps1 (deployment 'main' in the same resource group). The web image
    carries whatever brand pack app/src/web/public/brand/brands.json selects -
    run ..\deploy.ps1 -Only brand -Bank "<bank name>" first to change it.
#>

[CmdletBinding()]
param(
    [string]$ResourceGroup = $(if ($env:MRC_RESOURCE_GROUP) { $env:MRC_RESOURCE_GROUP } else { 'rg-mtgrenewal-dev-eastus-001' }),
    [string]$NamePrefix = 'mrc',
    # The reference estate runs the app tier in eastus2, not the eastus of the
    # Foundry tier - Container Apps quota was unavailable in eastus at the time.
    [string]$Location = 'eastus2',

    [string]$AadClientId,
    [string]$AadClientSecret,
    [string]$AadApiScope,
    [string]$AadTenantId,

    [string]$FoundryProjectEndpoint,
    [string]$FoundryAccountName,
    [string]$FoundryAgentName = 'mortgage-renewal-concierge',
    [string]$BankName,
    [ValidateSet('generic', 'tsys', 'fiserv', 'globalpayments')]
    [string]$CardProcessor = 'generic',

    [ValidateSet('infra', 'images', 'all')]
    [string]$Only = 'all',
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $root

function Stage($n, $t) {
    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor Cyan
    Write-Host " $n. $t" -ForegroundColor Cyan
    Write-Host ('=' * 72) -ForegroundColor Cyan
}

# `az acr build` streams the remote build log through colorama, which throws
# UnicodeEncodeError on a cp1252 console the moment the log contains a check
# mark. That kills the CLI with a non-zero exit code *after* the image has been
# built and pushed, so `--no-logs` is passed on every build below to keep the
# stream off the console entirely. Trusting $LASTEXITCODE would still abort on
# healthy builds, so confirm the outcome by asking the registry whether the tag
# arrived.
function Assert-ImagePushed($registry, $repository, $tag) {
    $exit = $LASTEXITCODE
    $tags = az acr repository show-tags -n $registry --repository $repository -o tsv 2>$null
    if ($tags -notcontains $tag) {
        throw "$repository image build failed - tag $tag is not in the registry."
    }
    if ($exit -ne 0) {
        Write-Host "   (CLI exited $exit but ${repository}:$tag was pushed - continuing)" `
            -ForegroundColor DarkGray
    }
}

try {
    $acct = az account show --query "{sub:name,user:user.name}" -o json | ConvertFrom-Json
    if (-not $acct) { throw 'Not logged in. Run: az login' }
    Write-Host "subscription : $($acct.sub)"
    Write-Host "identity     : $($acct.user)"
    Write-Host "resource grp : $ResourceGroup"

    if (-not $AadTenantId) { $AadTenantId = az account show --query tenantId -o tsv }

    if (-not ($FoundryProjectEndpoint -and $FoundryAccountName)) {
        $core = az deployment group show -g $ResourceGroup -n main `
            --query properties.outputs -o json 2>$null | ConvertFrom-Json
        if ($core) {
            if (-not $FoundryProjectEndpoint) { $FoundryProjectEndpoint = $core.foundryProjectEndpoint.value }
            if (-not $FoundryAccountName)     { $FoundryAccountName     = $core.foundryAccountName.value }
        }
    }
    if (-not $BankName) {
        $BankName = (python (Join-Path $root '..\tools\brand\bank_profile.py') | ConvertFrom-Json).name
    }
    Write-Host "bank         : $BankName"
    Write-Host "foundry      : $FoundryProjectEndpoint"

    # ------------------------------------------------------------- infra ---
    if ($Only -in @('infra', 'all')) {
        Stage 1 'Azure infrastructure (Bicep)'
        if (-not ($AadClientId -and $AadClientSecret -and $AadApiScope)) {
            throw @'
Missing Entra parameters. Create the app registrations first:

    python infra\provision_app_registrations.py --spa-redirect http://localhost:5173

then pass -AadClientId, -AadClientSecret and -AadApiScope.
'@
        }
        if (-not $FoundryProjectEndpoint) {
            throw 'Foundry project endpoint unknown - run the root deploy.ps1 first, or pass -FoundryProjectEndpoint.'
        }

        $verb = $WhatIf ? 'what-if' : 'create'
        az deployment group $verb `
            -g $ResourceGroup `
            -n mrc-app `
            --template-file infra/main.bicep `
            --parameters `
                namePrefix=$NamePrefix `
                location=$Location `
                aadTenantId=$AadTenantId `
                aadClientId=$AadClientId `
                aadClientSecret=$AadClientSecret `
                aadApiScope=$AadApiScope `
                foundryProjectEndpoint=$FoundryProjectEndpoint `
                foundryAccountName=$FoundryAccountName `
                foundryAgentName=$FoundryAgentName `
                bankName=$BankName `
                cardProcessor=$CardProcessor `
            -o table
        if ($LASTEXITCODE -ne 0) { throw 'Bicep deployment failed.' }
        if ($WhatIf) { Write-Host "`nwhat-if only." -ForegroundColor Yellow; return }
    }

    $out = az deployment group show -g $ResourceGroup -n mrc-app `
        --query properties.outputs -o json | ConvertFrom-Json
    if (-not $out) { throw "Deployment 'mrc-app' not found. Run with -Only infra first." }

    $acr = $out.acrName.value
    $server = $out.acrLoginServer.value
    $webUrl = $out.webUrl.value
    Write-Host "`nregistry : $server"
    Write-Host "web url  : $webUrl"

    # ------------------------------------------------------------ images ---
    if ($Only -in @('images', 'all')) {
        Stage 2 'Build and push images'
        $tag = Get-Date -Format 'yyyyMMddHHmmss'

        # The web bundle is built, not configured at runtime, so these values are
        # baked in permanently. Blank ones produce an app that loads and then
        # fails at sign-in, so recover them from the deployed BFF rather than
        # letting -Only images ship an unauthenticated bundle.
        if (-not $AadTenantId) {
            $AadTenantId = az containerapp show -g $ResourceGroup -n "ca-$NamePrefix-bff" `
                --query "properties.template.containers[0].env[?name=='AAD_TENANT_ID'].value | [0]" -o tsv
        }
        if (-not $AadApiScope) {
            $AadApiScope = az containerapp show -g $ResourceGroup -n "ca-$NamePrefix-bff" `
                --query "properties.template.containers[0].env[?name=='AAD_API_SCOPE'].value | [0]" -o tsv
        }
        $spaClientId = (az ad app list --display-name mortgage-renewal-concierge-spa `
            --query "[0].appId" -o tsv)
        foreach ($pair in @{ 'tenant id' = $AadTenantId; 'api scope' = $AadApiScope
                             'SPA client id' = $spaClientId }.GetEnumerator()) {
            if (-not $pair.Value) { throw "Could not resolve $($pair.Key) for the web build." }
        }

        Write-Host '-> BFF' -ForegroundColor Yellow
        az acr build --registry $acr --image "mrc/bff:$tag" --image "mrc/bff:latest" `
            --file src/bff/Dockerfile src/bff --no-logs -o none
        Assert-ImagePushed $acr 'mrc/bff' $tag

        Write-Host '-> web (Entra values are baked into the bundle)' -ForegroundColor Yellow
        az acr build --registry $acr --image "mrc/web:$tag" --image "mrc/web:latest" `
            --file src/web/Dockerfile src/web `
            --build-arg VITE_AAD_TENANT_ID=$AadTenantId `
            --build-arg VITE_AAD_CLIENT_ID=$spaClientId `
            --build-arg VITE_API_SCOPE=$AadApiScope --no-logs -o none
        Assert-ImagePushed $acr 'mrc/web' $tag

        Stage 3 'Point the apps at the new images'
        az containerapp update -g $ResourceGroup -n "ca-$NamePrefix-bff" `
            --image "$server/mrc/bff:$tag" -o none
        az containerapp update -g $ResourceGroup -n "ca-$NamePrefix-web" `
            --image "$server/mrc/web:$tag" -o none
        Write-Host "deployed tag $tag"

        # Record the deployed tag so the repo states which image is live.
        Set-Content -NoNewline -Path (Join-Path $root '.tag') -Value $tag
    }

    Stage 4 'Register the redirect URI'
    Write-Host @"
The SPA app registration needs the deployed URL as a redirect URI:

    python infra\provision_app_registrations.py --add-redirect $webUrl

Then open:  $webUrl
"@ -ForegroundColor Yellow

    Write-Host ''
    Write-Host 'DONE' -ForegroundColor Green
}
finally {
    Pop-Location
}
