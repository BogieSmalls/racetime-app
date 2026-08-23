# Z1RR RaceTime Operations, Qualification, and Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert locally verified release candidates into a restricted production candidate on the canonical hostname and, only after Council approval, execute a reversible public launch with measured recovery, capacity, security, and integration evidence.

**Architecture:** G0 produces versioned runbooks, evidence/traceability validators, and a hermetic cross-repository release collector. After G1, the dedicated host uses `racetime.z1rracing.com` behind Caddy default-deny and a staging-ACME certificate; late G2 discards qualification state, creates fresh production state, issues once from production ACME, and only then runs TTPBot/Restream/LiveSplit integration evidence. G3 removes the source restriction and moves the scheduler; DNS is already canonical and does not move at launch.

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
- RaceTime application work targets Django 5.2/Python 3.12 and produces same-commit immutable linux/arm64 and linux/amd64 images; A1 production runs ARM64 and the paid disaster-recovery fallback runs amd64. Provider work must preserve its plan's declared runtime.
- Production origins are one validated HTTPS origin with no path/query/userinfo; every REST/WSS/link derives from it and historical references remain provider-qualified.
- Discord is the sole public self-hosted login. Never persist Discord access/refresh tokens or grant category owners Django staff, host, database, secret, backup, or OCI access.
- Preserve GPL-3.0/upstream attribution and corresponding source for every deployed RaceTime build; LiveSplit work stays clean-room and copies no unlicensed legacy-provider code.

## File map

- Create `docs/runbooks/deploy.md`, `rollback.md`, `backup-restore.md`, `vm-loss.md`, `identity-recovery.md`, `access-review.md`, `incidents.md`, `status-comms.md`, `qualification.md`, `cutover.md`.
- Create `docs/operations/raci.md`, `severity-and-slo.md`, `external-app-register.example.md`.
- Create `docs/evidence/evidence.schema.json`, `go-no-go.template.md`, `cutover-log.template.md`.
- Create `scripts/ops/collect-release-identities.py`, `validate-evidence.py`, `validate-traceability.py`, `qualify-candidate.py`, `finalize-production.py`, `verify-dns.py`, `scheduler-cutover.py`.
- Create `tests/operations/` for runbook/evidence/state-machine contracts.
- Create `tests/load/race-lifecycle.js`, `tests/load/websocket-chat.js`, `tests/security/zap-rules.tsv`.
- Modify `docs/racetime-z1rr/launch-readiness-checklist.md` only by linking evidence/checking completed items during execution.

## Roles

| Role | Launch responsibility |
| --- | --- |
| Council decision owner | G1/G3/G4 decisions, risk acceptance, public messaging authority |
| Primary technical operator | Sole routine OCI/DNS/deploy/backup/monitoring executor and cutover commander; records technical/cost decisions |
| Recovery custodian | Holds the sealed offline package and acknowledges custody/release instructions; no routine access, operation, or technical approval role |
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

Use commands/artifact paths from subsystem plans. The VM-loss runbook includes the sealed-package handoff and a verified route to regain OCI tenancy, GitHub/GHCR, and authoritative DNS access without the primary operator's active session. Incident handling covers Discord, Twitch, DB, Redis, racebot, disk, TLS, backup, provider, duplicate scheduler, auth/security, OCI capacity/reclamation, and cost. Status communications include investigating/identified/monitoring/resolved/rollback templates and the rule to announce non-emergency rollback before reapplying the public restriction, or within five minutes after an emergency restriction.

- [ ] **Step 6: Write RACI/severity objectives**

Define P0–P3, response/escalation, database/media RPO, target RTO, maintenance windows, and launch-week on-call. Active-race data/auth compromise are P0.

- [ ] **Step 7: Run tests and tabletop dry-run**

The primary operator narrates deploy, rollback, and VM loss without relying on session memory. The recovery custodian confirms possession of the current sealed package and can follow only the release/handoff instructions; they are not asked to operate the service. Identity-recovery and incident owners find every required non-secret input. Record gaps and fix before commit.

- [ ] **Step 8: Commit**

```powershell
git add docs\runbooks docs\operations docs\evidence scripts\ops tests\operations
git commit -m "docs: define racetime launch operations"
```

## Task 2: Implement cross-repository release/evidence collection (G0)

**Files:**
- Create: `scripts/ops/collect-release-identities.py`
- Create: `scripts/ops/qualify-candidate.py`
- Create: `scripts/ops/finalize-production.py`
- Create: `tests/operations/test_release_identity.py`
- Create: `tests/operations/test_qualification_state.py`

- [ ] **Step 1: Write failing release identity tests**

Given repository paths/manifests, collect exact clean commit IDs, image digest, migration leaf, config schema, Restream commit/build hash, TTPBot commit/lock hash, LiveSplit DLL/package/update hash/signature key ID. Dirty trees, branch mismatch, missing artifact, mutable image tag, inconsistent embedded version, or secret-like output fail.

- [ ] **Step 2: Implement collector**

Read public metadata/files and invoke safe `git rev-parse/status`; never read `.env`, credentials, Windows Credential Manager, systemd environment, webhook, or Terraform state. Output schema-versioned JSON.

- [ ] **Step 3: Write failing qualification state-machine tests**

Stages are `release_identity`, `qualification_core`, `governance`, `failure`, `security`, `load`, `backup_restore`, `fresh_production`, `post_issuance_ttpbot`, `post_issuance_restream`, `post_issuance_livesplit`, `dress_rehearsal`, and `cutover_rehearsal`. A stage runs only after dependencies; the three programmatic-client stages require `fresh_production` production-certificate evidence; evidence hashes are immutable; reruns create new attempts; P0/P1 blocks final result.

- [ ] **Step 4: Implement qualification orchestrator**

`qualify-candidate.py` calls subsystem test commands/probes through explicit adapters, captures exit code/duration/safe stdout hashes, and writes evidence manifests. Mutating qualification tests require `--environment qualification --activation-record <path>` and the canonical host allowlist; staging-root trust is process-scoped only. `finalize-production.py` owns the separately tested late-G2 transition state machine and refuses G3/public mode. Both invoke the validators and never print secrets.

- [ ] **Step 5: Run hermetic tests and commit**

```powershell
.\venv\Scripts\python.exe -m unittest tests.operations.test_release_identity tests.operations.test_qualification_state -v
git add scripts\ops tests\operations
git commit -m "test: orchestrate racetime restricted qualification"
```

## G0 stop line

At G0, execute and accept **Tasks 1–2 only**. They produce GOV-004, OPS-001–004, the release-identity collector, the qualification state machine, and their hermetic tests for Master Tasks 4 and 6. OPS-005 is produced independently by Platform Task 9.

Do not begin Task 3 from delay, anxiety, or completion of G0. Task 3 requires the explicit G1 activation record; later tasks require their stated G2–G4 gates. No G0 step applies Terraform, creates canonical DNS or external apps/secrets, starts restricted qualification, changes schedulers, or publishes a component.

---

## Task 3: Record the G1 activation decision and refresh prerequisites (G1 only)

**Files:**
- Create: `docs/evidence/<decision-date>-plan-b-activation.md`
- Create: `docs/evidence/<date>-oci-preflight.json`
- Update: `docs/racetime-z1rr/launch-readiness-checklist.md`

- [ ] **Step 1: Stop unless the Council decision is explicit**

Record `PLAN_B_ACTIVATED`, reason, date, target window, primary technical operator, recovery custodian, rollback authority, and canonical hostname. Technical and routine cost decisions remain with the primary operator; `pending`, silence, delay, or anxiety is not activation.

- [ ] **Step 2: Refresh OCI read-only inventory**

List instances, shapes, OCPU/RAM/state, boot/block volumes/tags/size/VPUs, VNIC/public/private IP, VCN/subnet/security lists/NSGs, Bastion, buckets, dynamic groups/policies, alarms/budgets, limits/usage, current-month A1 OCPU/GB-hour slope, and cost. Confirm paid-tenancy status and the current 3,000/18,000 entitlement against the dated baseline; record the 744-hour RaceTime floor and refreshed combined Restream forecast.

- [ ] **Step 3: Verify recovery custody and account-level access routes**

Record the sealed package version, non-secret credential/key fingerprints, seal date, and custodian receipt. Verify the chosen route to regain OCI tenancy administration, GitHub/GHCR ownership, and authoritative DNS access without the primary operator's active session. Do not expose secrets or give the custodian routine access.

- [ ] **Step 4: Refresh external technical facts**

Confirm current OCI entitlement/pricing/capacity terms, Discord/Twitch redirect/scopes, Django/DOT/LiveSplit release/dependency advisories, DNS ownership, and TLS-ALPN-01 prerequisites against primary documentation. Reconcile material changes; do not re-adjudicate the already verified paid-tenancy basis without contrary evidence.

- [ ] **Step 5: Create a saved Terraform plan**

```bash
terraform -chdir=infra/oci init
terraform -chdir=infra/oci plan -var-file=production.tfvars -out=plan.bin
terraform -chdir=infra/oci show -json plan.bin > plan.json
```

Expected: create only the dedicated `racetime` A1 1-OCPU/6-GB instance, new 50-GB Balanced volume, and named support resources. Existing Restream instances and all five retained 47-GB volumes have no actions. The primary operator reviews `plan.json`, records the projected $2.13 incremental and approximately $3.61 retained-volume totals, and records any planned A1 compute overage without seeking a separate technical approval.

- [ ] **Step 6: Complete G1 pre-apply items**

If inventory, entitlement, account-recovery route, or the proposed resource actions differ materially, the primary operator records the reconciliation before apply. Do not check G1 until evidence links, operator record, and custodian receipt exist.

## Task 4: Apply the dedicated OCI platform and establish restricted qualification (G1 only)

**Files:**
- Create: `docs/evidence/<date>-oci-apply.json`
- Create: `docs/evidence/<date>-qualification-deploy.json`

- [ ] **Step 1: Apply only the reviewed saved plan**

```bash
terraform -chdir=infra/oci apply plan.bin
```

Expected: resource actions exactly equal reviewed plan. Any drift/replan stops execution.

- [ ] **Step 2: Verify post-apply OCI inventory and cost controls**

Confirm the new dedicated `racetime` VM at 1 OCPU/6 GB and new 50-GB Balanced volume; existing Restream resources are unchanged. Confirm no public SSH/DB/Redis, Bastion access, private versioned backup bucket/policy, and that TCP 443 is open to `0.0.0.0/0` and optional `::/0` for TLS-ALPN-01 while source restriction exists only in Caddy. Verify service alarms, below-2,650 forecast-relative/high-forecast suppression behavior, 2,900-hour escalation, retained-volume $3.61 +$1/+$3 alarms, and Object Storage 75%/90% alarms.

- [ ] **Step 3: Bootstrap host without application secrets in logs**

Patch OS/runtime, install pinned Docker/Caddy support/OCI CLI, configure primary key-only/Bastion access, verify the escrow recovery SSH key before sealing, configure time sync/firewall/root-owned config/log rotation/security updates, and reserve distinct qualification/production volume names. Run proportionate Ubuntu hardening checks without granting the recovery custodian routine access.

- [ ] **Step 4: Create canonical DNS and restricted qualification routing**

Create the sole A/AAAA record for `racetime.z1rracing.com` at the Terraform reserved public IP before ACME issuance; never create `staging.racetime.z1rracing.com`. Start Caddy with the root-owned expiring allowlist and the persistent `caddy-qualification` volume. Pin the only issuer's `dir` and `test_dir` to Let's Encrypt staging, enable TLS-ALPN-01, disable HTTP-01, and prove unlisted clients cannot fetch any route or upgrade WebSockets.

- [ ] **Step 5: Deploy exact RaceTime RC to qualification state**

Run config validation, migrate/bootstrap/static, start the stack, and verify health at the canonical hostname through process-scoped staging-root trust. Use explicitly named qualification DB/Redis/media/secrets/Caddy state; never mount final production state or use production bot/OAuth/alert credentials.

- [ ] **Step 6: Verify backup and alert transport before data creation**

Create canary qualification DB/media backups under a restore-ineligible `qualification/` prefix, decrypt/integrity verify, upload/list/download, run an isolated restore, and send test alerts to a private qualification sink/email. Confirm no production Caddy-state backup is created from staging-ACME state.

- [ ] **Step 7: Record evidence and complete G1**

Evidence includes reviewed/apply-plan hashes, before/after inventory, allowance/storage alarm tests, host/config/image IDs, canonical DNS response, adapted staging-issuer proof, TLS/WSS/default-deny results, backup/alert proof, and account-recovery-route record. No Terraform state or secrets are attached.

## Task 5: Register external applications and bootstrap governance (G1/G2)

**Files:**
- Create privately: qualification/production external-app register from `docs/operations/external-app-register.example.md`
- Create: `docs/evidence/<date>-external-apps.json`
- Create: `docs/evidence/<date>-governance.json`

- [ ] **Step 1: Register distinct qualification and production Discord identity apps**

Both use the exact callback `https://racetime.z1rracing.com/account/discord/callback`, scope `identify`, and no guild-membership requirement, but have distinct client IDs/secrets. Qualification credentials are active only against qualification state; production credentials remain disabled/unmounted until the fresh-production transition.

- [ ] **Step 2: Register distinct qualification and production Twitch apps**

Both use exact callback `https://racetime.z1rracing.com/account/twitch_auth` and minimum existing scopes with distinct credentials. Test qualification link/unlink and streaming policy through process-scoped trust; do not reuse Restream Twitch apps.

- [ ] **Step 3: Register distinct qualification and production TTPBot clients/category bots**

Grant only required `z1rr` category bot/create/action/chat permissions. Store qualification credentials in a root-owned qualification env; keep production credentials disabled/unmounted until fresh production. Neither scheduler is enabled by registration.

- [ ] **Step 4: Register LiveSplit public client**

Register distinct qualification and production application IDs under the `LiveSplit.Racetime.Z1RR` identity, both public authorization-code clients with redirect exactly `http://127.0.0.1:4888/`, no client secret, required S256 PKCE, and scopes exactly `read chat_message race_action`. Verify consent omits `create_race`; the production client is used only after production certificate issuance.

- [ ] **Step 5: Create and seal the break-glass identities**

Create the primary operator break-glass superuser and distinct escrow-only recovery superuser with unique strong credentials. Test the escrow superuser, recovery SSH key, and backup decryption key once; record non-secret fingerprints, seal them with recovery instructions, obtain the custodian receipt, and remove every routine access path for the custodian. Confirm admin is denied publicly and reachable only through Bastion/SSH loopback.

- [ ] **Step 6: Bootstrap Council governance**

Council members first create qualification accounts; through the local-only operator path run `bootstrap_z1rr --site-domain racetime.z1rracing.com --site-name "Z1RR RaceTime Qualification" --exclusive-public-category --owner-discord-id ID ...` for all approved members. Verify exact Site identity, sole public `z1rr`, ceilings/owners/goals/bots/moderators, idempotent second run, and that owners lack staff/infrastructure access. This state is explicitly disposable and is never promoted.

- [ ] **Step 7: Record only public identifiers/hashes and access roles**

Never place client secrets, tokens, Discord IDs unnecessary for proof, recovery password, webhook, or Credential Manager data in Git evidence.

## Task 6: Run pre-transition G2 qualification on disposable state

**Files:**
- Create: `docs/evidence/<date>-qualification-core.json`
- Create: `docs/evidence/<date>-qualification-browser.json`
- Create: `docs/evidence/<date>-qualification-provider-contracts.json`

- [ ] **Step 1: Qualify identity/account lifecycle**

Execute first login/name, returning login after Discord rename, denial/missing/mismatch/expiry/replay/concurrent callbacks, logout/session expiry, disabled surfaces, Twitch link/unlink/stream-required, deletion, audited identity transfer, primary break-glass path, and log canaries. Staging-root trust exists only in the browser automation profile/process, never the OS trust store.

- [ ] **Step 2: Qualify browser race lifecycle**

Two or more fixture accounts cover create/open/join/ready/auto-start/countdown/chat/DM/moderation/split/done/DNF/DQ/reconnect/record/rank/leaderboard. Verify racebot restart preserves authority and Redis loss interrupts live push only: authoritative in-race HTTP actions continue against MariaDB under emergency controls while fail-closed account/race-creation routes return generic 503.

- [ ] **Step 3: Qualify server-side provider contracts only**

Use fake/disabled-scheduler TTPBot and Restream contract adapters with `REQUESTS_CA_BUNDLE` or `NODE_EXTRA_CA_CERTS` scoped to the process. Prove origin/category/URL/state isolation without creating an operational room or producing BOT-006/RST G2 evidence. Do not run the real LiveSplit component or install a staging root in Windows.

- [ ] **Step 4: Qualify security boundaries of qualification state**

Prove root-owned allowlist expiry/record fields, public generic denial for application/static/media/OAuth/WebSocket routes, public admin denial, tunnel-only primary admin, qualification credential isolation, and that the recovery custodian has no allowlist or routine system access.

- [ ] **Step 5: Prove qualification state is disposable**

Inventory qualification DB/Redis/media/secrets/Caddy volume IDs, sessions, and OAuth/bot/alert credentials. Tests fail if any identifier collides with the reserved production names or if a qualification backup is marked production-restorable.

- [ ] **Step 6: Validate pre-transition evidence**

Validate the three qualification manifests and record explicitly that BOT-006, LS-008, OPS-008, and final Restream integration evidence remain pending until production certificate issuance.

- [ ] **Step 7: Validate evidence**

```powershell
.\venv\Scripts\python.exe scripts\ops\validate-evidence.py docs\evidence\<date>-qualification-core.json
.\venv\Scripts\python.exe scripts\ops\validate-evidence.py docs\evidence\<date>-qualification-browser.json
.\venv\Scripts\python.exe scripts\ops\validate-evidence.py docs\evidence\<date>-qualification-provider-contracts.json
```

Expected: all three PASS with no open P0/P1; no post-issuance artifact is falsely marked complete.

## Task 7: Run G2 failure, security, load, and recovery qualification

**Files:**
- Create: `tests/load/race-lifecycle.js`
- Create: `tests/load/websocket-chat.js`
- Create: `tests/security/zap-rules.tsv`
- Create: `docs/evidence/<date>-failure-security.json`
- Create: `docs/evidence/<date>-load.json`
- Create: `docs/evidence/<date>-restore-pretransition.json`

- [ ] **Step 1: Define measured load from historical peak**

Calculate the larger of twice the largest expected TTP room (entrants plus spectators/Restream/LiveSplit) and the realistic aggregate peak across four simultaneous rooms. Record the exact virtual-user/WebSocket/chat/reconnect model, not only request rate.

- [ ] **Step 2: Write k6 lifecycle/WebSocket scenarios**

Fixture users authenticate through a test bypass available only inside the allowlisted qualification network, create/join/read/chat/reconnect, and read leaderboards. Mutating actions use disposable races. Thresholds: no data errors, recorded p95 HTTP/WSS target, <1% non-injected failures, 20% CPU burst headroom and 30% memory headroom after steady state, no swap thrash/restart.

- [ ] **Step 3: Run failure injection**

Inject Discord/Twitch unavailable, Redis loss/restart, MariaDB pause/restart, racebot crash, Caddy/web restart, backup failure, full-ish disk/inode threshold, one provider down, network partition/reconnect, TLS/clock skew, and VM reboot. Verify Redis loss preserves authoritative in-race transitions while fail-closed route classes deny safely, and verify every failure-table alert/result.

- [ ] **Step 4: Run security checks**

Run `manage.py check --deploy`, dependency/container/IaC/secret scans, ZAP baseline with reviewed false positives, public port scan, admin/internal/default-deny checks, cookies/CSRF/CORS, HSTS exactly 300 while restricted, forwarding-header spoofing, OAuth/PKCE abuse/rate limits, upload type/size/non-execution, log redaction, category permission boundaries, and no public DB/Redis/SSH. Adapted Caddy config must prove one staging issuer, `ca == test_ca`, TLS-ALPN-only, and no ZeroSSL/cross-environment fallback.

- [ ] **Step 5: Run load test and record resource curves**

Run the same workload on the recorded ARM64 production shape and `VM.Standard.E5.Flex` amd64 recovery shape, starting from idle through ramp/steady/reconnect/recovery. If the default 1-OCPU/6-GB shape fails, the primary operator records optimization or resize, updates Terraform/forecast/recovery target, and reruns the complete load and restore gates. G2/G3 remain blocked; there is no waiver.

- [ ] **Step 6: Run qualification backup and empty-stack restore**

Use qualification DB/media data to verify encrypt/decrypt/integrity/upload and restore into explicitly isolated ARM64 and amd64 stacks. Measure RPO/RTO and confirm the procedure cannot select qualification data for a production restore. Final production Caddy-state/full-restore evidence is completed after issuance in Task 8.

- [ ] **Step 7: Rebuild on an empty compatible host/VM fixture**

Follow `vm-loss.md` using Git, the same-commit multi-platform manifest, config, sealed recovery material, verified OCI/GitHub/GHCR/DNS account-recovery route, and Object Storage. Prove the paid amd64 path at the operator-recorded shape; record actual/forecast cost without a Council cost-approval step.

- [ ] **Step 8: Validate pre-transition evidence/no blockers**

Any P0/P1 holds G2. Any P2 needs owner/date/Council risk acceptance. Fix and rerun the affected stage rather than editing a failed result; G2 is not complete until Task 8's production transition and post-issuance evidence also pass.

## Task 8: Create fresh production state, issue production TLS, and complete G2 (G2)

**Files:**
- Create: `scripts/ops/finalize-production.py`
- Create: `tests/operations/test_production_transition.py`
- Create: `scripts/ops/scheduler-cutover.py`
- Create: `scripts/ops/verify-dns.py`
- Create: `tests/operations/test_scheduler_cutover.py`
- Create: `tests/operations/test_dns_verification.py`
- Create: `docs/evidence/<date>-production-transition.json`
- Create: `docs/evidence/<date>-ttpbot-e2e.json`
- Create: `docs/evidence/<date>-restream-e2e.json`
- Create: `docs/evidence/<date>-livesplit-e2e.json`
- Create: `docs/evidence/<date>-dress-rehearsal.json`
- Create: `docs/evidence/<date>-restore.json`
- Create: `docs/evidence/<date>-cutover-rehearsal.json`

- [ ] **Step 1: Write failing fresh-production transition tests**

States: qualification running → maintenance/default-deny barrier → qualification schedulers/writes stopped → qualification backup sealed under restore-ineligible prefix → fresh production volumes/secrets created → Compose stopped/repointed → qualification credentials/sessions revoked → fresh production bootstrapped locally → production Caddy state selected → bounded production ACME issuance → normal G2 allowlist restored → post-issuance integrations complete. Fail on reordering, reused volume/credential/session identifiers, promotion/copy of qualification state, issuer mismatch/fallback, deadline breach, or a rollback reference to qualification state.

- [ ] **Step 2: Implement and dry-run the transition controller**

`finalize-production.py` is dry-run by default; `--apply --change-id` requires the G1 record and passed pre-transition evidence. It orchestrates explicit commands but never reads/displays secret values, stores append-only state outside Git, resumes only after probing reality, and leaves the hard barrier in place on every failure.

- [ ] **Step 3: Execute the fresh-production state transition**

Enter the barrier; stop qualification schedulers/writes; seal qualification backups; create fresh production DB/Redis/media/secret volumes; stop and repoint Compose without copying data; revoke qualification OAuth/bot/alert credentials and sessions while stopped; start fresh state; and bootstrap `racetime.z1rracing.com`, sole `z1rr`, Council owners, final goals/bots/moderators through the local-only command. Record IDs/hashes only.

- [ ] **Step 4: Switch once to production Caddy state and issue the certificate**

While the hard barrier remains, select a fresh persistent `caddy-production` volume whose only issuer pins both `dir` and `test_dir` to Let's Encrypt production. Adapt/verify exactly one issuer, TLS-ALPN-only, no ZeroSSL, then start Caddy with a bounded issuance deadline. OCI/host 443 remains public for validation. A deadline breach leaves the barrier and production-only retries in place and blocks G2; no fallback certificate is accepted. Record Certificate Transparency exposure and ordinary trust-chain evidence.

- [ ] **Step 5: Back up and restore fresh production state**

Capture and verify production DB/media plus encrypted Caddy state, retaining current and two prior verified generations. Restore into isolated ARM64 and recorded amd64 stacks, verify representative accounts/category/race/media/TLS configuration without contacting production ACME, and meet the recorded RPO/RTO. Add the final production backup-decryption material to the sealed recovery package, test the package, update its non-secret record/custodian receipt, and reseal it. Qualification backups remain ineligible.

- [ ] **Step 6: Run post-issuance TTPBot, Restream, and LiveSplit evidence**

Relax only to the normal G2 allowlist. With ordinary certificate validation and no CA override/bypass, run BOT-006 exactly-once room/announcement recovery, Restream provider selection/persistence/realtime/history/failure isolation, and LS-008 stock-side-by-side authorization/race lifecycle/adversarial cases. Use production-state accounts and final credentials but isolated schedule/webhook channels.

- [ ] **Step 7: Execute the complete restricted dress rehearsal**

One scheduled room flows TTPBot → test Discord → browser/LiveSplit entrants → Restream draft/realtime → finish/record/leaderboard on exact production artifacts. Validate OPS-008 and prove qualification credentials/state cannot authenticate or restore.

- [ ] **Step 8: Rehearse G3 cutover and rollback without changing DNS**

Test scheduler states old running → old stopped/lock absent → new config/probed → new running/lock held → first-room observe, plus rollback duplicate protection. `verify-dns.py` proves the already-canonical A/AAAA, certificate/SAN, HTTPS/WSS, and reserved IP. Rehearse removing/reapplying only the Caddy source restriction, HSTS 300→public value, scheduler, release publication, and communications; no DNS record changes occur.

- [ ] **Step 9: Complete the G2 checklist/sign-off**

Technical, operations, Competitive Integrity, and Council representatives sign only after every linked artifact validates, including fresh-production transition, production TLS, dual-architecture load/restore, post-issuance clients, dress rehearsal, and rollback.

## Task 9: Prepare G3 release and public communication

**Files:**
- Create: `docs/evidence/<launch-date>-go-no-go.md`
- Create: `docs/evidence/<launch-date>-cutover-log.md` from template
- Update privately: production secret/access/recovery inventory
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

- [ ] **Step 6: Refresh the G3 access and recovery inventory**

Verify the primary operator's current OCI/GitHub/GHCR/DNS/host/app access, the account-level recovery route, production OAuth/bot/webhook ownership and revocation paths, and the current sealed-package fingerprints/custodian receipt. Remove expired qualification/tester access and qualification credentials; record no secret values.

## Task 10: Execute G3 go/no-go and cutover

**Files:**
- Update live: `docs/evidence/<launch-date>-go-no-go.md`
- Append live: `docs/evidence/<launch-date>-cutover-log.md`

- [ ] **Step 1: Re-run immutable release identity and preflight**

Expected: exact G2 artifacts, healthy fresh-production stack, no active race, current primary-operator/access/custody records, and no unexplained alert or consumption anomaly.

- [ ] **Step 2: Take/verify final prelaunch backup**

Require manifest/object/decrypt/integrity proof and off-VM visibility before proceeding.

- [ ] **Step 3: Complete the G3 checklist and Council Go**

Unchecked mandatory item means No-go. Record decision and timestamp before any public change.

- [ ] **Step 4: Remove the canonical-host restriction under operator watch**

Verify authoritative/public DNS still resolves the unchanged Terraform reserved IP and the production certificate is current. Change `RACETIME_ACCESS_PHASE` to `public`, raise HSTS to at least 31536000 without preload, remove only the Caddy source-IP restriction, and verify public HTTPS/WSS/health/login plus admin denial. If validation fails, reapply the restriction and execute the communications/rollback path; do not change DNS or restore qualification state.

- [ ] **Step 5: Bootstrap/review final Council/category/client state**

Run `bootstrap_z1rr --site-domain racetime.z1rracing.com --site-name "Z1RR RaceTime" --exclusive-public-category --owner-discord-id ID ...`, then review exact Site identity, sole public `z1rr`, owners/mods/goals/bots/OAuth/Twitch/Discord callbacks and ordinary-user create permission. Confirm the second run is unchanged. No secret output.

- [ ] **Step 6: Run final controlled production smoke without scheduler**

Designated Council fixture accounts create, complete, and delete a deliberately unlisted test race through browser and Z1RR LiveSplit; Restream reads it; verify record policy and ordinary trust validation. Clean up only the explicit test room through supported application actions.

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

For a non-emergency rollback, publish the rollback notice before hiding the canonical host. For a security/integrity emergency, reapply the restriction first only when necessary and publish through the independent Discord path within five minutes. Start the promised status cadence.

- [ ] **Step 2: Stop the new scheduler before any old scheduler start**

- [ ] **Step 3: Determine whether a new-destination room exists for upcoming slot**

If yes, do not create duplicate old room; coordinate cancellation/continuation/communication explicitly.

- [ ] **Step 4: Restore prior bot release/env/state as one set and probe**

- [ ] **Step 5: Reapply the canonical-host source restriction if the site is rolling back**

Keep canonical DNS and production Caddy state. Never restore, promote, or authenticate with qualification volumes, backups, sessions, tokens, or credentials.

- [ ] **Step 6: Roll application by release-manifest migration strategy**

Never blindly reverse schema or overwrite database with an old backup for a code rollback.

- [ ] **Step 7: Verify old scheduler/provider path, production backups, monitoring, rollback notice/status cadence, and resolution communication**

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

Review the primary and escrow-only superusers, Council owners/mods/bots, GitHub protected environments/secrets/ownership recovery, OCI policies/Bastion/tenancy recovery, authoritative DNS recovery, Discord/Twitch/OAuth clients/webhooks, current sealed-package custody, and TTPBot old credentials. The recovery custodian still has no routine system access.

- [ ] **Step 5: Record cost/capacity and incidents**

Compare actual A1 usage/slope and retained-volume/Object Storage spend to the dated forecast. Below 2,650 hours validate the forecast-relative warning; at/above 2,650 validate the recorded utilization/cost and suppressed duplicate warning; always validate the 2,900-hour escalation. Diagnose Restream duty-cycling first for shared A1 anomalies and record operator forecast/shape changes without a Council cost-approval step. Any P0/P1 extends launch watch.

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
