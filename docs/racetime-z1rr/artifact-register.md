# Z1RR RaceTime Launch Artifact Register

**Date:** 2026-08-22
**Control document:** `docs/racetime-z1rr/requirements-and-decisions.md`

This register is the definition of deliverables. An artifact is not complete because a file exists; its acceptance evidence must also exist. `G0` artifacts may be built locally while the Racetime.gg request is pending. `G1+` artifacts require the corresponding decision gate.

## 1. Planning and source-control artifacts

| ID | Gate | Repository/path | Artifact | Acceptance evidence |
| --- | --- | --- | --- | --- |
| GOV-001 | G0 | `docs/racetime-z1rr/requirements-and-decisions.md` | Requirements, ADRs, activation boundary | Council/technical review recorded; no unresolved launch-blocking decision |
| GOV-002 | G0 | `docs/racetime-z1rr/artifact-register.md` | This deliverable register | Every requirement maps to at least one artifact and verification |
| GOV-003 | G0 | `docs/racetime-z1rr/launch-readiness-checklist.md` | Gate-by-gate go/no-go checklist | Named approvers and evidence links completed before G3 |
| GOV-004 | G0 | `docs/racetime-z1rr/requirements-traceability.md`, `scripts/ops/validate-traceability.py`, `tests/operations/test_traceability.py` | Requirement-to-artifact verification ledger and gate validator | Fixture tests reject unknown IDs, broken/missing evidence, invalid status, unambiguous-range errors, orphan registered artifacts, and due `Planned` rows; current gate passes |
| SRC-001 | G0 | `docs/upstream/UPSTREAM_BASELINE.json` | Machine-readable upstream default branch/commit, refs, fetch date, repository URLs | Schema test proves `branches[default_branch] == upstream_head` and validates every recorded ref |
| SRC-002 | G0 | `artifacts/source/racetime-app-<date>.bundle` (not Git-tracked) | Complete Git bundle of all reachable refs | `git bundle verify`; SHA-256 in manifest; restore rehearsal |
| SRC-003 | G0 | `artifacts/source/racetime-app-wiki-<date>.bundle` or absence record | Wiki preservation | Bundle verifies or GitHub reports no wiki repository, with dated evidence |
| SRC-004 | G0 | `docs/upstream/SHA256SUMS`, `docs/upstream/RESTORE.md` | Checksums and restoration procedure | Empty-directory restore checks out recorded default branch and exact HEAD, then verifies all refs |
| SRC-005 | G0/G1 | GitHub fork configuration | `origin` fork and read-only-intent `upstream` remote | Guard verifies advertised upstream default/HEAD, gate-specific fork default, exact URLs, and disabled upstream push |
| SRC-006 | G0/G1 | `.github/workflows/upstream-drift.yml` | Locally contract-tested at G0; dispatchable and scheduled after G1 default-branch change | G0 comparator/workflow-contract tests pass; G1 manual dispatch and schedule smoke pass; no write scope/automatic merge |

## 2. Core application and identity artifacts

| ID | Gate | Repository/path | Artifact | Acceptance evidence |
| --- | --- | --- | --- | --- |
| APP-001 | G0 | `project/settings/test.py`, `racetime/tests/settings/` | Deterministic test settings and settings tests | `manage.py test racetime.tests.settings` passes without external services |
| APP-002 | G0 | `project/settings/production.py`, `.env.production.example` | Fail-closed production settings/env schema | Missing/invalid dedicated throttle key or exact fixed Caddy `/32` fails startup; key is independent from Django; `check --deploy` clean with fixture env |
| APP-003 | G0 | `racetime/models/identity.py`, migration `0082_externalidentity.py` | Provider-neutral external identity model | Migration round-trip; uniqueness/cascade tests pass |
| APP-004 | G0 | `racetime/discord.py`, `racetime/views/discord_auth.py`, routes/templates | Discord authorization, callback, name selection | Success, denial, expiry, state mismatch/replay, duplicate callback, provider failure tests pass |
| APP-005 | G0 | `racetime/forms.py`, account templates/routes, `racetime/throttling.py` | Public account-surface and endpoint-abuse policy | Disabled routes absent/404; profile/Twitch work; route inventory and real-Redis concurrency/rate-limit tests pass |
| APP-006 | G0 | `racetime/management/commands/transfer_external_identity.py` | Audited recovery/identity-transfer command | Dry-run, collision, confirmation, evidence, actor, and audit tests pass |
| APP-007 | G0 | `racetime/management/commands/bootstrap_z1rr.py` | Idempotent site/category/goal/owner bootstrap | Exact Site identity; sole public `z1rr`; two runs identical; Council changes not overwritten |
| APP-008 | G0 | `racetime/views/health.py`, route/tests | Public liveness and internal readiness checks | Public response is minimal; DB/Redis/racebot failures classified without sensitive output |
| APP-009 | G0 | templates/static assets and `docs/policies/*.md` | Z1RR branding, attribution, privacy, acceptable use, deletion/contact text | Link/branding snapshot tests; legal/operations review |
| APP-010 | G0 | `racetime/views/user.py`, OAuth tests | Correct public-client PKCE policy for Z1RR LiveSplit | S256 success; plain/missing/wrong verifier/replay rejected; stock compatibility exception cannot match Z1RR app |
| APP-011 | G0 | `project/settings/ci.py`, `racetime/tests/`, `.github/workflows/test.yml` | Distinct fast and service-backed CI baseline | Non-zero SQLite job and non-zero MariaDB/Redis job both pass service probes, migrations, static build, lint/security checks |
| APP-012 | G0 | `package.json`, `package-lock.json` | Front-end dependency remediation | `npm audit --omit=dev` has no high/critical findings; UI smoke passes |

## 3. Production platform artifacts

| ID | Gate | Repository/path | Artifact | Acceptance evidence |
| --- | --- | --- | --- | --- |
| PLT-001 | G0 | `Dockerfile`, `.docker/start-production`, `.docker/healthcheck` | Multi-stage `linux/arm64` and `linux/amd64` web/racebot images from one commit | Both variants run non-root, contain no dev server/debug toolbar activation, and pass the same healthcheck |
| PLT-002 | G0 | `deploy/compose.production.yml` | Internal web/racebot/MariaDB/Redis/Caddy/maintenance stack | `docker compose config` clean; fixed two-member proxy IPAM and separate data network; no DB/Redis host ports |
| PLT-003 | G0 | `deploy/Caddyfile` | HTTPS/WebSocket/static/media ingress and loopback-only admin listener | Caddy validation plus HTTP/WSS tests; `/admin` is unavailable publicly |
| PLT-004 | G0 | `.env.production.example`, `deploy/env/ci.env`, `deploy/validate-config.py` | Secret-free environment contracts and validator | Placeholder/unknown/insecure values fail; fixture production config and fixed Caddy `/32` match pass |
| PLT-005 | G0 | `.github/workflows/container.yml`, `.github/workflows/release.yml` | Multi-platform immutable build, scan, SBOM, provenance and release metadata | One SHA-tagged manifest references verified `linux/arm64` and `linux/amd64` digests from the same commit; SBOM, scan threshold, and provenance attestation pass for both |
| PLT-006 | G0 | `infra/oci/*.tf`, `infra/oci/*.tfvars.example`, `infra/oci/README.md` | Versioned OCI network/instance/import/bucket/IAM/alarms definitions | `terraform fmt/check/validate`; saved plan reviewed; no apply before G1 |
| PLT-007 | G0 | `deploy/scripts/preflight.sh`, `deploy/scripts/deploy.sh`, `deploy/scripts/rollback.sh` | Race-aware release and rollback tooling | Shell tests cover active-race refusal, backup gate, migration failure, smoke failure, override audit |
| PLT-008 | G0 | `deploy/backup/backup.sh`, `verify.sh`, `restore-test.sh`, retention tests | Encrypted DB/media backup and isolated restore automation | Local fake-OCI tests plus decrypt/integrity/retention tests pass |
| PLT-009 | G1 | OCI resource inventory/evidence | Dedicated `racetime` A1 VM initially at 1 OCPU/6 GB with new 50-GB Balanced boot volume, NSG, Bastion, private bucket, dynamic group/policy, and alarms | Read-only inventory matches the reviewed Terraform plan; verified 3,000/18,000 entitlement, default 744-hour RaceTime floor, and dated combined A1 forecast are recorded; forecast-relative utilization/slope warning, 2,900-hour escalation, separate retained-volume $3.61 +$1/+$3 alarms, and Object Storage 75%/90% alarms exist |
| PLT-010 | G1 | DNS/OAuth/secrets inventories (private) | Production secret and external-app records | Two-operator access, redirect URI review, secret scan and recovery-copy confirmation |

## 4. Restream artifacts (`Z1RR.Restream`)

| ID | Gate | Repository/path | Artifact | Acceptance evidence |
| --- | --- | --- | --- | --- |
| RST-001 | G0 | `lib/racetime.js` | Origin-aware, validated REST client | Two-origin unit tests, relative URL resolution, timeout/rate-limit behavior |
| RST-002 | G0 | `mini/server/race-info/racetime-providers.ts` | Validated provider/logical-source registry | Approved/self-hosted/invalid/duplicate configuration tests |
| RST-003 | G0 | `mini/server/race-info/race-reference.ts` | Provider-qualified identity parser/serializer | Round-trip, host-confusion, legacy default, canonical URL tests |
| RST-004 | G0 | `mini/server/db/broadcast-drafts.ts` | Additive persisted provider/category/canonical URL fields | Legacy database migration and historical URL preservation tests |
| RST-005 | G0 | routes, broadcast sync, crops, tracker bridge/manager | Provider identity propagation through server paths | Contract tests prove identity survives every boundary |
| RST-006 | G0 | `mini/server/race-info/racetime-realtime.ts` | Provider-aware WSS connection and origin allowlist | Relative/absolute WSS, reconnect, disallowed-host, and provider-isolation tests |
| RST-007 | G0 | race browser client components | Z1RR-first, host-visible two-section selection UI | React tests and Playwright selection/history link smoke |
| RST-008 | G0 | `.env.example`, docs/runbook | Outcome-switch configuration | Same build runs approved and self-hosted fixtures by config only |

## 5. TTPBot artifacts (`TTPBot`)

| ID | Gate | Repository/path | Artifact | Acceptance evidence |
| --- | --- | --- | --- | --- |
| BOT-001 | G0 | `ttpbot/provider.py`, `ttpbot/runtime_config.py` | Validated provider origin/category contract | HTTPS, loopback-dev, path/query/userinfo rejection tests |
| BOT-002 | G0 | `ttpbot/__init__.py`, `ttpbot/bot.py` | Provider-derived racetime-bot configuration and URL resolution | Both outcome fixtures create the expected API request and absolute room link |
| BOT-003 | G0 | `ttpbot/state.py`, state migration/tests | Destination-bound, versioned idempotency state | Same-destination restart preserves state; mismatch fails closed; explicit migration tested |
| BOT-004 | G0 | `deploy/ttpbot.env.example`, service/runbook | Destination and one-scheduler operations contract | Config validator and systemd security analysis pass |
| BOT-005 | G0 | `deploy/ttpbot-preflight` | Read-only credentials/category/scheduler/collision preflight | Mock integration and qualification dry-run pass; no room created in check mode |
| BOT-006 | G2 | late-G2 restricted-production evidence | Exactly-once scheduled room and announcement rehearsal after production certificate issuance and normal G2 allowlist restoration | Ordinary certificate validation with no CA override/bypass; restart injected before/after creation; only one room and one webhook observed |

## 6. LiveSplit artifacts (`LiveSplit.Racetime.Z1RR`, Plan B only)

| ID | Gate | Repository/path | Artifact | Acceptance evidence |
| --- | --- | --- | --- | --- |
| LS-001 | G0 | `docs/clean-room-provenance.md`, `LICENSE`, `THIRD-PARTY-NOTICES.md` | Clean-room/legal boundary | Reviewer confirms no copied unlicensed source and notices cover dependencies |
| LS-002 | G0 | solution/projects and pinned LiveSplit reference script | .NET 4.8.1 side-by-side plugin build | Clean Windows runner builds against pinned LiveSplit 1.8.37 artifact |
| LS-003 | G0 | OAuth core and loopback listener | S256 PKCE public-client implementation | RFC-style verifier/challenge vectors and adversarial callback/token tests pass |
| LS-004 | G0 | Windows credential store | Refresh-token storage and deletion | Store/read/overwrite/delete tests; logs contain no token material |
| LS-005 | G0 | REST/WebSocket protocol client | Z1RR RaceTime race/chat/action protocol | Mock-server contract suite and reconnect/idempotency tests pass |
| LS-006 | G0 | provider factory/API/settings/info/UI | LiveSplit integration with distinct identity | Stock and Z1RR DLL load side by side; settings/credentials do not collide |
| LS-007 | G0 | CI/release scripts, update XML, SBOM, signed checksums | Reproducible distributable | Two clean builds match, manifest verifies, update feed resolves pinned release |
| LS-008 | G2 | late-G2 restricted-production E2E evidence | Browser authorize plus complete timer race lifecycle after production certificate issuance and normal G2 allowlist restoration | Ordinary certificate validation with no CA override/bypass; login/join/ready/start/split/done/forfeit/reconnect/revoke cases pass |

## 7. Operations, evidence, and launch artifacts

| ID | Gate | Repository/path | Artifact | Acceptance evidence |
| --- | --- | --- | --- | --- |
| OPS-001 | G0 | `docs/runbooks/deploy.md`, `rollback.md` | Routine/emergency deploy and migration rollback | Tabletop with primary and backup operators |
| OPS-002 | G0 | `docs/runbooks/backup-restore.md`, `vm-loss.md` | Backup/restore/rebuild procedures | Empty-host restore rehearsal meets RPO/RTO targets |
| OPS-003 | G0 | `docs/runbooks/identity-recovery.md`, `access-review.md` | Account recovery and least-privilege review | Sample transfer audit and quarterly checklist review |
| OPS-004 | G0 | `docs/runbooks/incidents.md`, `status-comms.md` | Severity, escalation, Discord/status templates | Tabletop for DB, Discord, racebot, disk, and provider failures |
| OPS-005 | G0 | `deploy/monitoring/` | Health probes, metrics/log rules, redaction, Discord adapter, forecast-relative A1 utilization/slope and independent storage-cost controls | Synthetic health, forecast-buffer/slope, 2,900-hour utilization, Restream duty-cycle diagnostic, retained-volume, and Object Storage alerts reach the test sink; secret canaries never appear in logs |
| OPS-006 | G2 | `docs/evidence/<date>-load.json` | Four-room/2x load evidence manifest for the recorded ARM64 production and amd64 recovery shapes | Same-commit `linux/arm64` A1 and `linux/amd64` paid-fallback runs both meet thresholds and 20% CPU/30% memory headroom; a default-shape failure records the operator's optimization-or-resize decision and complete retest |
| OPS-007 | G2 | `docs/evidence/<date>-restore.json` | Isolated ARM64 and amd64 full-restore evidence manifest at the recorded recovery target | Accounts/category/race/media samples verify on both architectures; measured RPO and shape are recorded and the paid amd64 fallback restores within the four-hour RTO |
| OPS-008 | G2 | `docs/evidence/<date>-dress-rehearsal.json` | Late-G2 restricted-production cross-system race evidence manifest | After production issuance and normal G2 allowlist restoration, TTPBot → Discord → browser/LiveSplit → Restream → recorded leaderboard succeeds with ordinary certificate validation and no CA override/bypass |
| OPS-009 | G3 | private secret/access inventory | Current operators, owners, clients, webhooks, policies, recovery copies | Primary and backup operator sign-off; stale access removed |
| OPS-010 | G3 | `docs/evidence/<date>-go-no-go.md` | Launch decision and rollback trigger sheet | Council, technical, operations, and integrity approvals |
| OPS-011 | G4 | `docs/evidence/<date>-stabilization.md` | Seven-day post-launch report | Availability/incidents/backup/access review plus actual A1 usage slope, attribution diagnosis, retained-volume and Object Storage reconciliation against the dated forecast; no open P0/P1 issue |

## 8. Mandatory evidence conventions

Each evidence document records: UTC and local timestamps, commit/image digests, environment, operator, commands or test identifiers, expected and observed results, redacted logs/screenshots where helpful, deviations, open findings with severity/owner/date, and an explicit pass/fail conclusion. Secrets, access tokens, cookies, webhook URLs, Discord IDs not necessary to prove the test, and OCI credential material are prohibited.

An artifact with an open P0 or P1 finding is not accepted. P2 findings require a named owner, due date, and Council risk acceptance before G3. P3 findings may enter the normal backlog.
