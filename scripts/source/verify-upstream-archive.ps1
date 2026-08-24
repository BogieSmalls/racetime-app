[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ArchiveDirectory,

    [Parameter(Mandatory = $true)]
    [string]$MetadataDirectory,

    [Parameter(Mandatory = $true)]
    [string]$RestoreDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

function Assert-Property {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not ($Object.PSObject.Properties.Name -contains $Name)) {
        throw "Manifest is missing required property: $Name"
    }
}

function Assert-ObjectId {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -cnotmatch "^[0-9a-f]{40}$") {
        throw "$Label is not a lowercase Git object ID."
    }
}

function Get-ArchiveDetails {
    param(
        [Parameter(Mandatory = $true)][object]$Record,
        [Parameter(Mandatory = $true)][string]$ArchiveRoot,
        [Parameter(Mandatory = $true)][hashtable]$ChecksumManifest
    )

    foreach ($name in @("file", "sha256", "bytes")) {
        Assert-Property -Object $Record -Name $name
    }
    $fileName = [string]$Record.file
    if (
        [string]::IsNullOrWhiteSpace($fileName) -or
        [IO.Path]::GetFileName($fileName) -cne $fileName
    ) {
        throw "Archive file must be a leaf filename."
    }
    if ([string]$Record.sha256 -cnotmatch "^[0-9a-f]{64}$") {
        throw "Archive SHA-256 is invalid: $fileName"
    }
    $expectedBytes = [int64]$Record.bytes
    if ($expectedBytes -lt 1) {
        throw "Archive size is invalid: $fileName"
    }
    if (-not $ChecksumManifest.ContainsKey($fileName)) {
        throw "SHA256SUMS is missing $fileName"
    }
    $sumRecord = $ChecksumManifest[$fileName]
    if (
        $sumRecord.sha256 -cne [string]$Record.sha256 -or
        $sumRecord.bytes -ne $expectedBytes
    ) {
        throw "SHA256SUMS disagrees with UPSTREAM_BASELINE.json for $fileName"
    }

    $archivePath = Join-Path $ArchiveRoot $fileName
    if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
        throw "Archive file is missing: $fileName"
    }
    $actualBytes = (Get-Item -LiteralPath $archivePath).Length
    if ($actualBytes -ne $expectedBytes) {
        throw "Archive size mismatch for $fileName"
    }
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    if ($actualHash -cne [string]$Record.sha256) {
        throw "Archive SHA-256 mismatch for $fileName"
    }
    return [ordered]@{
        file = $fileName
        path = $archivePath
        sha256 = $actualHash
        bytes = $actualBytes
    }
}

function Get-BundleHeads {
    param([Parameter(Mandatory = $true)][string]$Bundle)

    $heads = @{}
    $bundleOutput = (Invoke-Git -Arguments @("bundle", "list-heads", $Bundle)) -split "\r?\n"
    foreach ($line in @($bundleOutput)) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $parts = $line -split "\s+", 2
        if ($parts.Count -ne 2) {
            throw "Unexpected bundle head: $line"
        }
        Assert-ObjectId -Value $parts[0] -Label "Bundle head"
        if ($heads.ContainsKey($parts[1])) {
            throw "Duplicate bundle ref: $($parts[1])"
        }
        $heads[$parts[1]] = $parts[0]
    }
    return $heads
}

function Assert-Bundle {
    param(
        [Parameter(Mandatory = $true)][string]$Bundle,
        [Parameter(Mandatory = $true)][string]$VerificationRepository
    )

    Invoke-Git -Arguments @("init", "--bare", $VerificationRepository) | Out-Null
    Invoke-Git -Arguments @(
        "--git-dir", $VerificationRepository, "bundle", "verify", $Bundle
    ) | Out-Null
}

$archivePath = Get-FullPath $ArchiveDirectory
$metadataPath = Get-FullPath $MetadataDirectory
$restorePath = Get-FullPath $RestoreDirectory

if (-not (Test-Path -LiteralPath $archivePath -PathType Container)) {
    throw "ArchiveDirectory does not exist."
}
if (-not (Test-Path -LiteralPath $metadataPath -PathType Container)) {
    throw "MetadataDirectory does not exist."
}
if (Test-Path -LiteralPath $restorePath) {
    if (-not (Test-Path -LiteralPath $restorePath -PathType Container)) {
        throw "RestoreDirectory must be a directory."
    }
    if (@(Get-ChildItem -Force -LiteralPath $restorePath).Count -ne 0) {
        throw "RestoreDirectory must be missing or empty."
    }
}

$baselineFile = Join-Path $metadataPath "UPSTREAM_BASELINE.json"
$sumsFile = Join-Path $metadataPath "SHA256SUMS"
if (-not (Test-Path -LiteralPath $baselineFile -PathType Leaf)) {
    throw "UPSTREAM_BASELINE.json is missing."
}
if (-not (Test-Path -LiteralPath $sumsFile -PathType Leaf)) {
    throw "SHA256SUMS is missing."
}
$baseline = Get-Content -Raw -LiteralPath $baselineFile | ConvertFrom-Json
foreach ($name in @(
    "captured_at_utc", "upstream_url", "fork_url", "default_branch",
    "upstream_head", "branches", "tags", "source_bundle", "wiki"
)) {
    Assert-Property -Object $baseline -Name $name
}

$defaultBranch = [string]$baseline.default_branch
if ([string]::IsNullOrWhiteSpace($defaultBranch)) {
    throw "default_branch cannot be empty."
}
Invoke-Git -Arguments @("check-ref-format", "refs/heads/$defaultBranch") | Out-Null
Assert-ObjectId -Value ([string]$baseline.upstream_head) -Label "upstream_head"

$branches = @{}
foreach ($property in @($baseline.branches.PSObject.Properties | Sort-Object Name)) {
    $name = [string]$property.Name
    Invoke-Git -Arguments @("check-ref-format", "refs/heads/$name") | Out-Null
    Assert-ObjectId -Value ([string]$property.Value) -Label "Branch $name"
    $branches[$name] = [string]$property.Value
}
if (-not $branches.ContainsKey($defaultBranch)) {
    throw "default_branch is not present in branches."
}
if ($branches[$defaultBranch] -cne [string]$baseline.upstream_head) {
    throw "branches[default_branch] must equal upstream_head."
}

$tags = @{}
foreach ($property in @($baseline.tags.PSObject.Properties | Sort-Object Name)) {
    $name = [string]$property.Name
    Invoke-Git -Arguments @("check-ref-format", "refs/tags/$name") | Out-Null
    Assert-ObjectId -Value ([string]$property.Value) -Label "Tag $name"
    $tags[$name] = [string]$property.Value
}

$checksumManifest = @{}
foreach ($line in @(Get-Content -LiteralPath $sumsFile)) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }
    if ($line -cnotmatch "^([0-9a-f]{64})\s+([0-9]+)\s+([^\\/]+)$") {
        throw "Invalid SHA256SUMS line."
    }
    $name = $Matches[3]
    if ($checksumManifest.ContainsKey($name)) {
        throw "Duplicate SHA256SUMS entry: $name"
    }
    $checksumManifest[$name] = [ordered]@{
        sha256 = $Matches[1]
        bytes = [int64]$Matches[2]
    }
}

$sourceArguments = @{
    Record = $baseline.source_bundle
    ArchiveRoot = $archivePath
    ChecksumManifest = $checksumManifest
}
$sourceArchive = Get-ArchiveDetails @sourceArguments
Assert-Property -Object $baseline.wiki -Name "status"
if ([string]$baseline.wiki.status -cnotin @("absent", "archived")) {
    throw "Unknown wiki status."
}
$wikiArchive = $null
if ([string]$baseline.wiki.status -ceq "archived") {
    $wikiArguments = @{
        Record = $baseline.wiki
        ArchiveRoot = $archivePath
        ChecksumManifest = $checksumManifest
    }
    $wikiArchive = Get-ArchiveDetails @wikiArguments
}
$expectedArchiveCount = if ($null -eq $wikiArchive) { 1 } else { 2 }
if ($checksumManifest.Count -ne $expectedArchiveCount) {
    throw "SHA256SUMS contains an unexpected archive entry."
}

$restoreParent = Split-Path -Parent $restorePath
if ([string]::IsNullOrWhiteSpace($restoreParent)) {
    throw "RestoreDirectory must have a parent directory."
}
New-Item -ItemType Directory -Force -Path $restoreParent | Out-Null
$scratchName = ".source-restore-scratch-$([guid]::NewGuid().ToString('N'))"
$scratchPath = Join-Path $restoreParent $scratchName
$stagedRestore = Join-Path $scratchPath "source"
$separator = [IO.Path]::DirectorySeparatorChar
$comparison = [StringComparison]::OrdinalIgnoreCase

try {
    New-Item -ItemType Directory -Path $scratchPath | Out-Null
    Assert-Bundle -Bundle $sourceArchive.path -VerificationRepository (Join-Path $scratchPath "verify-source.git")
    $bundleHeads = Get-BundleHeads -Bundle $sourceArchive.path
    foreach ($entry in $branches.GetEnumerator()) {
        $ref = "refs/heads/$($entry.Key)"
        if (-not $bundleHeads.ContainsKey($ref) -or $bundleHeads[$ref] -cne $entry.Value) {
            throw "Bundle branch does not match manifest: $($entry.Key)"
        }
    }
    foreach ($entry in $tags.GetEnumerator()) {
        $ref = "refs/tags/$($entry.Key)"
        if (-not $bundleHeads.ContainsKey($ref) -or $bundleHeads[$ref] -cne $entry.Value) {
            throw "Bundle tag does not match manifest: $($entry.Key)"
        }
    }

    Invoke-Git -Arguments @("clone", $sourceArchive.path, $stagedRestore) | Out-Null
    foreach ($entry in $branches.GetEnumerator()) {
        Invoke-Git -Arguments @(
            "-C", $stagedRestore, "update-ref", "refs/heads/$($entry.Key)", $entry.Value
        ) | Out-Null
    }
    Invoke-Git -Arguments @(
        "-C", $stagedRestore, "symbolic-ref", "HEAD", "refs/heads/$defaultBranch"
    ) | Out-Null
    Invoke-Git -Arguments @(
        "-C", $stagedRestore, "reset", "--hard", [string]$baseline.upstream_head
    ) | Out-Null

    foreach ($entry in $branches.GetEnumerator()) {
        $actual = (Invoke-Git -Arguments @(
            "-C", $stagedRestore, "rev-parse", "refs/heads/$($entry.Key)"
        ) | Select-Object -First 1).Trim()
        if ($actual -cne $entry.Value) {
            throw "Restored branch differs from manifest: $($entry.Key)"
        }
    }
    foreach ($entry in $tags.GetEnumerator()) {
        $actual = (Invoke-Git -Arguments @(
            "-C", $stagedRestore, "rev-parse", "refs/tags/$($entry.Key)"
        ) | Select-Object -First 1).Trim()
        if ($actual -cne $entry.Value) {
            throw "Restored tag differs from manifest: $($entry.Key)"
        }
    }
    $actualBranch = (Invoke-Git -Arguments @(
        "-C", $stagedRestore, "symbolic-ref", "--short", "HEAD"
    ) | Select-Object -First 1).Trim()
    $actualHead = (Invoke-Git -Arguments @(
        "-C", $stagedRestore, "rev-parse", "HEAD"
    ) | Select-Object -First 1).Trim()
    if ($actualBranch -cne $defaultBranch -or $actualHead -cne [string]$baseline.upstream_head) {
        throw "Restored checkout does not match the exact default branch and upstream_head."
    }

    if ($null -ne $wikiArchive) {
        Assert-Bundle -Bundle $wikiArchive.path -VerificationRepository (Join-Path $scratchPath "verify-wiki.git")
        $wikiHeads = Get-BundleHeads -Bundle $wikiArchive.path
        if ($wikiHeads.Count -eq 0) {
            throw "Wiki bundle contains no refs."
        }
        Invoke-Git -Arguments @(
            "clone", $wikiArchive.path, (Join-Path $stagedRestore "wiki")
        ) | Out-Null
        Invoke-Git -Arguments @(
            "-C", (Join-Path $stagedRestore "wiki"), "fsck", "--full"
        ) | Out-Null
    }

    if (Test-Path -LiteralPath $restorePath) {
        Remove-Item -LiteralPath $restorePath
    }
    Move-Item -LiteralPath $stagedRestore -Destination $restorePath
    Write-Output "PASS: restored $($baseline.upstream_head) on $defaultBranch"
}
finally {
    if (Test-Path -LiteralPath $scratchPath) {
        $resolvedScratch = [IO.Path]::GetFullPath($scratchPath)
        $expectedParent = [IO.Path]::GetFullPath($restoreParent).TrimEnd($separator) + $separator
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
