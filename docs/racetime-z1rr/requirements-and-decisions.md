# Z1RR Raceroom Requirements and Decision Record

**Date:** 2026-08-24
**Status:** Approved for contingency-readiness work; external activation remains gated
**Architecture source:** `docs/superpowers/specs/2026-08-12-plan-b-racetime-architecture-design.md`

## 1. Authority and operating boundary

The racetime.gg request is still pending. This record authorizes the team to produce and test source code, container definitions, infrastructure definitions, integration changes, release packages, and runbooks locally or in isolated non-public environments. It does **not** authorize provisioning public infrastructure, changing public DNS, creating production Discord/Twitch/OAuth applications, redirecting TTPBot, publishing the LiveSplit component, or announcing/cutting over the community.

The Council must record an explicit **Plan B activation decision** before any externally visible or billable Plan-B action. One narrow source-preservation exception is operator-authorized at G0: a private, versioned OCI Object Storage bucket may hold only the two upstream Git bundles and their public manifest/checksum files as the verified off-workstation custody copy. The bucket is not a Plan-B runtime or backup resource, creates no public endpoint, must use server-side encryption and private access, and does not authorize Compute, network, DNS, OAuth, secret, scheduler, publication, or production-backup changes. If racetime.gg grants a separately administered `z1rr` category, the self-hosted application, OCI site, Discord authentication, and Z1RR LiveSplit provider are canceled; the provider-neutral Restream and TTPBot changes are configured for `https://racetime.gg/z1rr`.

## 2. Decision gates

| Gate | Decision owner | Entry condition | Permitted work | Exit evidence |
| --- | --- | --- | --- | --- |
| G0 — Request pending | Z1RR Council | Current state | Plans, source preservation (including the private custody-only bucket defined above), local code/build/test artifacts, provider-neutral Restream/TTPBot work | Reviewed plan bundle and green local CI |
| G1 — Plan B activated | Z1RR Council, recorded in Council minutes | racetime.gg declines, cannot meet the required date, or Council otherwise explicitly activates | Dedicated OCI production-candidate resources, restricted canonical DNS/TLS, production app registrations and secrets | Dated activation record naming the primary technical operator and recovery custodian plus the reviewed qualification allowlist |
| G2 — Restricted qualification complete | Primary operator + Competitive Integrity representative | All component builds green; restricted production candidate available | Private qualification; sealed qualification evidence; fresh production-state initialization; qualification-credential revocation; final restricted smoke/dress rehearsal | Signed evidence packet proving production-state transition, public denial, and no open P0/P1 findings |
| G3 — Public launch approved | Z1RR Council | G2 finalization is complete, every mandatory launch gate passes, and rollback is rehearsed | Remove canonical-host access restriction, publish user documentation and LiveSplit release, cut over TTPBot destination | Go/no-go record, verified backups, current contact roster |
| G4 — Stabilized | Primary operator + Council | Seven monitored days and at least one completed scheduled TTP slate | Normal operations; legacy archive project may begin | Stabilization report and access review |

No implementer may infer a later gate from completion of an earlier gate.

## 3. Resolved architecture decisions

### ADR-001: External identities use a separate model

Create an `ExternalIdentity` model rather than adding a Z1RR-specific field to `User`. It stores `provider`, immutable provider `subject`, owning `User`, and timestamps. Unique constraints on `(provider, subject)` and `(provider, user)` allow exactly one Discord identity per account while keeping the upstream user table neutral and leaving room for a future provider without another user-table migration.

Discord access and refresh tokens are never persisted. Public users retain the upstream unique-email requirement through `<discord-id>@discord.invalid`, never shown or editable in public forms. Local passwords exist only for the primary operator's break-glass superuser and a distinct escrow-only recovery superuser whose tested credentials are kept in the sealed offline recovery package defined in ADR-006.

### ADR-002: New Discord users are created only after name selection

The Discord callback stores a short-lived pending identity in the server-side session. It does not create or authenticate a database user. A separate name-selection POST validates that pending identity and atomically creates `User` plus `ExternalIdentity`, calls `set_unusable_password()`, logs the user in, and consumes the pending session value. This avoids partially onboarded users and keeps race actions unavailable until the account is complete.

### ADR-003: Provider identity is immutable data

Every external race reference is represented by:

```json
{
  "providerId": "z1rr-racetime",
  "category": "z1rr",
  "room": "example-slug",
  "url": "https://raceroom.z1rracing.com/z1rr/example-slug"
}
```

`providerId + category + room` is the stable key. `url` is the canonical historical link captured at selection time. Existing Restream records without these fields migrate to `racetime-gg`, `z1r`, and their existing slug/URL. No code may reconstruct an old URL using the currently configured provider.

### ADR-004: Runtime provider configuration has one canonical origin

Origins are absolute HTTPS URLs with no path, query, fragment, username, or password. A local-development-only switch may admit loopback HTTP. REST, OAuth, WebSocket, returned `Location` headers, persisted URLs, and Discord announcements derive from that origin. Host and scheme are never configured independently in production.

### ADR-005: Production is a single-node, immutable-image deployment

Caddy is the only public service. Daphne web, racebot, MariaDB, Redis, and maintenance jobs run on an internal Compose network. Each release manifest contains tested `linux/arm64` and `linux/amd64` variants built from the same commit; A1 production selects ARM64 and the amd64 variant is the paid-shape disaster-recovery fallback. Images are non-root where the component permits and pinned by digest or immutable commit tag. Development bind mounts and `runserver` are forbidden in production.

### ADR-006: Backup transport uses OCI Instance Principal

Backup scripts create consistent MariaDB/media artifacts and capture encrypted production Caddy state after issuance, renewal, or material change. They compress and client-encrypt artifacts, verify a decrypt/integrity pass, and upload with OCI CLI Instance Principal authentication. The VM holds a root-readable backup key; the primary operator holds a working copy outside the VM and bucket; and a distinct copy, recovery SSH key, escrow-only local-superuser credential, and instructions are stored in a tamper-evident sealed offline package with a designated non-technical Council recovery custodian. The custodian has no routine access or technical approval role and releases the package only to the primary operator or a formally designated replacement for recovery. Record only package version, non-secret fingerprints, seal date, and custody receipt; rotate, retest, and reseal after use or relevant credential changes. The recovery record also names a verified route to regain OCI tenancy administration, GitHub organization/container-registry ownership, and authoritative DNS account access without the unavailable operator's active session. That route may use sealed recovery material, another account owner, or the platform's documented account-recovery process; it grants no standing technical approval role. The private Object Storage bucket has server-side encryption and a dedicated prefix/policy. Restore tests run into an isolated empty stack; production restore always requires explicit operator approval.

### ADR-007: The LiveSplit component is clean-room and public-client only

The new component targets the current LiveSplit provider interfaces and Z1RR Raceroom's documented HTTP/WebSocket contracts. It copies no source from the unlicensed `steto-scope/LiveSplit.Racetime` repository. OAuth uses Authorization Code with S256 PKCE, loopback redirect, no client secret, exact state comparison, and a persisted refresh token protected by Windows Credential Manager.

### ADR-008: Upstream mirror and deployable fork use separate protected branches

Raceroom `master` remains the default, upstream-only mirror throughout G0. `z1rr-production` is created from the recorded baseline only after G1 Plan-B activation, becomes the protected default branch, accepts Z1RR product changes through reviewed pull requests, and is the only branch allowed to build releases. Upstream updates enter `master` first and then reach `z1rr-production` through a reviewed baseline-sync PR. `z1rr-production` is never merged back into `master`; force-push and branch deletion are disabled on both.

### ADR-009: Production uses a new dedicated OCI VM and one canonical hostname

After G1 activation, create a new Terraform-managed Compute instance named `racetime` using `VM.Standard.A1.Flex`, 1 OCPU, 6 GB RAM, and a new 50-GB Balanced boot volume. This is an operator-authorized intentional storage cost of approximately $2.13 per month at the current published US list price. Do not repurpose `z1rr-restream-control-staging`; it remains available for its existing staging purpose until a separate migration decision is approved.

The 1-OCPU/6-GB configuration is the documented production and recovery default. Raceroom is the tenancy's only always-on A1 workload with no duty-cycle lever: in a 31-day month the default establishes a floor of 744 OCPU-hours, 24.8% of the 3,000-hour allowance. A 2-OCPU deployment would consume 1,488 hours, 49.6%, before Restream runs, so 1 OCPU is the preferred starting allocation and preserves 2,256 hours for duty-cycled, revenue-generating Restream work. The primary technical operator may resize when measured performance requires it and records the reason, resulting forecast, and replacement load/recovery evidence.

On 2026-08-23 the operator confirmed this is a paid tenancy. Oracle's paid-tenancy price list and A1-specific Compute documentation both state 3,000 free A1 OCPU-hours and 18,000 GB-hours monthly; the older general Always Free page remains inconsistent at 1,500/9,000. The 3,000/18,000 entitlement is the verified planning basis. G1 confirms that account status and current terms have not changed and records Limits, Quotas and Usage plus Cost Analysis; it does not re-adjudicate the entitlement.

Run NFR-PERF-001 early in G2. If the default shape misses the gate, the primary technical operator chooses optimization or resize and records which and why. Any resize updates Terraform, the A1/Restream forecast, and the recovery target. G2/G3 remain blocked until the complete load and recovery gates pass on the recorded production and amd64 fallback shapes; there is no performance waiver.

The first restricted deployment and public production both use `https://raceroom.z1rracing.com`. The legacy `https://racetime.z1rracing.com` name is a Caddy redirect-only alias: after the same pre-G3 source-IP check it returns a 308 to the canonical origin and never serves application, static, media, OAuth, or WebSocket routes. Both names resolve to the same reserved IPv4 address and receive certificates from the same single pinned ACME issuer, but only `raceroom.z1rracing.com` is an application origin. There is no `staging.raceroom.z1rracing.com` hostname or DNS-promotion step. Before G3, both names are operator-restricted; G3 only removes that restriction and cuts over integrations after the Council go decision.

While the host is still restricted under G2, operators enter a maintenance/default-deny transition barrier, stop qualification schedulers and writes, seal qualification backups under a restore-ineligible `qualification/` prefix, create fresh production volumes and secrets, stop Compose, and repoint the stopped application. While it remains stopped and the barrier remains enforced, operators revoke qualification OAuth/bot/alert credentials and invalidate qualification sessions and tokens. They then start the application on fresh production state behind the barrier and bootstrap final production state through a local operator management command that is not publicly routed. After revocation, bootstrap, and production-TLS evidence passes, operators relax the hard barrier only to the normal G2 source-IP allowlist and rerun final restricted smoke and dress-rehearsal checks. Only then may the Council grant G3 and remove the canonical-host source-IP restriction. Rollback must never restore qualification data, backups, sessions, tokens, or credentials.

Pre-G3 access is a Caddy default-deny source-IP allowlist applied before every application, static, media, OAuth, and WebSocket route and before the legacy-host redirect. A root-owned expiring record contains exact CIDRs for the primary technical operator, approved scheduled testers, `coop-relay`, and required Restream hosts; it has no shared HTTP password. Each entry records owner, purpose, adding operator, and expiry; the recovery custodian receives no routine allowlist entry or infrastructure access. Caddy has exactly one explicit ACME issuer and no ZeroSSL issuer. Qualification pins both the issuer `dir` and CertMagic `test_dir` to Let's Encrypt staging and uses dedicated test trust stores. Late in G2, operators switch once to a separate persistent production Caddy state volume whose sole issuer pins both `dir` and `test_dir` to Let's Encrypt production. This same-environment pinning prevents automatic retry from crossing between staging and production. Both phases use TLS-ALPN-01 with HTTP-01 disabled; the source-IP filter applies after the ACME TLS handshake, so no public application-path exemption exists. Adapted-config tests must prove exactly one issuer, equal expected `ca` and `test_ca` values, and the challenge settings. The G2 transition controller applies a bounded issuance deadline; any Caddy background retries remain production-only. A deadline breach leaves the maintenance/default-deny barrier in place, alerts operators, and blocks G2; Caddy cannot serve or promote an untrusted fallback certificate. Production issuance makes both the canonical hostname and redirect-only alias visible in public Certificate Transparency logs, an accepted late-G2 disclosure after G1 activation. Unlisted public probes must receive a generic denial on both names and cannot fetch assets, receive the redirect, reach OAuth callbacks, or upgrade WebSockets.

## 4. Functional requirements

### Core service

- **FR-CORE-001:** Serve `https://raceroom.z1rracing.com` and WebSocket upgrades through Caddy with only ports 80/443 public. Use that canonical hostname for restricted qualification and production; do not create a staging subdomain or perform a hostname promotion at launch. Return a source-restricted 308 from the redirect-only `racetime.z1rracing.com` alias without proxying any application route. Before G3, default-deny source-IP controls protect both hostnames and every HTTP/static/media/OAuth/WebSocket route and admit only approved expiring CIDRs. OCI security lists/NSGs and the host firewall must admit inbound TCP 443 from `0.0.0.0/0` and, if enabled, `::/0` so unpredictable TLS-ALPN-01 validators can reach Caddy; the pre-G3 source-IP restriction exists only in Caddy's post-handshake HTTP handler.
- **FR-CORE-002:** Preserve upstream race creation, joining, ready/start/done/DNF/DQ, chat, moderation, recording, rating, leaderboard, API, OAuth, and racebot semantics.
- **FR-CORE-003:** Expose one active public category, `z1rr`; any active authenticated user can create a race.
- **FR-CORE-004:** Give all Council members category-owner rights without Django staff, shell, database, secret, backup, or OCI access.
- **FR-CORE-005:** Provide an idempotent bootstrap command for site identity, category limits/defaults, initial goals, and safe owner assignment.
- **FR-CORE-006:** Provide `/healthz` with a minimal response and internal dependency health checks that expose no secret or topology details.

### Identity and account lifecycle

- **FR-ID-001:** Any valid Discord account can authenticate with `identify`; Z1RR Discord membership is not required.
- **FR-ID-002:** Match returning users by immutable Discord user ID even after Discord username/display-name changes.
- **FR-ID-003:** Let first-time users choose a valid racetime.gg display name and let existing users edit it under upstream active-race rules.
- **FR-ID-004:** Disable public email/password create/login/reset/change, email editing, Patreon, and public category requests; retain tunnel-only staff login.
- **FR-ID-005:** Keep Twitch link/unlink separate and preserve streaming-required behavior.
- **FR-ID-006:** Delete/deactivate identities consistently on account deletion and provide a manual, evidence-requiring, audited Discord-account transfer command.
- **FR-ID-007:** Reject missing, mismatched, replayed, or expired OAuth state; bound login initiation/callback attempts; never log codes, tokens, cookies, or synthetic email addresses.

### TTPBot

- **FR-BOT-001:** Select target by validated origin plus category, supporting either `racetime.gg/z1rr` or self-hosted `z1rr`.
- **FR-BOT-002:** Derive REST/WSS/absolute room links and announcements from the selected origin.
- **FR-BOT-003:** Namespace idempotency state by destination and fail closed on an unexpected state/destination mismatch.
- **FR-BOT-004:** Preserve schedule, goal selection, seed behavior, Discord announcements, state files, restart recovery, and duplicate suppression.
- **FR-BOT-005:** Provide a cutover preflight that proves exactly one scheduler is enabled.

### Restream

- **FR-RESTREAM-001:** Show logical Z1RR first and Z1R pickup second in one race browser.
- **FR-RESTREAM-002:** Configure each logical source independently with provider ID, origin, category, and label.
- **FR-RESTREAM-003:** Carry provider-qualified identity and canonical URL through API responses, selection, drafts, hydration, crop discovery, realtime, active broadcasts, history, and user links.
- **FR-RESTREAM-004:** Migrate legacy records to `racetime-gg:z1r` without rewriting existing URLs.
- **FR-RESTREAM-005:** Isolate provider failures so one source remains usable when the other REST or WebSocket endpoint fails.

### LiveSplit

- **FR-LS-001:** Install `LiveSplit.Racetime.Z1RR.dll` side by side with the stock provider without assembly, settings, credential, menu, or update-feed collisions.
- **FR-LS-002:** List Z1RR races and support login, join, leave, ready/unready, start timing, split, done, forfeit, chat/reconnect behavior required by the current racetime.gg protocol.
- **FR-LS-003:** Implement correct S256 PKCE with a new verifier per authorization, exact loopback redirect, exact state verification, one-time code exchange, refresh, revocation, and logout.
- **FR-LS-004:** Produce a reproducible Windows build, SBOM, SHA-256 manifest, signed manifest, update XML, installation/rollback guide, and clean-room provenance record.

### Operations and recovery

- **FR-OPS-001:** Refuse normal deployment while any race is active; require a named emergency override and audit record.
- **FR-OPS-002:** Take and verify a pre-deployment database backup before migrations.
- **FR-OPS-003:** Back up MariaDB every six hours and media nightly; capture encrypted production Caddy state after initial issuance, renewal, or material change with the current and two previous verified generations; retain 14 daily-equivalent database/media recovery days, 13 weekly points, and 12 monthly points; and alert on freshness/verification failure.
- **FR-OPS-004:** Meet database RPO <= 6 hours, media RPO <= 24 hours, and target RTO <= 4 hours when compatible OCI capacity is available.
- **FR-OPS-005:** Monitor HTTPS, WebSocket, web/racebot/db/Redis health, restart loops, CPU/memory/disk/inodes, backup freshness, TLS, OAuth failures, tenancy-wide A1 OCPU-hour consumption and slope, Object Storage usage, retained-volume cost, and spend. A1 usage alerts must direct operators to check Restream sleep automation, encoders, and control planes because OCI cannot attribute a shared allowance overage to Raceroom alone.
- **FR-OPS-006:** Deliver operational alerts to a private Discord channel with email fallback and no secrets. Use an independent public Discord path for launch and rollback status: announce a non-emergency rollback before hiding the canonical host; for a security/integrity emergency, restrict first only when necessary and announce within five minutes; publish the promised status cadence and a resolution notice.
- **FR-OPS-007:** Rebuild from Git, immutable multi-platform images, configuration, operator-held working secrets plus the sealed offline recovery package, verified OCI/GitHub/registry/DNS account-recovery routes, and Object Storage on the dedicated `racetime` A1 VM or a temporary paid Linux amd64 shape. The paid fallback defaults to 1 OCPU/6 GB and must pass the same recovery and performance gates at the operator-recorded recovery shape. Shape changes require a dated technical and cost record, not Council approval.

## 5. Non-functional requirements

- **NFR-SEC-001:** Production passes `manage.py check --deploy`; secure cookies, HTTPS redirect, explicit hosts/origins, proxy headers, limited CORS, clickjacking protection, and body/upload limits are fail-closed. HSTS uses `max-age=300` through restricted G2, rises to at least `31536000` only after G3 Go, and is not submitted for preload before a separate post-G4 Council decision.
- **NFR-SEC-002:** MariaDB/Redis have no host-published ports. Secrets are root-owned or externally managed and never committed or printed. Routine infrastructure access belongs only to the primary technical operator; a tested, sealed offline recovery package and verified account-level OCI/GitHub/registry/DNS recovery route exist under ADR-006 without creating a standing second technical approver.
- **NFR-SEC-003:** Dependencies and images are pinned, scanned, and updated through reviewed pull requests. The current `js-cookie <=3.0.5` high-severity advisory must be remediated before the first release candidate.
- **NFR-SEC-004:** Redis-backed distributed limits cover authentication, race creation, OAuth decisions, account mutations, search, and autocomplete with explicit per-user/IP policies, trusted-proxy client-IP resolution, a dedicated non-reused HMAC secret, bounded `Retry-After`, and no raw identity in keys/logs. Limiter loss fails closed for authentication, OAuth decisions, race creation, and account/admin mutations. Authoritative in-race ready/start/done/DNF/DQ/split transitions continue against MariaDB under bounded per-process emergency controls with audit and alerting; they never depend on limiter availability.
- **NFR-REL-001:** Database migrations are backward-aware; destructive changes use expand/migrate/contract. Rollback instructions accompany every schema release.
- **NFR-REL-002:** Redis loss may interrupt/reconnect clients but cannot lose authoritative race results or prevent core in-race state transitions solely because the distributed limiter is unavailable.
- **NFR-PERF-001:** Early in G2, the default 1-OCPU/6-GB ARM64 host must sustain the greater of twice the largest expected TTP room's browser/chat/reconnect load or the realistic aggregate peak across four simultaneously active rooms, with 30% memory and 20% CPU burst headroom after steady state. Failure blocks G2/G3 until the primary technical operator either optimizes or records a resize and the full gate passes on the resulting production shape. Before G3, the operator-recorded amd64 fallback shape must pass the same gate. There is no launch waiver.
- **NFR-PRIV-001:** Collect only Discord ID and minimum transient profile data; document Discord/Twitch data, logs, deletion, and backup expiry.
- **NFR-OSS-001:** Preserve GPL-3.0 and upstream attribution. Network use alone does not trigger GPL-3.0 source publication; source visibility follows ADR-008 and is not launch authorization. Satisfy corresponding-source obligations whenever object code is conveyed, and publish the exact corresponding source for every public deployment at G3 as Council policy.
- **NFR-TEST-001:** Add an automated test baseline because the fork currently discovers zero Django tests. Pull requests must run unit/integration tests, migrations, static checks, dependency audit, and both `linux/arm64` and `linux/amd64` image builds and smoke tests. Before late-G2 production certificate issuance, staging-ACME checks may trust the staging root only through process-scoped CA bundles or disposable automation profiles, never an ordinary OS/client trust store. Final TTPBot, Restream, and LiveSplit integration evidence must run after production issuance with ordinary certificate validation and no trust bypass.
- **NFR-COST-001:** Create the authorized 50-GB Balanced boot volume for the dedicated `racetime` VM, with expected incremental storage/performance cost of approximately $2.13 per month at the current published US list price. G1 evidence records the verified 3,000/18,000 entitlement, the default 744-OCPU-hour Raceroom floor, the dated combined A1 forecast, expected compute, approximately $3.61 retained-volume cost, and Object Storage assumptions. Below a 2,650-hour active forecast, an allowance-utilization warning—explicitly not a spend alert—fires when projected month-end A1 OCPU-hours exceed the forecast by the greater of 100 hours or 5%, or the observed slope projects crossing that buffer within 72 hours. At an accepted forecast of 2,650 hours or higher, forecast acceptance itself records expected allowance utilization, overage/cost if any, and Restream duty-cycle assumptions; the near-duplicate forecast-relative warning is suppressed for that forecast. Utilization always escalates at 2,900 actual or projected hours, still before billing at 3,000. The operator may update the dated forecast for planned tournament activity. Retained-volume cost is monitored separately at $3.61 plus $1 warning and plus $3 escalation; Object Storage alarms at 75% and 90% of verified byte/request entitlements. Routine compute, retained-volume, Object Storage, and operator-recorded shape-change costs are authorized operating expenses: alerts require diagnosis, reconciliation, and forecast updates, not Council approval. Reconcile the first complete billing cycle and every threshold crossing.

## 6. Current verified baseline

Compute was verified read-only on 2026-08-22; boot-volume `size_in_gbs` and `vpus_per_gb` were reverified on 2026-08-23:

- `coop-relay`: running E2 micro, 1 OCPU / 1 GB.
- `z1rr-restream-control`: stopped A1, 2 OCPUs / 6 GB.
- `z1rr-restream-control-staging`: stopped A1, 2 OCPUs / 6 GB.
- `z1rr-restream-encoder-a1` and `z1rr2-restream-encoder-a1`: stopped A1, 12 OCPUs / 16 GB each.
- Five retained 47-GB boot volumes total 235 GB.
- Approved but not provisioned at G0: one new dedicated `racetime` A1 instance initially at 1 OCPU/6 GB with a new 50-GB Balanced boot volume. After G1 creation, retained boot storage will total 285 GB, 85 GB above the documented free allocation; at current published prices and 10 VPUs/GB, the projected retained-volume charge is approximately $3.61 per month. `z1rr-restream-control-staging` remains unchanged.
- Verified planning entitlement as of 2026-08-23: this is a paid tenancy, and both Oracle's paid price list and A1-specific Compute documentation specify 3,000 free OCPU-hours and 18,000 GB-hours monthly. G1 confirms that basis remains current.
- Operator-reported A1 consumption evidence: July 2026 exceeded approximately 3,000 OCPU-hours before the Restream sleep automation; the post-automation August 2026 normalized monthly estimate is approximately 1,000 OCPU-hours; and Restream is forecast at 750–2,000 OCPU-hours per month for the next three to four months. These dated measurements are planning evidence, not permanent assumptions, and G1 refreshes them from OCI usage data.
- At the default shape, Raceroom adds 744 OCPU-hours and 4,464 GB-hours in a 31-day month. Against the 3,000/18,000 planning allowance, total OCPU use is 1,494 hours at the low Restream forecast and 2,744 at the high forecast; both plan to $0 A1 compute, leaving 2,256 Restream OCPU-hours before compute billing begins. At the most memory-heavy inventoried Restream A1 ratio of 3 GB-hours per OCPU-hour, the low/high combined memory cases are at most 6,714/10,464 GB-hours, also below the 18,000-hour planning allowance.
- The Raceroom fork has no substantive automated tests (`manage.py test` found zero) but its Django system check is clean.
- `npm audit` reports one high-severity `js-cookie <=3.0.5` advisory with a fix available.
- Current LiveSplit 1.8.37 targets .NET Framework 4.8.1 and exposes `IRaceProviderFactory`, `RaceProviderAPI`, `RaceProviderSettings`, and `IRaceInfo` in `LiveSplit.Core`.
- The only known racetime.gg LiveSplit provider repository declares no license and was last updated in 2023; it is an interoperability reference that may not be copied.

Re-run every mutable inventory and dependency check at G1 and G3; this section is evidence, not a permanent assumption.

## 7. Deferred scope

The Seasons 1–4 legacy TTP archive begins only after G4. Account federation, historical room insertion, ordinary Z1R pickup migration, active-active availability, and a general-purpose race platform redesign require separate architecture decisions.
