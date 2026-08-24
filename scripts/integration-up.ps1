[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$composeFile = Join-Path $repositoryRoot 'deploy\compose.integration.yml'
$environmentFile = Join-Path $repositoryRoot 'deploy\env\integration.env.example'
$artifactRoot = Join-Path $repositoryRoot 'artifacts\integration'
$readyFile = Join-Path $artifactRoot '.ready'
$projectName = 'z1rr-racetime-integration'
$origin = 'https://integration.racetime.test:8443'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker is required to start the isolated integration stack.'
}
if (-not (Test-Path -LiteralPath $composeFile -PathType Leaf)) {
    throw "Integration Compose file is unavailable: $composeFile"
}
if (-not (Test-Path -LiteralPath $environmentFile -PathType Leaf)) {
    throw "Integration environment fixture is unavailable: $environmentFile"
}

$sourceText = [IO.File]::ReadAllText($composeFile) + [IO.File]::ReadAllText($environmentFile)
foreach ($forbidden in @(
    'racetime.z1rracing.com',
    '.env.production',
    'discord.com/api/webhooks',
    'hooks.slack.com'
)) {
    if ($sourceText.Contains($forbidden, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Integration configuration contains forbidden production material: $forbidden"
    }
}
if (-not $sourceText.Contains("name: $projectName", [StringComparison]::Ordinal)) {
    throw 'Integration Compose project identity does not match the guarded project.'
}

$compose = @('compose', '--project-name', $projectName, '--file', $composeFile, '--env-file', $environmentFile)
$rendered = (& docker @compose config | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw 'docker compose config failed.'
}
foreach ($forbidden in @('racetime.z1rracing.com', '0.0.0.0:80', '0.0.0.0:443')) {
    if ($rendered.Contains($forbidden, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Rendered integration configuration contains forbidden value: $forbidden"
    }
}

[IO.Directory]::CreateDirectory($artifactRoot) | Out-Null
if (Test-Path -LiteralPath $readyFile) {
    Remove-Item -LiteralPath $readyFile -Force
}

try {
    & docker @compose --profile racebot build web racebot
    if ($LASTEXITCODE -ne 0) { throw 'Integration application build failed.' }

    & docker @compose up --detach db redis fixture-provider
    if ($LASTEXITCODE -ne 0) { throw 'Integration dependency startup failed.' }

    & docker @compose run --rm web migrate
    if ($LASTEXITCODE -ne 0) { throw 'Integration migration failed.' }
    & docker @compose run --rm web collectstatic
    if ($LASTEXITCODE -ne 0) { throw 'Integration static collection failed.' }
    & docker @compose run --rm --env PYTHONPATH=/srv/racetime --entrypoint python web /fixtures/prepare_integration.py
    if ($LASTEXITCODE -ne 0) { throw 'Integration fixture preparation failed.' }

    & docker @compose --profile racebot up --detach web racebot caddy
    if ($LASTEXITCODE -ne 0) { throw 'Integration application startup failed.' }

    $expectedServices = @(
        'caddy', 'db', 'fixture-provider', 'racebot', 'redis', 'web'
    )
    $healthy = $false
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        try {
            $serviceStatusesJson = (& docker @compose --profile racebot ps --format json | Out-String)
            if ($LASTEXITCODE -ne 0) {
                throw 'Unable to inspect integration service health.'
            }
            $serviceStatuses = @($serviceStatusesJson | ConvertFrom-Json)
            $observedServices = @($serviceStatuses.Service | Sort-Object -Unique)
            $servicesHealthy = (
                $serviceStatuses.Count -eq $expectedServices.Count -and
                -not (Compare-Object -ReferenceObject $expectedServices -DifferenceObject $observedServices)
            )
            foreach ($status in $serviceStatuses) {
                if ($status.State -ne 'running' -or $status.Health -ne 'healthy') {
                    $servicesHealthy = $false
                    break
                }
            }
            if (-not $servicesHealthy) {
                Start-Sleep -Seconds 1
                continue
            }

            $response = Invoke-WebRequest -Uri 'https://127.0.0.1:8443/healthz' `
                -Headers @{ Host = 'integration.racetime.test' } `
                -SkipCertificateCheck -TimeoutSec 2
            if ($response.StatusCode -eq 200 -and $response.Content -eq '{"status":"ok"}') {
                $healthy = $true
                break
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $healthy) {
        throw 'Integration services and health endpoint did not become ready.'
    }

    $identity = [ordered]@{
        schema_version = 1
        project = $projectName
        origin = $origin
        started_at_utc = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json
    [IO.File]::WriteAllText($readyFile, $identity + [Environment]::NewLine)
    Write-Host "Integration stack ready at $origin"
} catch {
    $timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $logFile = Join-Path $artifactRoot "$timestamp-compose.log"
    $logs = (& docker @compose --profile racebot logs --no-color 2>&1 | Out-String)
    [IO.File]::WriteAllText($logFile, $logs)
    throw
}
