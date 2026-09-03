# Review Raceroom access

## Purpose

Quarterly and prelaunch review of least privilege, break-glass escrow, external
apps, repository/registry/DNS ownership, and revocation routes.

## Prerequisites

Private access inventory, secret fingerprints (never values), Terraform plan/
inventory, GitHub/OCI/DNS ownership exports, external app register, Django
operator audit, scheduler inventory, and sealed-package metadata.

## Roles

The primary technical operator performs and records the review. Council role
owners confirm organizational need for category/moderation access. The recovery
custodian confirms seal/version/fingerprint custody only and has no routine role.

## Inputs and exact commands

```bash
terraform -chdir=infra/oci show -json /root/reviewed.tfplan
docker compose --env-file /etc/z1rr-racetime/compose.env \
  -f deploy/compose.production.yml exec -T web \
  python manage.py deployment_preflight --format json
```

Use `docs/operations/external-app-register.example.md` as the secret-free field
contract; the real register remains private.

## Safety preflight

Confirm the review channel is private, exports are redacted, no secret values or
provider subject IDs are copied, and account-level recovery covers OCI tenancy,
GitHub/GHCR, and authoritative DNS. Do not rotate credentials until every
consumer/recovery path is identified.

## Normal steps

1. Enumerate OCI IAM/dynamic group/Bastion, GitHub owners/rules/environments,
   GHCR package access, DNS account recovery, Discord/Twitch apps, category
   roles, Django superusers, bot clients, webhooks, and scheduler hosts.
2. Match every entry to owner, purpose, scopes, creation/last-used/expiry,
   rotation/revocation and recovery routes. Remove stale access.
3. Confirm only the primary technical operator has routine infrastructure access.
4. Confirm exactly two local superusers: operator break-glass and separate sealed
   escrow recovery; public local login remains unavailable.
5. Verify sealed package metadata, recovery SSH key and backup-key copy, custodian
   instructions, account-level recovery, and rotate/reseal after any use.
6. Rotate due credentials one at a time, probe consumers, revoke prior values,
   and record fingerprints only.

## Verification

```bash
python -m unittest tests.operations.test_runbook_contract -v
```

Verify zero unexplained principals, stale sessions/apps/webhooks/schedulers, public
admin routes, duplicate owners, or missing revocation/recovery paths.

## Rollback and escalation

If rotation breaks a consumer, stop the affected scheduler/integration, restore
the prior credential only if still secure, probe, and retry. Suspected compromise
is P0/P1 under [incidents.md](incidents.md), not a routine rollback.

## Evidence fields

UTC/local review window, operator/reviewer roles, system counts, non-secret entry
IDs/fingerprints, changes/revocations, seal/account-recovery confirmations,
command/export hashes, findings/owners/dates, pass/fail.

## Secret handling

Never store credential values, provider IDs, private keys, tokens, cookies,
webhooks, Terraform state, recovery passwords, or sealed contents in evidence.

## Last reviewed

Owner: primary technical operator. Last reviewed: 2026-08-24.
