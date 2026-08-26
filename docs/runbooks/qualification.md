# Qualify the restricted Raceroom candidate

## Purpose

Execute G2 qualification on the canonical host without making it public, then
discard qualification state and prove fresh production state/certificate before
programmatic-client evidence.

## Prerequisites

Explicit G1 activation, reviewed allowlist, immutable release identities, guarded
OCI/DNS/apps/secrets, staging/production ACME configs, disposable qualification
volumes, fresh production volume names, evidence validators, and test roster.

## Roles

The primary technical operator executes and records. Competitive Integrity owns
race-record acceptance; component leads accept their integrations. Council does
not substitute a waiver for failed security/load/recovery gates.

## Inputs and exact commands

```bash
python scripts/ops/qualify-candidate.py run \
  --config /root/qualification-adapters.json \
  --stage qualification_core \
  --activation-record /root/g1-activation.json
python scripts/ops/finalize-production.py \
  --config /root/fresh-production-transition.json --apply \
  --activation-record /root/g1-activation.json \
  --change-id Z1RR-G2-YYYYMMDD-NNN
```

The qualification controller executes one explicitly configured adapter; every
mutating adapter requires the root-owned G1 activation record. The finalization
controller is dry-run by default and requires `--apply`, the activation record,
and a change ID. The canonical allowlist remains in force and G3/public is refused.

## Safety preflight

Confirm canonical and redirect-alias A records resolve to the same reserved IP,
no AAAA/CNAME exists, 443 is public for TLS-ALPN-01 on both names, and Caddy
default-deny precedes every route, staging issuer has `ca == test_ca`, HTTP-01 is
disabled, state generation is qualification-only, schedulers are fake/disabled,
and no ordinary trust store contains the staging root.

## Normal steps

1. Collect immutable identities and run qualification core/governance on
   disposable state. Browser/server-side checks may use a per-process staging CA.
2. Run failure/security/load/backup-restore on recorded ARM64 and amd64 shapes.
   TTPBot/Restream/LiveSplit final evidence remains pending.
3. Enter maintenance/default-deny, stop writes/schedulers, seal qualification
   backup under restore-ineligible `qualification/`, and never promote its state.
4. Create fresh production DB/Redis/media/secret/Caddy volumes. While stopped,
   repoint the application, revoke qualification credentials, invalidate
   qualification sessions/tokens, bootstrap through the local command, and prove
   qualification credentials/state cannot authenticate or restore.
5. Start behind the hard barrier. Switch to the persistent production Caddy
   volume with one production issuer (`ca == test_ca`), TLS-ALPN-only. Enforce a
   bounded issuance deadline; no fallback/issuer crossover is accepted.
6. After ordinary production-chain trust is proven, restore the normal G2
   allowlist and run TTPBot, Restream, and LiveSplit integrations with no CA bypass.
7. Complete dress rehearsal, production-Caddy backup/restore, cutover rehearsal,
   evidence validation, and P0/P1 review. Keep public restriction.

## Verification

```bash
python scripts/ops/validate-evidence.py /srv/evidence/dress-rehearsal.json
python scripts/ops/validate-traceability.py --gate G2
```

Verify issuer pin, certificate/SAN/CT, public denial, fresh volumes/credentials,
revocations, production-only backup eligibility, four-room/2x headroom, ARM64/
amd64 restore, end-to-end room/result, and no G3/public state.

## Rollback and escalation

Any failure leaves hard barrier and schedulers stopped. Qualification state is
never a production rollback. Fix/retry the failed stage with a new immutable
attempt. A P0/P1, untrusted TLS, failed recovery/load gate, or client CA bypass
blocks G2/G3 without waiver.

## Evidence fields

Activation/change IDs, UTC/local stage/attempt times, identities/hashes, allowlist
record hash, volume generations, issuer/adapted-config/certificate proof, test
commands/results, revocations, load/RPO/RTO, findings/acceptance/result.

## Secret handling

Never store allowlist contents, credentials, CA private state, OAuth codes/tokens,
cookies, qualification/production secrets, webhook, or Terraform state in Git or
evidence. Staging roots are process-scoped only.

## Last reviewed

Owner: primary technical operator. Last reviewed: 2026-08-24.
