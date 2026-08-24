# Severity, response, and service objectives

## Severity

| Level | Definition/examples | Acknowledge/update | Gate effect |
| --- | --- | --- | --- |
| P0 | active-race data/integrity loss; auth compromise; public admin/secrets; uncontrolled duplicate scheduler | Immediate / 15 min | Stop deploy/cutover, contain, Council/Integrity notification |
| P1 | Production unavailable; DB/verified backup failure; trusted TLS failure; material wrong room/result | 15 min / 30 min | Stop deploy/cutover until fixed and verified |
| P2 | Degraded component, recovery/capacity threshold, accepted non-critical risk | 1 hour / 60 min or material change | Owner/date; G2/G3 requires `COUNCIL-YYYY-NNN` acceptance when open |
| P3 | Warning, forecast variance, housekeeping, documentation gap | One business day / routine | Owner and due date |

P0/P1 evidence never passes. P2 acceptance is organizational risk acceptance,
not permission to waive load, recovery, TLS, integrity, or security launch gates.

## Recovery objectives

- Database RPO: at most six hours; alert after seven hours without a verified point.
- Media RPO: at most 24 hours; alert after 26 hours.
- Production Caddy state: capture after issuance/renewal/material change; retain
  current plus two prior verified generations.
- Target RTO: four hours when compatible OCI capacity is available, measured on
  recorded ARM64 production and Linux/amd64 recovery shapes.
- Redis is non-authoritative. Loss may interrupt live push/chat, but MariaDB-backed
  in-race transitions continue under bounded emergency controls.

## Service and capacity objectives

- G2 load: greater of 2x largest expected TTP room or aggregate four concurrent
  rooms, with 20% CPU and 30% memory headroom on recorded production/fallback.
- HTTPS/WSS: P1 after two consecutive five-minute failures.
- TLS: P2 below 21 days. Disk/inodes: P2 at 80%. Restart loop: P1 at three.
- OAuth: P2 at 20% failures over at least ten requests/five minutes.
- A1: forecast-relative P3 below 2,650 hours, suppression/record at or above it,
  P2 at 2,900 actual/projected; inspect Restream duty-cycle first.

## Maintenance and launch coverage

Routine changes use a declared blackout with zero active races and a verified
rollback target. During launch week, the primary technical operator publishes
availability windows and an emergency contact route; nobody is represented as
on-call without their explicit agreement. TTP schedule blackouts are confirmed
with the TTP/Major Tourney lead.

## Evidence

Every incident/change records UTC/local timestamps, severity, acknowledge/update/
restore times, RPO/RTO or service impact, owner, communications, immutable release
and backup IDs, findings, and result. Secrets/PII are prohibited.

Last reviewed: 2026-08-24 by the primary technical operator.
