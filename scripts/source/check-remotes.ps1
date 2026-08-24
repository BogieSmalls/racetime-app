[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Repository,

    [Parameter(Mandatory)]
    [string]$MetadataPath,

    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9._/-]+$')]
    [string]$ExpectedForkDefaultBranch,

    [switch]$AllowNonGitHubFixture
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedUpstreamUrl = 'https://github.com/racetimeGG/racetime-app.git'
$ExpectedForkUrl = 'https://github.com/BogieSmalls/racetime-app.git'

function Stop-RemoteGuard {
    param([Parameter(Mandatory)][string]$Reason)

    [Console]::Error.WriteLine("FAIL: $Reason")
    exit 1
}

function Invoke-GitInspection {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & git @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        Stop-RemoteGuard 'Git remote inspection failed.'
    }
    return ,@($output)
}

function Read-AdvertisedHead {
    param(
        [Parameter(Mandatory)][string[]]$Lines,
        [Parameter(Mandatory)][string]$RemoteLabel
    )

    $symbolicRef = $null
    $commit = $null
    foreach ($line in $Lines) {
        if ($line -match '^ref:\s+(refs/heads/[^\s]+)\s+HEAD$') {
            $symbolicRef = $Matches[1]
            continue
        }
        if ($line -match '^([0-9a-f]{40})\s+HEAD$') {
            $commit = $Matches[1]
        }
    }

    if (-not $symbolicRef -or -not $commit) {
        Stop-RemoteGuard "$RemoteLabel does not advertise a complete symbolic HEAD."
    }

    return [pscustomobject]@{
        Ref = $symbolicRef
        Commit = $commit
    }
}

try {
    $repositoryPath = (Resolve-Path -LiteralPath $Repository).Path
    $metadataFile = (Resolve-Path -LiteralPath $MetadataPath).Path
    $metadata = Get-Content -LiteralPath $metadataFile -Raw | ConvertFrom-Json

    foreach ($field in @('upstream_url', 'fork_url', 'default_branch', 'upstream_head')) {
        if (-not $metadata.PSObject.Properties.Name.Contains($field)) {
            Stop-RemoteGuard 'Baseline metadata is missing a required remote-boundary field.'
        }
    }
    if ($metadata.default_branch -notmatch '^[A-Za-z0-9._/-]+$' -or
        $metadata.upstream_head -notmatch '^[0-9a-f]{40}$') {
        Stop-RemoteGuard 'Baseline metadata contains an invalid branch or commit.'
    }

    if (-not $AllowNonGitHubFixture) {
        if ($metadata.upstream_url -cne $ExpectedUpstreamUrl -or
            $metadata.fork_url -cne $ExpectedForkUrl) {
            Stop-RemoteGuard 'Baseline repository identity does not match the production contract.'
        }
    }

    $originFetch = (Invoke-GitInspection @('-C', $repositoryPath, 'remote', 'get-url', 'origin'))[0]
    $upstreamFetch = (Invoke-GitInspection @('-C', $repositoryPath, 'remote', 'get-url', 'upstream'))[0]
    $upstreamPush = (Invoke-GitInspection @('-C', $repositoryPath, 'remote', 'get-url', '--push', 'upstream'))[0]

    if ($originFetch -cne [string]$metadata.fork_url) {
        Stop-RemoteGuard 'The origin fetch remote does not match the recorded fork.'
    }
    if ($upstreamFetch -cne [string]$metadata.upstream_url) {
        Stop-RemoteGuard 'The upstream fetch remote does not match the recorded source.'
    }
    if ($upstreamPush -cne 'DISABLED') {
        Stop-RemoteGuard 'The upstream push URL is not disabled.'
    }

    $upstreamHead = Read-AdvertisedHead `
        -Lines (Invoke-GitInspection @('-C', $repositoryPath, 'ls-remote', '--symref', 'upstream', 'HEAD')) `
        -RemoteLabel 'Upstream'
    $originHead = Read-AdvertisedHead `
        -Lines (Invoke-GitInspection @('-C', $repositoryPath, 'ls-remote', '--symref', 'origin', 'HEAD')) `
        -RemoteLabel 'Origin'

    if ($upstreamHead.Ref -cne "refs/heads/$($metadata.default_branch)" -or
        $upstreamHead.Commit -cne [string]$metadata.upstream_head) {
        Stop-RemoteGuard 'Upstream default HEAD differs from the recorded baseline.'
    }
    if ($originHead.Ref -cne "refs/heads/$ExpectedForkDefaultBranch") {
        Stop-RemoteGuard 'Origin default branch differs from the gate-specific expectation.'
    }

    [Console]::Out.WriteLine('PASS: origin/upstream source boundary is configured.')
}
catch {
    Stop-RemoteGuard 'Remote-boundary validation failed safely.'
}
