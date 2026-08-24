# Roll back RaceTime

## Purpose

Return to the prior verified digest/config set without restoring qualification
state or creating a second scheduler. Rollback follows the release manifest's
declared schema strategy; it is not a generic database restore.

## Prerequisites

The failed and prior release manifests, append-only deploy audit, verified
predeploy backup, [status templates](status-comms.md), and a known scheduler
owner. The primary technical operator must identify whether races are active.

## Roles

The primary technical operator chooses and executes routine or emergency
rollback. The Council decision owner owns public messaging. The recovery
custodian is uninvolved unless host/account recovery is separately invoked.

## Inputs and exact commands

```bash
sudo /srv/z1rr-racetime/current/deploy/scripts/rollback.sh \
  --environment production --release-manifest /srv/releases/failed.json \
  --target-manifest /srv/releases/prior.json \
  --change-id Z1RR-ROLLBACK-YYYYMMDD-NNN
```

For an active-race P0 only, add the script's named incident override and exact
incident ID. Never set a broad `FORCE` environment value.

## Safety preflight

Confirm exact prior digests/config, rollback class, current migration leaf,
active-race state, last verified backup, scheduler lock, and public restriction.
A destructive/non-reversible migration refuses rollback and requires the
manifest's forward-fix target. Never select qualification backups or credentials.

## Normal steps

1. For a non-emergency public rollback, announce before reapplying the Caddy
   source restriction. For security/integrity emergencies, restrict first only
   when necessary and announce within five minutes.
2. Stop the new scheduler and prove its process and lock are absent.
3. Acquire the deployment lock and re-run authoritative active-race assessment.
4. Apply the manifest's code-only/reversible rollback or approved forward fix.
5. Restore prior image, config, and scheduler state as one reviewed set. Do not
   restore the database merely to roll back code.
6. Probe internal/public health and the prior scheduler destination before
   starting exactly one scheduler.
7. Send monitoring and resolution notices; keep the verified backup pinned.

## Verification

```bash
sudo /srv/z1rr-racetime/current/deploy/scripts/preflight.sh \
  --environment production --release-manifest /srv/releases/prior.json
sudo docker compose --env-file /etc/z1rr-racetime/deploy.env \
  -f /srv/z1rr-racetime/current/deploy/compose.production.yml ps
```

Verify prior SHA/digests, schema leaf, HTTPS/WSS/login, one scheduler lock, no
duplicate/misdirected room, backup/monitoring continuity, and public restriction
state. Preserve UTC/local timing.

## Rollback and escalation

If the rollback itself fails, leave the maintenance/default-deny barrier in
place, stop schedulers, preserve DB/media, classify P0/P1, and follow
[incidents.md](incidents.md). Use [backup-restore.md](backup-restore.md) only for
actual data loss/corruption, not ordinary release reversal.

## Evidence fields

Incident/change ID, trigger, actor role, timestamps, active races, prior/failed
digests, migration decision, backup ID, scheduler states, restriction/message
timing, command/result hashes, smoke results, findings, final status.

## Secret handling

Do not copy environment, scheduler credential, OAuth token, webhook, cookie, or
database content into the log. Hash only redacted output.

## Last reviewed

Owner: primary technical operator. Last reviewed: 2026-08-24.
