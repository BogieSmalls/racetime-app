# Z1RR RaceTime Core and Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coordinate the separately testable Z1RR RaceTime core-identity and production-platform workstreams into one deployable local release candidate.

**Architecture:** Application behavior and infrastructure/recovery are intentionally specified in two focused plans. Execute the core identity plan first to lock its settings, health, migration, and bootstrap contracts; then execute the platform plan against those contracts and qualify them together in the isolated integration stack.

**Tech Stack:** Django/Channels/Daphne, MariaDB, Redis, Docker Compose/Caddy, OCI/Terraform, GitHub Actions

---

## Control documents

**Spec:** [Plan-B RaceTime architecture](../specs/2026-08-12-plan-b-racetime-architecture-design.md)
**Requirements and gates:** [Requirements and decision record](../../racetime-z1rr/requirements-and-decisions.md)
**Artifact register:** [Launch artifact register](../../racetime-z1rr/artifact-register.md)
**Master plan:** [Contingency launch master plan](2026-08-22-z1rr-racetime-launch-master.md)
**Requirements owned:** all APP-001–012 and PLT-001–008 G0 requirements coordinated by the two detailed plans.

## Global Constraints

- G0 permits only local, non-public readiness work. OCI apply, DNS, production OAuth/apps, scheduler changes, publication, and cutover require their recorded G1–G3 gates.
- Preserve both outcome lanes: `racetime.gg/z1rr` and self-hosted `racetime.z1rracing.com/z1rr`. Do not alter ordinary `racetime.gg/z1r` pickup racing.
- RaceTime application work targets Django 5.2/Python 3.12 and immutable ARM64 production images; provider work must preserve its plan's declared runtime.
- Production origins are one validated HTTPS origin with no path/query/userinfo; every REST/WSS/link derives from it and historical references remain provider-qualified.
- Discord is the sole public self-hosted login. Never persist Discord access/refresh tokens or grant category owners Django staff, host, database, secret, backup, or OCI access.
- Preserve GPL-3.0/upstream attribution and corresponding source for every deployed RaceTime build; LiveSplit work stays clean-room and copies no unlicensed legacy-provider code.

## Task 1: Execute and accept the core identity release candidate
## Integration interfaces

**Core → platform consumes:** `project.settings.production` and its complete env schema; additive migrations through `0082_externalidentity`; `/healthz` plus authenticated internal readiness; `deployment_preflight`; and idempotent `bootstrap_z1rr` with the exact flags recorded in the master plan.

**Platform → integration produces:** immutable ARM64 web/racebot image digests, rendered Compose/Caddy configuration, migration/bootstrap output, and safe health/backup/deploy probes. The platform may not invent a second settings schema, health route, bootstrap signature, or authoritative active-race source.

---


**Files:**
- Plan: `docs/superpowers/plans/2026-08-22-z1rr-racetime-core-identity.md`
- Evidence: `docs/evidence/<execution-date>-core-identity-rc.md`

- [ ] **Step 1: Execute every task in the core identity plan using its TDD steps**

- [ ] **Step 2: Run the core plan's final verification block**

- [ ] **Step 3: Resolve its independent code/provenance/security review findings**

- [ ] **Step 4: Mark APP-001–APP-012 accepted only with linked evidence**

Expected: no public OAuth app or externally visible service was created.

## Task 2: Execute and accept the platform/recovery release candidate

**Files:**
- Plan: `docs/superpowers/plans/2026-08-22-z1rr-racetime-platform-recovery.md`
- Evidence: `docs/evidence/<execution-date>-platform-rc.md`

- [ ] **Step 1: Execute every task in the platform/recovery plan using the accepted core contracts**

- [ ] **Step 2: Run the platform plan's final verification block**

- [ ] **Step 3: Resolve its independent deployment/recovery/IaC/security review findings**

- [ ] **Step 4: Mark PLT-001–PLT-008 accepted only with linked evidence**

Expected: no Terraform apply, OCI mutation, public DNS, production secret/app creation, or public service start occurred.

## Task 3: Qualify the combined local release candidate

**Files:**
- Create: `docs/evidence/<execution-date>-core-platform-integration-rc.md`
- Integration files: the master plan's Task 5

- [ ] **Step 1: Build the immutable ARM64 application images from the accepted core commit**

- [ ] **Step 2: Start only the isolated integration Compose project with fixture credentials**

- [ ] **Step 3: Run migrations, idempotent bootstrap, and static collection**

- [ ] **Step 4: Run HTTP/WSS and Discord-fixture account-creation tests**

- [ ] **Step 5: Run the complete browser race lifecycle and authoritative result/leaderboard checks**

- [ ] **Step 6: Run backup/restore and deploy/rollback failure-path tests**

- [ ] **Step 7: Run health and logging-redaction canary tests**

- [ ] **Step 8: Confirm `manage.py check --deploy`, Compose/Caddy/Terraform validation, dependency/container/secret scans, and substantive test count pass**

- [ ] **Step 9: Request a combined review against APP-001–012 and PLT-001–008**

- [ ] **Step 10: Record exact commit/image/config/migration hashes and stop at G0**

This coordinating plan does not duplicate or replace either detailed plan. A step is complete only when its referenced detailed plan and evidence are complete.
