# Z1RR RaceTime Requirements Traceability Matrix

**Date:** 2026-08-22
**Requirements:** `docs/racetime-z1rr/requirements-and-decisions.md`
**Artifacts:** `docs/racetime-z1rr/artifact-register.md`

Status starts `Planned`. During execution, change it only to `Verified ([evidence](...))` with a linked evidence manifest or `Accepted exception (Council-ID, [evidence](...))`. `Implemented` without verification is not a terminal status. The gate validator rejects unknown IDs, missing evidence targets, terminal statuses without evidence, and any row whose stated gate is due but remains `Planned`; G4 closeout rejects every remaining `Planned` row. Under `APPROVED_CATEGORY`, self-hosted-only rows use the recorded outcome-decision ID as their accepted exception rather than pretending they were verified.

Coverage is bidirectional: every registered artifact must appear in at least one FR/NFR row or the architecture/control coverage table below. The validator expands only unambiguous same-prefix ranges such as `SRC-001–006` and `GOV-001–004`; an unreferenced register entry is an error, not an implicit governance exception.

## Core service

| Requirement | Plan/task | Artifacts | Primary automated verification | Gate | Status |
| --- | --- | --- | --- | --- | --- |
| FR-CORE-001 HTTPS/WSS Caddy | Platform Tasks 3–4 | PLT-002, PLT-003 | `test_compose_contract`, `test_caddy_contract`, external HTTPS/WSS smoke | G2 | Planned |
| FR-CORE-002 upstream race semantics | Core Tasks 1, 11; Operations Task 6 | APP-011, OPS-008 | full Django suite and browser lifecycle/dress rehearsal | G2 | Planned |
| FR-CORE-003 one public `z1rr`, user creation | Core Task 7; Operations Task 6 | APP-007 | bootstrap idempotency plus ordinary-user race creation | G2 | Planned |
| FR-CORE-004 Council owner boundary | Core Task 7; Operations Tasks 5–6 | APP-007, OPS-009 | owner permission negative tests and governance evidence | G2/G3 | Planned |
| FR-CORE-005 idempotent bootstrap | Core Task 7 | APP-007 | two-run state equality and Council-change preservation | G0 | Planned |
| FR-CORE-006 health | Core Task 9; Platform Tasks 3, 9 | APP-008, OPS-005 | public/internal health and monitoring tests | G0/G2 | Planned |

## Identity and account lifecycle

| Requirement | Plan/task | Artifacts | Primary automated verification | Gate | Status |
| --- | --- | --- | --- | --- | --- |
| FR-ID-001 any Discord account | Core Tasks 3–4 | APP-004 | Discord `identify` callback tests without guild check | G0/G2 | Planned |
| FR-ID-002 immutable returning identity | Core Tasks 2, 4 | APP-003, APP-004 | repeat login after Discord profile rename | G0/G2 | Planned |
| FR-ID-003 chosen/editable RaceTime name | Core Tasks 4–5 | APP-004, APP-005 | name validation/active-race edit tests | G0/G2 | Planned |
| FR-ID-004 disabled password/email/etc.; operator login | Core Task 5; Platform Task 4 | APP-005, PLT-003 | route policy and public/loopback admin smoke | G0/G2 | Planned |
| FR-ID-005 separate Twitch identity | Core Task 5; Operations Task 6 | APP-005 | link/unlink and streaming-required regression | G0/G2 | Planned |
| FR-ID-006 deletion and audited transfer | Core Tasks 2, 6; Operations Task 1 | APP-003, APP-006, OPS-003 | cascade plus transfer dry-run/collision/audit and access-review contract tests | G0/G2 | Planned |
| FR-ID-007 OAuth state/rate/log safety | Core Tasks 3–5A; Platform Task 1 | APP-004, APP-005, APP-011 | mismatch/replay/expiry/distributed-rate/redaction tests | G0/G2 | Planned |

## TTPBot

| Requirement | Plan/task | Artifacts | Primary automated verification | Gate | Status |
| --- | --- | --- | --- | --- | --- |
| FR-BOT-001 origin/category outcome switch | TTPBot Tasks 1–2 | BOT-001, BOT-002 | approved/self-hosted provider fixtures | G0 | Planned |
| FR-BOT-002 derived REST/WSS/links | TTPBot Tasks 1, 4 | BOT-001, BOT-002 | URL resolution and room-creation tests | G0 | Planned |
| FR-BOT-003 destination-bound state | TTPBot Task 3 | BOT-003 | migration/mismatch/atomic-write tests | G0 | Planned |
| FR-BOT-004 preserve schedule/seed/recovery | TTPBot Tasks 4, 7 | BOT-002, BOT-003, BOT-006 | existing suite plus injected restart integration | G0/G2 | Planned |
| FR-BOT-005 one scheduler | TTPBot Tasks 5–6; Operations Tasks 8, 10 | BOT-004, BOT-005 | `flock` and cutover-state tests/first-room evidence | G0/G3 | Planned |

## Restream

| Requirement | Plan/task | Artifacts | Primary automated verification | Gate | Status |
| --- | --- | --- | --- | --- | --- |
| FR-RESTREAM-001 Z1RR-first two-source UI | Restream Tasks 3, 7 | RST-002, RST-007 | React/Playwright source order and independent state | G0 | Planned |
| FR-RESTREAM-002 independent source config | Restream Tasks 1–3, 8 | RST-001, RST-002, RST-008 | both outcome and invalid config tests | G0 | Planned |
| FR-RESTREAM-003 provider identity propagation | Restream Tasks 2, 4–7 | RST-003–RST-007 | boundary matrix and Playwright E2E | G0/G2 | Planned |
| FR-RESTREAM-004 legacy migration | Restream Task 4 | RST-004 | copied legacy SQLite migration/integrity test | G0 | Planned |
| FR-RESTREAM-005 failure isolation | Restream Tasks 3, 6, 9 | RST-006, RST-007 | concurrent provider REST/WSS failure tests | G0/G2 | Planned |

## LiveSplit

| Requirement | Plan/task | Artifacts | Primary automated verification | Gate | Status |
| --- | --- | --- | --- | --- | --- |
| FR-LS-001 side-by-side identity | LiveSplit Tasks 2, 7–8 | LS-002, LS-006 | reflection/load/settings/credential collision smoke | G0/G2 | Planned |
| FR-LS-002 race/chat/action lifecycle | LiveSplit Tasks 3, 6, 8 | LS-005, LS-006, LS-008 | mock server plus late-G2 restricted-production timer lifecycle after production issuance, using ordinary certificate validation with no override/bypass | G0/G2 | Planned |
| FR-LS-003 correct public PKCE | Core Task 8; LiveSplit Tasks 4–5 | APP-010, LS-003, LS-004 | RFC vector/adversarial server+client E2E | G0/G2 | Planned |
| FR-LS-004 reproducible signed release | LiveSplit Tasks 1, 9–10 | LS-001, LS-007 | clean-room, double build, SBOM, signed hash/update tests | G0/G3 | Planned |

## Operations and recovery

| Requirement | Plan/task | Artifacts | Primary automated verification | Gate | Status |
| --- | --- | --- | --- | --- | --- |
| FR-OPS-001 active-race deploy refusal | Platform Tasks 5, 7; Operations Task 1 | PLT-007, OPS-001 | Django authority, shell state-machine, and deploy/rollback runbook contract tests | G0/G2 | Planned |
| FR-OPS-002 verified predeploy backup | Platform Tasks 6–7 | PLT-007, PLT-008 | injected backup failure blocks promotion | G0/G2 | Planned |
| FR-OPS-003 schedule/retention/alert | Platform Task 6; Operations Tasks 4, 7 | PLT-008, OPS-005, OPS-007 | timer/retention/freshness/restore tests | G0/G2 | Planned |
| FR-OPS-004 RPO/RTO | Operations Task 7 | OPS-007 | measured isolated restore report | G2 | Planned |
| FR-OPS-005 monitoring coverage | Platform Task 9 | OPS-005 | synthetic probe/rule/alert suite | G0/G2 | Planned |
| FR-OPS-006 Discord/email alerts | Platform Task 9; Operations Task 4 | OPS-005 | authenticated redacted fake/live test sink | G2 | Planned |
| FR-OPS-007 empty-host rebuild | Platform Tasks 2, 6, 8; Operations Task 7 | PLT-001, PLT-005, PLT-006, PLT-008, OPS-002, OPS-006, OPS-007 | same-commit ARM64/amd64 manifest, dual-architecture load evidence at recorded shapes, and empty-host amd64 restore/RTO evidence | G2 | Planned |

## Non-functional requirements

| Requirement | Plan/task | Artifacts | Primary automated verification | Gate | Status |
| --- | --- | --- | --- | --- | --- |
| NFR-SEC-001 Django/web security | Core Task 5A; Platform Tasks 1, 4; Operations Task 7 | APP-002, APP-005, PLT-003 | `check --deploy`, route-inventory/Redis throttle, Caddy/ZAP/proxy/cookie tests | G0/G2 | Planned |
| NFR-SEC-002 network/secrets | Platform Tasks 1, 3, 8; Operations Tasks 5, 7, 9 | PLT-002, PLT-004, PLT-006, PLT-010 | Compose/IaC/port/secret scans plus external-app/secret inventory validation | G0/G1/G2/G3 | Planned |
| NFR-SEC-003 pin/scan and js-cookie | Core Task 1; Platform Tasks 2, 10 | APP-012, PLT-001, PLT-005 | npm/container/dependency audit thresholds | G0/G3 | Planned |
| NFR-SEC-004 distributed abuse controls | Core Task 5A; Platform Task 4 | APP-005, PLT-003 | route inventory, exact policy, concurrent real-Redis, unavailable-limiter tests | G0/G2 | Planned |
| NFR-REL-001 migration/rollback safety | Core Task 2; Platform Task 7; Operations Task 1 | APP-003, PLT-007, OPS-001 | migration round trip, rollback-class tests, and runbook contract/tabletop | G0/G2 | Planned |
| NFR-REL-002 Redis non-authority | Operations Tasks 6–7 | APP-011, OPS-008 | Redis restart race lifecycle evidence | G2 | Planned |
| NFR-PERF-001 default-shape four-room/2x load/headroom | Operations Task 7 | OPS-006 | Same workload and k6 resource/correctness report pass on recorded ARM64 production and amd64 recovery shapes; failure records operator optimization-or-resize choice and blocks G2 until full retest passes | G2 | Planned |
| NFR-PRIV-001 data minimization/disclosure | Core Tasks 2–5, 10 | APP-003–APP-005, APP-009 | model/session/log/content tests | G0/G2 | Planned |
| NFR-OSS-001 GPL/source attribution | Source plan; Core Task 10; Platform Task 10 | SRC-001–006, APP-009, PLT-005 | attribution/source-link/archive tests | G0/G3 | Planned |
| NFR-TEST-001 substantive CI | Core Tasks 1, 11; Platform Task 2; all subsystem RC tasks | APP-001, APP-011, PLT-001, PLT-005 | deterministic test settings, separate non-zero SQLite and MariaDB/Redis jobs, and same-commit `linux/arm64` plus `linux/amd64` build/smoke artifacts | G0 | Planned |
| NFR-COST-001 operator-owned resource/consumption controls | Platform Task 8; Operations Tasks 3–4, 12 | PLT-006, PLT-009, OPS-005, OPS-011 | Initial 1-OCPU/6-GB A1 and 50-GB volume plan/inventory; verified entitlement and dated combined forecast; forecast-relative/slope warning and 2,900-hour escalation; separate storage alarms; standing-overage and recorded-shape-change evidence | G1/G4 | Planned |

## Architecture coverage not represented by a single requirement ID

| Architecture topic | Coverage |
| --- | --- |
| Source/branch strategy §6 | Master Task 1 protected `master` mirror/`z1rr-production` promotion; source preservation plan; SRC-001–006 |
| OCI placement/cost §8 | Platform Task 8; Operations Tasks 3–4; PLT-006/009 |
| Break-glass §9.4 | Core Task 5; Platform Task 4; Operations Tasks 5–7 |
| Branding/policies §9.6 | Core Task 10; APP-009 |
| Qualification/build/release §13 | Master Tasks 5–9; Platform Tasks 2–3, 7, 10; Operations Tasks 4–10 |
| Failure handling §17 | Operations Tasks 1, 7, 11; OPS-004/005/008 |
| Verification gates §18 | Launch checklist, GOV-001–004 control documents/validator, Master Tasks 6–10, Operations Tasks 1 and 6–10 |
| Activation/cutover §19 | Requirements gates plus Master Tasks 7–10, Operations Tasks 8–12, and OPS-010 signed go/no-go evidence |
| Legacy archive §12 | Explicitly deferred until G4; separate design/plan required |
