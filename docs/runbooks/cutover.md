# Cut over RaceTime publicly

## Purpose

Execute the G3 public change by removing only the canonical-host source
restriction, publishing reviewed artifacts/docs, and moving exactly one TTPBot
scheduler. DNS does not change at launch.

## Prerequisites

Signed G2 packet, Council G3 go/no-go, frozen release identities, verified final
backup, public docs/LiveSplit draft, contact roster, blackout, one scheduler
lock, cutover log, rollback target, and healthy monitoring/email fallback.

## Roles

Council decision owner records Go/Hold and public message. The primary technical
operator is cutover commander and sole routine executor. Component/Integrity
leads accept their observable outcomes; recovery custodian has no cutover access.

## Inputs and exact commands

```bash
python scripts/ops/collect-release-identities.py \
  --config /etc/z1rr-racetime/release-paths.json
python scripts/ops/validate-traceability.py --gate G3
python scripts/ops/scheduler-cutover.py --dry-run \
  --config /etc/z1rr-racetime/scheduler-cutover.json
```

Use `docs/evidence/go-no-go.template.md` and `cutover-log.template.md`. Execute
one timestamped action at a time; do not batch commands.

## Safety preflight

Revalidate identities, G2 evidence/no P0/P1, backup, production TLS/ordinary
trust, DNS/reserved IP, public-denial state, HSTS 300, one old scheduler, new
config collision probe, Discord/status paths, rollback timing, and active races.
Hold on any mismatch; never change DNS to fix a cutover problem.

## Normal steps

1. Record final Go/Hold, actor and UTC/local timestamp. On Hold, change nothing.
2. Announce maintenance/launch and start the append-only cutover log.
3. Remove only the Caddy source-IP restriction; raise HSTS to the reviewed public
   value without preload. Verify assets/OAuth/WSS/admin denial and monitoring.
4. Publish public docs and signed LiveSplit release/update metadata.
5. Stop/disable old TTPBot scheduler; prove process/lock absent. Install new
   release/config/state as one set, run provider/collision preflight, then start
   exactly one scheduler/lock.
6. Observe first scheduled room: canonical URL/category/goal/policy/time, one
   announcement, browser/LiveSplit, Restream persistence/reload, finish/record/
   leaderboard. Record before proceeding.
7. Send launch complete and retain immediate rollback readiness.

## Verification

```bash
python scripts/ops/verify-dns.py --origin https://racetime.z1rracing.com \
  --expected-ip-file /root/racetime-reserved-ip
python scripts/ops/validate-evidence.py /srv/evidence/cutover.json
```

Verify DNS unchanged, trusted cert/SAN, HTTPS/WSS, public route/admin denial,
HSTS, one scheduler/room/announcement, integrations/result/leaderboard, backup,
alerts, and artifact publication hashes.

## Rollback and escalation

Duplicate/misdirected room, auth failure, bad announcement, missing persistence/
result, TLS/security/integrity, or P0/P1 triggers [rollback.md](rollback.md).
Non-emergency notice precedes reapplying restriction; emergency notice follows
within five minutes. Stop new scheduler before restoring old set.

## Evidence fields

Go/no-go ID, UTC/local per-action actor/start/end/result/rollback status, frozen
identities, backup, DNS/TLS/restriction/HSTS, publication hashes, scheduler states,
first-room/integration acceptance, messages, alerts, findings/result.

## Secret handling

Never log apps/secrets, allowlist CIDRs, scheduler/env state, tokens, cookies,
webhooks, DNS credentials, private release key, or Terraform state.

## Last reviewed

Owner: primary technical operator. Last reviewed: 2026-08-24.
