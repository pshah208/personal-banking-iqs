<#
.SYNOPSIS
    End-to-end deployment for the Mortgage Renewal Concierge demo.

.DESCRIPTION
    Runs the full stack in dependency order:

      0. Brand      resolve the bank's public branding (name, logo, colours) into
                    a brand pack the web app, agent and seeded content all use.
      1. Bicep      Azure control plane - AI Search, Foundry account/project/model,
                    optional Fabric capacity, role assignments.
      2. Fabric IQ  workspace, lakehouse, OneLake upload, Delta tables, Direct Lake
                    semantic model (Fabric data plane - no ARM provider).
      3. Foundry IQ AI Search index + the renewal policy documents.
      4. Work IQ    Entra app registration, persona mapping, then mail, Teams and
                    files into Microsoft 365 (Graph - no ARM provider).
      5. Agent      the Foundry agent and its three function tools.

    Every stage is idempotent and can be run on its own with -Only.
    Then deploy the web app with app\deploy.ps1.

.PARAMETER Bank
    Name of the bank to brand the demo as, e.g. "Royal Bank of Canada". The
    brand stage looks it up (Wikidata + the bank's website) and writes
    app/src/web/public/brand/<id>/. Omit to keep the current brand
    (the fictional "CFC Bank" on a fresh clone).

.PARAMETER BankDomain
    The bank's website, when the name alone does not resolve it.

.PARAMETER BankShort
    Short name used in narrative copy (e.g. "RBC"). Optional.

.PARAMETER ResourceGroup
    Resource group for the Bicep deployment. Created in -Location if missing.

.PARAMETER Location
    Region for the resource group (and, for the greenfield parameters, the
    resources). Must be on the allow-list in docs/allowed.md where one exists.

.PARAMETER ParametersFile
    Bicep parameters. The greenfield file creates everything in one resource
    group; infra/main.parameters.json mirrors the original reference estate.

.PARAMETER PrincipalId
    Entra object ID granted data-plane roles and Fabric capacity admin.
    Defaults to the signed-in user (or the service principal in CI).

.PARAMETER FabricCapacity
    Name of the Fabric capacity hosting the workspace. Defaults to the one the
    Bicep stage created.

.PARAMETER Only
    Run a single stage: brand | bicep | fabric | realtime | foundry-iq | work-iq | agent.

.PARAMETER Skip
    Stages to leave out of a full run, e.g. -Skip fabric,work-iq (CI uses this).

.PARAMETER SkipWorkIq
    Skip the Microsoft 365 seeding. Use when the tenant content already exists -
    re-seeding is safe but slow, and the Teams step needs interactive auth.

.PARAMETER WhatIf
    For the bicep stage, run what-if instead of deploying.

.EXAMPLE
    .\deploy.ps1 -Bank "Royal Bank of Canada" -ResourceGroup rg-mtgrenewal-dev-eastus-001 -WhatIf
    .\deploy.ps1 -Bank "Royal Bank of Canada" -ResourceGroup rg-mtgrenewal-dev-eastus-001
    .\deploy.ps1 -Only brand -Bank "TD Bank" -BankShort TD
    .\deploy.ps1 -Only agent

.NOTES
    SYNTHETIC DEMO DATA. The bank name and marks are a branding label only.
    Requires: az CLI (logged in), Python 3.10+, and the packages in requirements.txt.
#>

[CmdletBinding()]
param(
    [string]$Bank,
    [string]$BankDomain,
    [string]$BankShort,
    [string]$ResourceGroup = $(if ($env:MRC_RESOURCE_GROUP) { $env:MRC_RESOURCE_GROUP } else { 'rg-mtgrenewal-dev-eastus-001' }),
    [string]$Location = 'eastus',
    [string]$ParametersFile = 'infra/main.parameters.greenfield.json',
    [string]$PrincipalId,
    [string]$FabricCapacity,
    [ValidateSet('brand', 'bicep', 'fabric', 'realtime', 'foundry-iq', 'work-iq', 'agent')]
    [string]$Only,
    [ValidateSet('bicep', 'fabric', 'realtime', 'foundry-iq', 'work-iq', 'agent')]
    [string[]]$Skip = @(),
    [switch]$SkipWorkIq,
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $root

function Write-Stage($n, $text) {
    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor Cyan
    Write-Host " $n. $text" -ForegroundColor Cyan
    Write-Host ('=' * 72) -ForegroundColor Cyan
}

. (Join-Path $root 'tools/caller.ps1')

function Invoke-Step($label, [scriptblock]$block) {
    Write-Host "-> $label" -ForegroundColor Yellow
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$label failed (exit $LASTEXITCODE)" }
}

$run = { param($stage) ((-not $Only) -or ($Only -eq $stage)) -and ($stage -notin $Skip) }

try {
    # ------------------------------------------------------------ 0 brand ----
    # Branding needs no Azure login, so it runs first and can run alone.
    if (($Only -eq 'brand') -or (-not $Only -and $Bank)) {
        Write-Stage 0 'Bank branding'
        if ($Bank) {
            $brandArgs = @('tools/brand/fetch_brand.py', '--bank', $Bank, '--exclusive')
            if ($BankDomain) { $brandArgs += @('--domain', $BankDomain) }
            if ($BankShort)  { $brandArgs += @('--short', $BankShort) }
            $bankId = python @brandArgs
            if ($LASTEXITCODE -ne 0) { throw "brand lookup for '$Bank' failed - pass -BankDomain, or run tools/brand/fetch_brand.py with --logo/--primary" }
            $env:BANK_ID = ($bankId | Select-Object -Last 1).Trim()
        }
        python tools/brand/fetch_brand.py --list
        if ($Only -eq 'brand') { return }
    }
    $bankProfile = python tools/brand/bank_profile.py | ConvertFrom-Json
    Write-Host "bank         : $($bankProfile.name) ($($bankProfile.id))"

    $account = az account show --query "{sub:name,id:id,user:user.name,type:user.type}" -o json | ConvertFrom-Json
    if (-not $account) { throw 'Not logged in. Run: az login' }
    Write-Host "subscription : $($account.sub)"
    Write-Host "identity     : $($account.user)"
    Write-Host "resource grp : $ResourceGroup"

    # Outputs of the Bicep deployment, so any stage can run on its own. When the
    # bicep stage ran in this invocation its outputs always win (a shell reused
    # across resource groups must not keep the previous endpoints); otherwise
    # values already in the environment win, so manual overrides survive.
    function Import-DeploymentOutputs([bool]$Fresh) {
        $out = az deployment group show -g $ResourceGroup -n main `
            --query properties.outputs -o json 2>$null | ConvertFrom-Json
        if (-not $out) { return }
        $map = @{
            SEARCH_ENDPOINT          = $out.searchEndpoint.value
            SEARCH_INDEX             = $out.searchIndexName.value
            FOUNDRY_PROJECT_ENDPOINT = $out.foundryProjectEndpoint.value
            FOUNDRY_MODEL            = $out.modelDeploymentName.value
        }
        foreach ($k in $map.Keys) {
            if ($Fresh -or -not [Environment]::GetEnvironmentVariable($k)) {
                [Environment]::SetEnvironmentVariable($k, $map[$k])
            }
        }
        if (-not $script:FabricCapacity -and $out.fabricCapacityName.value) {
            $script:FabricCapacity = $out.fabricCapacityName.value
        }
        Write-Host "`nresolved from deployment outputs:"
        Write-Host "  SEARCH_ENDPOINT          = $env:SEARCH_ENDPOINT"
        Write-Host "  FOUNDRY_PROJECT_ENDPOINT = $env:FOUNDRY_PROJECT_ENDPOINT"
        Write-Host "  FOUNDRY_MODEL            = $env:FOUNDRY_MODEL"
        if ($script:FabricCapacity) { Write-Host "  FABRIC_CAPACITY          = $script:FabricCapacity" }
    }

    # ------------------------------------------------------------ 1 bicep ----
    if (& $run 'bicep') {
        Write-Stage 1 'Azure control plane (Bicep)'

        if ((az group exists -n $ResourceGroup) -ne 'true') {
            if ($WhatIf) { throw "Resource group $ResourceGroup does not exist - what-if needs it. Create it or run without -WhatIf." }
            Invoke-Step "create resource group $ResourceGroup ($Location)" {
                az group create -n $ResourceGroup -l $Location -o none
            }
        }

        # The greenfield parameters ship with placeholders for the principal that
        # gets data-plane roles and Fabric admin; fill them with the caller.
        $overrides = @{}
        $paramText = Get-Content $ParametersFile -Raw
        if ($paramText -match 'REPLACE-WITH-ENTRA-OBJECT-ID' -or $PrincipalId) {
            $principalType = 'User'
            if (-not $PrincipalId) {
                # From the ARM token's claims - no Microsoft Graph permission needed.
                $claims = Get-CallerClaims
                $PrincipalId = $claims.oid
                if ($claims.idtyp -eq 'app' -or $account.type -eq 'servicePrincipal') { $principalType = 'ServicePrincipal' }
            }
            if (-not $PrincipalId) { throw 'Could not resolve the caller object ID - pass -PrincipalId.' }
            $overrides.agentPrincipalId   = @{ value = $PrincipalId }
            $overrides.agentPrincipalType = @{ value = $principalType }
            $overrides.fabricAdminMembers = @{ value = @($PrincipalId) }
            Write-Host "   principal    : $PrincipalId ($principalType)"
        }
        if ($PSBoundParameters.ContainsKey('Location') -or $paramText -match 'REPLACE-WITH-ENTRA-OBJECT-ID') {
            $overrides.location = @{ value = $Location }
        }
        # A skipped Fabric stage must not leave a billed capacity behind.
        if ('fabric' -in $Skip) {
            $overrides.createFabricCapacity = @{ value = $false }
        }
        $overrideFile = Join-Path ([IO.Path]::GetTempPath()) "mrc-overrides-$PID.json"
        @{ '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
           contentVersion = '1.0.0.0'; parameters = $overrides } |
            ConvertTo-Json -Depth 6 | Set-Content -Path $overrideFile -Encoding utf8

        $verb = $WhatIf ? 'what-if' : 'create'
        try {
            Invoke-Step "az deployment group $verb" {
                az deployment group $verb `
                    -g $ResourceGroup `
                    -n main `
                    --template-file infra/main.bicep `
                    --parameters $ParametersFile `
                    --parameters "@$overrideFile" `
                    -o table
            }
        } finally {
            Remove-Item $overrideFile -ErrorAction SilentlyContinue
        }
        if ($WhatIf) {
            Write-Host "`nwhat-if only - stopping here." -ForegroundColor Yellow
            return
        }
    }
    Import-DeploymentOutputs -Fresh ((& $run 'bicep') -and -not $WhatIf)

    # ----------------------------------------------------------- 2 fabric ----
    if (& $run 'fabric') {
        Write-Stage 2 'Fabric IQ - workspace, lakehouse, tables, semantic model'
        if (-not $FabricCapacity) {
            throw 'No Fabric capacity - pass -FabricCapacity, or deploy one with createFabricCapacity=true.'
        }

        $capState = az resource list --resource-type Microsoft.Fabric/capacities `
            --query "[?name=='$FabricCapacity'] | [0].id" -o tsv
        if ($capState) {
            $state = az resource show --ids $capState --query properties.state -o tsv
            if ($state -ne 'Active') {
                Invoke-Step "resume capacity $FabricCapacity" {
                    az rest --method post --url "https://management.azure.com$capState/resume?api-version=2023-11-01"
                }
                Write-Host '   waiting 30s for the capacity to come up...'
                Start-Sleep -Seconds 30
            } else {
                Write-Host "   capacity $FabricCapacity already Active"
            }
        }

        Invoke-Step 'deploy_fabric.py' {
            python data/fabric-iq/deploy_fabric.py --capacity $FabricCapacity
        }

        $ws = python data/fabric-iq/deploy_fabric.py --status 2>$null |
            Select-String -Pattern '^workspace\s+\S+\s+(\S+)' |
            ForEach-Object { $_.Matches[0].Groups[1].Value }
        if ($ws) {
            $env:FABRIC_WORKSPACE_ID = $ws
            $env:FABRIC_SEMANTIC_MODEL = 'sm_mortgage_renewals'
            Write-Host "  FABRIC_WORKSPACE_ID = $ws"
        }
    }

    # ---------------------------------------------------------- 2b realtime ----
    if (& $run 'realtime') {
        Write-Stage '2b' 'Real-time card processor - Eventstream -> Eventhouse -> insights'
        Invoke-Step 'deploy_realtime.py' { python data/fabric-iq/deploy_realtime.py }
        Write-Host '   Stream events with: python data/fabric-iq/stream_processor_events.py --replay --minutes 10' -ForegroundColor Yellow
        Write-Host '   Let the web app read the stream: deploy_realtime.py --grant-principal <BFF managed identity object id>,' -ForegroundColor Yellow
        Write-Host '   then app\deploy.ps1 picks PROCESSOR_KQL_URI / PROCESSOR_KQL_DB up from data/fabric-iq/.env.realtime.' -ForegroundColor Yellow
    }

    # ------------------------------------------------------- 3 foundry-iq ----
    if (& $run 'foundry-iq') {
        Write-Stage 3 'Foundry IQ - AI Search index + policy corpus'

        if (-not $env:SEARCH_ENDPOINT) {
            throw 'SEARCH_ENDPOINT not set. Run the bicep stage first, or set it manually.'
        }
        if (-not $env:SEARCH_ADMIN_KEY) {
            $svcName = ([uri]$env:SEARCH_ENDPOINT).Host.Split('.')[0]
            $svcRg = az resource list --resource-type Microsoft.Search/searchServices `
                --query "[?name=='$svcName'] | [0].resourceGroup" -o tsv
            if ($svcRg) {
                $env:SEARCH_ADMIN_KEY = az search admin-key show -g $svcRg `
                    --service-name $svcName --query primaryKey -o tsv
                Write-Host "   resolved admin key for $svcName"
            }
        }
        Invoke-Step 'index_renewal_policies.py' {
            python data/foundry-iq/index_renewal_policies.py
        }
    }

    # ---------------------------------------------------------- 4 work-iq ----
    if ((& $run 'work-iq') -and -not $SkipWorkIq) {
        Write-Stage 4 'Work IQ - Microsoft 365 seeding'
        Write-Host 'This writes into user mailboxes and creates a Team.' -ForegroundColor Yellow
        Write-Host 'DEMO TENANTS ONLY.' -ForegroundColor Yellow

        if (-not ($env:WORKIQ_CLIENT_ID -and $env:WORKIQ_CLIENT_SECRET)) {
            Write-Host @'

  The seeder app registration is not configured. Run:

      python data/work-iq/provision_seeder_app.py

  then set the three WORKIQ_* variables it prints and re-run with -Only work-iq.
  (The secret is shown once and is deliberately not persisted by this script.)
'@ -ForegroundColor Yellow
            return
        }

        Invoke-Step 'map personas onto licensed accounts' {
            python data/work-iq/seed_work_iq.py --auth cli --map-users
        }
        Invoke-Step 'seed mail'  { python data/work-iq/seed_work_iq.py --only mail --purge }
        Invoke-Step 'seed team'  { python data/work-iq/seed_work_iq.py --only teams }
        Invoke-Step 'seed files' { python data/work-iq/seed_work_iq.py --only files }

        Write-Host @'

  Channel messages need DELEGATED auth - ChannelMessage.Send does not exist as an
  application permission. Run this last step interactively:

      python data/work-iq/seed_work_iq.py --only teams --messages-only --auth device
'@ -ForegroundColor Yellow
    }
    elseif ($SkipWorkIq) {
        Write-Stage 4 'Work IQ - SKIPPED (-SkipWorkIq)'
    }

    # ------------------------------------------------------------ 5 agent ----
    if (& $run 'agent') {
        Write-Stage 5 'Foundry agent + three IQ tools'
        if (-not $env:FOUNDRY_PROJECT_ENDPOINT) {
            throw 'FOUNDRY_PROJECT_ENDPOINT not set. Run the bicep stage first.'
        }
        Invoke-Step 'create_agent.py --create' { python agent/create_agent.py --create }

        Write-Host "`nTest it:" -ForegroundColor Green
        Write-Host '    python agent/create_agent.py --demo'
    }

    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor Green
    Write-Host ' DONE' -ForegroundColor Green
    Write-Host ('=' * 72) -ForegroundColor Green
    Write-Host @"

Remember to pause the Fabric capacity when finished - it bills while Active:
    az rest --method post --url "https://management.azure.com<capacity-id>/suspend?api-version=2023-11-01"

And delete the seeder app registration when the demo is over - it holds
Mail.ReadWrite and User.ReadWrite.All tenant-wide:
    python data/work-iq/provision_seeder_app.py --delete
"@ -ForegroundColor Yellow
}
finally {
    Pop-Location
}
