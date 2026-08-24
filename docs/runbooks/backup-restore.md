# Back up and restore RaceTime

## Purpose

Produce encrypted, verified database/media/production-Caddy recovery points and
restore them only into an isolated compatible stack. Targets: database RPO six
hours, media RPO 24 hours, target RTO four hours.

## Prerequisites

Root-owned backup config, instance-principal access to the exact private bucket
and `production/` prefix, age recipient/private recovery key separation, safe
scratch/status directories, immutable maintenance image, and current manifests.

## Roles

The primary technical operator runs backup/restore and records evidence. The
recovery custodian releases the sealed backup-key copy only under the documented
handoff. Council receives P0/P1 data-loss status, not routine approvals.

## Inputs and exact commands

```bash
sudo /srv/z1rr-racetime/current/deploy/backup/backup.sh --type database \
  --release-sha "$RELEASE_SHA"
sudo /srv/z1rr-racetime/current/deploy/backup/backup.sh --type media \
  --release-sha "$RELEASE_SHA"
sudo /srv/z1rr-racetime/current/deploy/backup/backup.sh \
  --type production-caddy-state --release-sha "$RELEASE_SHA"
sudo /srv/z1rr-racetime/current/deploy/backup/verify.sh \
  --manifest /var/lib/z1rr-racetime/backup-status/last-database.json \
  --require-verified
```

Use `restore-test.sh` with exact `production/...manifest.json` object names for
database, media, and production Caddy state. Qualification prefixes are invalid.

## Safety preflight

Confirm production generation, named volumes, free space, clock, instance
principal, encryption recipient fingerprint, bucket/prefix, and no symlinks.
A missing named volume must fail without creating an empty replacement. Confirm
the restore project/volumes cannot equal production and ACME is disabled there.

## Normal steps

1. Database: take a consistent dump, compress, encrypt, locally decrypt/verify,
   atomically upload artifact then manifest then completion marker.
2. Media: snapshot the declared read-only volume, compress/encrypt/verify/upload.
3. Caddy: after production issuance/renewal/material change, capture only the
   production Caddy volume; never capture qualification Caddy state.
4. Apply retention only after a dry-run plan: keep every point for 14 days, one
   newest weekly through week 13, one newest monthly through month 12, and the
   current plus two previous verified Caddy generations.
5. Restore into unique isolated volumes, decrypt/integrity-check, load DB/media/
   Caddy, start the matching architecture stack without ACME, and verify samples.
6. Destroy only the explicitly named isolated restore resources after evidence.

## Verification

```bash
sudo /srv/z1rr-racetime/current/deploy/backup/restore-test.sh \
  --database-manifest production/database/EXACT.manifest.json \
  --media-manifest production/media/EXACT.manifest.json \
  --caddy-manifest production/production-caddy-state/EXACT.manifest.json
```

Verify accounts/category/race/results/media samples, Caddy validation, manifest
hashes, completion markers, RPO, measured RTO, ARM64 and amd64 recovery behavior.

## Rollback and escalation

A failed backup never replaces last-known-good status. A failed restore remains
isolated, writes failure status, and alerts. For production loss, stop writers,
invoke [incidents.md](incidents.md), select the newest verified eligible point,
and record data-loss bounds. Never promote a qualification restore.

## Evidence fields

UTC/local times, release/architecture, manifest/object IDs and hashes, recipient
fingerprint, types/ages, sample IDs (non-PII), RPO/RTO, commands, expected/
observed results, cleanup, findings, pass/fail.

## Secret handling

Never print the age private key, OCI credentials, DB password/dump, media
contents, Caddy account material, or bucket auth. Sealed material stays offline.

## Last reviewed

Owner: primary technical operator. Last reviewed: 2026-08-24.
