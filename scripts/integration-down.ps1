[CmdletBinding()]
param(
    [switch]$CaptureLogs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$composeFile = Join-Path $repositoryRoot 'deploy\compose.integration.yml'
$environmentFile = Join-Path $repositoryRoot 'deploy\env\integration.env.example'
$artifactRoot = Join-Path $repositoryRoot 'artifacts\integration'
$readyFile = Join-Path $artifactRoot '.ready'
$projectName = 'z1rr-racetime-integration'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker is required to stop the isolated integration stack.'
}
$composeText = [IO.File]::ReadAllText($composeFile)
if (-not $composeText.Contains("name: $projectName", [StringComparison]::Ordinal)) {
    throw 'Refusing to stop a Compose project without the exact integration identity.'
}

$compose = @('compose', '--project-name', $projectName, '--file', $composeFile, '--env-file', $environmentFile)
if ($CaptureLogs) {
    [IO.Directory]::CreateDirectory($artifactRoot) | Out-Null
    $timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $logFile = Join-Path $artifactRoot "$timestamp-compose.log"
    $logs = (& docker @compose --profile racebot logs --no-color 2>&1 | Out-String)
    [IO.File]::WriteAllText($logFile, $logs)
}

& docker @compose --profile racebot down --volumes --remove-orphans
if ($LASTEXITCODE -ne 0) {
    throw 'Integration Compose shutdown failed.'
}
if (Test-Path -LiteralPath $readyFile) {
    Remove-Item -LiteralPath $readyFile -Force
}
Write-Host 'Integration stack stopped; only z1rr-racetime-integration resources were removed.'
