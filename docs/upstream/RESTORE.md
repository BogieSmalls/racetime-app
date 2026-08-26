# Raceroom upstream source archive and recovery

This runbook preserves the exact public Raceroom upstream source, its named refs,
and its wiki before Z1RR implementation diverges. Bundle files are deliberately
**not committed** to Git. The committed manifest and checksums describe the
independently stored bundle files.

## Prerequisites

Use PowerShell 7 and Git 2.51 or later from the repository root. Confirm the
working repository has the expected remotes and that `upstream` cannot push:

```powershell
pwsh -NoProfile -File scripts\source\check-remotes.ps1 `
  -Repository . `
  -MetadataPath docs\upstream\UPSTREAM_BASELINE.json `
  -ExpectedForkDefaultBranch master
```

The archive operator needs read access to these public repositories:

- `https://github.com/racetimeGG/racetime-app.git`
- `https://github.com/racetimeGG/racetime-app.wiki.git`
- `https://github.com/BogieSmalls/racetime-app.git`

The operator also needs an empty local destination, operator-held encrypted
storage, and Council-approved off-workstation storage. Do not put credentials,
local absolute paths, bucket secrets, or signed download URLs into committed
metadata or evidence.

## Create an archive

From the repository root, run:

```powershell
$sourceArchiveDirectory = Join-Path (Get-Location) "artifacts\source"
pwsh -NoProfile -File scripts\source\preserve-upstream.ps1 `
  -UpstreamUrl https://github.com/racetimeGG/racetime-app.git `
  -ForkUrl https://github.com/BogieSmalls/racetime-app.git `
  -WikiUrl https://github.com/racetimeGG/racetime-app.wiki.git `
  -OutputDirectory $sourceArchiveDirectory `
  -MetadataDirectory docs\upstream
```

The command uses fresh mirror clones, runs `git fsck --full`, creates complete
bundles with all named refs, verifies the bundles, and then writes:

- ignored bundle files under `artifacts\source`;
- `docs\upstream\UPSTREAM_BASELINE.json`, including `default_branch`, exact
  `upstream_head`, named branch and tag object IDs, hashes, sizes, and wiki state;
- `docs\upstream\SHA256SUMS`, sorted by archive filename.

A Git or wiki probe failure is a failed archive, not evidence that the wiki is
absent. Do not distribute or supersede a failed archive attempt.

## Verify an archive

Restore into a new, uniquely named temporary directory:

```powershell
$sourceArchiveDirectory = Join-Path (Get-Location) "artifacts\source"
$sourceRestoreTarget = Join-Path ([IO.Path]::GetTempPath()) `
  ("z1rr-racetime-source-restore-" + [guid]::NewGuid().ToString("N"))
pwsh -NoProfile -File scripts\source\verify-upstream-archive.ps1 `
  -ArchiveDirectory $sourceArchiveDirectory `
  -MetadataDirectory docs\upstream `
  -RestoreDirectory $sourceRestoreTarget
```

A valid run checks manifest size and SHA-256 before Git reads the bundle, runs
`git bundle verify`, checks every recorded branch and tag object, restores the
wiki when archived, and checks out the recorded `default_branch` at the exact
`upstream_head`. Only a final `PASS:` result is acceptable.

After reviewing the result, remove only the exact temporary target that this
procedure created. Never point cleanup at a repository root, drive root, home
directory, or unresolved environment variable.

## Create the second copy

Maintain **two independently controlled copies** of every accepted archive:

1. operator-held encrypted storage; and
2. Council-approved off-workstation storage under separate credentials and a
   separate failure domain.

Copy the source bundle, wiki bundle when present, `UPSTREAM_BASELINE.json`, and
`SHA256SUMS` together. Verify the off-workstation copy after upload by downloading
it to a new empty location and running the verifier against that downloaded copy.
Record only storage role, immutable object/version identifier, hash, size,
verification time, and custodian in acceptance evidence.

Do not delete the only verified prior archive before its replacement has passed
restoration from both custody locations. Retain the prior archive until the new
archive and both copies have independently passed verification.

## Restore into an empty directory

The verifier accepts only a missing or empty restore directory. Use its exact
invocation from the verification section. Do not pre-initialize the target and do
not copy files into it. A failure never authorizes use of a partially restored
directory; correct the archive or metadata problem and restore again to a new
empty target.

Confirm the result independently:

```powershell
git -C $sourceRestoreTarget symbolic-ref --short HEAD
git -C $sourceRestoreTarget rev-parse HEAD
git -C $sourceRestoreTarget show-ref --heads --tags
git -C (Join-Path $sourceRestoreTarget "wiki") fsck --full
```

The first two outputs must equal the manifest's `default_branch` and
`upstream_head` exactly.

## Recreate the GitHub fork

1. Create a completely empty `BogieSmalls/racetime-app` GitHub repository. Do not
   initialize it with a README, license, or `.gitignore`.
2. Complete a verified empty-directory restore and retain its terminal output as
   evidence.
3. Replace the bundle origin with the empty fork and add the read-only upstream:

   ```powershell
   git -C $sourceRestoreTarget remote remove origin
   git -C $sourceRestoreTarget remote add origin https://github.com/BogieSmalls/racetime-app.git
   git -C $sourceRestoreTarget remote add upstream https://github.com/racetimeGG/racetime-app.git
   git -C $sourceRestoreTarget remote set-url --push upstream DISABLED
   ```

4. Push the restored named branches and tags explicitly:

   ```powershell
   git -C $sourceRestoreTarget push origin 'refs/heads/*:refs/heads/*'
   git -C $sourceRestoreTarget push origin 'refs/tags/*:refs/tags/*'
   ```

5. Reapply required reviews, status checks, force-push/deletion restrictions,
   environment protections, and repository access before enabling automation.
6. For a G0 or neutral recovery, set the fork default to the manifest's recorded
   upstream default, currently `master`.
7. For a G1-or-later Plan-B recovery, first verify and protect the restored
   `z1rr-production` branch, then set it as the fork default while retaining
   upstream-only `master`.

Never use `git push --mirror` against a non-empty destination without reviewed
destructive authorization. Explicit ref pushes make the intended creation
visible and do not silently delete destination refs.

## Reapply the upstream remote guard

After GitHub reports the intended default branch, run the guard with the
gate-appropriate value:

```powershell
pwsh -NoProfile -File scripts\source\check-remotes.ps1 `
  -Repository $sourceRestoreTarget `
  -MetadataPath docs\upstream\UPSTREAM_BASELINE.json `
  -ExpectedForkDefaultBranch master
# Use -ExpectedForkDefaultBranch z1rr-production only after G1 activation.
```

The command must confirm exact fetch URLs, disabled upstream push, upstream HEAD
at the manifest baseline, and the expected fork default. A failed guard blocks
source acceptance and all downstream gates.

## Quarterly rehearsal

Once per quarter and after every archive replacement:

1. obtain the copy from each custody location without using a cached local copy;
2. verify each copy into a distinct empty directory;
3. compare all branch/tag counts, exact default branch, `upstream_head`, and wiki
   status with the manifest;
4. rehearse the GitHub recreation steps without pushing to a production fork;
5. record date, archive identity, result, operator, discrepancies, and corrective
   work in the G0 evidence record.

A rehearsal is incomplete until both custody copies restore. Do not infer
recoverability from a successful checksum alone.

## Custody and access

Limit write/delete access to the primary operator and the designated recovery
path. The off-workstation custodian may release sealed access material to the
primary operator or a formally designated replacement, but gains no standing
technical approval role. Record access changes and test recovery after rotation.
Keep encryption keys separate from encrypted bundles and ensure the documented
account-level recovery path covers OCI, GitHub organization/registry, and
authoritative DNS access.

## Incident handling

On a checksum mismatch, truncated bundle, missing ref, lost custody copy, or
unauthorized access:

1. stop using and copying the affected archive;
2. preserve the suspect bytes and logs without altering committed metadata;
3. identify whether source, transit, destination, or credentials failed;
4. verify the other independent copy into a new empty directory;
5. rotate affected credentials and encryption material;
6. create a replacement archive from the canonical public repositories when
   possible, verify it, establish both copies, and record the incident outcome.

Never weaken hashes, edit the manifest to match suspect bytes, accept a merely
reachable commit in place of the exact default-branch tip, or advance a gate on
the basis of an unverified archive.
