# Z1RR RaceTime Plan B Architecture Design

**Date:** 2026-08-12; revised 2026-08-23
**Status:** Approved for G0 local contingency-readiness work; external deployment remains conditional on G1 Plan-B activation
**Primary repository:** `BogieSmalls/racetime-app`
**Related repositories:** `Z1RR.Restream`, `TTPBot`, and a future `LiveSplit.Racetime.Z1RR`

## 1. Summary

Z1RR will first ask racetime.gg to create a separately administered `z1rr`
category for organized Z1RR activity. If that request is approved, ordinary
pickup races remain in `racetime.gg/z1r`, organized Z1RR programs move to
`racetime.gg/z1rr`, and no independent Racetime deployment is needed.

If the request is declined, **Plan B** creates an independent deployment of the
open-source Racetime application at `https://racetime.z1rracing.com`. The site
will be branded **Z1RR RaceTime**, contain one public `z1rr` category, accept
any valid Discord account, and become the immediate production home for
organized Z1RR races. It will have its own accounts, race history, category
governance, OAuth clients, and operational ownership. It will not synchronize
accounts or live data with racetime.gg.

The deployment will run as a containerized, single-node production system on a
dedicated OCI Ampere A1 VM. TTPBot remains independently hosted on the existing
`coop-relay` VM. Z1RR.Restream supports the logical `z1rr` source regardless of
which Racetime host provides it. A separate LiveSplit provider is required only
if `z1rr` is hosted at `racetime.z1rracing.com`.

This design favors low recurring cost, upstream compatibility, operational
simplicity, and recoverability over high availability. Planned maintenance of
approximately 5–15 minutes is acceptable when no race is active.

## 2. Decision matrix

| Concern | Dyn approves `racetime.gg/z1rr` | Plan B: self-hosted `z1rr` |
| --- | --- | --- |
| Z1RR category | `racetime.gg/z1rr` | `racetime.z1rracing.com/z1rr` |
| Ordinary pickup races | Remain at `racetime.gg/z1r` | Remain at `racetime.gg/z1r` |
| Organized Z1RR races | Move to `racetime.gg/z1rr` | Move to Z1RR RaceTime |
| Category owners | Z1RR Council on racetime.gg | Z1RR Council on Z1RR RaceTime |
| TTPBot change | Category changes to `z1rr`; host remains racetime.gg | Host and category change |
| Z1RR.Restream | Adds logical `z1rr` source on racetime.gg | Adds logical `z1rr` source on Z1RR RaceTime |
| LiveSplit | Stock Racetime provider is sufficient | Separate Z1RR provider is required |
| Independent site work | G0 artifacts canceled | Local readiness at G0; external deployment at G1 |
| Legacy TTP archive | Optional Council archive | Post-launch read-only site archive |

Source preservation and the Restream work are outcome-independent. G0 also
permits local implementation and verification of the contingency application,
container images, IaC definitions, Discord login, integration adapters,
LiveSplit provider, release packages, and runbooks. These Plan-B-only artifacts
are canceled if Dyn approves the requested category. G0 never permits Terraform
apply, OCI/DNS/external-app mutation, deployment, publication, or cutover.

## 3. Goals

Plan B must:

- Provide a production-quality, public Racetime service for organized Z1RR
  racing without requiring cooperation or data access from racetime.gg.
- Preserve familiar Racetime room behavior, APIs, WebSockets, chat, race
  recording, leaderboards, moderation, and OAuth integration.
- Let any valid Discord account sign in and let users choose their Racetime
  display names.
- Let any registered user create races in the `z1rr` category, matching normal
  Racetime behavior.
- Give all Z1RR Council members category-owner rights while limiting server,
  database, secrets, and Django superuser access to the primary operator and
  one backup operator.
- Support TTPBot, Z1RR.Restream, LiveSplit, Discord announcements, Twitch
  linking, and streaming-required rooms before production cutover.
- Operate near zero incremental monthly cost and alert before costs become
  material.
- Recover from application failure, database corruption, operator error, or VM
  loss using versioned infrastructure configuration and encrypted backups.
- Preserve upstream attribution and make Z1RR branding unmistakable without
  implying authorship of the underlying Racetime project.

## 4. Non-goals

Plan B will not:

- Mirror or federate accounts, sessions, rooms, chat, ratings, or leaderboards
  with racetime.gg.
- Move ordinary Z1R pickup racing away from `racetime.gg/z1r`.
- Import historical TTP racers as synthetic local accounts or insert legacy
  rooms into the new live ratings database.
- Fork or redistribute the entire LiveSplit application.
- Provide active-active high availability or zero-downtime database migration.
- Build a new racing engine when the upstream Racetime application already
  supplies the required semantics.
- Require Z1RR Discord-server membership for authentication.
- Require transactional email for public account creation or recovery.
- Make the legacy Seasons 1–4 archive a launch blocker.

## 5. Approaches considered

### 5.1 Selected: containerized single VM

Run Caddy, Racetime web/Daphne, the upstream racebot, MariaDB, Redis, and backup
jobs in Docker Compose on a dedicated OCI A1 VM. Keep TTPBot on `coop-relay`.

This approach stays close to upstream's existing service topology while adding
a reproducible production layer. Images, configuration, and backups are enough
to rebuild the site. Container boundaries also make dependency upgrades,
staging, rollback, and resource limits easier to reason about.

### 5.2 Rejected: native system services

Installing MariaDB, Redis, Caddy, and Python services directly on Ubuntu could
save a small amount of memory. It would make dependency state, upgrades,
rollback, and full-machine reconstruction more manual. The small efficiency
gain does not outweigh the operational cost.

### 5.3 Rejected: split or managed platform

Placing the database, Redis, or ingress on separate VMs or managed services
would reduce the single failure domain but add cost, networking, credentials,
and capacity dependencies. It is disproportionate to expected Z1RR traffic.

## 6. Source and branch strategy

The neutral public fork is `https://github.com/BogieSmalls/racetime-app`, with:

- `origin` pointing to the BogieSmalls fork;
- `upstream` pointing to `racetimeGG/racetime-app`; and
- the local checkout retained in `Z1RR.RaceTime`.

The fork was created from upstream commit
`4dbe61fb06d2a132f2e1212e34ac2ae3a6d18069` on 2026-08-12.

`master` remains an unmodified mirror of `upstream/master`. At G0, Plan B
application changes may be implemented and tested on reviewed readiness feature
branches and worktrees, but no deployable production branch or environment is
activated. After G1, the approved changes move through review into the
long-lived `z1rr-production` branch. Upstream changes are merged deliberately,
tested under the applicable gate, and manually promoted. Production never
deploys an unreviewed upstream commit automatically.

The `z1rr-production` branch is not created or made default until Plan B is
activated. Creating and preserving the neutral fork remains authorized at G0.

Before contacting Dyn, source preservation should also include:

- all current remote branches and tags;
- a bare or bundle archive with a recorded checksum;
- a snapshot of the upstream wiki; and
- enough restoration notes to recreate the public fork if GitHub changes its
  fork relationship or upstream availability.

The GPL-3.0 license and upstream attribution remain intact. Ordinary GPL-3.0
does not impose an AGPL-style source-publication requirement merely because a
modified service is reachable over a network. G2 source and release artifacts
may be visible under ADR-008's reviewed branch policy, but that visibility is
not launch authorization. The team meets corresponding-source duties whenever
object code is conveyed and, as Council policy, publishes the exact source for
the public deployment at G3. Z1RR-specific commits remain focused for review.

License reference: <https://www.gnu.org/licenses/gpl-faq.en.html#UnreleasedMods>

## 7. Production topology

### 7.1 Public request path

Only Caddy is public. DNS for `racetime.z1rracing.com` resolves to a reserved or
stable OCI public address. Caddy:

- terminates TLS and renews certificates;
- redirects HTTP to HTTPS;
- proxies normal HTTP and WebSocket upgrades to Daphne;
- serves collected static assets and uploaded media from read-only/shared
  volumes as appropriate; and
- applies request-size and selected rate limits without changing Racetime room
  semantics.

Only ports 80 and 443 are internet-facing. SSH is key-only and restricted by
OCI security rules so port 22 is not publicly reachable. Operators use OCI
Bastion or another short-lived OCI-managed session for SSH access. MariaDB and
Redis are not published from the Compose network.

Inbound TCP 443 remains open to `0.0.0.0/0` in the OCI security list/NSG and
host firewall; if public IPv6 is enabled, it is also open to `::/0`.
Let's Encrypt's multi-perspective TLS-ALPN-01 validators are not assigned to the
operator allowlist. The G2 source-IP restriction is implemented only in Caddy's
ordinary HTTP handler after the TLS handshake, never at the OCI or host-network
layer.

### 7.2 Containers

The normal production stack contains:

- **Caddy:** TLS, reverse proxy, WebSocket forwarding, static/media delivery.
- **Racetime web:** Django served by Daphne/ASGI. Upstream's development
  `manage.py runserver` is not used in production.
- **Racetime racebot:** the upstream racebot process as an independent service.
- **MariaDB:** authoritative accounts, categories, races, results, rankings,
  OAuth applications, and audit data.
- **Redis:** Channels layer and cache; never treated as durable authority.
- **Backup/maintenance jobs:** database export, media backup, retention,
  integrity verification, and scheduled health tasks.

Persistent storage is limited to the MariaDB volume, media, separate
qualification/production Caddy state, operational state, and logs with enforced
rotation. Static assets and
application code are replaceable build artifacts.

### 7.3 External dependencies

The application relies on:

- Discord OAuth for public authentication;
- Twitch OAuth/API for optional channel linking and streaming checks;
- OCI Object Storage for off-machine backups;
- DNS and public certificate authorities;
- GitHub/container registry for source and pinned images; and
- Discord webhooks for operational alerts.

Failure of Discord prevents new logins but does not invalidate existing
sessions or stop active rooms. Failure of Twitch affects linking and streaming
checks but does not corrupt race data. External-service failures are surfaced
clearly and retried only where safe.

## 8. OCI placement and cost envelope

### 8.1 Current inventory as of 2026-08-22

Read-only OCI inventory found:

- `coop-relay`: running `VM.Standard.E2.1.Micro`, 1 GB RAM;
- `z1rr-restream-control`: stopped A1, 2 OCPUs / 6 GB;
- `z1rr-restream-control-staging`: stopped A1, 2 OCPUs / 6 GB;
- two stopped Restream encoder A1 VMs, each 12 OCPUs / 16 GB; and
- five retained 47 GB boot volumes, 235 GB total.

`coop-relay` does not consume A1 allowance. The existing boot volumes already
exceed OCI's currently documented 200 GB Always Free block-volume allocation.

### 8.2 Selected dedicated production allocation

After G1 activation, create a new Terraform-managed Compute instance named
`racetime` as:

- `VM.Standard.A1.Flex`;
- 1 OCPU;
- 6 GB RAM; and
- a new 50 GB Balanced boot volume, the current Terraform/image-source minimum.

Z1RR RaceTime owns this VM exclusively. `z1rr-restream-control-staging` remains
unchanged and available for its existing staging purpose until a separately
approved migration moves that work elsewhere. RaceTime production does not
share a host, Compose project, networks, volumes, or secrets with Restream
staging.

The Council accepts the intentional cost of the new boot volume. At current
published US list prices of $0.0255 per GB-month for storage plus $0.017 per
GB-month for Balanced performance, 50 GB costs $2.125, approximately $2.13 per
month. Read-only inventory on 2026-08-23 verified that all five retained boot
volumes report `size_in_gbs=47` and `vpus_per_gb=10`, totaling 235 GB. Creating
the new volume raises retained storage to 285 GB, 85 GB above the documented
200 GB allocation, for a projected retained-volume charge of $3.6125,
approximately $3.61 per month. OCI Cost Analysis remains billing authority.

The accepted paid storage overage requires this deployment to use a paid OCI
tenancy. Oracle's current official sources are inconsistent: the price list
explicitly gives each paid tenancy 3,000 A1 OCPU-hours and 18,000 GB-hours per
month, while the Always Free resource page says all accounts receive 1,500/9,000
and that paid accounts retain Always Free resources. The G1 preflight records
the account's billing status, Limits, Quotas and Usage output, Cost Analysis,
and current-month A1 usage before Terraform apply. The paid price-list allowance
is the planning case, but the tenancy record is operational authority. A
mismatch blocks apply only until compute cost and Restream headroom are repriced
and the Council records the revised decision.

A continuously running 1-OCPU/6-GB VM consumes 744 OCPU-hours and 4,464
GB-hours in a 31-day month. Under 3,000/18,000 it leaves 2,256 OCPU-hours and
13,536 GB-hours: at most 188 aggregate hours for a 12-OCPU/16-GB Restream
encoder, with OCPU-hours binding before memory.

The pessimistic 1,500/9,000 case leaves 756 OCPU-hours and 4,536 GB-hours with
the locked deployment: 63 aggregate encoder-hours. At current A1 list rates of
$0.01/OCPU-hour and $0.0015/GB-hour, a fully unallowanced 31-day compute line is
approximately $14.14; this is a bounded repricing case, not the expected budget.

The 1-OCPU/6-GB allocation is locked for launch. Run the full load gate early in
G2, before the fresh-production transition, using the greater of twice the
largest expected TTP-room load or the realistic aggregate peak across four
simultaneous race rooms. Failure blocks G2/G3
and requires profiling, optimization, and a complete retest on the same shape.
It does not authorize a resize or launch waiver. Any future CPU increase must
return to the Council as a new architecture decision with revised RaceTime
cost, Restream headroom, and amd64 recovery evidence.

After provisioning, G1 evidence records an expected A1 compute line of exactly
$0.00, the approximately $3.61 retained-storage forecast, and the resulting
combined monthly baseline as an exact dollar value. Any nonzero A1 compute line
causes an immediate entitlement/reforecast warning. Combined forecast or actual
spend above baseline plus $1 warns and above baseline plus $3 escalates. The
first complete billing cycle is reconciled against the entitlement evidence and
forecast.
The platform must not assume that an Always Free
VM has an SLA. OCI documents possible idle-instance reclamation and temporary
shape-capacity shortages, so rebuild onto a temporary paid shape is part of the
recovery plan.

References:

- <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm>
- <https://registry.terraform.io/providers/oracle/oci/latest/docs/resources/core_instance.html>
- <https://www.oracle.com/cloud/price-list/>
- <https://www.oracle.com/cloud/compute/arm/>
- <https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/resource-billing-stopped-instances.htm>
- <https://www.oracle.com/cloud/free/faq/>

## 9. Site identity, public accounts, and governance

### 9.1 Public authentication

Discord is the only public sign-in and account-creation mechanism.

1. The user selects **Continue with Discord**.
2. Z1RR RaceTime creates an OAuth authorization-code request with a short-lived,
   session-bound `state` value.
3. Discord returns basic identity after consent.
4. Z1RR RaceTime uses the immutable Discord user ID as the external account key.
5. On first login, the user selects an editable Racetime display name. The
   existing discriminator behavior resolves duplicate names.
6. The account is saved with an unusable local password.
7. Later logins resolve the same account even when the Discord username or
   display name changes.

Only the minimum Discord identity scope is requested. Discord access tokens
are not retained after the identity exchange unless a library requires a
short-lived session artifact; no refresh token is needed. Any valid Discord
account may sign in, and Z1RR server membership is not checked.

### 9.2 Compatibility with the upstream user model

The upstream user model requires a unique email and uses email as Django's
`USERNAME_FIELD`. To avoid a large authentication-model fork, public Discord
accounts receive a unique, internal, non-deliverable address such as
`<discord-id>@discord.invalid`. The address:

- is never requested from Discord;
- is never shown or editable in the public profile;
- is never used for mail; and
- remains an implementation detail, not a recovery credential.

As decided by ADR-001, an `ExternalIdentity` model links Discord to the
Racetime user. It stores `provider`, immutable provider `subject`, owning
`User`, and timestamps, with unique constraints on `(provider, subject)` and
`(provider, user)`. No Z1RR-specific `discord_id` field is added to the upstream
`User` table.

Public password login, password creation, password reset, email editing,
registration mail, public category requests, and Patreon UI are disabled.
Transactional site email is not a launch dependency.

### 9.3 Display name and connections

Discord authenticates the person but does not dictate the public racing name.
Users choose and later edit their Racetime display name under existing name
rules. Name changes remain forbidden while the user is in an active race.

Twitch remains a separate optional connection. A connected Twitch channel is
required only when the room's streaming policy requires one. Discord identity
and Twitch channel identity must not be conflated.

### 9.4 Break-glass access and recovery

One primary and one backup infrastructure operator retain local superuser
accounts with strong, unique passwords. Their staff login and Django admin are
not part of the public login flow and are reachable only through a restricted
operator path such as Bastion/SSH tunneling or tightly constrained ingress.

If a racer loses a Discord account, account transfer is a manual, audited
operator procedure with identity verification. There is no weaker email or
password fallback. Discord outages pause new logins; existing authenticated
sessions and active races continue.

### 9.5 Governance

The site contains one active public category, slug `z1rr`. All Z1RR Council
members are category owners. They can administer category details, goals,
moderators, bots, leaderboards, and race support through normal Racetime
category-owner interfaces.

The category's `max_owners` value is set by a site operator high enough for the
Council and reasonable growth. Upstream defaults it to five but validates
values through 100. Category owners can add or remove owners within the current
ceiling; only site staff can change the ceiling.

Council category ownership does not grant shell, database, Django staff,
secrets, OCI, backup, or deployment access.

### 9.6 Branding and attribution

Visible branding is **Z1RR RaceTime**. The site must clearly state that it is a
Z1RR-operated deployment powered by the open-source racetime.gg project, link
to the source fork and GPL license, and avoid implying endorsement by or shared
administration with racetime.gg.

The site needs a concise privacy notice, acceptable-use/moderation policy,
account-deletion explanation, and contact route. The privacy notice identifies
Discord and Twitch data used, logs retained for abuse/security, backup
retention, and the fact that deleted records may persist in encrypted backups
until retention expiry.

## 10. Site bootstrap and configuration

An idempotent management command or equivalent bootstrap operation configures:

- Z1RR site title, header, metadata, footer, links, and upstream attribution;
- the single `z1rr` category;
- the owner/moderator/bot ceilings;
- initial goals and category defaults;
- disabled public features such as category requests and Patreon;
- TTPBot's category bot identity/credentials; and
- required OAuth application records where safe to automate.

Bootstrap must be safe to rerun and must not overwrite Council-managed goals,
owners, or production credentials after initial creation. Secrets are injected
from deployment configuration, never printed or committed. One-time outputs
are stored directly in the appropriate secret store.

Production settings must override upstream's development defaults, including:

- unique secret keys;
- `DEBUG = False`;
- explicit allowed hosts and trusted origins;
- secure session and CSRF cookies;
- HTTPS redirects and HSTS;
- restricted CORS;
- real proxy/client IP handling;
- production database/Redis credentials;
- correct site URI and absolute-link generation;
- finite upload/body limits;
- structured logging; and
- static/media paths shared with Caddy.

## 11. Integration architecture

### 11.1 Z1RR.Restream: required for either outcome

Restream must separate **provider hosts** from **logical category sources**.
The provider registry supports at least:

- `racetime-gg` -> `https://racetime.gg`; and
- `z1rr-racetime` -> `https://racetime.z1rracing.com`.

Logical sources are configured independently:

- **Z1R:** provider `racetime-gg`, category `z1r`;
- **Z1RR if approved:** provider `racetime-gg`, category `z1rr`; or
- **Z1RR under Plan B:** provider `z1rr-racetime`, category `z1rr`.

The race browser remains one screen with clearly separated Z1RR and Z1R
sections. Z1RR appears first. UI labels reflect the logical community and also
make the actual host visible enough to prevent mistaken links or room actions.

Every race has a provider-qualified identity containing provider, category,
and room slug, for example:

- `racetime-gg:z1rr/example-slug`;
- `z1rr-racetime:z1rr/example-slug`; or
- `racetime-gg:z1r/example-slug`.

Provider identity and the original absolute room URL follow the race through:

- API responses and route parameters;
- current-race selection;
- broadcast drafts and hydration;
- crop discovery and synchronization;
- realtime/WebSocket connections;
- persisted broadcast history; and
- user-facing links.

Existing persisted races without provider data default to
`racetime-gg:z1r` for backward compatibility. If Z1RR changes providers later,
historical broadcasts retain their original host and never silently resolve
against the new provider.

Providers fail independently. A racetime.gg error affects only its section and
associated active connections; it cannot make the Z1RR RaceTime section
unusable, and vice versa.

### 11.2 TTPBot

TTPBot remains a standalone systemd service on `coop-relay`, preserving its
schedule, state files, Discord announcements, chat archives, seed behavior,
restart recovery, and duplicate-prevention logic.

Its Racetime destination becomes a first-class production configuration:

- if approved: host `racetime.gg`, category `z1rr`;
- under Plan B: host `racetime.z1rracing.com`, category `z1rr`, secure mode;
- distinct OAuth/category-bot credentials for the selected destination.

Hard-coded `racetime.gg` URL construction and `z1r`-specific naming are removed
from generated room links and announcements. Host, scheme, category, REST
paths, WebSocket paths, and absolute returned URLs derive from one validated
provider configuration.

Cutover enforces one active scheduler. The old destination is disabled before
the new destination is enabled, outside a room-open window, and the next
scheduled room is observed for exactly-once creation and announcement.

### 11.3 LiveSplit: Plan B only

If Dyn approves `racetime.gg/z1rr`, the stock LiveSplit Racetime provider is
sufficient and no Z1RR component is built.

Under Plan B, create an independently installable
`LiveSplit.Racetime.Z1RR.dll` rather than forking LiveSplit itself. LiveSplit's
component loader supports side-by-side DLL providers. The Z1RR provider has:

- a distinct assembly, factory, component, and menu identity;
- `racetime.z1rracing.com` REST and WSS endpoints;
- its own settings and Windows credential names;
- a Z1RR RaceTime OAuth application;
- a separate signed/reproducible release and update feed; and
- no collision with stock `LiveSplit.Racetime.dll`.

The desktop component is a public OAuth client and uses one required flow:
Authorization Code with S256 PKCE and no client secret. The application is
registered as a Django OAuth Toolkit public client with a fixed loopback
redirect such as `http://127.0.0.1:4888/`. The component opens a short-lived
loopback listener, generates cryptographically random `state` and
`code_verifier` values, sends the S256 challenge, verifies returned `state`, and
exchanges the code using `client_id`, exact redirect URI, and `code_verifier`
without a client secret. Refresh also authenticates as a public client without
a secret.

The fork pins `django-oauth-toolkit>=3.0,<4.0`; that library supports PKCE and
authorization-code exchange without a secret for public clients. Production
requires PKCE for the LiveSplit public-client application. The existing
Racetime compatibility behavior that strips PKCE parameters for an application
named `LiveSplit` must be removed or explicitly prevented from matching the
Z1RR application. End-to-end authorization, refresh, revocation, replay, wrong
verifier, wrong state, and occupied-loopback-port tests are release gates. If
the pinned server or client fails this flow, implementation must fix the server
or component before launch; embedding a confidential client secret or disabling
PKCE is not an acceptable fallback.

The official `LiveSplit.Racetime` repository currently does not declare a
license. Z1RR should recreate the provider against LiveSplit interfaces and
Racetime's documented public API/WebSocket behavior rather than copy and
redistribute unlicensed source. This licensing check is a release gate.

## 12. Legacy TTP archive

Historical import is not a launch blocker. After production stabilizes, an
export process snapshots public TTP Seasons 1–4 data from racetime.gg:

- four separate leaderboard standings;
- goal metadata and season ranges;
- public room metadata and results where useful; and
- original racetime.gg links and source timestamps.

Z1RR RaceTime presents the data in a separate, clearly labeled, read-only
**Legacy TTP Archive**. It does not:

- create local users for historical racers;
- insert old rooms into production race tables;
- affect new ratings or leaderboards; or
- claim the rooms were hosted by Z1RR RaceTime.

The raw export is reproducible and versioned or checksummed. The presentation
can be static data/templates or a bounded archive model, chosen during its own
design/plan after launch.

## 13. Deployment and qualification

### 13.1 Build and release

GitHub Actions builds and smoke-tests `linux/arm64` and `linux/amd64` variants
from one multi-stage Dockerfile and publishes a single multi-platform manifest
for each Git commit SHA. Releases are immutable. A1 production selects the
ARM64 digest; paid x86 disaster recovery selects the amd64 digest. Production
Compose pins exact digests or immutable tags and never follows `latest`.

Build reference: <https://docs.docker.com/build/building/multi-platform/>

Deployment is manual and performs:

1. active-race preflight;
2. verified pre-deployment database backup;
3. image pull/build verification;
4. migration preview/checks;
5. database migrations;
6. static asset collection;
7. controlled service restart;
8. HTTP, WebSocket, database, Redis, racebot, and login smoke tests; and
9. operator confirmation.

The deployment command refuses to proceed during an active room unless an
operator explicitly invokes a documented emergency override. Maintenance is
scheduled in historically quiet windows and announced when user-visible.

Application rollback pins the previous image. Schema-changing releases require
an explicit migration/rollback review because reverting code does not
automatically reverse database changes. Destructive migrations should use
expand/migrate/contract sequencing across releases.

### 13.2 Restricted production qualification

The new `racetime` VM is the production candidate used for G2 qualification.
Its first externally reachable deployment uses the final canonical hostname,
`racetime.z1rracing.com`. There is no `staging.racetime.z1rracing.com` record or
hostname/DNS promotion at G3.

The restriction is a Caddy default-deny source-IP allowlist implemented as the
first ordinary HTTP handler after the TLS handshake and before every
application, static, media, OAuth, and WebSocket route. A root-owned file
outside Git contains exact CIDRs for the primary and backup infrastructure
operators, approved scheduled testers, `coop-relay`, and the required Z1RR
Restream hosts. Each entry records owner, purpose, approving operators, and an
expiry no later than the end of its scheduled test window. Two operators
approve every change. There is no shared HTTP password.

Qualification certificate automation is explicit:

- Caddy initially uses one explicit ACME issuer and a persistent
  `caddy-qualification` data volume. Its `dir` and CertMagic `test_dir` are both
  pinned to Let's Encrypt's staging endpoint, so automatic fallback/retry stays
  in staging. No production or ZeroSSL issuer is configured. Staging roots are
  available only through process-scoped CA bundles or disposable browser-
  automation profiles that are destroyed after the run, never ordinary
  operator/client OS trust stores.
- Staging certificates use test CT logs and are not reliably discoverable
  through production CT monitoring. This reduces but does not promise zero
  hostname disclosure during qualification.
- TLS-ALPN-01 is the only enabled challenge. Caddy completes it during the TLS
  handshake before the source-IP HTTP handler; HTTP-01 is disabled, so
  `/.well-known/acme-challenge/` is not a public allowlist exemption. Port 80
  serves no application or challenge path while restricted; it redirects only
  allowlisted sources and gives unlisted sources the generic denial.
  The OCI security list/NSG and host firewall keep TCP 443 open to
  `0.0.0.0/0` and, when enabled, `::/0`; neither layer applies the qualification
  CIDRs. Source-IP denial occurs only in Caddy after TLS-ALPN-01 can complete.
- After fresh production application state is active behind the transition
  barrier in late G2, operators create `caddy-production` exactly once. Its one
  explicit ACME issuer pins both `dir` and `test_dir` to Let's Encrypt's
  production endpoint; no ZeroSSL issuer is present. This prevents CertMagic's
  retry path from crossing from production to staging. The G2 transition
  controller has a bounded issuance-observation deadline; any Caddy background
  retries remain production-only. A deadline breach alerts operators, leaves the
  maintenance/default-deny barrier in place, and blocks G2; Caddy never serves
  or promotes an untrusted fallback certificate. Successful issuance makes
  `racetime.z1rracing.com` visible in public CT logs; the Council accepts this
  narrowly timed disclosure after G1 activation.
- The production Caddy state volume persists across application-state resets,
  deployments, and rollbacks and is included in encrypted recovery artifacts.
  Preflight rejects accidental recreation without incident approval and an
  explicit certificate-rate-limit check; the current exact-identifier limit is
  five new certificates per seven days and must be reverified at G1.

An unlisted source receives a generic `404`, cannot fetch assets or reach an
OAuth callback, and cannot receive a WebSocket `101`. Before either issuance,
CI adapts the Caddyfile to JSON and rejects anything other than exactly one
issuer with `ca == test_ca ==` the expected environment endpoint, HTTP-01
disabled, and TLS-ALPN-01 enabled. A hermetic issuer-failure test proves retries
cannot cross environments. Pre-production-certificate evidence is limited to
those config/failure tests, denial probes from at least three unlisted public
sources, and browser/server-side checks using only process-scoped CA bundles or
disposable automation profiles. It does not count TTPBot, Restream, or LiveSplit
end-to-end integration evidence. After the production certificate is issued and
the hard barrier returns to the normal G2 allowlist, final evidence includes
successful allowed browser/OAuth/TTPBot/Restream/LiveSplit/WSS flows using
ordinary certificate validation with no bypass; staging and production issuer
identity; HTTP-01 denial; exactly one production issuance; and persistence of
the production Caddy state across an application redeploy.

Qualification runs the exact immutable production image and production Compose
topology with final hostname/TLS/proxy/security configuration, qualification-
only MariaDB/Redis/media volumes, non-production integration credentials, and
no production scheduler or production Discord announcement.

While the canonical host is still restricted under G2, operators:

1. Enter a maintenance/default-deny transition barrier that blocks every
   externally routed application path, including previously allowlisted testers
   and integrations. Retain only internal health checks and root/operator access
   to local management commands; neither is routed through public Caddy.
   Stop all qualification schedulers and writes.
2. Seal qualification backups beneath a distinct `qualification/` object prefix;
   production restore tooling rejects that prefix.
3. Create fresh production MariaDB, Redis, media, and application-operational
   volumes plus the approved production secret bundle. These do not reuse or
   replace either Caddy state volume.
4. Stop the Compose application and repoint it to the fresh production volumes,
   but do not start it.
5. While the application remains stopped and the transition barrier remains
   enforced, revoke qualification Discord/Twitch/OAuth/bot/alert credentials and
   invalidate qualification sessions and tokens. Verify provider-side revocation
   where the provider exposes that state.
6. Start the application on fresh production state behind the transition barrier.
7. Bootstrap final production site/category/owner state with a root/operator
   management command executed locally on the host.
8. Create the persistent production Caddy state once, switch to production
   ACME, issue the public certificate, and retain short G2 HSTS.
9. After revocation, bootstrap, and production-TLS evidence passes, replace the
   hard transition barrier with the normal G2 source-IP allowlist. Public access
   remains denied. Rerun deployment, login, HTTP/WSS, TLS/issuer, integration
   smoke, and dress-rehearsal checks against the fresh production state.
10. Obtain the Council's G3 go/no-go decision only after that evidence passes;
    only G3 removes the canonical-host source-IP restriction.

Rollback may use the last valid production backup/release, but never
qualification data, backups, sessions, tokens, or credentials.
`z1rr-restream-control-staging` remains a separate Restream staging host and is
not part of the RaceTime qualification deployment.

References:

- <https://letsencrypt.org/docs/staging-environment/>
- <https://letsencrypt.org/docs/rate-limits/>
- <https://letsencrypt.org/docs/challenge-types/#tls-alpn-01>
- <https://caddyserver.com/docs/automatic-https>
- <https://caddyserver.com/docs/caddyfile/directives/tls>
- <https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/securitylists.htm>

## 14. Backups and disaster recovery

### 14.1 Backup policy

Encrypted off-machine backups are written to a private OCI Object Storage
bucket:

- encrypted production Caddy state after initial issuance, renewal, or material
  change, retaining the current and two previous verified generations;
- compressed MariaDB logical export every six hours;
- media snapshot nightly;
- additional database backup before each deployment;
- rolling recovery points for 14 days;
- weekly recovery points for three months; and
- monthly recovery points through one year.

A deduplicating/encrypted backup tool may implement the policy as long as
restore points and retention are independently verifiable. Encryption keys
must have an operator-held recovery copy outside the VM and outside the backup
bucket. OCI-side encryption and private bucket policy remain enabled even when
client-side encryption is used.

The approximately $3.61 monthly projection in §8.2 covers retained boot-volume
overage only. Object Storage is a separate, usage-dependent cost surface: fixed
retention-point counts do not cap bytes as MariaDB and media grow. At G1,
operators record the tenancy's applicable free byte/request entitlements,
current tier usage, and the compressed/encrypted size of the first full backup.
Monitoring alarms at 75% and 90% of the verified byte and request entitlements;
forecast charges or a retention expansion require Council approval. Lifecycle
pruning is tested so expired points release storage rather than grow forever.

Expected objectives are:

- database RPO: no more than six hours;
- media RPO: no more than 24 hours; and
- service RTO: target four hours when compatible OCI capacity is available.

### 14.2 Restore assurance

Backup success means more than upload success. Jobs verify object presence,
non-zero size, encryption/decryption, and database dump integrity. At least
quarterly, automation restores into an isolated empty database, starts a
temporary application stack, and verifies accounts, category configuration,
representative race data, and media references.

### 14.3 VM-loss recovery

The disaster-recovery package consists of:

- infrastructure and firewall configuration in Git;
- production Compose/Caddy configuration;
- encrypted production Caddy state;
- pinned multi-platform application image/source;
- operator-held secrets and backup key;
- encrypted Object Storage backups;
- DNS update instructions; and
- a rehearsed rebuild/restore runbook.

If A1 capacity is unavailable, the primary paid fallback is
`VM.Standard.E5.Flex` at 1 OCPU/6 GB using the release's `linux/amd64` variant.
At G1, a capacity report and image-compatibility check must verify that shape in
the home region; if unavailable, operators record an equivalent paid amd64
shape at 1 OCPU/6 GB before G2 can complete. Before G3, the selected amd64 shape
must pass the same load/headroom gate and restore within four hours. A quarterly
isolated recovery exercise restores the amd64 image and encrypted production
data/Caddy state and proves the target four-hour RTO. Any different temporary
CPU count or performance target requires a new Council-approved architecture
decision; it is not implied by invoking DR. Cost alerts remain active, and the
service can move back to A1 after capacity returns.

## 15. Monitoring, alerting, and logs

A minimal `/healthz` endpoint reports health without exposing versions,
credentials, database details, or internal addresses. Internal checks cover web
process, MariaDB, Redis, and required racebot behavior.

Monitoring covers:

- public HTTPS and WebSocket reachability;
- container health and restart loops;
- CPU, memory, disk, inode, and database growth;
- active-room and racebot anomalies;
- backup freshness and retention failure;
- Object Storage bytes, request count, lifecycle pruning, and spend forecast;
- TLS renewal;
- Discord and Twitch integration failures;
- repeated authentication/rate-limit abuse;
- OCI resource limits; and
- OCI spending thresholds.

Application/host alerts and OCI webhook notifications go to a private Z1RR
operations Discord channel. OCI billing email remains a fallback. If OCI cannot
deliver directly to Discord, a small authenticated webhook adapter on
`coop-relay` converts OCI notifications into Discord messages.

Logs are structured, rotated, and scrubbed of OAuth codes, access tokens,
secrets, session cookies, and unnecessary personal data. Audit logs distinguish
site staff actions, category-owner actions, moderation actions, deployment
events, and manual identity recovery.

## 16. Security controls

Required controls include:

- root-owned environment files or OCI Vault for secrets; never Git;
- separate production and qualification credentials;
- least-privilege OCI dynamic groups/policies for backup upload and monitoring;
- no public MariaDB or Redis listeners;
- non-root containers and dropped Linux capabilities where supported;
- read-only application filesystems except declared volumes;
- pinned dependencies/base images and automated vulnerability reporting;
- secure proxy headers, cookies, CSRF, and allowed hosts/origins; HSTS is
  `max-age=300` through G2 and at least `31536000` after G3, without preload;
- OAuth `state`, exact redirect-URI allowlists, short-lived codes, and mandatory
  S256 PKCE for public clients;
- distributed rate limiting for Discord login initiation/callback failures,
  OAuth decisions, race creation, account/admin mutations, search, and other
  abuse-prone endpoints;
- upload type/size validation and non-executable media delivery;
- key-only restricted SSH and patched host/container runtime;
- protected GitHub branches and reviewed production changes; and
- periodic access review for superusers, Council owners, bots, OAuth clients,
  Discord webhooks, and OCI policies.

Limiter loss fails closed for authentication, OAuth decisions, race creation,
and account/admin mutations. Ready/start/done/DNF/DQ/split requests are
authoritative in-race state transitions: during limiter loss they continue
against MariaDB under bounded per-process emergency controls and emit an audit
event plus operations alert. Ordinary chat/search may remain unavailable. Raw
identity never appears in keys or logs.

Security controls must not make an active race depend on Discord availability
after login or on Redis limiter availability for authoritative state changes.
Revocation, bans, and manual account transfer require documented, audited
behavior.

## 17. Failure handling

| Failure | Expected behavior |
| --- | --- |
| Discord unavailable | Existing sessions and active races continue; new login shows a clear retryable error. |
| Twitch unavailable | Existing race data remains safe; linking/stream checks fail closed with a clear message. |
| Redis/limiter restarts | Clients reconnect with bounded backoff; authoritative state reloads from MariaDB; core in-race state transitions use bounded audited emergency controls instead of being denied. |
| MariaDB unavailable | Mutating requests fail safely; services do not fabricate or partially record results. |
| Racebot crashes | Container restarts and alerts; room state remains authoritative in the database. |
| One Restream provider fails | Only that provider's section/connection errors; the other source remains usable. |
| TTPBot loses connection | It reconnects without duplicate rooms/webhooks, using persisted idempotency state. |
| Backup fails | Production remains available; an immediate operations alert identifies the missing recovery point. |
| Deployment smoke test fails | Stop promotion and pin the previous image; follow the migration-specific rollback procedure. |
| Disk approaches limit | Alert before exhaustion; halt nonessential staging/backups locally while preserving off-machine backups. |
| VM is lost/reclaimed | Rebuild from Git and Object Storage on A1 or the recorded paid amd64 fallback. |

## 18. Verification and launch gates

### 18.1 Core application

Verify:

- first Discord login and account creation;
- repeat login after Discord username/display-name changes;
- user-selected Racetime display names and duplicate-name discrimination;
- denied/canceled/expired OAuth and invalid `state` handling;
- logout and session expiry;
- disabled public password/email/category-request surfaces;
- restricted break-glass login;
- manual lost-Discord-account transfer with audit entry;
- Twitch link/unlink and streaming-required behavior;
- public race creation by an ordinary registered user;
- complete entrant ready/start/done/DNF/DQ lifecycle;
- chat, reconnection, moderation, recording, and leaderboard updates; and
- Council owner permissions without infrastructure permissions.

### 18.2 Integrations

The order is mandatory. Before step 8 in Section 13.2 issues the production
certificate, run only the ACME/configuration, denial, and browser/server-side
checks that use process-scoped CA bundles (for example `REQUESTS_CA_BUNDLE` or
`NODE_EXTRA_CA_CERTS`) or a disposable browser-automation profile. Do not add
the staging root to Windows, Linux, container-base, or other ordinary trust
stores, and do not count a trust bypass as final integration evidence. After
step 9 restores the normal G2 allowlist, run every end-to-end item below against
the production certificate with ordinary certificate validation and no CA
override or bypass.

Verify:

- TTPBot creates exactly one scheduled room on the selected host/category;
- correct absolute room URLs in Discord announcements and persisted bot state;
- reminders, seed handling, chat archive, restart recovery, and duplicate
  suppression;
- stock and Z1RR LiveSplit providers installed side by side under Plan B;
- the Z1RR provider's login, join, ready, start, split/finish, forfeit, and
  reconnect behavior;
- Restream shows separate Z1RR and Z1R sections on one screen;
- `z1rr` works when configured on either provider host;
- provider-qualified identity survives drafts, hydration, sync, realtime,
  history, and links; and
- failure of either provider does not break the other.

### 18.3 Operations

Verify:

- one immutable manifest builds and smoke-tests both `linux/arm64` and
  `linux/amd64`, and the ARM64 variant starts from an empty A1 host;
- migrations and bootstrap are repeatable;
- active-race deployment refusal;
- successful deployment and application rollback;
- database/media/Caddy-state backup, retention, encryption, restore eligibility,
  Object Storage lifecycle pruning, byte/request alarms, and cost forecast;
- full restore to an empty isolated ARM64 environment and quarterly restore to
  the recorded paid amd64 fallback within the target RTO;
- the recorded paid amd64 fallback passes the same load/headroom gate at the
  fixed 1-OCPU/6-GB configuration before G3;
- staging-ACME qualification, test-only trust, adapted-config issuer pinning,
  a hermetic no-cross-environment fallback test, a bounded transition deadline,
  TLS-ALPN-only validation, HTTP-01 denial, one late-G2 production issuance,
  production Caddy-state persistence, TLS renewal, HSTS transition, and
  WebSocket proxy behavior;
- OCI/host/service/billing alerts reach operations Discord, and launch/rollback
  public communications meet the independent-path timing and cadence contract;
- the paid-tenancy entitlement record resolves the official-source discrepancy;
  expected A1 compute is $0.00, any nonzero compute line alerts, and locked
  1-OCPU Restream headroom is recorded under both entitlement cases;
- OCI/host ingress leaves public TCP 443 available for TLS-ALPN-01 while Caddy's
  post-handshake source-IP policy denies unapproved HTTP and WebSocket traffic;
- logs omit credentials and rotate before filling disk; and
- the greater of twice the largest expected TTP-room browser/chat/reconnect load
  or the realistic aggregate peak across four simultaneous rooms passes early
  G2 with the required headroom on the locked 1-OCPU/6-GB shape.

### 18.4 Launch definition

Plan B is launch-ready only when a scheduled race can be created by TTPBot,
announced in Discord, joined and controlled from browsers and the Z1RR
LiveSplit provider, displayed in Z1RR.Restream, completed, recorded, and ranked
without depending on racetime.gg administration.

## 19. Activation and cutover

Source preservation is already active and must finish before the Council
contacts Dyn. Restream's provider/category abstraction is outcome-independent.
During G0, the team may also implement and verify all contingency application,
image, IaC-definition, integration, release, and runbook artifacts locally or
with hermetic test doubles. This work creates no public or billable Plan-B
resource and is discarded if the Racetime.gg category request succeeds.

Terraform apply, OCI resource creation or mutation, DNS changes, external app
registration, secret creation, any restricted deployment, and publication are
forbidden until the Council explicitly records G1 activation. The canonical
host remains operator-restricted through G2 finalization and becomes public
only after G3 approval.

Public cutover occurs in a historically quiet, race-free window. Before the
Council votes on G3, G2 has already sealed the qualification evidence, switched
the deployment to fresh production state and secrets, revoked qualification
credentials and sessions, verified a production backup, and completed the
restricted production smoke test and dress rehearsal. The canonical
`racetime.z1rracing.com` DNS record and TLS configuration are already present
and operator-restricted; G3 does not change the hostname or promote a staging
record.

After the Council records G3 Go:

1. Verify the signed G2 evidence, G3 decision record, frozen release hashes,
   eligible production backup, and existing canonical DNS, TLS, health checks,
   and alert delivery.
2. Publish the exact corresponding RaceTime source, launch instructions, and
   Z1RR LiveSplit provider.
3. Disable TTPBot's scheduler for the old destination and verify that it has no
   active room or pending creation job.
4. Through the cutover state machine, remove the canonical-host source-IP
   restriction, raise HSTS to at least one year without preload, and enable the
   new scheduler destination while enforcing that exactly one production
   scheduler is enabled.
5. Observe the first scheduled room and its TTPBot, LiveSplit, Restream, OAuth,
   WebSocket, and audit-log flows.
6. Monitor the first week closely and retain rollback configuration.

Qualification state, backups, sessions, and credentials are never rollback
assets. Early rollback re-applies the canonical-host restriction, disables the
new scheduler, and restores the old Racetime.gg destination only after the
single-scheduler and room-integrity checks pass. Application rollback may use
only eligible production backups and frozen production releases; it never
changes DNS or restores qualification state.

Before a non-emergency rollback hides the canonical host, operations announces
the rollback, impact, fallback destination, and next-update time in the public
Z1RR Discord. A security/integrity emergency may restrict first but must announce
within five minutes through the independent Discord path. Operations posts
updates on the promised cadence and a resolution notice after service or the old
destination is verified.

If Dyn approves `racetime.gg/z1rr`, self-hosting work is canceled:

- Restream enables its logical Z1RR source at `racetime-gg:z1rr`;
- TTPBot changes only its category to `z1rr` and receives appropriate bot
  credentials;
- the stock LiveSplit Racetime provider remains in use; and
- the Plan B VM, Discord-auth changes, and separate LiveSplit provider are not
  deployed.

## 20. Implementation decomposition

Each subproject receives its own implementation plan, tests, and release gate:

1. **Source preservation and upstream workflow** (`racetime-app`,
   outcome-independent and completed before contacting Dyn)
2. **Restream provider/category abstraction** (`Z1RR.Restream`, required in
   either outcome and authorized independently of Plan B activation)
3. **OCI production platform and recovery automation** (`racetime-app`
   deployment assets plus OCI configuration)
4. **Discord identity and Z1RR site bootstrap** (`racetime-app`)
5. **TTPBot provider-safe destination configuration** (`TTPBot`)
6. **Z1RR LiveSplit provider** (new repository, Plan B only)
7. **End-to-end qualification, cutover, and operations runbooks** (cross-repository)
8. **Legacy TTP archive** (post-launch follow-up)

The dependency order under Plan B is:

- complete source preservation before contacting Dyn;
- after Plan B activation, establish deployment foundations;
- implement core application/identity and deploy the restricted qualification
  environment on the canonical hostname;
- implement Restream, TTPBot, and LiveSplit integrations in parallel against
  that restricted environment, but defer their final end-to-end evidence until
  late-G2 production-certificate issuance;
- complete backups, monitoring, security, load, and restore verification;
- execute the dress rehearsal and public cutover; and
- add the legacy archive after stabilization.

No implementation plan may silently broaden the design into ordinary Z1R race
migration, account federation, or high availability. Those would require a new
design decision.
