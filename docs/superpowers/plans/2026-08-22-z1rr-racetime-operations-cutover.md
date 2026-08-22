# Z1RR RaceTime Operations, Qualification, and Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert locally verified release candidates into a privately qualified staging system and, only after Council approval, execute a reversible public launch with measured recovery, capacity, security, and integration evidence.

**Architecture:** G0 produces versioned runbooks, evidence/traceability validators, and a hermetic cross-repository release collector; G1–G4 then use those accepted controls to make external decisions auditable. The qualification harness records immutable component IDs and exercises the complete TTPBot → Discord → browser/LiveSplit → Restream → recorded leaderboard path; public DNS and the scheduler move only after every mandatory gate and fresh backup pass.

**Tech Stack:** Bash/Python/PowerShell, Docker Compose, OCI/Terraform/CLI, Caddy, Playwright, k6, OWASP ZAP baseline, GitHub releases, Namecheap-managed DNS, Discord/Twitch OAuth, Markdown/JSON evidence

---

## Control documents

**Spec:** [Plan-B RaceTime architecture](../specs/2026-08-12-plan-b-racetime-architecture-design.md)
**Requirements and gates:** [Requirements and decision record](../../racetime-z1rr/requirements-and-decisions.md)
**Artifact register:** [Launch artifact register](../../racetime-z1rr/artifact-register.md)
**Master plan:** [Contingency launch master plan](2026-08-22-z1rr-racetime-launch-master.md)
**Requirements owned:** FR-OPS-001–007 and all G0–G4 evidence/qualification obligations for rows that name an Operations task.

## Global Constraints

- G0 permits only local, non-public readiness work. OCI apply, DNS, production OAuth/apps, scheduler changes, publication, and cutover require their recorded G1–G3 gates.
- Preserve both outcome lanes: `racetime.gg/z1rr` and self-hosted `racetime.z1rracing.com/z1rr`. Do not alter ordinary `racetime.gg/z1r` pickup racing.
- RaceTime application work targets Django 5.2/Python 3.12 and immutable ARM64 production images; provider work must preserve its plan's declared runtime.
- Production origins are one validated HTTPS origin with no path/query/userinfo; every REST/WSS/link derives from it and historical references remain provider-qualified.
- Discord is the sole public self-hosted login. Never persist Discord access/refresh tokens or grant category owners Django staff, host, database, secret, backup, or OCI access.
- Preserve GPL-3.0/upstream attribution and corresponding source for every deployed RaceTime build; LiveSplit work stays clean-room and copies no unlicensed legacy-provider code.

## File map

- Create `docs/runbooks/deploy.md`, `rollback.md`, `backup-restore.md`, `vm-loss.md`, `identity-recovery.md`, `access-review.md`, `incidents.md`, `status-comms.md`, `staging.md`, `cutover.md`.
- Create `docs/operations/raci.md`, `severity-and-slo.md`, `external-app-register.example.md`.
- Create `docs/evidence/evidence.schema.json`, `go-no-go.template.md`, `cutover-log.template.md`.
- Create `scripts/ops/collect-release-identities.py`, `validate-evidence.py`, `validate-traceability.py`, `qualify-staging.py`, `verify-dns.py`, `scheduler-cutover.py`.
- Create `tests/operations/` for runbook/evidence/state-machine contracts.
- Create `tests/load/race-lifecycle.js`, `tests/load/websocket-chat.js`, `tests/security/zap-rules.tsv`.
- Modify `docs/racetime-z1rr/launch-readiness-checklist.md` only by linking evidence/checking completed items during execution.

## Roles

| Role | Launch responsibility |
| --- | --- |
| Council decision owner | G1/G3/G4 decisions, risk acceptance, public messaging authority |
| Primary infrastructure operator | OCI/DNS/deploy/backup/monitoring execution and cutover commander |
| Backup infrastructure operator | Independent verification, recovery keys/access, can execute rollback/rebuild |
| TTP/Major Tourney lead | TTP schedule, blackout window, TTPBot room/announcement acceptance |
| Tech and Restream lead | Restream provider and end-to-end broadcast acceptance |
| Competitive Integrity lead | Category governance/moderation/race-record integrity acceptance |
| Discord Moderation lead | policy/moderation/contact/account-support readiness |
| League/TC/TT representatives | non-TTP organized-race workflow smoke and user documentation review |

No person approves their own infrastructure change as the sole G3 approver.

## Task 1: Create executable runbooks and evidence contracts (G0)

**Files:**
- Create: all `docs/runbooks/*`, `docs/operations/*`, `docs/evidence/*` listed above
- Create: `tests/operations/test_runbook_contract.py`
- Create: `tests/operations/test_evidence_schema.py`
- Create: `tests/operations/test_traceability.py`
- Create: `scripts/ops/validate-evidence.py`
- Create: `scripts/ops/validate-traceability.py`

- [ ] **Step 1: Write failing runbook contract tests**

Assert each runbook contains purpose, prerequisites, roles, exact inputs/commands, safety preflight, normal steps, verification, rollback/escalation, evidence fields, secret handling, and last-reviewed owner/date. Cross-links must resolve.

- [ ] **Step 2: Write failing evidence-schema and traceability tests**

For evidence manifests, require environment, UTC/local timestamps, operator/reviewer roles, component commit/image/DLL/config hashes, requirements/artifact IDs, command/test IDs, expected/observed result, redacted attachments, findings with severity/owner/date, and pass/fail; prohibit secret-like fields/values. For the Markdown traceability matrix, fixtures cover unknown/duplicate requirement or artifact IDs, invalid/duplicate statuses, missing/broken evidence links, exceptions without Council IDs, same-prefix artifact-range expansion, a registered artifact absent from all requirement and architecture/control coverage, due rows still `Planned`, and one valid matrix per gate.

- [ ] **Step 3: Run and observe failures**

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests\operations -v
```

- [ ] **Step 4: Implement evidence and traceability validators**

`validate-evidence.py` accepts one JSON evidence manifest plus referenced local files, verifies hashes/required results/open findings and prints only safe IDs. A P0/P1 finding or expired evidence fails. P2 requires risk-acceptance ID; P3 requires owner/date. Separately, `validate-traceability.py --gate G0|G1|G2|G3|G4` parses the requirements, artifact register, and Markdown matrix; validates IDs/status/evidence targets; expands only unambiguous same-prefix ranges; rejects unknown references and every registered artifact absent from both requirement rows and architecture/control coverage; and rejects every row due by the selected gate that remains `Planned`. Neither validator rewrites its input.

- [ ] **Step 5: Write runbooks**

Use commands/artifact paths from subsystem plans. Incident runbook covers Discord, Twitch, DB, Redis, racebot, disk, TLS, backup, provider, duplicate scheduler, auth/security, OCI capacity/reclamation, and cost. Status communications include investigating/identified/monitoring/resolved/rollback templates.

- [ ] **Step 6: Write RACI/severity objectives**

Define P0–P3, response/escalation, database/media RPO, target RTO, maintenance windows, and launch-week on-call. Active-race data/auth compromise are P0.

- [ ] **Step 7: Run tests and tabletop dry-run**

Primary narrates deploy; backup narrates rollback/VM loss; identity recovery and incident owners find every required input without session context. Record gaps and fix before commit.

- [ ] **Step 8: Commit**

```powershell
git add docs\runbooks docs\operations docs\evidence scripts\ops tests\operations
git commit -m "docs: define racetime launch operations"
```

## Task 2: Implement cross-repository release/evidence collection (G0)

**Files:**
- Create: `scripts/ops/collect-release-identities.py`
- Create: `scripts/ops/qualify-staging.py`
- Create: `tests/operations/test_release_identity.py`
- Create: `tests/operations/test_qualification_state.py`

- [ ] **Step 1: Write failing release identity tests**

Given repository paths/manifests, collect exact clean commit IDs, image digest, migration leaf, config schema, Restream commit/build hash, TTPBot commit/lock hash, LiveSplit DLL/package/update hash/signature key ID. Dirty trees, branch mismatch, missing artifact, mutable image tag, inconsistent embedded version, or secret-like output fail.

- [ ] **Step 2: Implement collector**

Read public metadata/files and invoke safe `git rev-parse/status`; never read `.env`, credentials, Windows Credential Manager, systemd environment, webhook, or Terraform state. Output schema-versioned JSON.

- [ ] **Step 3: Write failing qualification state-machine tests**

Stages are `release_identity`, `core`, `governance`, `ttpbot`, `restream`, `livesplit`, `failure`, `security`, `load`, `backup_restore`, `cutover_rehearsal`. A stage runs only after dependencies; evidence hash is immutable; rerun creates a new attempt; pass cannot be hand-edited; P0/P1 blocks final result.

- [ ] **Step 4: Implement qualification orchestrator**

It calls subsystem test commands/probes through explicit adapters, captures exit code/duration/safe stdout hashes, writes evidence manifests, then invokes `validate-evidence.py` and `validate-traceability.py --gate G2` before final staging pass. Mutating staging tests require `--environment staging --activation-record <path>`; production is unsupported in this tool.

- [ ] **Step 5: Run hermetic tests and commit**

```powershell
.\venv\Scripts\python.exe -m unittest tests.operations.test_release_identity tests.operations.test_qualification_state -v
git add scripts\ops tests\operations
git commit -m "test: orchestrate racetime staging qualification"
```

## G0 stop line

At G0, execute and accept **Tasks 1–2 only**. They produce GOV-004, OPS-001–004, the release-identity collector, the qualification state machine, and their hermetic tests for Master Tasks 4 and 6. OPS-005 is produced independently by Platform Task 9.

Do not begin Task 3 from delay, anxiety, or completion of G0. Task 3 requires the explicit G1 activation record; later tasks require their stated G2–G4 gates. No G0 step applies Terraform, creates public DNS or production apps/secrets, starts restricted staging, changes schedulers, or publishes a component.

---

## Task 3: Record the G1 activation decision and refresh prerequisites (G1 only)

**Files:**
- Create: `docs/evidence/<decision-date>-plan-b-activation.md`
- Create: `docs/evidence/<date>-oci-preflight.json`
- Update: `docs/racetime-z1rr/launch-readiness-checklist.md`

- [ ] **Step 1: Stop unless the Council decision is explicit**

Record `PLAN_B_ACTIVATED`, reason, date, target window, primary/backup operators, spend authority, rollback authority, and approved public hostname. `pending`, silence, delay, or anxiety is not activation.

- [ ] **Step 2: Refresh OCI read-only inventory**

List instances, shapes, OCPU/RAM/state, boot/block volumes/tags/size/VPUs, VNIC/public/private IP, VCN/subnet/security lists/NSGs, Bastion, buckets, dynamic groups/policies, alarms/budgets, limits/usage, and current month cost. Compare to 2026-08-22 evidence.

- [ ] **Step 3: Back up any retained Restream staging data**

Before import/rebuild, identify and verify data/config that must survive. Use its own backup/runbook; never assume the stopped VM is disposable.

- [ ] **Step 4: Refresh external technical facts**

Verify current OCI Free Tier limits/pricing/capacity behavior, Discord/Twitch redirect/scopes, Django/DOT/LiveSplit release/dependency advisories, DNS ownership, and TLS prerequisites against primary documentation. Update plans/config if a material change occurred.

- [ ] **Step 5: Create a saved Terraform plan**

```bash
terraform -chdir=infra/oci init
terraform -chdir=infra/oci plan -var-file=production.tfvars -out=plan.bin
terraform -chdir=infra/oci show -json plan.bin > plan.json
```

Expected: imported exact resources; no unapproved delete/replace/new boot volume/paid resource. Two operators review `plan.json` and projected cost.

- [ ] **Step 6: Complete G1 pre-apply items**

If any required inventory/resource differs, return to architecture/cost review. Do not check G1 until evidence links and two operator signatures exist.

## Task 4: Apply OCI platform and establish restricted staging (G1 only)

**Files:**
- Create: `docs/evidence/<date>-oci-apply.json`
- Create: `docs/evidence/<date>-staging-deploy.json`

- [ ] **Step 1: Apply only the reviewed saved plan**

```bash
terraform -chdir=infra/oci apply plan.bin
```

Expected: resource actions exactly equal reviewed plan. Any drift/replan stops execution.

- [ ] **Step 2: Verify post-apply OCI inventory and cost controls**

Confirm selected VM/47-GB volume, target 1 OCPU/6 GB, NSG 80/443 only, no public SSH/DB/Redis, Bastion, private versioned backup bucket/policy, notifications, health/allowance alarms, and $1/$3 budget alerts.

- [ ] **Step 3: Bootstrap host without application secrets in logs**

Patch OS/runtime, install pinned Docker/Caddy support/OCI CLI, configure key-only/Bastion access, time sync, firewall, root-owned config dirs, log rotation, automatic security updates/reboot policy, and distinct Compose projects. Run CIS-relevant checks proportionate to Ubuntu host.

- [ ] **Step 4: Create restricted staging hostname/routing**

Use `staging.racetime.z1rracing.com` with Namecheap A record to Terraform's reserved public IP only after activation. Restrict Caddy by operator access control and distinct staging Discord/Twitch apps. Production `racetime.z1rracing.com` may resolve only when required for final TLS testing and must remain operator-only until G3.

- [ ] **Step 5: Deploy exact RaceTime RC to staging**

Run config validation, migrate/bootstrap/static, start stack, and verify health. Use isolated staging DB/Redis/media/secrets; never TTPBot production credentials or production Discord webhook.

- [ ] **Step 6: Verify backup and alert transport before data creation**

Create a canary DB/media backup, decrypt/integrity verify, upload/list/download, run isolated restore, and send test alerts to private test sink/email.

- [ ] **Step 7: Record evidence and complete G1**

Evidence includes reviewed/apply plan hashes, before/after inventory, cost alarms, host/config/image IDs, DNS response, TLS/WSS, backup/alert proof. No Terraform state or secrets attached.

## Task 5: Register external applications and bootstrap governance (G1/G2)

**Files:**
- Create privately: production/staging external-app register from `docs/operations/external-app-register.example.md`
- Create: `docs/evidence/<date>-external-apps.json`
- Create: `docs/evidence/<date>-governance.json`

- [ ] **Step 1: Register staging Discord identity app**

Exact callback `https://staging.racetime.z1rracing.com/account/discord/callback`; scope `identify`; no bot/server-membership requirement. Production app is distinct with exact production callback and is not enabled publicly yet.

- [ ] **Step 2: Register staging/production Twitch apps**

Exact account-link callback is `https://<host>/account/twitch_auth`; minimum existing scopes. Test link/unlink and streaming checks; do not reuse Restream Twitch apps.

- [ ] **Step 3: Register TTPBot confidential client/category bot in staging**

Grant only required `z1rr` category bot/create/action/chat permissions. Store credentials in root-owned staging bot env; production client remains disabled/unused until cutover.

- [ ] **Step 4: Register LiveSplit public client**

Application identity `LiveSplit.Racetime.Z1RR`, client type public, authorization-code grant, redirect exactly `http://127.0.0.1:4888/`, no client secret used, S256 PKCE required, scopes exactly `read chat_message race_action`. Verify the registered client and consent page omit `create_race`; any future room-creation feature requires a new Council-approved requirement and security review.

- [ ] **Step 5: Create break-glass operators through tunnel-only path**

Primary/backup use unique strong local passwords and MFA/host access controls where available. Confirm admin is 404 publicly and reachable through Bastion/SSH loopback listener only.

- [ ] **Step 6: Bootstrap Council governance**

Council members first create Discord accounts; run `bootstrap_z1rr --site-domain staging.racetime.z1rracing.com --site-name "Z1RR RaceTime Staging" --exclusive-public-category --owner-discord-id ID ...` for all approved members. Verify exact Site identity, sole public `z1rr`, ceilings/owners/goals/bots/moderators, idempotent second run, and that owners lack staff/infrastructure access.

- [ ] **Step 7: Record only public identifiers/hashes and access roles**

Never place client secrets, tokens, Discord IDs unnecessary for proof, recovery password, webhook, or Credential Manager data in Git evidence.

## Task 6: Run G2 core and integration qualification

**Files:**
- Create: `docs/evidence/<date>-core-functional.json`
- Create: `docs/evidence/<date>-ttpbot-e2e.json`
- Create: `docs/evidence/<date>-restream-e2e.json`
- Create: `docs/evidence/<date>-livesplit-e2e.json`
- Create: `docs/evidence/<date>-dress-rehearsal.json`

- [ ] **Step 1: Qualify identity/account lifecycle**

Execute first login/name, returning login after Discord rename, denial/missing/mismatch/expiry/replay/concurrent callbacks, logout/session expiry, disabled surfaces, Twitch link/unlink/stream-required, deletion, audited identity transfer, break-glass path, and log canaries.

- [ ] **Step 2: Qualify browser race lifecycle**

Two or more accounts cover create/open/join/ready/auto-start/countdown/chat/DM/moderation/split/done/DNF/DQ/reconnect/record/rank/leaderboard. Verify racebot restart and Redis restart preserve authority.

- [ ] **Step 3: Qualify TTPBot exactly once**

Use a non-production staging schedule/goal/webhook. Inject restart before create, after uncertain create response, after state save, before webhook, and after webhook. Observe exactly one room and one announcement; state URL/provider correct; scheduler lock rejects second instance.

- [ ] **Step 4: Qualify Restream**

Configure Z1RR self-hosted first and pickup Racetime.gg second. Select TTP room; save/reload/stage a draft; sync realtime/crops/tracker/history; verify original URL. Independently fail each provider and confirm the other remains usable.

- [ ] **Step 5: Qualify LiveSplit**

Install stock and RC side by side in a clean LiveSplit 1.8.37 copy. Execute browser authorize, join/ready/start/split/done, forfeit, reconnect, refresh/revoke/logout. Execute wrong verifier/state, replay, occupied port, denial/timeout, token/provider loss, and verify credentials/logs.

- [ ] **Step 6: Execute a complete private dress rehearsal**

One scheduled staging TTP room flows TTPBot → test Discord → browser+LiveSplit entrants → Restream draft/realtime → finish/record/leaderboard. Use exact candidate artifacts and production-equivalent config names, but isolated credentials/data.

- [ ] **Step 7: Validate evidence**

```powershell
.\venv\Scripts\python.exe scripts\ops\validate-evidence.py docs\evidence\<date>-dress-rehearsal.json
```

Expected: PASS and no open P0/P1.

## Task 7: Run G2 failure, security, load, and recovery qualification

**Files:**
- Create: `tests/load/race-lifecycle.js`
- Create: `tests/load/websocket-chat.js`
- Create: `tests/security/zap-rules.tsv`
- Create: `docs/evidence/<date>-failure-security.json`
- Create: `docs/evidence/<date>-load.json`
- Create: `docs/evidence/<date>-restore.json`

- [ ] **Step 1: Define measured load from historical peak**

Calculate largest expected TTP room entrants plus spectators/Restream/LiveSplit; test at least 2x entrants and realistic WebSocket/chat/reconnect bursts. Record exact virtual-user model, not only request rate.

- [ ] **Step 2: Write k6 lifecycle/WebSocket scenarios**

Fixture users authenticate through test bypass available only in staging qualification network, create/join/read/chat/reconnect and read leaderboards. Mutating actions use isolated races. Thresholds: no data errors, p95 HTTP/WSS latency target set from staging baseline, <1% non-injected failures, steady CPU with 20% burst headroom, memory 30% headroom, no swap thrash/restart.

- [ ] **Step 3: Run failure injection**

Discord/Twitch unavailable, Redis restart, MariaDB pause/restart, racebot crash, Caddy/web restart, backup failure, full-ish disk/inode threshold, one provider down, network partition/reconnect, TLS/clock skew, and VM reboot. Verify the failure table behavior and alerts.

- [ ] **Step 4: Run security checks**

`manage.py check --deploy`, dependency/container/IaC/secret scans, ZAP baseline with reviewed false-positive file, public port scan, admin/internal denial, cookies/CSRF/CORS/HSTS/proxy spoofing, OAuth/PKCE abuse/rate limits, upload type/size/non-execution, log redaction, category permission boundaries, and no public DB/Redis/SSH.

- [ ] **Step 5: Run load test and record resource curves**

Start from idle, ramp, steady, reconnect spike, recover. Record VM/container/db/Redis metrics and race correctness. If headroom fails, tune/query/index or revise approved shape/cost before G2; do not waive NFR-PERF silently.

- [ ] **Step 6: Run fresh backup and empty-stack restore**

Use current staging data, verify encrypt/decrypt/integrity/upload, destroy only the explicitly isolated restore stack, restore, and verify accounts/category/completed race/leaderboard/media. Measure data cutoff and start-to-service times against RPO/RTO.

- [ ] **Step 7: Rebuild on an empty compatible host/VM fixture**

Follow `vm-loss.md` using Git/image/config/secrets/backup; if OCI A1 capacity cannot be assumed, prove the temporary paid-shape path in plan/tabletop and record exact approval/cost controls.

- [ ] **Step 8: Validate evidence/no blockers**

Any P0/P1 holds G2. Any P2 needs owner/date/Council risk acceptance. Fix and rerun the affected stage rather than editing a failed result.

## Task 8: Rehearse exact cutover and rollback (G2)

**Files:**
- Create: `scripts/ops/scheduler-cutover.py`
- Create: `scripts/ops/verify-dns.py`
- Create: `tests/operations/test_scheduler_cutover.py`
- Create: `tests/operations/test_dns_verification.py`
- Create: `docs/evidence/<date>-cutover-rehearsal.json`

- [ ] **Step 1: Write failing scheduler cutover state-machine tests**

States: old running → old stop requested → old lock/process absent → old config/state archived → new config validated/probed → new start/lock held → first-room observe. Disallow new start before proven old stop; disallow rollback old start if a new-destination upcoming room exists; every transition requires timestamp/actor/evidence.

- [ ] **Step 2: Implement non-secret scheduler helper**

It orchestrates approved systemctl/preflight commands but never edits/displays secrets. Default is dry-run; `--apply --change-id` required. It stores append-only state outside Git and supports resume only after re-probing actual process/lock/provider room state.

- [ ] **Step 3: Write/implement DNS verifier**

Resolve authoritative and at least three public recursive resolvers, verify A/AAAA set against Terraform output, TTL, HTTPS certificate/SAN, health, WSS, and no stale unexpected address. It is read-only; Namecheap record change remains an explicit two-operator manual step with before/after screenshot/export.

- [ ] **Step 4: Rehearse with staging aliases/fake schedulers**

Measure every step and rollback. Inject failure after DNS, after new scheduler start, and after first-room detection. Rehearsal does not change production DNS or bot.

- [ ] **Step 5: Finalize cutover/rollback runbooks**

Replace estimated durations with measured values; record exact old/new env/state backups, DNS record/TTL, release hashes, responsible actor, verification command, rollback trigger/deadline, and communication messages.

- [ ] **Step 6: Complete G2 checklist/sign-off**

Technical, operations, Competitive Integrity, and Council representatives sign only after every linked artifact validates.

## Task 9: Prepare G3 release and public communication

**Files:**
- Create: `docs/evidence/<launch-date>-go-no-go.md`
- Create: `docs/evidence/<launch-date>-cutover-log.md` from template
- External: public user documentation and signed LiveSplit release draft

- [ ] **Step 1: Freeze exact releases/config**

Record clean commits/image digests/migration/config/Restream/TTPBot/LiveSplit package+DLL+signature/update hashes. No change after dress rehearsal without rerunning affected gates.

- [ ] **Step 2: Draft public user instructions**

Explain Z1RR RaceTime scope, Discord account/name, Twitch link, LiveSplit checksum/install/rollback, browser fallback, organized-vs-pickup boundary, privacy/policies, support/status, and launch time. Do not announce until Go.

- [ ] **Step 3: Draft operational communication**

Race Seekers/Council/organizer messages for go, delay, rollback, first-room issue, and resolved. Name the old/new host clearly.

- [ ] **Step 4: Stage signed LiveSplit release without publishing**

Independently download protected artifact, verify signed checksums/SBOM/clean-room evidence/side-by-side install. Update feed URL remains unpublished/inaccessible to users until Go.

- [ ] **Step 5: Schedule race-free blackout**

Confirm no active room and no TTPBot room-open window; coordinate TC/TT/TTP/League/major/minor tournaments and H2H activity. Freeze category/config changes.

## Task 10: Execute G3 go/no-go and cutover

**Files:**
- Update live: `docs/evidence/<launch-date>-go-no-go.md`
- Append live: `docs/evidence/<launch-date>-cutover-log.md`

- [ ] **Step 1: Re-run immutable release identity and preflight**

Expected: exact G2 artifacts, healthy stack, no active race, current operators, no critical alert/cost anomaly.

- [ ] **Step 2: Take/verify final prelaunch backup**

Require manifest/object/decrypt/integrity proof and off-VM visibility before proceeding.

- [ ] **Step 3: Complete two-person G3 checklist and Council Go**

Unchecked mandatory item means No-go. Record decision and timestamp before any public change.

- [ ] **Step 4: Publish production DNS/site under operator watch**

In Namecheap, set `racetime.z1rracing.com` A record to the Terraform reserved public IP with rehearsed TTL. Verify authoritative/public DNS, certificate, HTTPS, WSS, health, admin denial, monitoring, and external login. If validation fails, restore previous/parking record and communicate delay.

- [ ] **Step 5: Bootstrap/review final Council/category/client state**

Run `bootstrap_z1rr --site-domain racetime.z1rracing.com --site-name "Z1RR RaceTime" --exclusive-public-category --owner-discord-id ID ...`, then review exact Site identity, sole public `z1rr`, owners/mods/goals/bots/OAuth/Twitch/Discord callbacks and ordinary-user create permission. Confirm the second run is unchanged. No secret output.

- [ ] **Step 6: Run final private production smoke without scheduler**

Council accounts create/complete/delete an unlisted test race through browser and Z1RR LiveSplit; Restream reads it; verify record policy. Clean up only the explicit test room through supported application actions.

- [ ] **Step 7: Publish signed LiveSplit release and user instructions**

Verify public download/update/checksum signature from a clean machine. Announce only after production smoke.

- [ ] **Step 8: Move the scheduler using the rehearsed state machine**

Stop/disable old destination; prove process/lock absent; archive old state/env; atomically install new provider/category/credentials; config/probe preflight; start one service; prove one lock/process. Never enable both.

- [ ] **Step 9: Observe first scheduled room**

Exactly one correct room, goal/policy/time, canonical URL, one Discord announcement, TTPBot state, browser/LiveSplit join, Restream provider, completion/record/leaderboard. Record each result before closing launch bridge.

- [ ] **Step 10: Announce completion or execute rollback trigger**

Do not call launch complete merely because DNS/site loads. First-room end-to-end acceptance is required.

## Task 11: Execute rollback when triggered

**Files:**
- Append: cutover log and incident evidence

- [ ] **Step 1: Declare rollback authority/reason and freeze changes**

- [ ] **Step 2: Stop the new scheduler before any old scheduler start**

- [ ] **Step 3: Determine whether a new-destination room exists for upcoming slot**

If yes, do not create duplicate old room; coordinate cancellation/continuation/communication explicitly.

- [ ] **Step 4: Restore prior bot release/env/state as one set and probe**

- [ ] **Step 5: Restore previous DNS/site routing if the site itself is rolling back**

- [ ] **Step 6: Roll application by release-manifest migration strategy**

Never blindly reverse schema or overwrite database with an old backup for a code rollback.

- [ ] **Step 7: Verify old path, backups, monitoring, and community communication**

- [ ] **Step 8: Preserve evidence and open incident review before retry**

## Task 12: Stabilize through G4

**Files:**
- Create: `docs/evidence/<date>-stabilization.md`
- Update: `docs/racetime-z1rr/launch-readiness-checklist.md`

- [ ] **Step 1: Run launch-week daily review**

Review active/completed races, auth/OAuth failures, racebot/TTPBot duplicates/restarts, Restream/LiveSplit issues, latency/resources/db/disk/inodes, backups/restore status, TLS/alerts, OCI allowances/spend, support/moderation incidents.

- [ ] **Step 2: Verify each six-hour DB and nightly media recovery point**

Alert gap remains an incident until a new verified point exists; availability does not make backup failure acceptable.

- [ ] **Step 3: Complete at least one full TTP slate**

Sample every room/announcement/provider/reference/result/ranking and gather organizer/user friction without collecting unnecessary personal data.

- [ ] **Step 4: Remove temporary launch access**

Review superusers, Council owners/mods/bots, GitHub protected environments/secrets, OCI policies/Bastion, Discord/Twitch/OAuth clients/webhooks, backup key custody, and TTPBot old credentials.

- [ ] **Step 5: Record cost/capacity and incidents**

Compare actual spend/allowance/headroom to forecast; assign P2/P3 follow-ups. Any P0/P1 extends launch watch.

- [ ] **Step 6: Obtain G4 approval**

Council/operations approve stabilized normal operations. Only then begin the separate legacy TTP archive project.

## Final qualification commands

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests\operations -v
.\venv\Scripts\python.exe scripts\ops\collect-release-identities.py --config docs\operations\release-paths.json
.\venv\Scripts\python.exe scripts\ops\validate-evidence.py docs\evidence\<date>-dress-rehearsal.json
.\venv\Scripts\python.exe scripts\ops\verify-dns.py --hostname racetime.z1rracing.com --expected-from-terraform infra\oci\public-ip.json
.\venv\Scripts\python.exe scripts\ops\validate-traceability.py --gate G0
```

At G0, run tests, collector, and traceability validation only with local artifacts; DNS/external evidence commands begin at their stated gates. Before G1, G2, G3, and G4 approval, rerun the traceability validator with that exact gate and archive its safe output. Use @superpowers:verification-before-completion at every gate and @superpowers:finishing-a-development-branch only after the associated repository's reviewed release is integrated.
