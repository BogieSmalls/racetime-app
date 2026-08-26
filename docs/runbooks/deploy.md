# Deploy Raceroom

## Purpose

Deploy one immutable Raceroom release without interrupting an active race or
promoting an unverified migration. This procedure implements `OPS-001` and
`FR-OPS-001/002`; it never creates OCI or DNS resources.

## Prerequisites

A reviewed release manifest, digest-addressed ARM64 images, root-owned deployment
config, current [backup/restore](backup-restore.md) status, Bastion access, and a
blackout window. The primary technical operator records the change ID and exact
release SHA. G1/G2 activation evidence must exist for any non-local environment.

## Roles

The primary technical operator is the sole routine executor and records the
technical decision. The Council decision owner is notified for public-impact
changes. The recovery custodian has no deploy access.

## Inputs and exact commands

```bash
sudo /srv/z1rr-racetime/current/deploy/scripts/preflight.sh \
  --environment production --release-manifest /srv/releases/release.json
sudo /srv/z1rr-racetime/current/deploy/scripts/deploy.sh \
  --environment production --release-manifest /srv/releases/release.json \
  --change-id Z1RR-CHANGE-YYYYMMDD-NNN
```

Use only the root-owned values in `/etc/z1rr-racetime/deploy.env`. Never paste
that file or expand its variables into evidence.

## Safety preflight

1. Verify clean release identity, manifest signature/hash, both platform digests,
   migration ceiling, config schema, and `GPL-3.0-only` source link.
2. Confirm the authoritative active-race probe reports zero active races. A probe
   error is not zero. Refuse the deploy when any race is active.
3. Confirm disk/time/config/Compose/Caddy/DB/Redis checks and the G1 activation
   record pass. Confirm production state cannot select qualification volumes.
4. Take and verify the predeploy database backup. Record its manifest ID/hash.
5. Confirm [rollback](rollback.md) target, migration class, status message, and
   prior image digests before changing anything.

## Normal steps

1. Acquire the deployment lock; a competing lock blocks the change.
2. Run local preflight and record only safe pass/fail IDs.
3. Pull exact digests and verify embedded commit labels.
4. Take the verified predeploy backup.
5. For no-migration releases keep write services running; otherwise enter the
   reviewed maintenance barrier and stop writers in the manifest order.
6. Run migrations once, start the new digest set, and execute internal then
   public HTTPS/WSS/login smoke.
7. Promote the release pointer only after every smoke passes. Release the lock
   and send the monitoring notice.

## Verification

```bash
sudo docker compose --env-file /etc/z1rr-racetime/deploy.env \
  -f /srv/z1rr-racetime/current/deploy/compose.production.yml ps
sudo /srv/z1rr-racetime/current/deploy/scripts/preflight.sh \
  --environment production --release-manifest /srv/releases/release.json
```

Verify release SHA/digests, health, WSS, admin denial, one scheduler, backup
freshness, alert delivery, and zero unexpected schema leaves. Record UTC/local
timestamps and the audit-log hash.

## Rollback and escalation

Any backup, migration, readiness, smoke, or integrity failure stops promotion and
invokes [rollback.md](rollback.md). A named emergency active-race override is
allowed only for a P0 security/integrity incident and requires its incident ID;
ambient environment variables cannot grant it. Follow [status-comms.md](status-comms.md).

## Evidence fields

Change/evidence IDs, UTC/local start/end, operator role, commit/image/config
hashes, active-race result, backup manifest/hash, command IDs and safe stdout
hashes, migration class, smoke results, monitoring receipt, findings, result.

## Secret handling

Do not print `.env`, secret volume contents, cookies, tokens, webhooks, database
URLs, or OAuth credentials. Redact command output before hashing/attachment.

## Last reviewed

Owner: primary technical operator. Last reviewed: 2026-08-24.
