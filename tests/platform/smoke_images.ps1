[CmdletBinding()]
param(
    [string]$ExpectedCommit = (git rev-parse HEAD),
    [switch]$SkipBuild,
    [ValidateSet('linux/arm64', 'linux/amd64')]
    [string]$Platform,
    [ValidateSet('web', 'racebot')]
    [string]$Target
)

$ErrorActionPreference = 'Stop'
$images = @(
    @{ Platform = 'linux/arm64'; Target = 'web'; Image = 'z1rr-racetime:web-arm64-test' },
    @{ Platform = 'linux/arm64'; Target = 'racebot'; Image = 'z1rr-racetime:racebot-arm64-test' },
    @{ Platform = 'linux/amd64'; Target = 'web'; Image = 'z1rr-racetime:web-amd64-test' },
    @{ Platform = 'linux/amd64'; Target = 'racebot'; Image = 'z1rr-racetime:racebot-amd64-test' }
)

if ($Platform) {
    $images = @($images | Where-Object { $_.Platform -eq $Platform })
}
if ($Target) {
    $images = @($images | Where-Object { $_.Target -eq $Target })
}
if ($images.Count -eq 0) {
    throw 'No image matches the requested platform/target filter'
}

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker command failed: $($Arguments -join ' ')"
    }
}

foreach ($item in $images) {
    if (-not $SkipBuild) {
        Invoke-Docker buildx build `
            --platform $item.Platform `
            --target $item.Target `
            --build-arg "VCS_REF=$ExpectedCommit" `
            --tag $item.Image `
            --load .
    }

    $revision = (& docker image inspect `
        --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' `
        $item.Image).Trim()
    if ($LASTEXITCODE -ne 0 -or $revision -ne $ExpectedCommit) {
        throw "$($item.Image) revision '$revision' does not match '$ExpectedCommit'"
    }

    $platform = (& docker image inspect `
        --format '{{ .Os }}/{{ .Architecture }}' $item.Image).Trim()
    if ($LASTEXITCODE -ne 0 -or $platform -ne $item.Platform) {
        throw "$($item.Image) platform '$platform' does not match '$($item.Platform)'"
    }

    $uid = (& docker run --rm `
        --platform $item.Platform `
        --read-only `
        --tmpfs /tmp:rw,noexec,nosuid,size=16m `
        --entrypoint /bin/sh `
        $item.Image -c 'id -u').Trim()
    if ($LASTEXITCODE -ne 0 -or $uid -ne '10001') {
        throw "$($item.Image) did not run as UID 10001"
    }

    $config = & docker image inspect `
        --format '{{ json .Config }}' $item.Image | ConvertFrom-Json
    if ($item.Target -eq 'web') {
        if (($config.Cmd -join ' ') -ne 'web' -or '8000/tcp' -notin $config.ExposedPorts.PSObject.Properties.Name) {
            throw "$($item.Image) does not have the web process contract"
        }
    }
    elseif (($config.Cmd -join ' ') -ne 'racebot') {
        throw "$($item.Image) does not have the racebot process contract"
    }

    $history = (& docker image history --no-trunc $item.Image) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        throw "cannot inspect $($item.Image) history"
    }
    $credentialPatterns = @(
        'DJANGO_SECRET_KEY=',
        'DB_PASSWORD=',
        'DISCORD_CLIENT_SECRET=',
        'TWITCH_CLIENT_SECRET=',
        'RACETIME_THROTTLE_HMAC_KEY='
    )
    foreach ($pattern in $credentialPatterns) {
        if ($history.Contains($pattern)) {
            throw "$($item.Image) history contains a credential variable"
        }
    }
}

$revisions = $images | ForEach-Object {
    (& docker image inspect `
        --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' `
        $_.Image).Trim()
} | Sort-Object -Unique
if ($revisions.Count -ne 1 -or $revisions[0] -ne $ExpectedCommit) {
    throw 'image targets do not share one embedded commit'
}

Write-Output "IMAGE_SMOKE=PASS commit=$ExpectedCommit targets=$($images.Count)"
