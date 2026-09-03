# Recover from VM loss

## Purpose

Rebuild Raceroom on an empty host after instance/boot-volume loss while meeting
the four-hour RTO when compatible OCI capacity exists and preserving the clean
qualification/production boundary.

## Prerequisites

Current Git source/release identity, multi-platform GHCR digests, Terraform state
recovery record, private Object Storage backups, operator working secrets or the
sealed recovery package, authoritative DNS access, and the account recovery
route below.

## Roles

The primary technical operator commands recovery. The recovery custodian may
release the tamper-evident sealed package only to that operator or a formally
designated replacement; the custodian does not operate OCI. Council receives
incident/status updates.

## Inputs and exact commands

```bash
terraform -chdir=infra/oci init -backend-config=/root/racetime-backend.hcl
terraform -chdir=infra/oci plan -out=/root/racetime-recovery.tfplan \
  -var-file=/root/racetime.tfvars
terraform -chdir=infra/oci show -json /root/racetime-recovery.tfplan
terraform -chdir=infra/oci apply /root/racetime-recovery.tfplan
```

Restore only reviewed resources. Default target is dedicated A1 ARM64 at the
operator-recorded shape. When A1 capacity is unavailable, use the paid
`VM.Standard.E5.Flex` linux/amd64 fallback, initially 1 OCPU/6 GB, and the same
commit's amd64 manifest; record Terraform/forecast/load evidence.

## Safety preflight

1. Declare P0/P1, start RTO clock, stop every scheduler, and preserve DNS.
2. Regain OCI tenancy administration, GitHub organization/GHCR ownership, and
   authoritative DNS via the verified account-level path without relying on the
   lost operator session. If unavailable, invoke the platform's documented
   ownership recovery immediately.
3. If working credentials are unavailable, inspect seal metadata, obtain the
   recovery custodian release, record seal condition/version/fingerprint, and do
   not expose contents to Council or evidence.
4. Verify Terraform backend/state, saved plan, source commit/license, image
   digests/attestations/SBOM, backup manifests, recovery key fingerprint, and
   qualification-ineligible prefixes.
5. Refuse any plan that changes Restream resources or authoritative DNS.

## Normal steps

1. Provision/recover the guarded instance, 50-GB boot, NSG, Bastion, bucket/IAM,
   and alarms from reviewed Terraform.
2. Harden host/firewall while leaving 443 public for TLS-ALPN-01; SSH remains
   Bastion-only. Install Docker and immutable config without printing secrets.
3. Pull exact architecture digests and create fresh named production volumes.
4. Restore newest verified production database, media, and production-Caddy
   state using [backup-restore.md](backup-restore.md).
5. Run migration/preflight, start behind the default-deny restriction, and prove
   HTTPS/WSS/login/admin denial, results/media, backup, alerts, and one scheduler.
6. Re-enable scheduler only after collision probe and record first-room watch.
7. Rotate/retest/reseal any escrow material used.

## Verification

```bash
curl -fsS https://raceroom.z1rracing.com/healthz
docker compose --env-file /etc/z1rr-racetime/compose.env ps
```

Verify RPO, four-hour RTO, exact commit/digests/config, account/category/race/
media/Caddy samples, TLS chain, DNS unchanged, one scheduler, backups/alerts,
and both host/application access recovery routes.

## Rollback and escalation

If capacity or restore fails, keep schedulers stopped and restriction enforced,
retain evidence/scratch safely, and try the reviewed compatible shape/AD path.
Do not weaken gates to meet RTO. Follow [status-comms.md](status-comms.md) cadence.

## Evidence fields

Incident ID, UTC/local timing/RTO, account-recovery path result, custodian release
metadata without secrets, plan hash/actions, shape/architecture/cost forecast,
digests, backup IDs/RPO, samples, DNS/TLS/scheduler/monitoring results, findings.

## Secret handling

Never record recovery credentials, SSH private keys, backup key, Terraform state,
OCI auth, registry token, DNS credential, `.env`, cookies, or sealed contents.

## Last reviewed

Owner: primary technical operator. Last reviewed: 2026-08-24.
