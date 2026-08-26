# Raceroom monitoring and alert response

## Purpose

Operate the secret-safe host probe and signed Discord alert adapter for
`raceroom.z1rracing.com`. This runbook covers normal checks, cost/utilization
signals, validation, recovery notices, and the first response to an alert. It
does not authorize G1 resources, public launch, or a production credential.

## Prerequisites

- A deployed, immutable Raceroom release and its reviewed Compose manifest.
- Root access through OCI Bastion and the account-recovery route in
  [vm-loss.md](vm-loss.md).
- A root-owned monitoring config that conforms to
  [`config.schema.json`](../../deploy/monitoring/config.schema.json).
- A root-owned internal-readiness bearer token, alert HMAC key, Discord webhook,
  and alert state directory; none may be stored in Git.
- Secret-free, atomic JSON snapshots for application, backup, and OCI metrics.
  The application snapshot contains only aggregate DB growth and OAuth counts;
  the backup snapshot is derived from verified manifests in
  `/var/lib/z1rr-racetime/backup-status`; the OCI snapshot is derived from the
  tenancy Usage/Monitoring APIs and the accepted forecast. Their producer must
  write a temporary file, `fsync`, then rename it into place.
- OCI Terraform alarms and ONS Discord-relay/email-fallback subscriptions from
  `infra/oci/monitoring.tf`. The in-host probe complements those alarms; it is
  not their only path.

## Roles

The primary technical operator owns configuration, response, forecast updates,
and evidence. The Council decision owner receives P0/P1 status and public-impact
communications. The recovery custodian only releases the sealed recovery
package under its custody instructions and has no routine monitoring access.

## Inputs and exact commands

Set paths without printing their contents:

```bash
export RACETIME_MONITOR_CONFIG=/etc/z1rr-racetime/monitoring.json
export RACETIME_MONITOR_RULES=/srv/z1rr-racetime/current/deploy/monitoring/rules.example.json
export RACETIME_MONITOR_OUTPUT=/var/lib/z1rr-racetime/monitoring/latest.json
export RACETIME_ALERT_PAYLOAD=/run/z1rr-racetime/alert.json
```

The config names the secret environment variables; the service manager loads
their values from a `0600` root-owned environment file. Do not type values into
a shell history. Run the probe as the service account with only the minimum
Docker-inspection, metrics-file, and output-directory access:

```bash
/srv/z1rr-racetime/venv/bin/python \
  /srv/z1rr-racetime/current/deploy/monitoring/probe.py \
  --config "$RACETIME_MONITOR_CONFIG" \
  --rules "$RACETIME_MONITOR_RULES" \
  --output "$RACETIME_MONITOR_OUTPUT"
```

A trusted local dispatcher extracts one normalized event, serializes it with
sorted keys and compact separators, signs the exact bytes with HMAC-SHA256, and
places only the signature in `RACETIME_ALERT_SIGNATURE`. Deliver it with:

```bash
/srv/z1rr-racetime/venv/bin/python \
  /srv/z1rr-racetime/current/deploy/monitoring/alert.py \
  --config "$RACETIME_MONITOR_CONFIG" \
  --payload "$RACETIME_ALERT_PAYLOAD"
```

The alert adapter allows only the configured HTTPS Discord host, accepts at
most 64 KiB, authenticates before parsing, redacts nested secret-like input,
uses bounded retries, deduplicates active events, and delivers recovery
notices. It prints only `{"result":"delivered|deduped"}`, never the webhook.

## Safety preflight

1. Confirm the config, secret environment file, alert state, metric snapshots,
   and output directory are root-owned, non-symlink paths with no group/world
   write permission.
2. Confirm `public_origin`, WSS URL, and TLS host are exactly
   `raceroom.z1rracing.com`; internal readiness must resolve to loopback.
3. Confirm the webhook allowlist is the exact reviewed Discord hostname and
   that `max_attempts` is no more than five.
4. Confirm metric inputs contain aggregates only—no Discord IDs, access tokens,
   cookies, request bodies, OAuth codes, webhook URLs, or database rows.
5. Confirm OCI custom alarms and email fallback remain enabled before changing
   the local probe. Never disable both paths in one maintenance window.
6. During G0, use fake adapters/sinks only. Do not create a webhook, query OCI,
   alter DNS, or contact the canonical host.

## Normal steps

1. Refresh application, backup, and OCI aggregate snapshots atomically.
2. Run the probe every five minutes. Keep only stable status/metric codes and
   never retain HTTP, OAuth, readiness, or WebSocket response bodies.
3. Persist consecutive HTTPS/WSS failure counts outside the probe output and
   pass them into the next evaluation. Page only after two consecutive failures.
4. For each firing event, build the exact v1 alert envelope, sign its canonical
   bytes, and invoke the adapter. When a previously firing condition clears,
   send the same stable `component:CODE` event ID with `status: resolved`.
5. Review the daily dashboard for DB growth, restarts, headroom, backup age,
   TLS, OAuth failure rate, A1 slope, Object Storage, retained volumes, and
   normalized billing events even when no P0/P1 alert fires.
6. Reconcile the first complete billing cycle and every cost/utilization
   threshold crossing with the dated forecast. These are authorized operating
   expenses; the required action is diagnosis and forecast reconciliation, not
   a Council cost approval.

## Thresholds and first response

- HTTPS/WSS: two consecutive failures are P1. Verify Caddy, web, certificate,
  DNS, and network reachability without weakening the source restriction.
- Containers: unhealthy/stopped or three restarts is P1. Check web/racebot/DB/
  Redis/Caddy logs through the redacting log path; do not paste raw logs.
- Host: CPU 80%, memory 70%, disk 80%, or inodes 80% is P2. Preserve the 20%
  CPU and 30% memory load-gate headroom; stop growth before disk/inode exhaustion.
- Database: at least 1 GiB growth in 24 hours is P3 and requires attribution.
- Backups: DB age over seven hours or verification failure is P1; media age over
  26 hours is P2. Keep current plus two verified production Caddy generations.
- TLS: fewer than 21 days remaining is P2. Check persistent Caddy state and the
  TLS-ALPN-01 renewal path; do not enable HTTP-01 or a second issuer.
- OAuth: at least ten requests and 20% errors in five minutes is P2. Check
  provider availability, redirect exactness, throttling, and abuse without PII.
- A1 forecast below 2,650 hours: non-paging P3 when month-end projection or the
  72-hour slope exceeds the accepted forecast by `max(100 hours, 5%)`. Inspect
  Restream sleep automation, encoders, and control planes first because the OCI
  allowance is tenancy-wide. At/above a 2,650-hour accepted forecast, record
  utilization/expected overage and suppress that near-duplicate warning.
- A1 actual/projected 2,900 hours: P2 escalation before the 3,000-hour allowance.
- Retained volumes: P3 at $4.61 and P2 at $6.61 versus the $3.61 baseline.
- Object Storage: P3 at 75% and P2 at 90% of verified byte/request entitlements.
- Any normalized billing event: P3 attribution/reconciliation; it is not by
  itself evidence of a Raceroom fault.

## Verification

Run the fake-sink contract without network access:

```bash
/srv/z1rr-racetime/venv/bin/python -m unittest \
  tests.platform.test_monitoring -v
```

Before G2, use the qualification allowlist to verify HTTPS, WSS, public admin
denial, internal readiness, a synthetic firing alert, dedupe, bounded retry,
email fallback, and recovery notice. Search captured output for seeded canaries;
any canary is a P1 and blocks G2. Record the observed alert timestamp and safe
event ID, not the message/webhook/secret.

## Rollback and escalation

If a new probe version fails, restore the prior immutable release and rule file;
preserve the alert state so recovery notices still correlate. Keep OCI alarms
and email fallback active. If Discord delivery fails after bounded retries,
treat the email fallback as authoritative and investigate the relay/webhook.
Follow [incidents.md](incidents.md) for P0/P1 response and
[status-comms.md](status-comms.md) for public impact. Monitoring failure never
authorizes bypassing TLS, exposing admin, printing secrets, or launching with a
failed backup/load/security gate.

## Evidence fields

Record UTC/local timestamps, release commit and image digest, config/rules hash,
safe event/test IDs, expected and observed status, retry/dedupe/recovery result,
alert-channel and email-fallback receipt timestamps, canary-search result,
requirements `FR-CORE-006`, `FR-OPS-003`, `FR-OPS-005`, `FR-OPS-006`, artifact
`OPS-005`, findings with severity/owner/date, and pass/fail. Attach only redacted
outputs whose hashes appear in the evidence manifest.

## Secret handling

Never commit or print the internal token, alert HMAC key, Discord webhook, OCI
credentials, cookies, OAuth codes, or request bodies. Store secrets in root-owned
files or the approved external store. Rotate the HMAC key and webhook after any
suspected disclosure; clear only their affected dedupe state, send a test and
recovery pair, and update the private access register. Do not place secret values
or their command lines in evidence.

## Last reviewed

Owner: primary technical operator. Last reviewed: 2026-08-24. Review after any
threshold, provider, alert path, cost model, or recovery change and at least
quarterly.
