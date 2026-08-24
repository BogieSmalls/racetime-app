# Z1RR RaceTime Core Identity and Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the upstream Racetime application into a tested Z1RR-branded service with Discord-only public accounts, safe OAuth/PKCE behavior, one idempotently bootstrapped `z1rr` category, and minimal health interfaces.

**Architecture:** Keep the upstream `User` model and racing engine intact. Link Discord with a separate `ExternalIdentity`, complete new-account creation only after display-name selection, use feature flags to remove public password/email/Patreon/category-request surfaces, and keep local superusers for the loopback-only operator path supplied by the platform plan.

**Tech Stack:** Python 3.12, Django 5.2, Django OAuth Toolkit 3.x, Channels, MariaDB/SQLite test settings, Redis/locmem test cache, `unittest.mock`, HTML/CSS/JavaScript

---

## Control documents

**Spec:** [Plan-B RaceTime architecture](../specs/2026-08-12-plan-b-racetime-architecture-design.md)
**Requirements and gates:** [Requirements and decision record](../../racetime-z1rr/requirements-and-decisions.md)
**Artifact register:** [Launch artifact register](../../racetime-z1rr/artifact-register.md)
**Master plan:** [Contingency launch master plan](2026-08-22-z1rr-racetime-launch-master.md)
**Requirements owned:** FR-CORE-002–006, FR-ID-001–007, the server half of FR-LS-003, NFR-SEC-001/003/004, NFR-PRIV-001, and NFR-TEST-001.

## Global Constraints

- G0 permits only local, non-public readiness work. OCI apply, DNS, production OAuth/apps, scheduler changes, publication, and cutover require their recorded G1–G3 gates.
- Preserve both outcome lanes: `racetime.gg/z1rr` and self-hosted `racetime.z1rracing.com/z1rr`. Do not alter ordinary `racetime.gg/z1r` pickup racing.
- RaceTime application work targets Django 5.2/Python 3.12 and produces same-commit immutable linux/arm64 and linux/amd64 images; A1 production runs ARM64 and the paid disaster-recovery fallback runs amd64. Provider work must preserve its plan's declared runtime.
- Production origins are one validated HTTPS origin with no path/query/userinfo; every REST/WSS/link derives from it and historical references remain provider-qualified.
- Discord is the sole public self-hosted login. Never persist Discord access/refresh tokens or grant category owners Django staff, host, database, secret, backup, or OCI access.
- Preserve GPL-3.0/upstream attribution and corresponding source for every deployed RaceTime build; LiveSplit work stays clean-room and copies no unlicensed legacy-provider code.

## File map

- Create `project/settings/test.py`: deterministic SQLite/locmem settings and dummy external configuration.
- Create `project/settings/ci.py`: service-backed MariaDB/Redis settings used only by CI/integration qualification.
- Create `racetime/models/identity.py`: `ExternalIdentity` model and invariants.
- Create `racetime/migrations/0082_externalidentity.py`: additive identity migration.
- Create `racetime/discord.py`: Discord endpoint client, response validation, state/pending-session helpers, safe next handling, and rate-limit key construction.
- Create `racetime/throttling.py`: Redis-backed policy for authentication and other abuse-prone endpoints.
- Create `racetime/views/discord_auth.py`: login initiation, callback, first-user name selection, and controlled error handling.
- Create `racetime/templates/racetime/user/discord_create_account.html`: name-selection form.
- Create `racetime/templates/racetime/user/discord_error.html`: non-sensitive retry page.
- Create `racetime/management/commands/transfer_external_identity.py`: dry-run/confirmed audited recovery.
- Create `racetime/management/commands/bootstrap_z1rr.py`: idempotent site/category/goals/owners setup.
- Create `racetime/views/health.py`: public liveness and authenticated/internal readiness views.
- Create `racetime/templates/racetime/policy/*.html`: privacy, acceptable use, account deletion, contact pages.
- Create `docs/policies/*.md`: Council-reviewable source text for privacy, acceptable use, deletion, and contact.
- Create `racetime/tests/identity/`, `racetime/tests/site/`, `racetime/tests/oauth/`, `racetime/tests/health/`: substantive Django tests.
- Modify `racetime/models/__init__.py`: export `ExternalIdentity`.
- Modify `racetime/views/__init__.py`: export Discord/health/policy views.
- Modify `racetime/urls.py`: Discord/public-policy/health routes and production feature gating.
- Modify `racetime/forms.py`: Discord name form and public profile form without email.
- Modify `racetime/views/user.py`: Discord landing/profile/deletion branding and PKCE compatibility guard.
- Modify account/base templates and static assets: Z1RR identity and correct account navigation.
- Modify `project/settings/base.py`: upstream-compatible defaults for new feature flags.
- Modify `package.json`, `package-lock.json`: close the high-severity `js-cookie` advisory.
- Create `.github/workflows/test.yml`: Django/MySQL/Redis, static assets, audit, migration and checks.

## Task 1: Create a real test baseline and close the known front-end advisory

**Files:**
- Create: `project/settings/test.py`
- Create: `project/settings/ci.py`
- Create: `racetime/tests/settings/test_test_settings.py`
- Create: `racetime/tests/settings/test_ci_settings.py`
- Create: `.github/workflows/test.yml`
- Modify: `package.json`
- Modify: `package-lock.json`

- [ ] **Step 1: Write a failing settings isolation test**

```python
from django.conf import settings
from django.test import SimpleTestCase

class TestSettingsTests(SimpleTestCase):
    def test_test_settings_are_isolated(self):
        self.assertFalse(settings.DEBUG)
        self.assertEqual(settings.EMAIL_BACKEND, "django.core.mail.backends.locmem.EmailBackend")
        self.assertEqual(settings.CHANNEL_LAYERS["default"]["BACKEND"], "channels.layers.InMemoryChannelLayer")
        self.assertNotIn("debug_toolbar", settings.INSTALLED_APPS)
```

- [ ] **Step 2: Run it and verify failure**

```powershell
.\venv\Scripts\python.exe manage.py test racetime.tests.settings --settings=project.settings.test -v 2
```

Expected: FAIL because `project.settings.test` does not exist.

- [ ] **Step 3: Implement test settings**

For `project.settings.test`, import `base`, set `DEBUG=False`, remove `debug_toolbar` app/middleware, use an in-memory SQLite database, in-memory channel layer/cache, locmem email, fast password hasher, `RT_SITE_URI="https://testserver"`, and dummy Discord/Twitch values. This is the deterministic fast unit-test profile and must never be described as service-backed. New settings flags are:

```python
RT_PUBLIC_PASSWORD_AUTH = False
RT_PUBLIC_CATEGORY_REQUESTS = False
RT_PATREON_ENABLED = False
RT_DISCORD_AUTH_ENABLED = True
RT_ENABLE_LEGACY_LIVESPLIT_PKCE_BYPASS = False
```

- [ ] **Step 4: Run settings test**

Expected: PASS and at least one test is discovered.

- [ ] **Step 5: Implement and test the service-backed CI profile**

`project.settings.ci` imports the test-safe flags but replaces `DATABASES` with `django.db.backends.mysql`, `CACHES` with the Redis cache backend, and `CHANNEL_LAYERS` with the Redis channel layer using required CI-only environment variables. `test_ci_settings.py` asserts the selected engine/backends and performs database transaction, cache set/get/delete, and channel send/receive tests. Missing service variables fail startup.

Run once against intentionally absent services and observe a connection failure; the service-backed job below must be the only place where this profile is accepted.

- [ ] **Step 6: Update `js-cookie` to a non-vulnerable current compatible release**

Use `npm install js-cookie@latest --save-exact`, review the package changelog/API compatibility, and run the existing static UI smoke. Do not suppress the advisory.

- [ ] **Step 7: Verify dependency state**

```powershell
npm ci
npm audit --omit=dev
```

Expected: no high/critical production finding.

- [ ] **Step 8: Add two explicit CI test jobs**

The fast job runs all tests with `project.settings.test` and has no service containers. The integration job declares MariaDB and Redis services with health checks, passes only CI fixture credentials, runs `racetime.tests.settings.test_ci_settings` and the full suite with `project.settings.ci`, and fails if the service probes are skipped. Both jobs run `npm ci`, audit, `collectstatic --noinput`, `makemigrations --check --dry-run`, and `check --deploy` using fixture production settings; record non-zero test counts. Grant only `contents: read`.

Acceptance requires both job names and their logs. A green SQLite job cannot substitute for a failed/skipped MariaDB/Redis job.

- [ ] **Step 9: Commit**

```powershell
git add project\settings\test.py project\settings\ci.py racetime\tests\settings .github\workflows\test.yml package.json package-lock.json
git commit -m "test: establish racetime application baseline"
```

## Task 2: Add the external-identity model

**Files:**
- Create: `racetime/models/identity.py`
- Create: `racetime/migrations/0082_externalidentity.py`
- Create: `racetime/tests/identity/test_model.py`
- Modify: `racetime/models/__init__.py`
- Modify: `racetime/admin/__init__.py`

- [ ] **Step 1: Write failing model tests**

```python
class ExternalIdentityModelTests(TestCase):
    def test_provider_subject_and_provider_user_are_unique(self):
        user = User.objects.create_user("1@discord.invalid", name="Racer")
        ExternalIdentity.objects.create(user=user, provider="discord", subject="1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExternalIdentity.objects.create(user=user, provider="discord", subject="2")

    def test_identity_is_deleted_with_user(self):
        user = User.objects.create_user("1@discord.invalid", name="Racer")
        identity = ExternalIdentity.objects.create(user=user, provider="discord", subject="1")
        identity_id = identity.id
        user.delete()
        self.assertFalse(ExternalIdentity.objects.filter(id=identity_id).exists())
```

Also test canonical lowercase provider, numeric non-empty Discord subject validation, `last_authenticated_at`, and uniqueness of `(provider, subject)` across users.

- [ ] **Step 2: Run and verify failure**

```powershell
.\venv\Scripts\python.exe manage.py test racetime.tests.identity.test_model --settings=project.settings.test -v 2
```

Expected: import/model failure.

- [ ] **Step 3: Implement the model**

```python
class ExternalIdentity(models.Model):
    user = models.ForeignKey("User", on_delete=models.CASCADE, related_name="external_identities")
    provider = models.CharField(max_length=32)
    subject = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    last_authenticated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("provider", "subject"), name="unique_external_provider_subject"),
            models.UniqueConstraint(fields=("provider", "user"), name="unique_external_provider_user"),
        ]
```

Normalize/validate in a manager/service before persistence; do not store Discord usernames, email, avatar, access token, or refresh token in this table.

- [ ] **Step 4: Generate and inspect the additive migration**

```powershell
.\venv\Scripts\python.exe manage.py makemigrations racetime --name externalidentity
.\venv\Scripts\python.exe manage.py sqlmigrate racetime 0082 --settings=project.settings.test
```

Expected: one new table/index/constraints; no `User`, race, or leaderboard rewrite.

- [ ] **Step 5: Register a read-only-oriented admin view**

Allow staff search by user/provider/subject and view timestamps. Disallow normal add; identity creation/recovery uses tested flows.

- [ ] **Step 6: Run migration/model tests**

Expected: PASS, including migrate from 0081 to 0082 and reverse to 0081 in a migration test.

- [ ] **Step 7: Commit**

```powershell
git add racetime\models racetime\migrations\0082_externalidentity.py racetime\tests\identity racetime\admin\__init__.py
git commit -m "feat: add provider-neutral external identities"
```

## Task 3: Implement the Discord client and state lifecycle

**Files:**
- Create: `racetime/discord.py`
- Create: `racetime/tests/identity/test_discord_client.py`
- Modify: `project/settings/base.py`

- [ ] **Step 1: Write failing authorization URL/state tests**

Assert exact Discord authorize origin/path, `response_type=code`, configured client ID/redirect, scope exactly `identify`, URL-safe 256-bit state, safe same-host `next`, issued timestamp, and one pending state per session.

- [ ] **Step 2: Write failing callback/token/user tests**

Mock `requests.Session`. Cover timeout, non-200, invalid JSON, missing/invalid `id`, mismatch/expired/replayed state, provider denial, and verify that exceptions/messages never contain code, client secret, token, or full response body.

- [ ] **Step 3: Run tests and observe failure**

```powershell
.\venv\Scripts\python.exe manage.py test racetime.tests.identity.test_discord_client --settings=project.settings.test -v 2
```

Expected: FAIL because client/helpers are absent.

- [ ] **Step 4: Implement the client contract**

```python
from abc import ABC, abstractmethod

@dataclass(frozen=True)
class DiscordIdentity:
    subject: str

class DiscordOAuthClientContract(ABC):
    @abstractmethod
    def authorization_url(self, state: str) -> str: raise NotImplementedError
    @abstractmethod
    def exchange_code(self, code: str) -> str: raise NotImplementedError
    @abstractmethod
    def fetch_identity(self, access_token: str) -> DiscordIdentity: raise NotImplementedError
```

Use configured `DISCORD_AUTHORIZE_URL`, `DISCORD_TOKEN_URL`, and `DISCORD_USER_URL`, exact redirect URI, connect/read timeout tuple, `raise_for_status`, and an allowlisted identity parser. Return only immutable subject. Keep access token local to the callback stack frame.

- [ ] **Step 5: Implement consume-once session state**

Use `secrets.token_urlsafe(32)`, store `{state, issued_at, next}`, compare with `secrets.compare_digest`, enforce 10 minutes, and `pop` before validation so mismatch/replay consumes it. Validate `next` using `url_has_allowed_host_and_scheme` and HTTPS.

- [ ] **Step 6: Add fail-closed base defaults**

Base defaults keep upstream development usable (`RT_DISCORD_AUTH_ENABLED=False`) and define no production credential. The production plan requires all Discord settings when enabled.

- [ ] **Step 7: Run tests and commit**

```powershell
.\venv\Scripts\python.exe manage.py test racetime.tests.identity.test_discord_client --settings=project.settings.test -v 2
git add racetime\discord.py racetime\tests\identity\test_discord_client.py project\settings\base.py
git commit -m "feat: add secure Discord OAuth client"
```

## Task 4: Implement Discord login and atomic first-account creation

**Files:**
- Create: `racetime/views/discord_auth.py`
- Create: `racetime/templates/racetime/user/discord_create_account.html`
- Create: `racetime/templates/racetime/user/discord_error.html`
- Create: `racetime/tests/identity/test_discord_views.py`
- Modify: `racetime/forms.py`
- Modify: `racetime/views/__init__.py`
- Modify: `racetime/urls.py`

- [ ] **Step 1: Write failing existing-user login tests**

Cover initiation redirect, callback finds `ExternalIdentity(provider="discord", subject=...)`, updates only `last_authenticated_at`, logs in using `ModelBackend`, records `discord_login`, consumes state, honors safe `next`, and ignores Discord name changes.

- [ ] **Step 2: Write failing new-user tests**

Callback stores `{subject, issued_at}` as pending and redirects to name selection without creating `User`. POST with a valid 3–25-character name atomically creates:

```text
email = <subject>@discord.invalid
name = submitted name
password = unusable
ExternalIdentity(provider=discord, subject=<subject>)
```

Then log in, consume pending identity, and redirect safely. Cover invalid name, expired/replayed pending identity, synthetic-email collision, identity race/concurrent callback, inactive linked user, and no public email field.

- [ ] **Step 3: Run view tests and observe failure**

Expected: missing views/routes/forms.

- [ ] **Step 4: Implement `DiscordDisplayNameForm`**

Reuse `User.name` model validators via a `ModelForm` exposing only `name`; never accept email, provider, subject, password, discriminator, staff, or active fields.

- [ ] **Step 5: Implement initiation/callback views**

Apply `never_cache`, CSRF protection where applicable, `sensitive_post_parameters`, and fixed-window cache rate limits for IP plus session. Show a generic retry page for provider/validation errors. Do not echo Discord error descriptions.

- [ ] **Step 6: Implement atomic account creation**

Inside `transaction.atomic`, lock/check the identity and synthetic email, create user, explicitly call `set_unusable_password()`, save, create identity, and record action. On a uniqueness race, roll back and retry identity lookup once; never attach an identity to an arbitrary existing email account.

- [ ] **Step 7: Add routes**

Use:

```text
/account/auth                 Discord landing
/account/discord              initiate
/account/discord/callback     callback
/account/discord/create       name selection
/account/logout               logout
```

- [ ] **Step 8: Run view/model tests**

Expected: PASS; test database contains no Discord token or provider profile metadata.

- [ ] **Step 9: Commit**

```powershell
git add racetime\views\discord_auth.py racetime\views\__init__.py racetime\urls.py racetime\forms.py racetime\templates\racetime\user racetime\tests\identity
git commit -m "feat: authenticate public users with Discord"
```

## Task 5: Remove public password/email/Patreon/category-request paths

**Files:**
- Create: `racetime/tests/site/test_public_surface.py`
- Modify: `racetime/urls.py`
- Modify: `racetime/forms.py`
- Modify: `racetime/views/user.py`
- Modify: `racetime/templates/racetime/user/login_register.html`
- Modify: `racetime/templates/racetime/user/edit_account.html`
- Modify: `racetime/templates/racetime/user/edit_account_connections.html`
- Modify: `racetime/templates/racetime/user/tabs.html`
- Modify: `racetime/templates/racetime/base.html`

- [ ] **Step 1: Write failing route-policy tests**

With production flags, assert public create/login/password reset/password change/Patreon/category-request endpoints return 404 (not a form or provider redirect), no navigation link exposes them, and POST cannot mutate email/password/Patreon. Assert logout, Discord, profile name edit, account deletion, Twitch link/unlink, racing, and OAuth authorization remain.

- [ ] **Step 2: Run and observe failures**

```powershell
.\venv\Scripts\python.exe manage.py test racetime.tests.site.test_public_surface --settings=project.settings.test -v 2
```

- [ ] **Step 3: Gate URL patterns by explicit settings**

Build the account/category URL lists conditionally at import using flags. Disabled named routes must resolve only to a 404 view if an old bookmark needs graceful handling; they must not expose forms. Keep `/admin/` outside public `racetime.urls`; Caddy restricts it in the platform plan.

- [ ] **Step 4: Remove email from the public edit form**

`UserEditForm.Meta.fields` starts with `name`, not `email`; update logging conditions accordingly. Synthetic email remains operator-visible in admin only.

- [ ] **Step 5: Update account templates and branding**

Show one `Continue with Discord` action, explain Twitch is a separate racing connection, remove Patreon/security tabs for unusable-password accounts, and replace every user-facing `racetime.gg account` phrase with `Z1RR RaceTime account`.

- [ ] **Step 6: Run public-surface and existing profile/Twitch tests**

Expected: PASS with no regression to active-race name-change denial or streaming-required validation.

- [ ] **Step 7: Commit**

```powershell
git add racetime\urls.py racetime\forms.py racetime\views\user.py racetime\templates racetime\tests\site
git commit -m "feat: enforce Discord-only public accounts"
```

## Task 5A: Enforce distributed abuse limits on public endpoints

**Files:**
- Create: `racetime/throttling.py`
- Create: `racetime/tests/site/test_throttling.py`
- Modify: `project/settings/base.py`, `project/settings/test.py`, `project/settings/ci.py`, `project/settings/production.py`
- Modify: `racetime/urls.py` and the exact race-create/search/profile/OAuth views identified by the route inventory

- [ ] **Step 1: Inventory and classify every public mutation and lookup route**

Add a table-driven test that enumerates named URL patterns and fails when an authentication, account mutation, race creation, OAuth approval, search, or autocomplete route has no explicit throttle policy or a documented upstream WebSocket/racebot control. Do not rely on an informal list that can drift.

- [ ] **Step 2: Write failing policy and concurrency tests**

Set initial production policy to: Discord initiate/callback/name submission 10 per 10 minutes per IP and session; race creation 5 per 10 minutes per user plus 20 per hour per IP; search/autocomplete 60 per minute per user plus 120 per minute per IP; profile/Twitch mutations 10 per hour per user plus 30 per hour per IP; OAuth authorization decisions 30 per 10 minutes per user and IP. Tests cover the last allowed request, 429 plus bounded `Retry-After`, window reset, concurrent workers, user/IP isolation, IPv4/IPv6 normalization, missing session/user, and no raw identity in cache keys or logs. A Redis-loss matrix proves authentication, OAuth decisions, race creation, and account/admin mutations return a generic 503, while authoritative ready/start/done/DNF/DQ/split transitions continue against MariaDB under bounded per-process emergency controls with audit and alerting.

- [ ] **Step 3: Implement one Redis-backed throttle service**

Use atomic Redis counters with expiry and keys HMACed by the dedicated `RACETIME_THROTTLE_HMAC_KEY`; never reuse `DJANGO_SECRET_KEY`. Resolve client IP through one tested helper: accept exactly one normalized `HTTP_X_FORWARDED_FOR` address only when the immediate `REMOTE_ADDR` equals the configured Caddy `172.30.0.2/32`; otherwise ignore the header and use normalized `REMOTE_ADDR`. Caddy deletes inbound forwarding headers and sets the single client address. Production rejects locmem, a missing/invalid dedicated key, any trusted-proxy value other than the rendered fixed Caddy `/32`, and untrusted/multi-value forwarded input. Tests send two clients through that trusted proxy and prove distinct buckets, then prove direct spoofing and a different address in the same proxy subnet are ignored. Limiter loss fails closed only for authentication, OAuth decisions, race creation, account/admin mutations, and non-authoritative protected lookups; it never makes Redis authoritative for in-race state.

- [ ] **Step 4: Apply policies at the views, not only at Caddy**

Replace Task 4's initial Discord fixed-window helper with this shared throttle service—do not stack two counters—then apply named policies before expensive/provider/database work. Classify the upstream in-race action routes explicitly: when Redis is unavailable they use a bounded per-process emergency counter, emit an audit/alert signal, and continue their authoritative MariaDB transaction. Return generic JSON/HTML appropriate to other routes, never echo the throttle key. Keep Caddy request/body/connection limits as an independent outer layer in the platform plan.

- [ ] **Step 5: Run unit and MariaDB/Redis integration tests**

Run `racetime.tests.site.test_throttling` once with `project.settings.test` using a deterministic fake atomic cache and once in the service-backed CI job with `project.settings.ci` and real Redis. Expected: both PASS, including cross-process concurrency and injected Redis loss.

- [ ] **Step 6: Commit**

Commit `racetime/throttling.py`, settings, protected views/routes, and the route-inventory/integration tests together with message `feat: throttle public racetime endpoints`.

## Task 6: Add audited Discord identity recovery

**Files:**
- Create: `racetime/management/commands/transfer_external_identity.py`
- Create: `racetime/tests/identity/test_transfer_command.py`

- [ ] **Step 1: Write failing command tests**

Test that the command requires provider, current subject, new subject, target user hash/email, actor superuser, evidence reference, and defaults to dry-run. Test `--apply --confirm <target-user-hashid>`, collision rejection, non-staff actor rejection, current-subject mismatch, inactive target warning, no active-race mutation, and `UserAction` audit entries on target and actor.

- [ ] **Step 2: Run and observe failure**

Expected: unknown management command.

- [ ] **Step 3: Implement dry-run and confirmation**

Never accept a password/token. Normalize subjects using the same service as login. In apply mode, lock target identity and any row matching new subject, reject collision, update subject, and create actions containing provider, redacted subject suffixes, actor hashid, and evidence reference (bounded to 255 characters). Structured log the same audit without full Discord IDs.

- [ ] **Step 4: Run tests**

Expected: PASS and dry-run leaves all rows/audits unchanged.

- [ ] **Step 5: Commit**

```powershell
git add racetime\management\commands\transfer_external_identity.py racetime\tests\identity\test_transfer_command.py
git commit -m "feat: add audited Discord identity recovery"
```

## Task 7: Add idempotent Z1RR bootstrap

**Files:**
- Create: `racetime/management/commands/bootstrap_z1rr.py`
- Create: `racetime/tests/site/test_bootstrap_z1rr.py`

- [ ] **Step 1: Write failing bootstrap tests**

First run must set the current Django Site domain/name to the supplied Z1RR identity; create/activate category `z1rr`; set name/short name/limits/defaults; create initial goals; and deactivate every other public category when `--exclusive-public-category` is present. Owner arguments resolve existing Discord identities and add owners. Seed the test with a second active public category and assert it becomes inactive. Without the exclusivity flag, production bootstrap fails before mutation if another public category is active. Second identical run makes no changes. Later runs must not remove Council-created goals/owners or overwrite mutable category text unless `--reconcile-managed-fields` is explicit.

- [ ] **Step 2: Run and observe failure**

Expected: unknown command.

- [ ] **Step 3: Implement the command**

Interface:

```text
manage.py bootstrap_z1rr --site-domain DOMAIN [--site-name NAME]
                         --exclusive-public-category [--owner-discord-id ID ...]
                         [--goal NAME ...] [--reconcile-managed-fields] [--dry-run]
```

Defaults: site name `Z1RR RaceTime`, slug `z1rr`, public/active, owner ceiling 20, moderator ceiling 50, bot ceiling 20, and goal `Beat the game`. Restricted qualification and fresh production both require `racetime.z1rracing.com` plus `--exclusive-public-category`; the isolated local harness alone supplies `integration.racetime.test`. Validate Site/category field names against current models before coding. Never create users, Discord identities, OAuth secrets, or bot credentials.

- [ ] **Step 4: Run tests and a two-run local smoke**

Expected: second output reports no changes and database state is identical; Site identity is exact, `z1rr` is the sole public/active category, and a run without exclusivity fails closed when a conflicting public category exists.

- [ ] **Step 5: Commit**

```powershell
git add racetime\management\commands\bootstrap_z1rr.py racetime\tests\site\test_bootstrap_z1rr.py
git commit -m "feat: bootstrap the Z1RR race category"
```

## Task 8: Enforce correct PKCE behavior

**Files:**
- Create: `racetime/tests/oauth/test_pkce.py`
- Modify: `racetime/views/user.py`
- Modify: `project/settings/base.py`

**Interface — consumes from LiveSplit:** public client ID, redirect exactly `http://127.0.0.1:4888/`, Authorization Code with S256 challenge, and scopes exactly `read chat_message race_action`; no client secret and no `create_race` grant.

**Interface — produces for LiveSplit:** `GET /o/authorize`, `POST /o/token`, `POST /o/revoke_token`, and authenticated `GET /o/userinfo`, with sanitized fixtures proving authorize, refresh, revoke, replay rejection, and error shapes. Route names and payload fixtures are versioned in the server tests; the client plan consumes those fixtures rather than inferred behavior.

- [ ] **Step 1: Write failing OAuth tests**

Create confidential TTPBot and public `LiveSplit.Racetime.Z1RR` applications. Test public Authorization Code S256 success; missing challenge; `plain`; wrong verifier; wrong redirect; replayed code; refresh and revocation without client secret. Assert the legacy application-name bypass cannot match the Z1RR app and is disabled in production.

- [ ] **Step 2: Run and observe failures**

```powershell
.\venv\Scripts\python.exe manage.py test racetime.tests.oauth.test_pkce --settings=project.settings.test -v 2
```

- [ ] **Step 3: Replace the unconditional legacy bypass**

Only strip challenge parameters when `RT_ENABLE_LEGACY_LIVESPLIT_PKCE_BYPASS` is true **and** application name is exactly the legacy stock name. Production/test set it false. Set production `OAUTH2_PROVIDER["PKCE_REQUIRED"] = True`; confirm client-credentials flows remain unaffected.

- [ ] **Step 4: Run OAuth tests**

Expected: all adversarial cases rejected and S256/refresh/revoke pass without a client secret.

- [ ] **Step 5: Commit**

```powershell
git add racetime\views\user.py project\settings\base.py racetime\tests\oauth
git commit -m "fix: require PKCE for public OAuth clients"
```

## Task 9: Add health endpoints

**Files:**
- Create: `racetime/views/health.py`
- Create: `racetime/tests/health/test_health.py`
- Modify: `racetime/views/__init__.py`
- Modify: `racetime/urls.py`

- [ ] **Step 1: Write failing public health tests**

`GET /healthz` returns status 200 and exactly `{"status":"ok"}` without version, hostname, database, Redis, exception, or build data. It does not perform slow external calls.

- [ ] **Step 2: Write failing internal readiness tests**

`GET /internal/readyz` requires an exact bearer token from settings, checks `SELECT 1` and cache set/get/delete, returns generic component booleans, and returns 503 if either fails. Wrong/missing token is 404 to avoid advertising it.

- [ ] **Step 3: Run and observe failure**

Expected: routes absent.

- [ ] **Step 4: Implement bounded checks**

Use Django connection cursor and cache with configured short timeouts. Racebot process health is a container-level check in the platform plan, not fabricated by this endpoint.

- [ ] **Step 5: Run health tests and commit**

```powershell
.\venv\Scripts\python.exe manage.py test racetime.tests.health --settings=project.settings.test -v 2
git add racetime\views\health.py racetime\views\__init__.py racetime\urls.py racetime\tests\health
git commit -m "feat: add minimal racetime health checks"
```

## Task 10: Add Z1RR branding, policies, and attribution

**Files:**
- Create: `racetime/templates/racetime/policy/privacy.html`
- Create: `racetime/templates/racetime/policy/acceptable_use.html`
- Create: `racetime/templates/racetime/policy/account_deletion.html`
- Create: `racetime/templates/racetime/policy/contact.html`
- Create: `docs/policies/privacy.md`
- Create: `docs/policies/acceptable-use.md`
- Create: `docs/policies/account-deletion.md`
- Create: `docs/policies/contact.md`
- Create: `racetime/tests/site/test_branding_and_policies.py`
- Modify: `racetime/templates/racetime/base.html`
- Modify: `racetime/static/racetime/image/favicon.svg`
- Modify: `project/settings/base.py`

- [ ] **Step 1: Write failing content/link tests**

Assert visible `Z1RR RaceTime`, `Operated by Z1Rracing`, `Powered by the open-source Racetime project`, fork source/GPL links, privacy/acceptable use/deletion/contact links, and no statement implying Racetime.gg endorsement/shared administration.

- [ ] **Step 2: Run and observe failures**

- [ ] **Step 3: Add settings-driven site identity and policy views**

Write the Council-reviewable canonical policy text in `docs/policies/*.md`; the public HTML must reproduce the approved substance and tests compare required headings/contact/retention statements. Policy content covers Discord ID, transient OAuth data, optional Twitch, security logs, deletion, encrypted backup retention, contact, moderation, and source attribution. Keep legal claims factual and Council-reviewable.

- [ ] **Step 4: Add original Z1RR branding assets**

Use existing Council-owned assets or create code-native SVG/CSS; preserve upstream GPL notices and add third-party attribution. Do not reuse Racetime.gg trademarks as Z1RR identity.

- [ ] **Step 5: Run tests and commit**

```powershell
git add racetime\templates racetime\static project\settings\base.py racetime\tests\site docs\policies
git commit -m "feat: brand and document Z1RR RaceTime"
```

## Task 11: Verify the core release candidate

**Files:**
- Create: `docs/evidence/<execution-date>-core-identity-rc.md`

- [ ] **Step 1: Run the deterministic SQLite/locmem suite**

```powershell
.\venv\Scripts\python.exe manage.py test --settings=project.settings.test -v 2
```

Expected: substantive non-zero fast-test count and PASS; this result makes no MariaDB/Redis claim.

- [ ] **Step 2: Run the service-backed MariaDB/Redis CI suite**

```powershell
.\venv\Scripts\python.exe manage.py test --settings=project.settings.ci -v 2
```

Run inside the workflow job after its healthy MariaDB/Redis service checks. Expected: substantive non-zero test count, explicit database/cache/channel service probes, and PASS. A skipped or unavailable service fails the RC.

- [ ] **Step 3: Verify migrations/settings/static assets**

```powershell
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\venv\Scripts\python.exe manage.py check
npm ci
npm audit --omit=dev
```

Expected: no model drift, clean check, no high/critical production finding.

- [ ] **Step 4: Run targeted security regressions**

Run identity, public-surface, throttling, PKCE, health, and bootstrap suites separately and record exact output. Search logs/test fixtures for token/secret/cookie/synthetic-email canaries.

- [ ] **Step 5: Request code review**

Use @superpowers:requesting-code-review with APP-001–012 and FR-ID/FR-CORE requirements.

- [ ] **Step 6: Record evidence and commit**

```powershell
git add docs\evidence
git commit -m "docs: qualify racetime core identity release candidate"
```

Do not mark the public site launched. This plan ends at a locally deployable core RC; production settings/containers and external activation are handled by the platform/operations plans.
