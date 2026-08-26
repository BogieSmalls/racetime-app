# Recover or transfer an identity

## Purpose

Recover operator access or perform an audited Discord external-identity transfer
without changing race history, accepting a collision, or exposing a provider ID.

## Prerequisites

Bastion/local admin access, two break-glass application accounts (one normal
operator account and one sealed recovery account), verified claimant evidence,
and a change/incident ID. Public password reset/email login remains disabled.

## Roles

The primary technical operator verifies and executes transfers. Competitive
Integrity reviews disputed ownership. The recovery custodian only releases the
sealed recovery account under [vm-loss.md](vm-loss.md).

## Inputs and exact commands

```bash
docker compose --env-file /etc/z1rr-racetime/compose.env \
  -f deploy/compose.production.yml exec -T web \
  python manage.py transfer_external_identity \
  --provider discord --subject-file /run/z1rr-transfer/subject \
  --target-user-id TARGET --reason-id Z1RR-IDENTITY-YYYYMMDD-NNN --dry-run
```

Repeat without `--dry-run` only after the collision/lifecycle report passes.
Provider subject input is a root-owned temporary file and is securely removed.

## Safety preflight

Verify local admin route is not public, claimant/target account, provider,
existing identity owner, no `(provider, subject)` or `(provider, user)` collision,
active-race impact, reason ID, backup freshness, and audit destination. Refuse
manual database edits or transfer to an already-linked user.

## Normal steps

1. Record a non-secret case ID and verification basis.
2. Run dry-run; compare source/target safe internal user IDs and dependent row
   counts. Do not copy the Discord subject to evidence.
3. Take verified DB backup, execute once in a transaction, and record audit hash.
4. Revoke affected sessions/OAuth tokens and require fresh Discord login.
5. Verify the returned account, editable Raceroom name, Twitch link separation,
   historical race ownership, and collision constraints.
6. For deletion, use the documented account lifecycle so ExternalIdentity
   cascades and backup expiry—not ad-hoc row deletion—governs residual data.

## Verification

```bash
python manage.py test racetime.tests.identity.test_transfer_command \
  --settings=project.settings.test -v 2
```

Verify exactly one Discord identity per user/subject, immutable subject on profile
rename, audit reason, session revocation, race history, and no public admin path.

## Rollback and escalation

A failed transaction changes nothing. For a verified incorrect transfer, stop
account access, preserve audit, restore ownership only through a second audited
transfer, and classify the incident. Never restore the whole DB for one identity.

## Evidence fields

Case/reason ID, UTC/local timestamps, roles, safe internal user IDs, provider
name, dry-run counts, backup/audit hashes, session revocation, verification,
findings/result. Provider subjects and Discord IDs are prohibited.

## Secret handling

Do not record provider subject, Discord profile data, OAuth code/token, cookie,
break-glass password, subject-file content, or claimant documents.

## Last reviewed

Owner: primary technical operator. Last reviewed: 2026-08-24.
