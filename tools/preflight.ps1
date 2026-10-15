<#
.SYNOPSIS
    Pre-flight governance checks before deploying the demo into a subscription.

.DESCRIPTION
    Turns policy denials, RBAC 403s and off-list regions into a report before
    anything is deployed:

      1. policy assignments at and above the target scope
      2. top non-compliant policies (current compliance posture)
      3. the caller's role assignments covering the target scope
      4. whether those roles can deploy resources and assign roles (the Bicep
         creates role assignments)
      5. docs/naming.md and docs/allowed.md, when present

    Exits non-zero when the caller cannot deploy, or a region is not on the
    allow-list.

.EXAMPLE
    ./tools/preflight.ps1 -ResourceGroup rg-mtgrenewal-dev-eastus-001 -Locations eastus,eastus2
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$ResourceGroup,
    [string[]]$Locations = @('eastus', 'eastus2'),
    # App ID of a service principal caller (CI). Omit to use the signed-in user.
    [string]$CallerAppId,
    # Append the report here as well (GitHub job summary).
    [string]$SummaryPath
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'caller.ps1')

$sub = az account show --query id -o tsv
if (-not $sub) { throw 'Not logged in. Run: az login' }
# Object ID from the token claims - no Microsoft Graph permission needed.
$claims = Get-CallerClaims
$caller = @{
    name = if ($CallerAppId) { $CallerAppId } else { az account show --query user.name -o tsv }
    id   = $claims.oid
}

$scope = "/subscriptions/$sub/resourceGroups/$ResourceGroup"
$rgExists = (az group exists -n $ResourceGroup) -eq 'true'
$policyScope = $rgExists ? $scope : "/subscriptions/$sub"

$assignments = @(az policy assignment list --scope $policyScope --disable-scope-strict-match -o json | ConvertFrom-Json)
$posture = @(az policy state summarize --top 5 --query "policyAssignments[].{name:policyAssignmentId, nonCompliant:results.nonCompliantResources}" -o json 2>$null | ConvertFrom-Json)
# Inherited (management group) and group-based assignments count too.
$roles = @(az role assignment list --assignee-object-id $caller.id --all --include-inherited --include-groups `
    --query "[].{role:roleDefinitionName, scope:scope}" -o json | ConvertFrom-Json)
function Test-Covers([string]$roleScope) {
    $s = $roleScope.TrimEnd('/')
    $s -eq '/' -or $s -match '^/providers/Microsoft.Management/managementGroups/' -or
        $scope.Equals($s, [StringComparison]::OrdinalIgnoreCase) -or
        $scope.StartsWith("$s/", [StringComparison]::OrdinalIgnoreCase)
}
$roleNames = @($roles | Where-Object { Test-Covers $_.scope } | ForEach-Object role | Sort-Object -Unique)
$canWrite = [bool]($roleNames | Where-Object { $_ -in 'Owner', 'Contributor' })
$canRbac  = [bool]($roleNames | Where-Object { $_ -in 'Owner', 'User Access Administrator', 'Role Based Access Control Administrator' })

$naming  = Join-Path $repo 'docs/naming.md'
$allowed = Join-Path $repo 'docs/allowed.md'
$offList = @()
if (Test-Path $allowed) {
    $text = Get-Content $allowed -Raw
    $offList = @($Locations | Where-Object { $text -notmatch "\b$([regex]::Escape($_))\b" })
}

$rows = @(
    "| Target scope | ``$scope`` (exists: $rgExists) |"
    "| Policy assignments in scope | $($assignments.Count) |"
    "| Caller identity | ``$($caller.name)`` (object ``$($caller.id)``) |"
    "| Effective roles in scope | $(if ($roleNames) { $roleNames -join ', ' } else { 'none' }) |"
    "| Can deploy resources? | $(if ($canWrite) { '✅' } else { '❌ needs Owner or Contributor' }) |"
    "| Can assign roles? | $(if ($canRbac) { '✅' } else { '⚠️ Bicep role assignments will fail - grant User Access Administrator' }) |"
    "| Naming standard | $(if (Test-Path $naming) { 'docs/naming.md ✅' } else { 'docs/naming.md not present - CAF convention applied' }) |"
    "| Region allow-list | $(if (-not (Test-Path $allowed)) { 'docs/allowed.md not present - not enforced' } elseif (-not $offList) { "✅ $($Locations -join ', ')" } else { "❌ not allowed: $($offList -join ', ')" }) |"
)
$report = @('## Pre-flight report', '', '| Field | Value |', '|---|---|') + $rows
$report += @('', '### Policy assignments at or above the target scope', '', '| Assignment | Enforcement |', '|---|---|')
$report += $assignments | ForEach-Object { "| $(if ($_.displayName) { $_.displayName } else { $_.name }) | $($_.enforcementMode) |" }
if ($posture) {
    $report += @('', '### Top non-compliant assignments (subscription)', '', '| Assignment | Non-compliant resources |', '|---|---|')
    $report += $posture | ForEach-Object { "| $(($_.name -split '/')[-1]) | $($_.nonCompliant) |" }
}
$report += @('', 'Review any **Deny** policies above for: storage shared-key access, public network access, allowed locations and SKUs - the templates disable local auth and keys by default.')

$text = $report -join "`n"
Write-Host $text
if ($SummaryPath) { $text | Out-File -Append -FilePath $SummaryPath -Encoding utf8 }

if (-not $canWrite) { throw 'Caller cannot deploy into the target scope - see the pre-flight report.' }
if ($offList) { throw "Region(s) not on the allow-list in docs/allowed.md: $($offList -join ', ')" }
