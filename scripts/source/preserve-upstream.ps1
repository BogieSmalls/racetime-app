[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$UpstreamUrl,

    [Parameter(Mandatory = $true)]
    [string]$ForkUrl,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [string]$WikiUrl = "https://github.com/racetimeGG/racetime-app.wiki.git",

    [string]$MetadataDirectory = "docs/upstream",

    [switch]$AllowNonGitHubFixture
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$CanonicalUpstream = "https://github.com/racetimeGG/racetime-app.git"
$CanonicalFork = "https://github.com/BogieSmalls/racetime-app.git"
$CanonicalWiki = "https://github.com/racetimeGG/racetime-app.wiki.git"

function Get-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
}

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $output = @(& git @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return ,$output
}

function Get-Refs {
    param(
        [Parameter(Mandatory = $true)][string]$Mirror,
        [Parameter(Mandatory = $true)][ValidateSet("heads", "tags")][string]$Kind
    )

    $refs = [ordered]@{}
    $lines = Invoke-Git -Arguments @(
        "--git-dir", $Mirror,
        "for-each-ref", "--format=%(refname)|%(objectname)", "refs/$Kind"
    )
    foreach ($line in @($lines | Sort-Object)) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $separator = $line.IndexOf("|")
        if ($separator -lt 1) {
            throw "Unexpected ref record: $line"
        }
        $prefix = "refs/$Kind/"
        $name = $line.Substring(0, $separator)
        if (-not $name.StartsWith($prefix, [StringComparison]::Ordinal)) {
            throw "Unexpected ref namespace: $name"
        }
        $refs[$name.Substring($prefix.Length)] = $line.Substring($separator + 1)
    }
    return $refs
}

function Get-ArchiveRecord {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$FileName
    )

    $file = Get-Item -LiteralPath $Path
    if ($file.Length -lt 1) {
        throw "Archive is empty: $Path"
    }
    return [ordered]@{
        file = $FileName
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
        bytes = $file.Length
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    [IO.File]::WriteAllText($Path, $Content, [Text.UTF8Encoding]::new($false))
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$gitDirectory = Join-Path $repositoryRoot ".git"
$outputPath = Get-FullPath $OutputDirectory
$metadataPath = Get-FullPath $MetadataDirectory
$comparison = [StringComparison]::OrdinalIgnoreCase
$separator = [IO.Path]::DirectorySeparatorChar

if ($outputPath.Equals($repositoryRoot, $comparison)) {
    throw "OutputDirectory cannot be the repository root."
}
if (
    $outputPath.Equals($gitDirectory, $comparison) -or
    $outputPath.StartsWith($gitDirectory.TrimEnd($separator) + $separator, $comparison)
) {
    throw "OutputDirectory cannot be the repository Git directory."
}

if (-not $AllowNonGitHubFixture) {
    if ($UpstreamUrl -cne $CanonicalUpstream) {
        throw "UpstreamUrl must be $CanonicalUpstream"
    }
    if ($ForkUrl -cne $CanonicalFork) {
        throw "ForkUrl must be $CanonicalFork"
    }
    if ($WikiUrl -cne $CanonicalWiki) {
        throw "WikiUrl must be $CanonicalWiki"
    }
}

$outputParent = Split-Path -Parent $outputPath
if ([string]::IsNullOrWhiteSpace($outputParent)) {
    throw "OutputDirectory must have a parent directory."
}
New-Item -ItemType Directory -Force -Path $outputParent | Out-Null

$scratchName = ".source-preservation-scratch-$([guid]::NewGuid().ToString('N'))"
$scratchPath = Join-Path $outputParent $scratchName
$sourceMirror = Join-Path $scratchPath "racetime-app.git"
$wikiMirror = Join-Path $scratchPath "racetime-app.wiki.git"
$stagedOutput = Join-Path $scratchPath "output"
$stagedMetadata = Join-Path $scratchPath "metadata"

try {
    New-Item -ItemType Directory -Path $scratchPath | Out-Null
    New-Item -ItemType Directory -Path $stagedOutput | Out-Null
    New-Item -ItemType Directory -Path $stagedMetadata | Out-Null

    Invoke-Git -Arguments @("clone", "--mirror", $UpstreamUrl, $sourceMirror) | Out-Null
    Invoke-Git -Arguments @("--git-dir", $sourceMirror, "fsck", "--full") | Out-Null

    $defaultRef = (Invoke-Git -Arguments @(
        "--git-dir", $sourceMirror, "symbolic-ref", "HEAD"
    ) | Select-Object -First 1).Trim()
    if (-not $defaultRef.StartsWith("refs/heads/", [StringComparison]::Ordinal)) {
        throw "Upstream HEAD is not a branch: $defaultRef"
    }
    $defaultBranch = $defaultRef.Substring("refs/heads/".Length)
    $branches = Get-Refs -Mirror $sourceMirror -Kind heads
    $tags = Get-Refs -Mirror $sourceMirror -Kind tags
    if (-not $branches.Contains($defaultBranch)) {
        throw "Default branch $defaultBranch was not archived."
    }
    $upstreamHead = $branches[$defaultBranch]

    $timestamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $sourceName = "racetime-app-$timestamp.bundle"
    $sourceStaged = Join-Path $stagedOutput $sourceName
    Invoke-Git -Arguments @(
        "--git-dir", $sourceMirror, "bundle", "create", $sourceStaged, "--all"
    ) | Out-Null
    Invoke-Git -Arguments @(
        "--git-dir", $sourceMirror, "bundle", "verify", $sourceStaged
    ) | Out-Null
    $sourceRecord = Get-ArchiveRecord -Path $sourceStaged -FileName $sourceName

    $wikiRecord = [ordered]@{ status = "absent" }
    $wikiProbe = @(& git ls-remote $WikiUrl 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Wiki probe failed: $($wikiProbe -join [Environment]::NewLine)"
    }
    if (@($wikiProbe | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -gt 0) {
        Invoke-Git -Arguments @("clone", "--mirror", $WikiUrl, $wikiMirror) | Out-Null
        Invoke-Git -Arguments @("--git-dir", $wikiMirror, "fsck", "--full") | Out-Null
        $wikiName = "racetime-app-wiki-$timestamp.bundle"
        $wikiStaged = Join-Path $stagedOutput $wikiName
        Invoke-Git -Arguments @(
            "--git-dir", $wikiMirror, "bundle", "create", $wikiStaged, "--all"
        ) | Out-Null
        Invoke-Git -Arguments @(
            "--git-dir", $wikiMirror, "bundle", "verify", $wikiStaged
        ) | Out-Null
        $wikiArchive = Get-ArchiveRecord -Path $wikiStaged -FileName $wikiName
        $wikiRecord = [ordered]@{
            status = "archived"
            file = $wikiArchive.file
            sha256 = $wikiArchive.sha256
            bytes = $wikiArchive.bytes
        }
    }

    $baseline = [ordered]@{
        captured_at_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
        upstream_url = $CanonicalUpstream
        fork_url = $CanonicalFork
        default_branch = $defaultBranch
        upstream_head = $upstreamHead
        branches = $branches
        tags = $tags
        source_bundle = $sourceRecord
        wiki = $wikiRecord
    }
    $baselineJson = ($baseline | ConvertTo-Json -Depth 8) + [Environment]::NewLine
    $baselineStaged = Join-Path $stagedMetadata "UPSTREAM_BASELINE.json"
    Write-Utf8NoBom -Path $baselineStaged -Content $baselineJson

    $archiveRecords = @($sourceRecord)
    if ($wikiRecord.status -eq "archived") {
        $archiveRecords += $wikiRecord
    }
    $sumLines = @(
        $archiveRecords |
            Sort-Object file |
            ForEach-Object { "$($_.sha256)  $($_.bytes)  $($_.file)" }
    )
    $sumsStaged = Join-Path $stagedMetadata "SHA256SUMS"
    Write-Utf8NoBom -Path $sumsStaged -Content (($sumLines -join [Environment]::NewLine) + [Environment]::NewLine)

    foreach ($archive in $archiveRecords) {
        $finalArchive = Join-Path $outputPath $archive.file
        if (Test-Path -LiteralPath $finalArchive) {
            throw "Refusing to overwrite existing archive: $finalArchive"
        }
    }

    New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
    New-Item -ItemType Directory -Force -Path $metadataPath | Out-Null
    foreach ($archive in $archiveRecords) {
        Move-Item -LiteralPath (Join-Path $stagedOutput $archive.file) -Destination (Join-Path $outputPath $archive.file)
    }
    Move-Item -Force -LiteralPath $baselineStaged -Destination (Join-Path $metadataPath "UPSTREAM_BASELINE.json")
    Move-Item -Force -LiteralPath $sumsStaged -Destination (Join-Path $metadataPath "SHA256SUMS")

    Write-Output "PASS: archived upstream source at $upstreamHead"
    Write-Output "Metadata: $(Join-Path $metadataPath 'UPSTREAM_BASELINE.json')"
}
finally {
    if (Test-Path -LiteralPath $scratchPath) {
        $resolvedScratch = [IO.Path]::GetFullPath($scratchPath)
        $expectedParent = [IO.Path]::GetFullPath($outputParent).TrimEnd($separator) + $separator
        if (
            $resolvedScratch.StartsWith($expectedParent, $comparison) -and
            (Split-Path -Leaf $resolvedScratch) -eq $scratchName
        ) {
            Remove-Item -Recurse -Force -LiteralPath $resolvedScratch
        }
        else {
            throw "Refusing unsafe scratch cleanup: $resolvedScratch"
        }
    }
}
