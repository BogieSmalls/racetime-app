# Z1RR RaceTime core identity candidate evidence

**Execution date:** 2026-08-23<br>
**Branch:** `feature/racetime-readiness`<br>
**Candidate commit:** `a3ddafd3a9266de84c1fef364b1645262c5f91b5`<br>
**Implementation range:** `2f5f4d4e34bc02036edb506ccc8b90a0e45b8f3c..a3ddafd3a9266de84c1fef364b1645262c5f91b5`<br>
**Status:** Local candidate verified; G0 acceptance remains blocked on the
mandatory service-backed CI job and independent review.

This record is evidence for review, not launch authorization. No OCI resource,
DNS record, public OAuth application, production secret, scheduler, public
service, or release was created or changed.

## Candidate contents

The range contains the deterministic test/CI baseline, additive external
identity migration, Discord OAuth authentication and account creation,
Discord-only public-surface controls, distributed throttling, audited identity
transfer, idempotent `z1rr` bootstrap, S256 PKCE enforcement, liveness and
readiness endpoints, Z1RR branding, source/GPL attribution, and public policy
pages.

The exact feature commits are:

- `d6f2e3a` — deterministic SQLite and MariaDB/Redis CI baseline;
- `22dbc9d` — provider-neutral external identities;
- `087feff` — bounded, validated Discord OAuth client;
- `9f622c3` — Discord authentication and first-account naming;
- `9293632` — Discord-only public account/category surface;
- `d7b361c` — distributed endpoint throttling and emergency race controls;
- `763ed61` — audited external-identity recovery;
- `eedc1bc` — idempotent Z1RR category bootstrap;
- `cfc8883` — public-client S256 PKCE and exact redirect contract;
- `67a3592` — minimal public/internal health endpoints; and
- `a3ddafd` — Z1RR identity, attribution, and policies.

## Local verification

Local runtime: Python 3.11.0, Django 5.2.17, Node 24.11.1, npm 11.6.4.
The release workflow independently targets Python 3.12; local Python 3.11
success does not substitute for that workflow result.

| Check | Result |
| --- | --- |
| `manage.py test --settings=project.settings.test -v 1` | PASS — 140 tests in 50.105s; five explicitly service-only tests skipped |
| `manage.py check --settings=project.settings.base` | PASS — no issues (one intentional silenced upstream check) |
| `manage.py check --settings=project.settings.test` | PASS — no issues (one intentional silenced upstream check) |
| `makemigrations --check --dry-run --settings=project.settings.test` | PASS — no changes detected |
| `collectstatic --noinput --settings=project.settings.test` | PASS — 33 copied, 168 unchanged; generated `static/` remains ignored |
| `npm ci` | PASS — five packages audited, zero vulnerabilities |
| `npm audit --omit=dev` | PASS — zero vulnerabilities |
| `npm ls js-cookie --depth=0` | PASS — exact `js-cookie@3.0.8` |
| `git diff --check` for each committed feature boundary | PASS |

The five fast-suite skips are deliberate and visible: four tests in
`CISettingsContractTests` require MariaDB/Redis and one cross-process atomic
counter test requires real Redis. They are mandatory in the service-backed
job and are not accepted as skipped G0 evidence.

## Targeted security and behavior regressions

| Suite | Result |
| --- | --- |
| `racetime.tests.identity` | PASS — 47 tests |
| `racetime.tests.site.test_public_surface` | PASS — 7 tests |
| `racetime.tests.site.test_throttling` | PASS — 18 tests, one real-Redis-only skip |
| `racetime.tests.oauth.test_pkce` | PASS — 8 tests |
| `racetime.tests.health` | PASS — 10 tests |
| `racetime.tests.site.test_bootstrap_z1rr` | PASS — 8 tests |
| `racetime.tests.site.test_branding_and_policies` | PASS — 5 tests |

The health implementation reserves `/internal/readyz` from the upstream OAuth
bearer middleware so the internal readiness token does not trigger an OAuth
database lookup before the dependency probe. All other OAuth bearer paths
continue through the upstream middleware and the full PKCE/userinfo regression
passes.

A case-insensitive source scan found no production log/print statement that
combines a logging sink with access token, refresh token, client secret,
session cookie, or synthetic `@discord.invalid` data. Identity recovery logs
only provider, redacted subject fingerprints, user hashids, actor hashid, and
the required evidence reference.

## Mandatory evidence still open

### MariaDB/Redis and Python 3.12 CI

The intended local container run was unavailable because this Windows host has
no Docker engine and no WSL installation. A local MySQL service alone cannot
substitute for the declared MariaDB 11.4 plus Redis 7.4 job. No service probe
was faked and no skip was treated as success.

`.github/workflows/test.yml` declares healthy MariaDB and Redis services,
Python 3.12, exact CI-only credentials, the explicit service probe suite, the
complete service-backed suite, dependency audit, static collection, migration
drift, and Django checks. G0 acceptance requires a green run of both named
jobs from the reviewed candidate (or its review-only successor).

### Production profile and deployment check

`project.settings.production`, its fail-closed environment schema, and a clean
`check --deploy` result are owned by the platform/recovery plan. Test/base
settings checks above make no production-security claim. APP-002 and the
production half of NFR-SEC-001 remain open until that plan is implemented and
verified.

### Review and visual E2E

Independent code/provenance/security review of
`2f5f4d4..a3ddafd` is pending. The SVG mark is valid XML with an accessible
title/description and passes the branding tests; worktree ACLs prevented the
local image viewer from rendering it. Browser screenshot and responsive
visual review remain part of the isolated E2E gate.

## Acceptance statement

APP-001, APP-003–010, and APP-012 have substantive local evidence. APP-011 is
partially evidenced but remains open until service-backed CI passes. APP-002
remains open until the production-platform settings task passes. No APP
artifact is marked accepted by this provisional record alone.
