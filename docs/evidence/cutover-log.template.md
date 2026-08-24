# RaceTime cutover log — TEMPLATE

- Cutover/change ID:
- Go/no-go evidence/hash:
- Frozen release identity/hash:
- Primary technical operator:
- UTC/local start:
- Rollback target:

Record one completed row before beginning the next action.

| Seq | Action ID | Actor role | UTC/local start | UTC/local end | Expected | Observed | Evidence hash | Rollback status | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | final-preflight | | | | | | | n/a | |
| 2 | final-backup | | | | | | | pinned | |
| 3 | remove-restriction/HSTS | | | | | | | ready | |
| 4 | publish-docs/LiveSplit | | | | | | | ready | |
| 5 | stop-old-scheduler | | | | | | | ready | |
| 6 | start-new-scheduler | | | | | | | ready | |
| 7 | first-room-observation | | | | | | | ready | |
| 8 | resolution-message | | | | | | | n/a | |

## Findings/decision changes

Append only; corrections name the prior row and timestamp. Never erase history.

## Secret handling

Record safe IDs/hashes only. Never include credentials, tokens, cookies, webhook,
allowlist CIDRs, scheduler environment, Terraform state, or recovery material.
