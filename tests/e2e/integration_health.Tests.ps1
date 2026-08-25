[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $repositoryRoot 'scripts\integration-health.ps1')

$passed = 0

function Assert-True {
    param(
        [Parameter(Mandatory)]
        [bool]$Condition,
        [Parameter(Mandatory)]
        [string]$Name
    )

    if (-not $Condition) {
        throw "Assertion failed: $Name"
    }
    $script:passed++
}

function Assert-Throws {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Action,
        [Parameter(Mandatory)]
        [string]$Name
    )

    $threw = $false
    try {
        & $Action | Out-Null
    } catch {
        $threw = $true
    }
    Assert-True -Condition $threw -Name $Name
}

function New-ServiceStatus {
    param(
        [Parameter(Mandatory)]
        [string]$Service,
        [string]$State = 'running',
        [string]$Health = 'healthy'
    )

    [pscustomobject][ordered]@{
        Service = $Service
        State = $State
        Health = $Health
    }
}

$expectedServices = @('caddy', 'db', 'fixture-provider', 'racebot', 'redis', 'web')
$healthyStatuses = @($expectedServices | ForEach-Object { New-ServiceStatus -Service $_ })
$legacyArray = ConvertTo-Json -InputObject $healthyStatuses -Depth 4 -Compress
$jsonLines = ($healthyStatuses | ForEach-Object { $_ | ConvertTo-Json -Compress }) -join "`n"

$parsedLegacy = @(ConvertFrom-IntegrationComposePsJson -InputText $legacyArray)
Assert-True -Condition ($parsedLegacy.Count -eq 6) -Name 'legacy JSON array parses'
Assert-True -Condition (
    Test-IntegrationServicesHealthy -Statuses $parsedLegacy -ExpectedServices $expectedServices
) -Name 'legacy JSON array satisfies the exact healthy gate'

$parsedJsonLines = @(ConvertFrom-IntegrationComposePsJson -InputText ($jsonLines + "`n"))
Assert-True -Condition ($parsedJsonLines.Count -eq 6) -Name 'current JSONL parses'
Assert-True -Condition (
    Test-IntegrationServicesHealthy -Statuses $parsedJsonLines -ExpectedServices $expectedServices
) -Name 'current JSONL satisfies the exact healthy gate'

$invalidInputs = [ordered]@{
    'empty input is rejected' = ''
    'whitespace input is rejected' = '   '
    'empty legacy array is rejected' = '[]'
    'malformed JSON is rejected' = '{"Service":'
    'mixed JSONL and array is rejected' = (($jsonLines -split "`n")[0] + "`n" + $legacyArray)
    'scalar JSONL is rejected' = '42'
    'array containing a scalar is rejected' = '[{"Service":"caddy"},42]'
    'blank JSONL record is rejected' = (($jsonLines -split "`n")[0] + "`n`n" + ($jsonLines -split "`n")[1])
}
foreach ($case in $invalidInputs.GetEnumerator()) {
    Assert-Throws -Name $case.Key -Action {
        ConvertFrom-IntegrationComposePsJson -InputText $case.Value
    }
}

$missing = @($healthyStatuses | Select-Object -Skip 1)
Assert-True -Condition (-not (
    Test-IntegrationServicesHealthy -Statuses $missing -ExpectedServices $expectedServices
)) -Name 'missing service fails closed'

$duplicate = @($healthyStatuses + (New-ServiceStatus -Service 'web'))
Assert-True -Condition (-not (
    Test-IntegrationServicesHealthy -Statuses $duplicate -ExpectedServices $expectedServices
)) -Name 'duplicate service fails closed'

$extra = @($healthyStatuses + (New-ServiceStatus -Service 'worker'))
Assert-True -Condition (-not (
    Test-IntegrationServicesHealthy -Statuses $extra -ExpectedServices $expectedServices
)) -Name 'extra service fails closed'

$unhealthy = @($healthyStatuses | ForEach-Object {
    if ($_.Service -eq 'racebot') {
        New-ServiceStatus -Service $_.Service -Health 'unhealthy'
    } else {
        $_
    }
})
Assert-True -Condition (-not (
    Test-IntegrationServicesHealthy -Statuses $unhealthy -ExpectedServices $expectedServices
)) -Name 'unhealthy service fails closed'

$incomplete = @($healthyStatuses | ForEach-Object {
    if ($_.Service -eq 'web') {
        [pscustomobject]@{ Service = 'web'; State = 'running' }
    } else {
        $_
    }
})
Assert-True -Condition (-not (
    Test-IntegrationServicesHealthy -Statuses $incomplete -ExpectedServices $expectedServices
)) -Name 'incomplete service status fails closed'

Write-Output "PowerShell integration health tests: $passed passed"
