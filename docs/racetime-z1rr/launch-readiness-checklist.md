# Z1RR Raceroom Launch Readiness Checklist

**Use:** Operational gate sheet. Check a box only after linking dated evidence.
**Requirement source:** `docs/racetime-z1rr/requirements-and-decisions.md`
**Artifact source:** `docs/racetime-z1rr/artifact-register.md`

## G0 — Contingency package ready

- [x] Architecture, requirements, ADRs, artifact/traceability controls, refreshed launch checklist, master plan, and all subsystem plans describe the same approved design and have independent review evidence. ([plan review](../evidence/2026-08-22-plan-review.md); [current G0 evidence](../evidence/2026-08-24-g0-readiness.md))
- [x] Source archive restores to the recorded upstream baseline and has an off-workstation copy. ([evidence](../evidence/2026-08-24-source-custody.md))
- [ ] Raceroom, Restream, TTPBot, and LiveSplit readiness branches build and test locally without production credentials.
- [ ] Raceroom CI discovers substantive tests; the current `js-cookie` high-severity advisory is closed.
- [ ] Production Compose, Caddy, configuration validation, backup/restore, Terraform, monitoring, and runbooks validate without applying public infrastructure.
- [x] Approved-outcome configuration (`racetime.gg/z1rr`) remains viable without self-hosted components. ([evidence](../evidence/2026-08-24-g0-readiness.md))
- [ ] Council understands G0 completion is not authorization for OCI/DNS/OAuth/cutover changes.

**G0 decision:** [ ] Pass [x] Hold
**Evidence:** [2026-08-24 G0 readiness](../evidence/2026-08-24-g0-readiness.md); [redacted NAS parser/browser acceptance](../evidence/2026-08-24-nas-task5-parser-acceptance.md)
**Council record:**

## G1 — Plan B activation and external prerequisites

- [ ] Council activation record states the reason, date, target launch window, primary technical operator, recovery custodian, and rollback authority.
- [ ] OCI inventory, actual A1 usage, and the dated Restream forecast are refreshed; July/August measurements and the next three-to-four-month forecast are reconciled to OCI evidence.
- [x] Terraform plan creates only the dedicated `racetime` A1 initially at 1 OCPU/6 GB and one new 50-GB Balanced boot volume; `z1rr-restream-control-staging` and existing retained volumes remain unchanged. ([evidence](../evidence/2026-08-25-oci-plan-review.json))
- [x] Terraform plan has human review; destructive replacement and unexpected retained resources are absent. ([evidence](../evidence/2026-08-25-oci-plan-review.json))
- [x] Public IP, NSG/Bastion, private backup bucket, dynamic group/policy, notifications, and alarms exist and match reviewed definitions. ([evidence](../evidence/2026-08-25-oci-subnet-correction.md))
- [ ] TCP 443 is open to `0.0.0.0/0` (and `::/0` if enabled) for TLS-ALPN-01; source-IP restriction exists only in Caddy's post-handshake HTTP handler.
- [ ] Canonical `raceroom.z1rracing.com` and redirect-only alias `racetime.z1rracing.com` A records resolve to the same reserved Raceroom public IP, with no AAAA/CNAME, before either staging or production ACME issuance; launch requires no later DNS promotion.
- [ ] Caddy qualification config has exactly one Let's Encrypt staging issuer, pins `dir == test_dir`, enables TLS-ALPN-01, disables HTTP-01, and uses separate qualification state that persists across issuance/restarts, is never promoted to production, and is retired only after qualification completes.
- [ ] Distinct qualification/production Discord, Twitch, TTPBot, LiveSplit, alert, and OAuth credentials use exact reviewed redirect URIs and scopes.
- [ ] Root-owned production secrets and backup key, the primary operator's working recovery copy, and the tested sealed offline recovery package are verified; package version/fingerprints/seal date and custodian receipt are current without exposing secrets, and the recorded recovery route can regain OCI tenancy, GitHub/registry, and authoritative DNS account access without the primary operator's active session.
- [ ] No secret appears in Git history, CI logs, image layers, Compose rendering, or evidence.
- [ ] Cost evidence confirms the 3,000/18,000 entitlement and records the default 744-hour Raceroom floor and dated combined forecast; below 2,650 hours the forecast-relative/slope warning is active, while at or above 2,650 forecast acceptance records utilization/expected cost and suppresses that near-duplicate warning; the 2,900-hour escalation, separate retained-volume $3.61 +$1/+$3 alarms, and Object Storage 75%/90% alarms remain active.
- [ ] Routine metered overage and technically justified shape changes are operator-authorized; each requires a dated reason, updated forecast, and replacement load/recovery evidence.

**G1 decision:** [ ] Pass [ ] Hold
**Evidence:**
**Approvers:**

## G2 — Restricted qualification

### Qualification boundary and TLS

- [ ] Unlisted public HTTP, static, media, OAuth, and WebSocket probes receive the generic Caddy denial while approved expiring source CIDRs work.
- [ ] Staging-ACME checks use only process-scoped CA bundles or disposable automation/browser profiles; no staging root is installed in an ordinary OS, operator, bot, Node, .NET, or client trust store.
- [ ] Adapted Caddy config proves one issuer, expected equal `ca`/`test_ca`, TLS-ALPN-only validation, HTTP-01 denial, and no cross-environment retry.
- [ ] Production certificate issuance is reserved for fresh-production finalization below; programmatic TTPBot, Restream, and LiveSplit acceptance evidence is not collected against the staging certificate.

### Core accounts and governance

- [ ] First Discord login, chosen display name, repeat login after Discord rename, logout, and session expiry pass.
- [ ] OAuth denial, provider failure, missing/mismatched/expired/replayed state, and concurrent callbacks fail safely.
- [ ] Public password/email/Patreon/category-request endpoints are unavailable; tunnel-only superuser access works.
- [ ] Twitch link/unlink and streaming-required behavior pass without conflating Twitch and Discord identity.
- [ ] Manual Discord identity transfer requires actor/evidence/confirmation and leaves a reviewed audit trail.
- [ ] Ordinary user creates a race; Council owner administers goals/bots/moderators; Council owner cannot access infrastructure/admin.

### Race lifecycle

- [ ] Browser-only race covers open/join/ready/start/chat/split/done/DNF/DQ/moderation/reconnect/record/rank.
- [ ] Redis restart causes bounded reconnect and no authoritative data loss; in-race transitions continue through MariaDB-backed HTTP actions.
- [ ] Racebot restart recovers and continues expected room behavior.
- [ ] Discord and Twitch outage simulations preserve active race data and show clear retryable/fail-closed behavior.

### Platform and recovery

- [ ] One immutable manifest builds, smoke-tests, scans, and records SBOM/provenance for same-commit `linux/arm64` and `linux/amd64` images.
- [ ] Empty-host deployment and idempotent bootstrap complete successfully.
- [ ] Normal deployment refuses an active room; emergency override is explicit and audited.
- [ ] Failed migration/smoke rehearsal stops promotion and follows the schema-aware rollback path.
- [ ] Public admin is unreachable; Bastion/SSH-tunneled admin works for the primary operator; the distinct escrow SSH/admin credentials were tested before sealing and their non-secret fingerprints match the current custody record.
- [ ] HTTPS, WSS, TLS renewal rehearsal, cookies/CSRF/HSTS/proxy headers/CORS/body limits and media non-execution pass.
- [ ] Route inventory covers every public mutation/lookup; authentication, race creation, OAuth, profile/Twitch, search, and autocomplete limits pass concurrent real-Redis and unavailable-limiter tests.
- [ ] The throttle HMAC key is independently generated and differs from the Django key; only fixed Caddy `172.30.0.2/32` is trusted, the declared proxy subnet has no overlap, proxied clients retain separate buckets, and spoofed/multi-value forwarding headers fail safely.
- [ ] Six-hour DB and nightly media backups plus production Caddy state encrypt, decrypt-verify, upload, retain, prune, and alert correctly.
- [ ] Isolated ARM64 and paid amd64 restores verify accounts, category configuration, a completed race, leaderboard, media, and production Caddy state; amd64 meets the four-hour RTO at the recorded recovery shape.
- [ ] The greater of twice the largest expected TTP-room load or the realistic aggregate peak across four simultaneous rooms meets 20% CPU/30% memory headroom on the recorded ARM64 and amd64 shapes.
- [ ] A failed default-shape load gate records the operator's optimize-or-resize decision and blocks G2/G3 until Terraform, cost forecast, load evidence, and recovery evidence are updated and pass; no waiver path exists.
- [ ] Service, host, backup, TLS, auth-abuse, OCI allowance, below-2,650 forecast-relative A1 utilization/slope, at-or-above-2,650 forecast-record suppression, 2,900-hour utilization, Restream duty-cycle, retained-volume, Object Storage, and billing test cases reach the private operations channel/email fallback as applicable.
- [ ] Log canaries prove no codes, tokens, cookies, secrets, synthetic emails, or unnecessary Discord IDs are emitted.

### Fresh-production finalization

- [ ] Maintenance/default-deny barrier stops qualification schedulers and writes; qualification backups are sealed under a restore-ineligible prefix.
- [ ] Fresh production MariaDB, Redis, media, operational volumes, secrets, sessions, and credentials are created; qualification state is never promoted.
- [ ] Qualification OAuth/bot/alert credentials and sessions/tokens are revoked while the application remains stopped behind the barrier.
- [ ] Production Caddy uses a separate persistent state volume and exactly one Let's Encrypt production issuer with `dir == test_dir`, TLS-ALPN-01 enabled, and HTTP-01 disabled.
- [ ] Both production issuances (canonical and redirect-only alias) complete within the bounded deadline; normal public trust succeeds, Caddy state is backed up, and the accepted Certificate Transparency disclosure for both names is recorded.
- [ ] Final production bootstrap runs locally; hard default-deny relaxes only to the normal reviewed G2 source-IP allowlist.

### Final integrations after production issuance

- [ ] All following integration evidence uses the production certificate, ordinary certificate validation, and no CA override, trust bypass, or staging root.
- [ ] TTPBot exactly-once test injects restarts before/after room creation and Discord announcement.
- [ ] TTPBot persists the correct self-hosted canonical URL and refuses destination-mismatched state.
- [ ] Restream shows Z1RR first and Z1R pickup second; each source has visible host attribution.
- [ ] Restream provider identity survives selection, draft save/reload, hydration, crops, WebSocket updates, active broadcast, history, and link rendering.
- [ ] Taking either racetime.gg provider offline does not disable the other section.
- [ ] Stock and Z1RR LiveSplit providers load side by side; Z1RR login/join/ready/start/split/done/forfeit/reconnect/revoke pass.
- [ ] LiveSplit wrong verifier/state, replay, occupied port, browser cancel, refresh failure, and revoked token cases pass without secret leakage.
- [ ] LiveSplit consent requests exactly `read chat_message race_action`; `create_race` is absent from registration, authorization, and stored grants.
- [ ] Complete TTPBot → Discord → browser/LiveSplit → Restream → recorded leaderboard dress rehearsal passes on exact production artifacts.

### Documentation and people

- [ ] User login/LiveSplit/migration instructions, privacy, acceptable use, deletion/contact, status and support routes are reviewed.
- [ ] The primary operator has table-topped deploy, rollback, backup/restore, VM loss, identity recovery, incident, access review, and cutover runbooks; the recovery custodian has acknowledged possession and the package-release instructions.
- [ ] On-call contacts and incident severity/escalation are current for launch week.

**G2 decision:** [ ] Pass [ ] Hold
**Evidence packet:**
**Technical:**
**Operations:**
**Competitive Integrity:**

## G3 — Public cutover go/no-go

- [ ] Change freeze is active; exact release commit, multi-platform image digests, and DLL hashes are recorded.
- [ ] Fresh production database backup completed, decrypted/integrity-verified, uploaded, and listed from Object Storage.
- [ ] No active race exists on either destination and no room-open window overlaps cutover.
- [ ] Council accounts/owners, category/goal limits, moderation roster, bots, OAuth clients, Twitch links, and Discord webhook destinations are reviewed.
- [ ] Late-G2 private dress rehearsal passed after production certificate issuance and the final configuration change.
- [ ] LiveSplit signed manifest/update feed and rollback package are published and independently downloaded/verified.
- [ ] Canonical DNS and production TLS are already present; the last unlisted external probe was denied before Go, so G3 changes no DNS record.
- [ ] Old TTPBot scheduler is disabled and observed stopped before the Caddy restriction is removed or the new destination is enabled.
- [ ] Cutover state machine removes the canonical-host Caddy source restriction, raises HSTS, enables the new scheduler, and proves exactly one scheduler is active.
- [ ] HTTPS/TLS/WSS/health/monitoring/status pages pass from outside OCI immediately after restriction removal.
- [ ] Old credentials and state are retained only as rollback inputs and cannot schedule concurrently.
- [ ] User announcement includes start time, account creation, LiveSplit install, ordinary-pickup boundary, support, and rollback communication.
- [ ] Rollback triggers, decision owner, old destination configuration, Caddy restriction values, and communication template are open in the launch bridge.
- [ ] Council, technical, operations, and integrity approvers sign the go/no-go record.

**G3 decision:** [ ] Go [ ] No-go
**Go/no-go evidence:**
**Launch time:**
**Rollback deadline:**

## First room and first-week watch

- [ ] First scheduled room opens once, at the correct time/goal/policy, and announces once with the correct URL.
- [ ] Browser and LiveSplit entrants complete the first room; Restream follows the self-hosted provider; race records/ranks.
- [ ] Operators check service restarts, latency, errors, disk/database growth, backup freshness, A1 usage slope, and storage after the first room.
- [ ] Daily launch-week review records incidents, user friction, backup proof, capacity, consumption, and cost.
- [ ] Any rollback trigger is acted on by the named authority; no improvised dual-scheduler fallback.

## G4 — Stabilization

- [ ] Seven monitored days complete with no unresolved P0/P1 issue.
- [ ] At least one full scheduled TTP slate completes end to end.
- [ ] Backup/restore proof is current and the first weekly retention point exists.
- [ ] Access and OAuth-client review removes temporary launch access.
- [ ] Actual OCI A1 usage/slope, retained-volume cost, and Object Storage consumption are reconciled to the dated forecast; anomalies have an owner and routine authorized overage is recorded without a new approval gate.
- [ ] Raceroom production and amd64 recovery definitions match the latest dated operator resource record and verified load/recovery evidence.
- [ ] Findings are assigned as P2/P3 backlog items with owner/date.
- [ ] Council approves normal operations and may authorize the separate legacy archive design.

**G4 decision:** [ ] Stabilized [ ] Extended watch
**Evidence:**
**Approvers:**

## Immediate rollback triggers

Rollback or halt promotion when any of these occurs and cannot be corrected inside the agreed launch bridge:

- race state/result loss, duplicate rooms, or conflicting schedulers;
- authentication allowing account takeover, PKCE bypass, or public staff access;
- database migration integrity failure or unusable verified backup;
- widespread inability to join/ready/finish from browser or LiveSplit;
- Restream resolving a self-hosted race against racetime.gg or rewriting historical URLs;
- secrets in logs/artifacts, public MariaDB/Redis, unauthorized retained OCI resources, or an unexplained unbounded consumption slope;
- capacity exhaustion threatening active races;
- loss of primary-operator access while the sealed recovery package cannot be obtained or fails validation.
