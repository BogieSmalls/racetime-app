# Z1RR RaceTime Launch Readiness Checklist

**Use:** Operational gate sheet. Check a box only after linking dated evidence.
**Requirement source:** `docs/racetime-z1rr/requirements-and-decisions.md`
**Artifact source:** `docs/racetime-z1rr/artifact-register.md`

## G0 — Contingency package ready

- [ ] Architecture, requirements, ADRs, master plan, and all subsystem plans have independent plan-review approval.
- [ ] Source archive restores to the recorded upstream baseline and has an off-workstation copy.
- [ ] RaceTime, Restream, TTPBot, and LiveSplit readiness branches build and test locally without production credentials.
- [ ] RaceTime CI discovers substantive tests; the current `js-cookie` high-severity advisory is closed.
- [ ] Production Compose, Caddy, configuration validation, backup/restore, Terraform, monitoring, and runbooks validate without applying public infrastructure.
- [ ] Approved-outcome configuration (`racetime.gg/z1rr`) remains viable without self-hosted components.
- [ ] Council understands G0 completion is not authorization for OCI/DNS/OAuth/cutover changes.

**G0 decision:** [ ] Pass [ ] Hold
**Evidence:**
**Council record:**

## G1 — Plan B activation and external prerequisites

- [ ] Council activation record states the reason, date, target launch window, primary operator, backup operator, and rollback authority.
- [ ] OCI inventory and projected monthly cost have been refreshed; reused VM/volume is still safe and available.
- [ ] Terraform plan has human review; destructive replacement and unexpected paid resources are absent or explicitly approved.
- [ ] Public-IP, NSG/Bastion, private backup bucket, dynamic group/policy, notifications, and $1/$3 alarms exist and match the reviewed definitions.
- [ ] DNS records have low cutover TTL but are not yet directed publicly unless needed for restricted staging.
- [ ] Distinct staging/production Discord, Twitch, TTPBot, and LiveSplit app registrations use exact reviewed redirect URIs.
- [ ] Root-owned production secrets, backup key, operator recovery copy, and two-person access are verified.
- [ ] No secret appears in Git history, CI logs, image layers, Compose rendering, or evidence.

**G1 decision:** [ ] Pass [ ] Hold
**Evidence:**
**Approvers:**

## G2 — Staging qualification

### Core accounts and governance

- [ ] First Discord login, chosen display name, repeat login after Discord rename, logout, and session expiry pass.
- [ ] OAuth denial, provider failure, missing/mismatched/expired/replayed state, and concurrent callbacks fail safely.
- [ ] Public password/email/Patreon/category-request endpoints are unavailable; tunnel-only superuser access works.
- [ ] Twitch link/unlink and streaming-required behavior pass without conflating Twitch and Discord identity.
- [ ] Manual Discord identity transfer requires actor/evidence/confirmation and leaves a reviewed audit trail.
- [ ] Ordinary user creates a race; Council owner administers goals/bots/moderators; Council owner cannot access infrastructure/admin.

### Race lifecycle

- [ ] Browser-only race covers open/join/ready/start/chat/split/done/DNF/DQ/moderation/reconnect/record/rank.
- [ ] Redis restart causes bounded reconnect and no authoritative data loss.
- [ ] Racebot restart recovers and continues expected room behavior.
- [ ] Discord and Twitch outage simulations preserve active race data and show clear retryable/fail-closed behavior.

### Integrations

- [ ] TTPBot exactly-once test injects restarts before/after room creation and Discord announcement.
- [ ] TTPBot persists the correct self-hosted canonical URL and refuses destination-mismatched state.
- [ ] Restream shows Z1RR first and Z1R pickup second; each source has visible host attribution.
- [ ] Restream provider identity survives selection, draft save/reload, hydration, crops, WebSocket updates, active broadcast, history, and link rendering.
- [ ] Taking either Racetime provider offline does not disable the other section.
- [ ] Stock and Z1RR LiveSplit providers load side by side; Z1RR login/join/ready/start/split/done/forfeit/reconnect/revoke pass.
- [ ] LiveSplit wrong verifier/state, replay, occupied port, browser cancel, refresh failure, and revoked token cases pass without secret leakage.
- [ ] LiveSplit consent requests exactly `read chat_message race_action`; `create_race` is absent from registration, authorization, and stored grants.

### Platform and recovery

- [ ] ARM64 image build, SBOM, vulnerability threshold, provenance, immutable digest, and corresponding source link pass.
- [ ] Empty-host deployment and idempotent bootstrap complete successfully.
- [ ] Normal deployment refuses an active room; emergency override is explicit and audited.
- [ ] Failed migration/smoke rehearsal stops promotion and follows the schema-aware rollback path.
- [ ] Public admin is unreachable; Bastion/SSH-tunneled admin works for both break-glass operators.
- [ ] HTTPS, WSS, TLS renewal rehearsal, cookies/CSRF/HSTS/proxy headers/CORS/body limits and media non-execution pass.
- [ ] Route inventory covers every public mutation/lookup; authentication, race creation, OAuth, profile/Twitch, search, and autocomplete limits pass concurrent real-Redis and unavailable-limiter tests.
- [ ] The throttle HMAC key is independently generated and differs from the Django key; only fixed Caddy `172.30.0.2/32` is trusted, the declared proxy subnet has no overlap, proxied clients retain separate buckets, and same-subnet spoofed/multi-value forwarding headers fail safely.
- [ ] Six-hour DB and nightly media backups encrypt, decrypt-verify, upload, retain, and alert correctly.
- [ ] Isolated restore meets RPO/RTO and verifies accounts, category configuration, a completed race, leaderboard, and media references.
- [ ] Load at twice the expected largest TTP room meets the headroom thresholds.
- [ ] Service, host, backup, TLS, auth-abuse, OCI allowance, and billing test alerts reach the private operations channel/email fallback.
- [ ] Log canaries prove no codes, tokens, cookies, secrets, synthetic emails, or unnecessary Discord IDs are emitted.

### Documentation and people

- [ ] User login/LiveSplit/migration instructions, privacy, acceptable use, deletion/contact, status and support routes are reviewed.
- [ ] Deploy, rollback, backup/restore, VM loss, identity recovery, incident, access review, and cutover runbooks have primary/backup operator tabletops.
- [ ] On-call contacts and incident severity/escalation are current for launch week.

**G2 decision:** [ ] Pass [ ] Hold
**Evidence packet:**
**Technical:**
**Operations:**
**Competitive Integrity:**

## G3 — Public cutover go/no-go

- [ ] Change freeze is active; exact release commit/image/DLL hashes are recorded.
- [ ] Fresh database backup completed, decrypted/integrity-verified, uploaded, and listed from Object Storage.
- [ ] No active race exists on either destination and no room-open window overlaps cutover.
- [ ] Council accounts/owners, category/goal limits, moderation roster, bots, OAuth clients, Twitch links, and Discord webhook destinations are reviewed.
- [ ] Private dress rehearsal on the exact release artifacts passed after the final configuration change.
- [ ] LiveSplit signed manifest/update feed and rollback package are published and independently downloaded/verified.
- [ ] DNS/TLS/HTTPS/WSS/health/monitoring/status pages pass from outside OCI.
- [ ] Old TTPBot scheduler is disabled and observed stopped before new destination is enabled.
- [ ] Old credentials and state are retained but cannot schedule; one-scheduler preflight passes.
- [ ] User announcement includes start time, account creation, LiveSplit install, ordinary-pickup boundary, support, and rollback communication.
- [ ] Rollback triggers, decision owner, old destination configuration, DNS values, and communication template are open in the launch bridge.
- [ ] Council, technical, operations, and integrity approvers sign the go/no-go record.

**G3 decision:** [ ] Go [ ] No-go
**Go/no-go evidence:**
**Launch time:**
**Rollback deadline:**

## First room and first-week watch

- [ ] First scheduled room opens once, at the correct time/goal/policy, and announces once with the correct URL.
- [ ] Browser and LiveSplit entrants complete the first room; Restream follows the self-hosted provider; race records/ranks.
- [ ] Operators check service restarts, latency, errors, disk/database growth, backup freshness, and cost after the first room.
- [ ] Daily launch-week review records incidents, user friction, backup proof, and capacity/cost.
- [ ] Any rollback trigger is acted on by the named authority; no improvised dual-scheduler fallback.

## G4 — Stabilization

- [ ] Seven monitored days complete with no unresolved P0/P1 issue.
- [ ] At least one full scheduled TTP slate completes end to end.
- [ ] Backup/restore proof is current and the first weekly retention point exists.
- [ ] Access and OAuth-client review removes temporary launch access.
- [ ] Actual OCI cost/allowance consumption matches or improves the approved forecast.
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
- secrets in logs/artifacts, public MariaDB/Redis, or uncontrolled paid OCI creation;
- capacity exhaustion threatening active races;
- inability to reach both the primary and backup operator.
