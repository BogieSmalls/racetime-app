# Communicate service status

## Purpose

Provide predictable private and public incident/cutover messages without leaking
security details, racer identities, credentials, or unverified conclusions.

## Prerequisites

Incident/change ID, confirmed severity/impact, primary technical operator,
Council public-message owner, public Discord channel, private alert channel with
email fallback, and next-update time.

## Roles

The primary technical operator supplies verified technical facts and timing.
Council owns public wording/decisions. Discord Moderation handles replies and
keeps speculation/PII out. Recovery custodian is never named publicly.

## Inputs and exact commands

```text
INVESTIGATING — [service/feature] is [unavailable/degraded]. Started [time with
timezone]. [Known user impact; no speculation.] Next update by [time]. Ref [ID].

IDENTIFIED — Cause is isolated to [safe component description]. We are [action].
Impact remains [impact]. Next update by [time]. Ref [ID].

MONITORING — Service is restored and checks are passing since [time]. We are
monitoring [safe condition]. Next update by [time]. Ref [ID].

RESOLVED — [service/feature] has been stable since [time]. Impact window was
[start–end]. [Safe user action if any.] Follow-up [when/where]. Ref [ID].

ROLLBACK — We are returning RaceTime/integrations to the prior verified release.
[Canonical host restriction impact.] Next update by [time]. Ref [ID].
```

## Safety preflight

Verify impact and timestamps, remove names/IDs/URLs/logs/security exploit detail,
state uncertainty explicitly, and set a cadence. Do not claim resolution before
monitoring verifies it. Private alerts are not the independent public status path.

## Normal steps

1. Send INVESTIGATING at acknowledgement; P0 every 15 minutes, P1 every 30,
   P2 at material changes/60 minutes, P3 in routine reporting.
2. Send IDENTIFIED only after evidence isolates a cause/action.
3. Send MONITORING after recovery checks pass; continue cadence.
4. Send RESOLVED after the defined stability window and record follow-up.
5. For a non-emergency rollback, announce ROLLBACK before reapplying the public
   Caddy source restriction. For a security/integrity emergency, restrict first
   only when necessary and announce within five minutes.
6. Corrections are explicit and timestamped; do not silently edit history.

## Verification

```text
COMMS_CHECK=PASS id=Z1RR-INCIDENT-YYYYMMDD-NNN
required=ack,cadence,impact,resolution timestamps=recorded secrets=absent
```

Confirm message link/hash, promised cadence, public/private separation, rollback
ordering, and zero secret/PII canary matches.
Failed verification blocks a resolution message and keeps the declared cadence.

## Rollback and escalation

If a message exposes a secret, delete/redact where platform permits, rotate the
secret, preserve a non-secret incident record, and treat as P0/P1. If facts are
wrong, post a correction immediately. Technical containment follows
[incidents.md](incidents.md), not the communications channel.

## Evidence fields

Incident/change ID, UTC/local posted timestamps, channel class (not webhook),
template type, safe message hash/link, author roles, impact/cadence, correction,
secret scan, expected/observed result, findings.

## Secret handling

Never include racer/provider IDs, IP allowlists, exploit detail, raw errors,
tokens, cookies, webhooks, credentials, private contacts, or recovery metadata.

## Last reviewed

Owner: primary technical operator. Last reviewed: 2026-08-24.
