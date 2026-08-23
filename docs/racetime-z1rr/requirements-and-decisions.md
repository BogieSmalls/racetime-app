# Z1RR RaceTime Requirements and Decision Record

**Date:** 2026-08-23
**Status:** Approved for contingency-readiness work; external activation remains gated
**Architecture source:** `docs/superpowers/specs/2026-08-12-plan-b-racetime-architecture-design.md`

## 1. Authority and operating boundary

The Racetime.gg request is still pending. This record authorizes the team to produce and test source code, container definitions, infrastructure definitions, integration changes, release packages, and runbooks locally or in isolated non-public environments. It does **not** authorize provisioning public infrastructure, changing public DNS, creating production Discord/Twitch/OAuth applications, redirecting TTPBot, publishing the LiveSplit component, or announcing/cutting over the community.

The Council must record an explicit **Plan B activation decision** before any externally visible or billable Plan-B action. If Racetime.gg grants a separately administered `z1rr` category, the self-hosted application, OCI site, Discord authentication, and Z1RR LiveSplit provider are canceled; the provider-neutral Restream and TTPBot changes are configured for `https://racetime.gg/z1rr`.

## 2. Decision gates

| Gate | Decision owner | Entry condition | Permitted work | Exit evidence |
| --- | --- | --- | --- | --- |
| G0 — Request pending | Z1RR Council | Current state | Plans, source preservation, local code/build/test artifacts, provider-neutral Restream/TTPBot work | Reviewed plan bundle and green local CI |
| G1 — Plan B activated | Z1RR Council, recorded in Council minutes | Racetime.gg declines, cannot meet the required date, or Council otherwise explicitly activates | Dedicated OCI production-candidate resources, restricted canonical DNS/TLS, production app registrations and secrets | Dated activation record naming primary and backup operators plus the reviewed qualification allowlist |
| G2 — Restricted qualification complete | Primary operator + Competitive Integrity representative | All component builds green; restricted production candidate available | Private qualification; sealed qualification evidence; fresh production-state initialization; qualification-credential revocation; final restricted smoke/dress rehearsal | Signed evidence packet proving production-state transition, public denial, and no open P0/P1 findings |
| G3 — Public launch approved | Z1RR Council | G2 finalization is complete, every mandatory launch gate passes, and rollback is rehearsed | Remove canonical-host access restriction, publish user documentation and LiveSplit release, cut over TTPBot destination | Go/no-go record, verified backups, current contact roster |
| G4 — Stabilized | Primary operator + Council | Seven monitored days and at least one completed scheduled TTP slate | Normal operations; legacy archive project may begin | Stabilization report and access review |

No implementer may infer a later gate from completion of an earlier gate.

## 3. Resolved architecture decisions

### ADR-001: External identities use a separate model

Create an `ExternalIdentity` model rather than adding a Z1RR-specific field to `User`. It stores `provider`, immutable provider `subject`, owning `User`, and timestamps. Unique constraints on `(provider, subject)` and `(provider, user)` allow exactly one Discord identity per account while keeping the upstream user table neutral and leaving room for a future provider without another user-table migration.

Discord access and refresh tokens are never persisted. Public users retain the upstream unique-email requirement through `<discord-id>@discord.invalid`, never shown or editable in public forms. Local passwords remain available only for two break-glass superusers.

### ADR-002: New Discord users are created only after name selection

The Discord callback stores a short-lived pending identity in the server-side session. It does not create or authenticate a database user. A separate name-selection POST validates that pending identity and atomically creates `User` plus `ExternalIdentity`, calls `set_unusable_password()`, logs the user in, and consumes the pending session value. This avoids partially onboarded users and keeps race actions unavailable until the account is complete.

### ADR-003: Provider identity is immutable data

Every external race reference is represented by:

```json
{
  "providerId": "z1rr-racetime",
  "category": "z1rr",
  "room": "example-slug",
  "url": "https://racetime.z1rracing.com/z1rr/example-slug"
}
```

`providerId + category + room` is the stable key. `url` is the canonical historical link captured at selection time. Existing Restream records without these fields migrate to `racetime-gg`, `z1r`, and their existing slug/URL. No code may reconstruct an old URL using the currently configured provider.

### ADR-004: Runtime provider configuration has one canonical origin

Origins are absolute HTTPS URLs with no path, query, fragment, username, or password. A local-development-only switch may admit loopback HTTP. REST, OAuth, WebSocket, returned `Location` headers, persisted URLs, and Discord announcements derive from that origin. Host and scheme are never configured independently in production.

### ADR-005: Production is a single-node, immutable-image deployment

Caddy is the only public service. Daphne web, racebot, MariaDB, Redis, and maintenance jobs run on an internal Compose network. Images are ARM64, non-root where the component permits, and pinned by digest or immutable commit tag. Development bind mounts and `runserver` are forbidden in production.

### ADR-006: Backup transport uses OCI Instance Principal

Backup scripts create consistent MariaDB/media artifacts, compress and client-encrypt them, verify a decrypt/integrity pass, and upload with OCI CLI Instance Principal authentication. The VM holds a root-readable backup key and operators hold a separate recovery copy. The private Object Storage bucket has server-side encryption and a dedicated prefix/policy. Restore tests run into an isolated empty stack; production restore always requires explicit operator approval.

### ADR-007: The LiveSplit component is clean-room and public-client only

The new component targets the current LiveSplit provider interfaces and Z1RR RaceTime's documented HTTP/WebSocket contracts. It copies no source from the unlicensed `steto-scope/LiveSplit.Racetime` repository. OAuth uses Authorization Code with S256 PKCE, loopback redirect, no client secret, exact state comparison, and a persisted refresh token protected by Windows Credential Manager.

### ADR-008: Upstream mirror and deployable fork use separate protected branches

RaceTime `master` remains the default, upstream-only mirror throughout G0. `z1rr-production` is created from the recorded baseline only after G1 Plan-B activation, becomes the protected default branch, accepts Z1RR product changes through reviewed pull requests, and is the only branch allowed to build releases. Upstream updates enter `master` first and then reach `z1rr-production` through a reviewed baseline-sync PR. `z1rr-production` is never merged back into `master`; force-push and branch deletion are disabled on both.

### ADR-009: Production uses a new dedicated OCI VM and one canonical hostname

After G1 activation, create a new Terraform-managed Compute instance named `racetime` using `VM.Standard.A1.Flex`, 1 OCPU, 6 GB RAM, and a new 50-GB Balanced boot volume. This is a Council-approved intentional storage cost of approximately $2.13 per month at the current published US list price. Do not repurpose `z1rr-restream-control-staging`; it remains available for its existing staging purpose until a separate migration decision is approved.

The first restricted deployment and public production both use `https://racetime.z1rracing.com`. There is no `staging.racetime.z1rracing.com` hostname or DNS-promotion step. Before G3, the canonical hostname is operator-restricted; G3 only removes that restriction and cuts over integrations after the Council go decision.

While the host is still restricted under G2, operators stop qualification schedulers, seal qualification backups under a restore-ineligible `qualification/` prefix, create fresh production volumes and secrets, atomically switch the Compose deployment to them, revoke qualification OAuth/bot/alert credentials, invalidate qualification sessions and tokens, bootstrap final production state, and rerun final smoke and dress-rehearsal checks. Only then may the Council grant G3. Rollback must never restore qualification data, backups, sessions, tokens, or credentials.

Pre-G3 access is a Caddy default-deny source-IP allowlist applied before every application, static, media, and WebSocket route. A root-owned expiring record contains exact CIDRs for the primary and backup operators, approved scheduled testers, `coop-relay`, and required Restream hosts; it has no shared HTTP password. Two operators approve every entry and its expiry. Caddy's internal ACME handling remains available only as required for certificate issuance. Unlisted public probes must receive a generic denial and cannot fetch assets, reach OAuth callbacks, or upgrade WebSockets.

## 4. Functional requirements

### Core service

- **FR-CORE-001:** Serve `https://racetime.z1rracing.com` and WebSocket upgrades through Caddy with only ports 80/443 public. Use that canonical hostname for restricted qualification and production; do not create a staging subdomain or perform a hostname promotion at launch. Before G3, default-deny source-IP controls protect every HTTP/static/media/OAuth/WebSocket route and admit only approved expiring CIDRs.
- **FR-CORE-002:** Preserve upstream race creation, joining, ready/start/done/DNF/DQ, chat, moderation, recording, rating, leaderboard, API, OAuth, and racebot semantics.
- **FR-CORE-003:** Expose one active public category, `z1rr`; any active authenticated user can create a race.
- **FR-CORE-004:** Give all Council members category-owner rights without Django staff, shell, database, secret, backup, or OCI access.
- **FR-CORE-005:** Provide an idempotent bootstrap command for site identity, category limits/defaults, initial goals, and safe owner assignment.
- **FR-CORE-006:** Provide `/healthz` with a minimal response and internal dependency health checks that expose no secret or topology details.

### Identity and account lifecycle

- **FR-ID-001:** Any valid Discord account can authenticate with `identify`; Z1RR Discord membership is not required.
- **FR-ID-002:** Match returning users by immutable Discord user ID even after Discord username/display-name changes.
- **FR-ID-003:** Let first-time users choose a valid Racetime display name and let existing users edit it under upstream active-race rules.
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
- **FR-LS-002:** List Z1RR races and support login, join, leave, ready/unready, start timing, split, done, forfeit, chat/reconnect behavior required by the current Racetime protocol.
- **FR-LS-003:** Implement correct S256 PKCE with a new verifier per authorization, exact loopback redirect, exact state verification, one-time code exchange, refresh, revocation, and logout.
- **FR-LS-004:** Produce a reproducible Windows build, SBOM, SHA-256 manifest, signed manifest, update XML, installation/rollback guide, and clean-room provenance record.

### Operations and recovery

- **FR-OPS-001:** Refuse normal deployment while any race is active; require a named emergency override and audit record.
- **FR-OPS-002:** Take and verify a pre-deployment database backup before migrations.
- **FR-OPS-003:** Back up MariaDB every six hours, media nightly, retain 14 daily-equivalent recovery days, 13 weekly points, and 12 monthly points, and alert on freshness/verification failure.
- **FR-OPS-004:** Meet database RPO <= 6 hours, media RPO <= 24 hours, and target RTO <= 4 hours when OCI capacity is available.
- **FR-OPS-005:** Monitor HTTPS, WebSocket, web/racebot/db/Redis health, restart loops, CPU/memory/disk/inodes, backup freshness, TLS, OAuth failures, OCI allowance, and spend.
- **FR-OPS-006:** Deliver operational alerts to a private Discord channel with email fallback and no secrets.
- **FR-OPS-007:** Rebuild from Git, immutable images, configuration, operator-held secrets, and Object Storage on the dedicated `racetime` A1 VM or a temporary paid compatible shape.

## 5. Non-functional requirements

- **NFR-SEC-001:** Production passes `manage.py check --deploy`; secure cookies, HTTPS redirect, HSTS, explicit hosts/origins, proxy headers, limited CORS, clickjacking protection, and body/upload limits are fail-closed.
- **NFR-SEC-002:** MariaDB/Redis have no host-published ports. Secrets are root-owned or externally managed and never committed or printed.
- **NFR-SEC-003:** Dependencies and images are pinned, scanned, and updated through reviewed pull requests. The current `js-cookie <=3.0.5` high-severity advisory must be remediated before the first release candidate.
- **NFR-SEC-004:** Redis-backed distributed limits cover authentication, race creation, OAuth decisions, account mutations, search, and autocomplete with explicit per-user/IP policies, trusted-proxy client-IP resolution, a dedicated non-reused HMAC secret, bounded `Retry-After`, no raw identity in keys/logs, and fail-closed handling for authentication/mutations when the limiter is unavailable.
- **NFR-REL-001:** Database migrations are backward-aware; destructive changes use expand/migrate/contract. Rollback instructions accompany every schema release.
- **NFR-REL-002:** Redis loss may interrupt/reconnect clients but cannot lose authoritative race results.
- **NFR-PERF-001:** A 1-OCPU/6-GB ARM64 host sustains at least twice the largest expected TTP room's browser/chat/reconnect load with 30% memory and 20% CPU burst headroom after steady state.
- **NFR-PRIV-001:** Collect only Discord ID and minimum transient profile data; document Discord/Twitch data, logs, deletion, and backup expiry.
- **NFR-OSS-001:** Preserve GPL-3.0 and upstream attribution; publish corresponding source for every deployed build.
- **NFR-TEST-001:** Add an automated test baseline because the fork currently discovers zero Django tests. Pull requests must run unit/integration tests, migrations, static checks, dependency audit, and ARM64 image build.
- **NFR-COST-001:** Create one Council-approved 50-GB Balanced boot volume for the dedicated `racetime` VM, with expected incremental storage/performance cost of approximately $2.13 per month at the current published US list price; do not create further retained volumes without Council approval. Record OCI Cost Analysis's forecasted monthly retained-storage baseline as an exact dollar value in G1 evidence, warn above baseline plus $1, and escalate above baseline plus $3.

## 6. Current verified baseline

Compute was verified read-only on 2026-08-22; boot-volume `size_in_gbs` and `vpus_per_gb` were reverified on 2026-08-23:

- `coop-relay`: running E2 micro, 1 OCPU / 1 GB.
- `z1rr-restream-control`: stopped A1, 2 OCPUs / 6 GB.
- `z1rr-restream-control-staging`: stopped A1, 2 OCPUs / 6 GB.
- `z1rr-restream-encoder-a1` and `z1rr2-restream-encoder-a1`: stopped A1, 12 OCPUs / 16 GB each.
- Five retained 47-GB boot volumes total 235 GB.
- Approved but not provisioned at G0: one new dedicated `racetime` A1 instance at 1 OCPU/6 GB with a new 50-GB Balanced boot volume. After G1 creation, retained boot storage will total 285 GB, 85 GB above the documented free allocation; at current published prices and 10 VPUs/GB, the projected retained-volume charge is approximately $3.61 per month. `z1rr-restream-control-staging` remains unchanged.
- The RaceTime fork has no substantive automated tests (`manage.py test` found zero) but its Django system check is clean.
- `npm audit` reports one high-severity `js-cookie <=3.0.5` advisory with a fix available.
- Current LiveSplit 1.8.37 targets .NET Framework 4.8.1 and exposes `IRaceProviderFactory`, `RaceProviderAPI`, `RaceProviderSettings`, and `IRaceInfo` in `LiveSplit.Core`.
- The only known Racetime LiveSplit provider repository declares no license and was last updated in 2023; it is an interoperability reference that may not be copied.

Re-run every mutable inventory and dependency check at G1 and G3; this section is evidence, not a permanent assumption.

## 7. Deferred scope

The Seasons 1–4 legacy TTP archive begins only after G4. Account federation, historical room insertion, ordinary Z1R pickup migration, active-active availability, and a general-purpose race platform redesign require separate architecture decisions.
