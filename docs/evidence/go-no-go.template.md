# RaceTime G3 go/no-go — TEMPLATE

- Decision ID:
- UTC/local decision time:
- Frozen release-identity evidence/hash:
- G2 evidence packet/hash:
- Primary technical operator:
- Council decision owner:
- Competitive Integrity acceptance:
- TTP/Restream/component acceptance:

## Mandatory gates

- [ ] No open P0/P1 and every mandatory G2 row is verified.
- [ ] Exact ARM64/amd64 images, SBOM, provenance, source/license recorded.
- [ ] Fresh production state/certificate and qualification revocation proven.
- [ ] Final backup verified; ARM64/amd64 restore and RPO/RTO pass.
- [ ] Four-room/2x load and headroom pass on recorded shapes.
- [ ] Public denial, one issuer/TLS-ALPN, DNS/reserved IP, admin denial pass.
- [ ] TTPBot/Restream/LiveSplit dress rehearsal passes after production issuance.
- [ ] Scheduler/restriction rollback and public communications rehearsed.
- [ ] Contacts, monitoring, email fallback, public docs/release draft current.

## Findings and risk acceptance

List P2/P3 IDs, owners/dates, Council acceptance IDs where required. P0/P1 is Hold.

## Decision

Choose exactly one:

- `GO`
- `HOLD`

Reason and conditions:

## Rollback triggers

Duplicate/misdirected room, credential/auth failure, trusted TLS/security/integrity
failure, incorrect announcement, missing Restream/result/leaderboard, P0/P1, or
monitoring/backup loss.

## Secret handling

No credentials, tokens, cookies, webhooks, allowlist CIDRs, private contacts,
Terraform state, or recovery material.
