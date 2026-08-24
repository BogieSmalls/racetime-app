# Z1RR RaceTime Production Platform and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the Z1RR RaceTime core as an immutable multi-platform production stack with fail-closed settings, dedicated versioned OCI infrastructure, race-aware deployment, encrypted off-machine backups, monitoring, and rehearsable rollback/rebuild.

**Architecture:** Caddy is the only public container and proxies HTTP/WSS to non-root Daphne; web/racebot share same-commit ARM64/amd64 images while MariaDB and Redis remain internal. Terraform defines the dedicated `racetime` A1 instance and supporting resources without applying before G1, and tested scripts gate every deploy on active-race status plus a verified backup. Separate qualification and production Caddy/data state make the late-G2 fresh-production transition explicit.

**Tech Stack:** Docker/BuildKit/Compose, Caddy 2, Django/Daphne, MariaDB, Redis, Bash, Python `unittest`, Terraform OCI provider, OCI CLI Instance Principal, age/zstd, GitHub Actions/Trivy/Syft

---

## Control documents

**Spec:** [Plan-B RaceTime architecture](../specs/2026-08-12-plan-b-racetime-architecture-design.md)
**Requirements and gates:** [Requirements and decision record](../../racetime-z1rr/requirements-and-decisions.md)
**Artifact register:** [Launch artifact register](../../racetime-z1rr/artifact-register.md)
**Master plan:** [Contingency launch master plan](2026-08-22-z1rr-racetime-launch-master.md)
**Requirements owned:** FR-CORE-001/006, FR-OPS-001–007, NFR-SEC-001–003, NFR-REL-001, NFR-PERF-001, NFR-OSS-001, NFR-TEST-001, and NFR-COST-001.

## Global Constraints

- G0 permits only local, non-public readiness work. OCI apply, DNS, production OAuth/apps, scheduler changes, publication, and cutover require their recorded G1–G3 gates.
- Preserve both outcome lanes: `racetime.gg/z1rr` and self-hosted `racetime.z1rracing.com/z1rr`. Do not alter ordinary `racetime.gg/z1r` pickup racing.
- RaceTime application work targets Django 5.2/Python 3.12 and produces same-commit immutable linux/arm64 and linux/amd64 images; A1 production runs ARM64 and the paid disaster-recovery fallback runs amd64. Provider work must preserve its plan's declared runtime.
- Production origins are one validated HTTPS origin with no path/query/userinfo; every REST/WSS/link derives from it and historical references remain provider-qualified.
- Discord is the sole public self-hosted login. Never persist Discord access/refresh tokens or grant category owners Django staff, host, database, secret, backup, or OCI access.
- Preserve GPL-3.0/upstream attribution and corresponding source for every deployed RaceTime build; LiveSplit work stays clean-room and copies no unlicensed legacy-provider code.

## File map

- Create `project/settings/env.py`: strict environment parsing with secret-safe errors.
- Create `project/settings/production.py`: production security/database/cache/log/site/external-service settings.
- Create `project/logging.py`: JSON formatter and redaction filter.
- Create `.env.production.example`: complete placeholder-free environment schema using documented sentinel values.
- Create `deploy/env/ci.env`: non-secret CI fixture environment.
- Create `deploy/validate-config.py`: validate rendered runtime contract without printing values.
- Replace `Dockerfile`: Node/Python multi-stage linux/arm64 and linux/amd64 image with web/racebot targets.
- Create `.docker/start-production`, `.docker/healthcheck`: explicit process entrypoints.
- Create `deploy/compose.production.yml`: internal stack, volumes, healthchecks, resource limits.
- Create `deploy/Caddyfile`: canonical HTTPS/WSS/static/media, restricted/public phases, pinned ACME issuer, plus loopback-only admin listener.
- Create `racetime/management/commands/deployment_preflight.py`: authoritative active-race/migration/bootstrap checks.
- Create `deploy/scripts/deploy.sh`, `preflight.sh`, `rollback.sh`: release orchestration and audit.
- Create `deploy/backup/backup.sh`, `verify.sh`, `restore-test.sh`, `retention.py`: encrypted DB/media/production-Caddy-state OCI backup lifecycle.
- Create `deploy/systemd/*.service`, `*.timer`: backup/verification/restore-test schedules.
- Create `infra/oci/*.tf`, `*.tfvars.example`, `README.md`: dedicated-instance OCI definitions and reviewed-plan guardrails.
- Create `deploy/monitoring/`: health/backup/allowance/storage alert definitions and secret-safe Discord adapter contract.
- Create `.github/workflows/container.yml`, `release.yml`: test/build/scan/SBOM/provenance/publish gates.
- Create `tests/platform/`: settings/config/Compose/Caddy/deploy/backup/IaC contract tests.

## Task 1: Implement strict production configuration

**Files:**
- Create: `project/settings/env.py`
- Create: `project/settings/production.py`
- Create: `project/logging.py`
- Create: `.env.production.example`
- Create: `deploy/env/ci.env`
- Create: `tests/platform/test_production_settings.py`
- Create: `tests/platform/test_config_contract.py`

- [ ] **Step 1: Write failing environment parser tests**

Test required string, boolean, integer range, comma-list, URL origin, and secret minimum length. Missing/blank, `changeme`, `example`, wildcard host/origin, HTTP production origin, credentials in URL, invalid boolean, and unknown security-critical setting must raise `ImproperlyConfigured` naming only the variable.

- [ ] **Step 2: Run and verify failure**

```powershell
.\venv\Scripts\python.exe -m unittest tests.platform.test_config_contract -v
```

Expected: import/file failure.

- [ ] **Step 3: Implement `project/settings/env.py`**

Expose only:

```python
required(name: str) -> str
secret(name: str, minimum: int = 32) -> str
boolean(name: str, default: bool | None = None) -> bool
integer(name: str, minimum: int, maximum: int, default: int | None = None) -> int
csv(name: str, required: bool = False) -> list[str]
https_origin(name: str) -> str
```

Never include a value in an exception or repr.

- [ ] **Step 4: Write failing production settings assertions**

Assert `DEBUG=False`, no debug toolbar app/middleware, exact hosts/trusted origins, secure/HttpOnly/SameSite cookies, HTTPS redirect, phase-derived HSTS (`300` while restricted, at least `31536000` only when public, preload always false), proxy SSL header, restricted CORS, nosniff/referrer/frame policies, database/Redis credentials, dedicated throttle HMAC key, exact trusted-proxy CIDRs, static/media roots, body/upload limits, Discord flags, PKCE required, JSON logs, and no development secret/default credential.

- [ ] **Step 5: Implement `production.py`**

Import `base` then override. Use environment variables:

```text
DJANGO_SECRET_KEY, RT_SITE_URI, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS
DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
REDIS_URL, INTERNAL_HEALTH_TOKEN, RACETIME_THROTTLE_HMAC_KEY
RACETIME_TRUSTED_PROXY_CIDRS
DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI
TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET
STATIC_ROOT, MEDIA_ROOT, LOG_LEVEL
RACETIME_ACCESS_PHASE
```

Set public password/category requests/Patreon and legacy LiveSplit PKCE bypass false. `RACETIME_ACCESS_PHASE` accepts only `restricted` or `public`; settings derive HSTS from it and never enable preload. `RACETIME_THROTTLE_HMAC_KEY` is an independently generated base64 value decoding to at least 32 bytes and must differ from `DJANGO_SECRET_KEY`. Set `REAL_IP_HEADER="HTTP_X_FORWARDED_FOR"` and require `RACETIME_TRUSTED_PROXY_CIDRS=172.30.0.2/32`, the single fixed Caddy address on the Compose `proxy` network; Daphne is internal and the client-IP helper honors the header only for that immediate peer after Caddy overwrites it.

- [ ] **Step 6: Implement JSON logging/redaction**

Emit timestamp, level, logger, message, request/correlation ID, and safe exception class. Redact keys/strings matching authorization, token, code, secret, cookie, password, webhook, synthetic Discord email, and query parameters on OAuth routes. Tests inject canaries in nested dictionaries and exception messages.

- [ ] **Step 7: Write environment examples and validator**

`.env.production.example` contains every name with empty or clearly invalid sentinel; never a usable secret. `ci.env` contains distinct valid non-production fixture keys, exact test proxy `/32`, loopback/test domains, and `RACETIME_ACCESS_PHASE=restricted`. `deploy/validate-config.py` imports production settings, verifies the throttle key decodes to at least 32 bytes and differs from `DJANGO_SECRET_KEY`, requires the trusted-proxy value to equal the rendered Caddy fixed address as a `/32`—not the whole subnet—and rejects an unknown access phase while checking all other invariants/unknown variables. It prints only variable names plus PASS/FAIL.

- [ ] **Step 8: Run production deploy checks**

```powershell
$env:DJANGO_SETTINGS_MODULE='project.settings.production'
Get-Content deploy\env\ci.env | ForEach-Object { if ($_ -match '^([^#=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] } }
.\venv\Scripts\python.exe deploy\validate-config.py
.\venv\Scripts\python.exe manage.py check --deploy
```

Expected: both PASS; missing `DJANGO_SECRET_KEY` fixture test fails without printing it.

- [ ] **Step 9: Commit**

```powershell
git add project\settings project\logging.py .env.production.example deploy\env tests\platform
git commit -m "feat: add fail-closed production configuration"
```

## Task 2: Build immutable web and racebot images

**Files:**
- Modify: `Dockerfile`
- Create: `.docker/start-production`
- Create: `.docker/healthcheck`
- Create: `.dockerignore`
- Create: `tests/platform/test_image_contract.py`
- Create: `tests/platform/smoke_images.ps1`

- [ ] **Step 1: Write failing Dockerfile contract tests**

Assert production targets copy source rather than bind mount it, use `npm ci`, install pinned Python dependencies, run as non-root UID, use Daphne/racebot `--noreload`, expose only web 8000, include OCI CLI/age/zstd only in maintenance target, and contain no `runserver`, development secret, or production credential. Build metadata and dependency locks must be architecture-neutral so one commit produces both required platforms.

- [ ] **Step 2: Run and observe failure**

Expected: existing Dockerfile violates production contract.

- [ ] **Step 3: Implement multi-stage build**

Stages:

```text
assets: node LTS, npm ci, production static dependency tree
python-build: python:3.12-slim, compiler/MariaDB headers, wheelhouse/venv
runtime-base: slim runtime libraries, UID/GID 10001, source + venv + asset tree
web: start-production web
racebot: start-production racebot
maintenance: runtime-base + pinned OCI CLI, age, zstd, mariadb-client
```

Pin base images by digest at release time. Use `COPY --chown`; no shell package cache remains.

- [ ] **Step 4: Implement explicit entrypoints**

`web` runs `daphne -b 0.0.0.0 -p 8000 project.asgi:application`. `racebot` runs `python manage.py racebot --noreload`. Neither migrates automatically. A `collectstatic` mode writes the static volume as a one-shot deploy task.

- [ ] **Step 5: Build and smoke both platforms with BuildKit/QEMU**

```powershell
docker buildx build --platform linux/arm64 --target web -t z1rr-racetime:web-test --load .
docker buildx build --platform linux/arm64 --target racebot -t z1rr-racetime:racebot-test --load .
docker buildx build --platform linux/amd64 --target web -t z1rr-racetime:web-amd64-test --load .
docker buildx build --platform linux/amd64 --target racebot -t z1rr-racetime:racebot-amd64-test --load .
.\tests\platform\smoke_images.ps1
```

Expected: all four target/platform images start under the requested platform, report the same embedded commit, and pass health/process checks; `docker image history --no-trunc` secret scans are clean.

- [ ] **Step 6: Run non-root/process tests**

Expected: `id -u` is 10001; web command contains Daphne; racebot contains `--noreload`; read-only root filesystem starts with declared tmpfs/volumes.

- [ ] **Step 7: Commit**

```powershell
git add Dockerfile .docker .dockerignore tests\platform\test_image_contract.py tests\platform\smoke_images.ps1
git commit -m "build: add immutable multi-platform racetime images"
```

## Task 3: Define the production Compose topology

**Files:**
- Create: `deploy/compose.production.yml`
- Create: `tests/platform/test_compose_contract.py`

- [ ] **Step 1: Write failing rendered-Compose tests**

Render once with `CADDY_STATE_VOLUME=caddy-qualification` and once with `caddy-production`. Assert services `caddy`, `web`, `racebot`, `db`, `redis`; one-shot `migrate`, `collectstatic`; optional profile `maintenance`; a dedicated `proxy` bridge with IPAM `172.30.0.0/29`, fixed Caddy `172.30.0.2`, fixed web `172.30.0.3`, and no other members; a separate internal `data` network; no DB/Redis/web host ports; Caddy publishes public 80/443 plus exactly `127.0.0.1:8081:8081` for tunneled administration; no wildcard/non-loopback admin binding; healthchecks; restart policies; resource limits; read-only root filesystems where supported; separately named qualification/production DB, Redis, media, secrets, and Caddy-state volumes; exactly the selected Caddy state volume is mounted; log rotation; immutable image variables; and no `latest`/build/bind mount. Assert `RACETIME_TRUSTED_PROXY_CIDRS` is exactly `172.30.0.2/32`.

- [ ] **Step 2: Run and observe failure**

Expected: file absent.

- [ ] **Step 3: Implement the stack**

Use `RACETIME_IMAGE@RACETIME_IMAGE_DIGEST` or immutable SHA tag validated by deploy script. Pin Caddy/MariaDB/Redis by reviewed digest. Define a project-scoped `proxy` bridge with IPAM `172.30.0.0/29`; attach only Caddy at `172.30.0.2` and web at `172.30.0.3`. Attach web/racebot/DB/Redis as needed to a separate internal `data` network, with Caddy absent from it. Web receives media/static volumes; Caddy receives them read-only; database and Redis have separate data volumes. Qualification and fresh-production state use distinct explicitly selected DB/Redis/media/secret/Caddy names; no Compose command copies or promotes qualification state. Publish container port 8081 only as host `127.0.0.1:8081`; OCI NSG/security lists expose no 8081 rule. Deployment preflight rejects overlap between `172.30.0.0/29` and host routes/existing Docker networks; any subnet/address change requires one reviewed change to Compose, trusted-proxy env, tests, and evidence—never widening trust to the subnet.

- [ ] **Step 4: Add service healthchecks**

Web calls `/healthz`; DB uses `healthcheck.sh --connect --innodb_initialized`; Redis uses authenticated `PING`; racebot health invokes a dedicated command that checks process liveness and a bounded adoption probe rather than an invented HTTP endpoint.

- [ ] **Step 5: Render and test**

```powershell
docker compose --env-file deploy\env\ci.env -f deploy\compose.production.yml config
.\venv\Scripts\python.exe -m unittest tests.platform.test_compose_contract -v
```

Expected: PASS with no unresolved variable.

- [ ] **Step 6: Commit**

```powershell
git add deploy\compose.production.yml tests\platform\test_compose_contract.py
git commit -m "build: define racetime production stack"
```

## Task 4: Configure Caddy and restricted administration

**Files:**
- Create: `deploy/Caddyfile`
- Create: `deploy/caddy/qualification.env.example`
- Create: `deploy/caddy/production.env.example`
- Create: `tests/platform/test_caddy_contract.py`

- [ ] **Step 1: Write failing Caddy contract tests**

Adapt both configurations to JSON and assert exactly one ACME issuer, `ca == test_ca`, staging endpoints only in qualification and production endpoints only in production, TLS-ALPN-01 enabled, HTTP-01 disabled, and no ZeroSSL issuer. Assert canonical HTTPS/WSS routing, overwritten forwarding headers, request body cap, static/media controls, HSTS matching the access phase, and a root-owned source-IP allowlist applied after the ACME handshake but before every application/static/media/OAuth/WebSocket route. Unlisted requests and public `/admin*` or `/internal/*` return generic denial without assets or WebSocket upgrade. Assert container `:8081` is the sole admin/internal proxy and Compose publishes it only to host `127.0.0.1:8081`.

- [ ] **Step 2: Run and observe failure**

- [ ] **Step 3: Implement routes**

TLS/ACME completes before the ordinary HTTP handler. The root-owned allowlist record contains exact expiring CIDRs and is evaluated before admin denial, static, media, OAuth, application, and WebSocket routes; qualification and production issuer environments cannot fall back across endpoints. The separate container `:8081` server accepts admin/internal paths and has no public DNS host; its reachability boundary is the loopback-only Compose publish. Use `header_up -X-Forwarded-For` then `header_up X-Forwarded-For {remote_host}` and corresponding host/proto. Do not trust a client-supplied proxy chain. For media, set attachment/nosniff where appropriate and never execute scripts.

- [ ] **Step 4: Validate Caddy syntax**

```powershell
docker run --rm -v "${PWD}\deploy\Caddyfile:/etc/caddy/Caddyfile:ro" caddy:<pinned-version> caddy validate --config /etc/caddy/Caddyfile
```

Expected: valid configuration.

- [ ] **Step 5: Run HTTP/WSS integration smoke**

Start the fixture stack in both access phases. Assert unlisted clients receive the generic denial for every route class, an allowlisted client receives static/media/application/WSS, public `/admin/` is 404, host `127.0.0.1:8081` reaches login, the admin listener is unreachable through the host's non-loopback address and has no OCI ingress rule, and the adapted issuer/challenge/HSTS assertions pass.

- [ ] **Step 6: Commit**

```powershell
git add deploy\Caddyfile deploy\caddy tests\platform\test_caddy_contract.py
git commit -m "feat: add secure racetime edge routing"
```

## Task 5: Add authoritative deploy preflight

**Files:**
- Create: `racetime/management/commands/deployment_preflight.py`
- Create: `racetime/tests/site/test_deployment_preflight.py`
- Create: `deploy/scripts/preflight.sh`
- Create: `tests/platform/test_preflight_script.py`

- [ ] **Step 1: Write failing Django command tests**

The command exits non-zero when any race is open/invitational/pending/in-progress, migrations are unapplied, expected `z1rr` category is absent/inactive, database is read-only/unhealthy, or Redis set/get fails. `--json` emits counts/booleans but no race names/user data/secrets.

- [ ] **Step 2: Run and observe failure**

- [ ] **Step 3: Implement the command**

Query the exact active `RaceStates` used by `RaceBot.queryset`. Use Django's migration executor, category lookup, DB transaction rollback probe, and cache nonce. Never use the public API as the authority.

- [ ] **Step 4: Write failing shell-wrapper tests**

Mock Compose. Assert preflight checks activation/evidence files, immutable image/digest, config validator, disk headroom, time sync, stack health, authoritative command, and backup prerequisites. Default emergency override is rejected.

- [ ] **Step 5: Implement `preflight.sh`**

Interface:

```text
preflight.sh --environment production --release-sha <40-hex> [--emergency-change-id ID]
```

At G0 use `--environment integration`. Production requires a G1 activation record path and G2 evidence hash in a root-owned config. An emergency ID permits active-race continuation only when passed to deploy too; it logs the ID and still requires backup/config/health.

- [ ] **Step 6: Run tests and commit**

```powershell
git add racetime\management\commands\deployment_preflight.py racetime\tests\site deploy\scripts\preflight.sh tests\platform\test_preflight_script.py
git commit -m "feat: block unsafe racetime deployments"
```

## Task 6: Implement encrypted backup, verification, retention, and restore test

**Files:**
- Create: `deploy/backup/backup.sh`
- Create: `deploy/backup/verify.sh`
- Create: `deploy/backup/restore-test.sh`
- Create: `deploy/backup/retention.py`
- Create: `deploy/backup/manifest.schema.json`
- Create: `tests/platform/test_backup_scripts.py`
- Create: `tests/platform/test_retention.py`
- Create: `deploy/systemd/z1rr-racetime-backup.service`
- Create: `deploy/systemd/z1rr-racetime-backup.timer`
- Create: `deploy/systemd/z1rr-racetime-restore-test.service`
- Create: `deploy/systemd/z1rr-racetime-restore-test.timer`

- [ ] **Step 1: Write failing backup behavior tests**

Use fake `docker`, `age`, `zstd`, and `oci` executables. Assert DB mode uses `mariadb-dump --single-transaction --routines --events --triggers --hex-blob`, verifies the dump in an empty disposable MariaDB, compresses, encrypts, decrypts/verifies, writes a manifest, uploads final+manifest atomically, and removes bounded plaintext scratch in `trap`. Media mode snapshots only the declared volume with safe paths. Caddy-state mode accepts only the production state volume after issuance/renewal/material change, excludes qualification state, and retains the current plus two previous verified generations.

- [ ] **Step 2: Write failing retention tests**

Given object timestamps, retain every DB/media recovery point for 14 days, one weekly for weeks 3–13, one monthly for months 4–12, all pinned predeploy backups inside their explicit retention, the current plus two prior verified production Caddy-state generations, and never delete the newest verified point of any type. Dry-run is default; malformed/unverified manifests are quarantined/alerted, not silently deleted.

- [ ] **Step 3: Run and observe failure**

- [ ] **Step 4: Implement backup/manifest**

Manifest fields: schema, type (`database`, `media`, or `production-caddy-state`), start/end UTC, release SHA, database schema/migration set when applicable, source volume/generation identifier, source bytes/counts, plaintext SHA-256, encrypted SHA-256/bytes, encryption recipient/key ID, verification result/time, Object Storage namespace/bucket/object, and tool versions. It contains no password/key/token.

- [ ] **Step 5: Implement OCI transport**

Use `oci os object put/get/list/delete --auth instance_principal`; bucket/prefix come from root-owned env. Upload to a unique temporary object then copy/rename or mark complete only when data and manifest are both visible and hash/size match. Never infer `NamespaceNotFound` as an empty bucket.

- [ ] **Step 6: Implement restore test**

Download selected point, verify encrypted hash, decrypt/decompress, restore to isolated database/media/Caddy-state volumes under a unique Compose project, start an isolated web stack, and verify migrations, user/category/race/leaderboard row samples, media references, and Caddy configuration/certificate state without contacting production ACME. It refuses production database/volume names and accepts production replacement only through a separate documented command not present in this script.

- [ ] **Step 7: Add schedules**

Database timer runs every six hours; media runs nightly; production Caddy state is captured after initial issuance, renewal, or material configuration change; restore test runs quarterly with randomized delay. Services use hardening, root-owned env, bounded runtime/disk scratch, failure status file, and alert hook.

- [ ] **Step 8: Run all backup/retention tests**

Expected: PASS including upload failure, decrypt failure, DB integrity failure, disk low, object-list ambiguity, retention dry-run/apply, and cleanup.

- [ ] **Step 9: Commit**

```powershell
git add deploy\backup deploy\systemd tests\platform
git commit -m "feat: add encrypted racetime backup and restore automation"
```

## Task 7: Implement race-aware deploy and rollback

**Files:**
- Create: `deploy/scripts/deploy.sh`
- Create: `deploy/scripts/rollback.sh`
- Create: `deploy/release-manifest.schema.json`
- Create: `tests/platform/test_deploy_scripts.py`

- [ ] **Step 1: Write failing deploy state-machine tests**

Assert sequence: lock → preflight → verified predeploy backup → pull digest → verify manifest/signature/SBOM policy → migration plan/check → stop write traffic only when needed → migrate → collectstatic → start web/racebot → HTTP/WSS/DB/Redis/racebot/login smoke → promote record → unlock. Inject failure at every boundary and assert promotion stops.

- [ ] **Step 2: Write failing rollback tests**

Assert code-only rollback pins prior digest; schema release requires manifest-declared rollback class (`code-only`, `forward-fix`, `reversible`) and refuses blind reverse migration. Rollback also checks active race unless the same emergency ID is supplied.

- [ ] **Step 3: Run and observe failure**

- [ ] **Step 4: Implement deploy**

Use an atomic host lock and append-only JSONL audit (actor, release, timestamps, stage, result, emergency ID). Do not log environment output. Release manifest records commit, image digest, migration range/strategy, config schema version, minimum rollback digest, and smoke version.

- [ ] **Step 5: Implement rollback**

Restore prior immutable config/image for code-only. For forward-fix, deploy the approved repair. For reversible, execute only a reviewed named migration target after a fresh backup. Never restore an old database merely to roll back application code.

- [ ] **Step 6: Run tests and local stack deploy/rollback rehearsal**

Expected: successful promotion, injected smoke failure retains/restores prior release, audit has every transition, and no production resource used.

- [ ] **Step 7: Commit**

```powershell
git add deploy\scripts deploy\release-manifest.schema.json tests\platform\test_deploy_scripts.py
git commit -m "feat: orchestrate safe racetime releases"
```

## Task 8: Define the dedicated OCI infrastructure

**Files:**
- Create: `infra/oci/versions.tf`
- Create: `infra/oci/providers.tf`
- Create: `infra/oci/variables.tf`
- Create: `infra/oci/data.tf`
- Create: `infra/oci/network.tf`
- Create: `infra/oci/compute.tf`
- Create: `infra/oci/storage.tf`
- Create: `infra/oci/iam.tf`
- Create: `infra/oci/monitoring.tf`
- Create: `infra/oci/outputs.tf`
- Create: `infra/oci/terraform.tfvars.example`
- Create: `infra/oci/README.md`
- Create: `tests/platform/test_terraform_contract.py`

- [ ] **Step 1: Write failing Terraform contract tests**

Assert pinned OCI provider constraint, non-empty `activation_record` validation, a newly created instance named `racetime` at `VM.Standard.A1.Flex` 1 OCPU/6 GB, a new 50-GB Balanced (10 VPUs/GB) boot volume, and `prevent_destroy` on instance/boot volume/bucket. Existing Restream instances/volumes are data-only inventory and receive no create/update/delete action. Assert public TCP 443 remains open to `0.0.0.0/0` and optional `::/0` for TLS-ALPN-01, only 80/443 are public, no public SSH, Bastion path, private bucket/versioning, instance-principal IAM limited to backup prefix/monitoring, sensitive outputs, and the exact allowance/storage alarms from NFR-COST-001.

- [ ] **Step 2: Run and observe failure**

- [ ] **Step 3: Implement provider/variables/data sources**

Require explicit tenancy/compartment/region/AD/VCN/subnet/image IDs and dated activation record. Existing instance/volume IDs are optional read-only inventory inputs used only to prove the plan leaves them unchanged; never discover mutable resources by display name during apply. Remote state encryption/access is documented; secrets never enter tfvars.

- [ ] **Step 4: Implement dedicated compute and recovery shape contract**

Create only the dedicated `racetime` A1 instance and 50-GB volume after G1. Keep `z1rr-restream-control-staging` and every retained 47-GB volume unchanged. Document `VM.Standard.E5.Flex` 1 OCPU/6 GB as the default paid amd64 recovery target without provisioning it; any production/recovery resize is operator-authorized but must update Terraform, cost forecast, and replacement load/restore evidence.

- [ ] **Step 5: Implement network/storage/IAM/monitoring**

Prefer NSGs over broad security-list changes, but never source-restrict TCP 443 at OCI or the host firewall: the pre-G3 source filter lives only in Caddy after the TLS handshake. Restrict Object Storage policy to the dedicated bucket/prefix using the narrowest OCI-accepted statement; document any tenancy-scope exception. Alerts route through OCI Notifications to the authenticated/redacting adapter on `coop-relay` or email fallback.

- [ ] **Step 6: Validate without applying at G0**

```powershell
terraform -chdir=infra\oci fmt -check -recursive
terraform -chdir=infra\oci init -backend=false
terraform -chdir=infra\oci validate
```

Expected: PASS. `terraform plan` without `activation_record` fails before proposing resources.

- [ ] **Step 7: Write exact import/plan/apply/rollback runbook**

README includes read-only existing-resource inventory, `plan -out`, JSON plan review for create/update/delete/replace, primary-operator review/record, apply, post-apply inventory/cost check, state recovery, and verified OCI/GitHub/registry/DNS account-recovery route. Expected actions are only the dedicated instance/volume/supporting resources; any action against existing Restream resources stops this plan and requires a separate migration decision.

- [ ] **Step 8: Commit**

```powershell
git add infra\oci tests\platform\test_terraform_contract.py
git commit -m "infra: define guarded OCI racetime platform"
```

## Task 9: Add monitoring and secret-safe alerts

**Files:**
- Create: `deploy/monitoring/probe.py`
- Create: `deploy/monitoring/alert.py`
- Create: `deploy/monitoring/config.schema.json`
- Create: `deploy/monitoring/rules.example.json`
- Create: `tests/platform/test_monitoring.py`
- Create: `docs/runbooks/monitoring.md`

- [ ] **Step 1: Write failing probe/alert tests**

Cover HTTPS, WSS handshake, public admin denial, internal readiness, container restart count, disk/inode/database growth, backup freshness/status including production Caddy state, TLS expiry, OAuth error rate, tenancy A1 OCPU-hour usage/slope, Object Storage byte/request entitlements, retained-volume cost, and billing normalized events. Assert dedupe, recovery notices, bounded retries, redaction, webhook host allowlist, and secret canary absence.

- [ ] **Step 2: Run and observe failure**

- [ ] **Step 3: Implement probes and alert normalization**

Probe returns stable status codes/metrics, never response bodies from OAuth/internal errors. Alert adapter accepts an authenticated signed payload, maps severity/component/runbook link, redacts nested input, rate-limits, and sends to configured Discord webhook without logging URL.

- [ ] **Step 4: Document thresholds**

Set actionable service thresholds plus the exact cost model: below a 2,650-hour active A1 forecast, warn when projected month-end exceeds forecast by max(100 hours, 5%) or slope crosses that buffer within 72 hours; at or above 2,650, record expected utilization/overage and suppress that relative warning; always escalate at 2,900 actual/projected hours. Direct A1 alerts to inspect Restream duty-cycling first. Monitor retained boot-volume cost independently from the $3.61 baseline at +$1/+$3 and Object Storage at 75%/90% of verified byte/request entitlements. Include HTTPS/WSS consecutive failures, restart loops, memory/disk/inode headroom, DB growth, backup age >7 hours DB/>26 hours media, Caddy-state generation, TLS <21 days, and auth abuse. Avoid per-user PII.

- [ ] **Step 5: Run fake-sink alert tests and commit**

```powershell
git add deploy\monitoring tests\platform\test_monitoring.py docs\runbooks\monitoring.md
git commit -m "feat: monitor and alert on racetime health"
```

## Task 10: Add immutable container release CI

**Files:**
- Create: `.github/workflows/container.yml`
- Create: `.github/workflows/release.yml`
- Create: `tests/platform/test_workflow_contract.py`

- [ ] **Step 1: Write failing workflow-policy tests**

Assert read-only default permissions, pinned action commit SHAs, PR test/build without push, same-commit linux/arm64 and linux/amd64 manifest entries, per-platform smoke/digest output, unit/integration gate, Trivy high/critical threshold on both variants, Syft SPDX SBOM, provenance attestation, source commit/license link, immutable SHA tag, protected `production` environment, and no `latest` deployment.

- [ ] **Step 2: Run and observe failure**

- [ ] **Step 3: Implement PR container workflow**

Build all targets with cache, run image contract/health tests, scan, and upload reports. Never access production secrets on pull requests.

- [ ] **Step 4: Implement release workflow**

On signed version tag/manual protected dispatch, rebuild both platforms from one commit, publish one digest-addressed multi-platform manifest plus per-platform SBOM/provenance/release identities, and attach corresponding-source metadata. Deployment remains a separate explicit operator action.

- [ ] **Step 5: Run workflow tests and local Actions lint**

Expected: PASS with no mutable third-party action reference.

- [ ] **Step 6: Commit**

```powershell
git add .github\workflows tests\platform\test_workflow_contract.py
git commit -m "ci: build attest and scan racetime images"
```

## Task 11: Verify the platform release candidate and stop at G0

**Files:**
- Create: `docs/evidence/<execution-date>-platform-rc.md`

- [ ] **Step 1: Run the full platform test suite**

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests\platform -v
```

Expected: PASS.

- [ ] **Step 2: Build/smoke both architectures and start the isolated ARM64-compatible stack**

Build and smoke same-commit linux/arm64 and linux/amd64 web/racebot images. Then use local integration hostname/ports, restricted-phase fixture env, and the ARM64-compatible stack to run migrations/bootstrap/static, HTTP/WSS, racebot, DB, Redis, media write/read, and controlled restart smoke.

- [ ] **Step 3: Rehearse backup/decrypt/restore and deploy/rollback locally**

Expected: isolated restore verifies representative data; injected deploy failure returns to prior digest; no public resource is touched.

- [ ] **Step 4: Validate IaC/config/security scans**

Run Compose config, Caddy validate, Terraform fmt/init-backend-false/validate, secret scan, image vulnerability scan, SBOM generation, and `manage.py check --deploy`.

- [ ] **Step 5: Request review**

Use @superpowers:requesting-code-review against PLT-001–008 and NFR-SEC/REL/COST. Resolve blocking findings.

- [ ] **Step 6: Record evidence and commit**

```powershell
git add docs\evidence
git commit -m "docs: qualify racetime platform release candidate"
```

**G0 stop line:** Do not run `terraform apply`, create the dedicated OCI resources, create DNS or external apps/secrets, publish images as production, or start the public service. Those actions begin only in the operations plan after G1.
