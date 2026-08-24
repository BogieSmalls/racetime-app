# Respond to RaceTime incidents

## Purpose

Classify, contain, recover, communicate, and preserve evidence for service,
integrity, security, provider, capacity, and cost incidents.

## Prerequisites

[Severity/SLO](../operations/severity-and-slo.md), contact roster, monitoring and
email fallback, Bastion access, immutable release/backup identity, rollback and
status runbooks, and an incident ID.

## Roles

The primary technical operator is incident commander and sole routine executor.
Council owns public/community decisions; Competitive Integrity owns race-record
rulings; Discord Moderation owns community enforcement. The recovery custodian
only handles sealed-package release.

## Inputs and exact commands

```bash
python deploy/monitoring/probe.py --config /etc/z1rr-racetime/monitoring.json \
  --rules deploy/monitoring/rules.example.json \
  --output /var/lib/z1rr-racetime/monitoring/incident.json
sudo deploy/scripts/preflight.sh --environment production \
  --release-manifest /srv/releases/current.json
```

Open `Z1RR-INCIDENT-YYYYMMDD-NNN`; all command output is redacted before hashing.

## Safety preflight

Establish P0–P3, active races, data/auth/integrity exposure, blast radius,
scheduler state, backup freshness, last good release, communications cadence,
and whether containment risks data loss. Preserve clocks/logs/state; do not run
destructive remediation before evidence and an exact target are secured.

## Normal steps

1. Acknowledge, name commander, timestamp, classify, and send INVESTIGATING.
2. Contain only affected paths; keep authoritative MariaDB state and backups.
3. Diagnose by class:
   - Discord/Twitch provider or OAuth: stop affected login/link path, preserve
     existing sessions as policy permits, verify redirects/rate limits.
   - MariaDB/Redis: DB is authoritative; Redis loss degrades push/chat but
     in-race transitions continue under emergency controls.
   - racebot or duplicate scheduler: stop all new room creation, prove locks/
     processes, select one reviewed owner before restart.
   - disk/inodes/CPU/memory: stop growth, preserve DB/media; no blind deletion.
   - TLS/DNS/Caddy: keep 443 reachable for TLS-ALPN-01, one issuer, restriction;
     never enable HTTP-01 or public admin.
   - backup/restore: preserve last verified point and block deploy.
   - provider/API/Restream: isolate that provider without corrupting historical
     persistence or the other logical source.
   - auth/security/integrity: restrict first when necessary, revoke affected
     credentials/sessions, preserve audit, involve Competitive Integrity.
   - OCI capacity/reclamation/VM loss: follow [vm-loss.md](vm-loss.md).
   - cost/billing: inspect Restream duty-cycling first, attribute and update the
     forecast; authorized overage is not itself an outage.
4. Recover using [rollback.md](rollback.md), [backup-restore.md](backup-restore.md),
   or a reviewed forward fix. Verify and send MONITORING then RESOLVED.

## Verification

```bash
python scripts/ops/validate-evidence.py /srv/evidence/incident.json
```

Verify service/integrity/security, exact release/schema, results/media, one
scheduler, backup/alerts, credential revocation, and promised status timestamps.

## Rollback and escalation

Unsuccessful remediation returns to the last verified safe barrier/config; it
does not stack guesses. P0/P1 immediately blocks deploy/cutover. Rollback public
restriction/messaging follows [status-comms.md](status-comms.md).

## Evidence fields

Incident/severity, UTC/local timeline, roles, active races/impact, safe metrics,
release/config/backup IDs, actions/results/hashes, credentials revoked by
fingerprint only, communications, data-loss bound, findings and follow-ups.

## Secret handling

Never paste raw logs, request bodies, identities, OAuth codes/tokens, cookies,
webhooks, database rows, private keys, Terraform state, or recovery contents.

## Last reviewed

Owner: primary technical operator. Last reviewed: 2026-08-24.
