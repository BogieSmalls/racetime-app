# Z1RR RaceTime Contingency Launch Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce, qualify, and—only after explicit Council gates—launch `racetime.z1rracing.com` as a recoverable Z1RR-operated Racetime service while preserving the simpler `racetime.gg/z1rr` outcome.

**Architecture:** A dedicated single-node ARM64 OCI deployment runs Caddy, Django/Daphne, the upstream racebot, MariaDB, Redis, and backup jobs from same-commit ARM64/amd64 immutable images; amd64 is the paid disaster-recovery fallback. Discord supplies public identity, Restream and TTPBot consume a provider-origin contract, and a clean-room LiveSplit DLL is built only for the self-hosted outcome. Restricted qualification and public service share the canonical hostname but never data, credentials, sessions, or Caddy state.

**Tech Stack:** Django 5.2, Channels/Daphne, MariaDB, Redis, Docker Compose, Caddy, OCI/Terraform, Python/Bash, Node/Vitest/React, .NET Framework 4.8.1, GitHub Actions

---

## Control documents

- Architecture: `docs/superpowers/specs/2026-08-12-plan-b-racetime-architecture-design.md`
- Requirements/ADRs/gates: `docs/racetime-z1rr/requirements-and-decisions.md`
- Deliverables: `docs/racetime-z1rr/artifact-register.md`
- Operational go/no-go: `docs/racetime-z1rr/launch-readiness-checklist.md`
- Requirement verification ledger: `docs/racetime-z1rr/requirements-traceability.md`

The requirements record supersedes only the architecture document's implementation-timing ambiguity and unresolved external-identity choice. It does not broaden the product scope.

## Subsystem plan index

| Order | Plan | May execute at G0? | Produces |
| --- | --- | --- | --- |
| 1 | `2026-08-22-z1rr-racetime-source-preservation.md` | Yes | Verifiable upstream archive and drift workflow |
| 2 | `2026-08-22-z1rr-racetime-core-platform.md` | Yes, local/non-public | Production-ready app, Discord identity, containers, configuration, backups, IaC definitions |
| 3 | `2026-08-22-z1rr-racetime-restream-provider.md` | Yes | Provider-qualified Restream source and persistence |
| 4 | `2026-08-22-z1rr-racetime-ttpbot-provider.md` | Yes | Destination-safe bot configuration/state/cutover tooling |
| 5 | `2026-08-22-z1rr-racetime-livesplit-provider.md` | Yes, local/unpublished | Clean-room side-by-side provider and release artifacts |
| 6 | `2026-08-22-z1rr-racetime-operations-cutover.md` | Local tooling at G0; external steps at stated gates | Monitoring, runbooks, E2E evidence, rollout/rollback |

Implementation uses @superpowers:test-driven-development within every code task, @superpowers:verification-before-completion before every acceptance claim, and @superpowers:requesting-code-review at each subsystem release candidate.

## Outcome lanes

```text
Request pending (G0)
  ├─ Build/test provider-neutral + contingency artifacts locally
  ├─ Racetime.gg grants z1rr
  │    ├─ Configure Restream: racetime-gg:z1rr
  │    ├─ Configure TTPBot: https://racetime.gg + z1rr
  │    └─ Cancel self-hosted app/OCI/Discord auth/LiveSplit release
  └─ Council activates Plan B (G1)
       ├─ Apply reviewed OCI/external-app configuration
       ├─ Qualify disposable state, then initialize fresh restricted production (G2)
       └─ Council go/no-go → remove restriction/cut scheduler (G3) → stabilization (G4)
```

## Working-copy topology

Use one dedicated worktree per repository so changes cannot mix with the user's current branches:

```text
Z1RR.RaceTime/.worktrees/racetime-readiness
Z1RR.Restream/.worktrees/racetime-provider
TTPBot/.worktrees/racetime-provider
LiveSplit.Racetime.Z1RR/                 # new repository; Plan-B artifact
```

The RaceTime repository has two permanent protected branches with distinct purposes:

- `master` is an upstream mirror. Only reviewed upstream synchronization commits/tags may land there; no Z1RR product commit is merged into it.
- `z1rr-production` is the deployable Z1RR line. It is not created until G1 Plan-B activation; at G1 it is initialized once from the recorded upstream baseline, protected, made the default branch, and becomes the only branch allowed to publish production release candidates.

G0 implementation work uses `feature/racetime-readiness` from the recorded baseline and remains off `master`; after G1 it targets `z1rr-production`. Restream and TTPBot use `feature/racetime-provider` and their existing protected production branches; the clean-room LiveSplit repository uses feature branches targeting protected `main`. The existing planning worktree/branch may be merged into `feature/racetime-readiness` before code begins, never into the RaceTime upstream-mirror `master`.

## Phase dependency graph

| Phase | Work | Depends on | Can run in parallel with |
| --- | --- | --- | --- |
| P0 | Source archive, test baseline, branch protections | Reviewed plans | Nothing that changes upstream baseline |
| P1 | Core production settings/identity/bootstrap | P0 baseline | Restream, TTPBot, LiveSplit core |
| P2 | Container/IaC/backup artifacts | Production settings contract | Restream, TTPBot, LiveSplit |
| P3 | Local cross-system integration | Core + provider integrations | Documentation/tabletops |
| P4 | G1 external prerequisites | Council Plan-B activation | Final documentation only |
| P5 | G2 canonical-host qualification and fresh-production finalization | G1 + all component RCs | Independent load/security/restore tests |
| P6 | G3 cutover | G2 signed evidence | None |
| P7 | G4 stabilization | G3 launch | Backlog triage only |

## Task 1: Establish the controlled execution workspace

**Files:**
- Verify: `docs/racetime-z1rr/requirements-and-decisions.md`
- Verify: `docs/racetime-z1rr/artifact-register.md`
- Verify: `docs/racetime-z1rr/launch-readiness-checklist.md`
- Create in each repository: repository-specific worktree named above
- Verify: `docs/racetime-z1rr/requirements-traceability.md`

- [ ] **Step 1: Verify the plan bundle has no unresolved markers**

Run from `Z1RR.RaceTime`:

```powershell
rg -n "TODO|TBD|FIXME|CHANGEME" docs\racetime-z1rr docs\superpowers\plans
```

Expected: no unresolved implementation marker; examples explicitly described as invalid fixture values are allowed only when explained next to the value.

- [ ] **Step 2: Record clean/dirty state without modifying user work**

Run in each repository:

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
```

Expected: output is copied into the execution log; unrelated changes are left untouched.

- [ ] **Step 3: Create repository-local ignored worktree directories**

Use @superpowers:using-git-worktrees. Add `.worktrees/` to each repository's `.gitignore` in an isolated, reviewed commit before creating a worktree there.

Expected: `git check-ignore -q .worktrees` returns zero in every repository.

- [ ] **Step 4: Create feature worktrees from the recorded baselines**

```powershell
git worktree add .worktrees\racetime-readiness -b feature/racetime-readiness <recorded-upstream-baseline>
```

Use the repository-specific branch/path names above for Restream and TTPBot. Create the LiveSplit repository only from the clean-room plan; do not fork or clone the unlicensed provider.

- [ ] **Step 5: Establish and verify source-control governance**

At G0, protect default branch `master` against force-push/deletion and restrict it to reviewed upstream mirror updates; do not merge Z1RR workflows or product changes there. Record the protection export/screenshots and a negative direct-push test. Prepare—but do not apply—the G1 ruleset/default-branch checklist for `z1rr-production`: pull requests, at least one independent approval, required CI/security checks, conversation resolution, no force-push/deletion, and release environments restricted to that branch.

Promotion path after G1 is explicit: create `z1rr-production` from the recorded baseline, set it as default, merge Z1RR feature PRs into it, and build immutable releases only from its clean merge commit. Later upstream synchronization updates `master`; a reviewed baseline-sync PR brings the selected upstream commit into `z1rr-production`. Never merge `z1rr-production` back into `master`.

- [ ] **Step 6: Commit only workspace-control changes**

```powershell
git add .gitignore
git commit -m "chore: isolate racetime readiness worktrees"
```

Expected: no application file enters this commit.

## Task 2: Establish objective baseline evidence

**Files:**
- Create: `docs/evidence/2026-08-22-g0-baseline.md`
- Modify: `docs/racetime-z1rr/artifact-register.md` only to add evidence links, not change requirements

- [ ] **Step 1: Capture RaceTime baseline tests and dependency audit**

```powershell
.\venv\Scripts\python.exe manage.py test
.\venv\Scripts\python.exe manage.py check
npm audit --omit=dev
```

Expected baseline: zero discovered Django tests, clean Django system check, and one high-severity `js-cookie <=3.0.5` finding. Record exact versions and output; do not call this a passing release baseline.

- [ ] **Step 2: Capture Restream baseline**

```powershell
Set-Location D:\Projects\Streaming\Z1RR\Z1RR.Restream\mini
npm ci
npm run typecheck
npm test -- --run
```

Expected: commands complete successfully before provider changes; record any pre-existing failure and stop that workstream until triaged with @superpowers:systematic-debugging.

- [ ] **Step 3: Capture TTPBot baseline**

```powershell
Set-Location D:\Projects\Streaming\Z1RR\TTPBot
python -m unittest discover -s tests -v
```

Expected: all existing bot tests pass.

- [ ] **Step 4: Capture current LiveSplit interface/release evidence**

Record LiveSplit release `1.8.37`, target `net4.8.1`, and the commit hashes of the official `IRaceProviderFactory`, `RaceProviderAPI`, `RaceProviderSettings`, and `IRaceInfo` files used for interoperability. Record that `steto-scope/LiveSplit.Racetime` has no declared license; do not download its source into the new repository.

- [ ] **Step 5: Capture read-only OCI capacity inventory**

Use OCI CLI read-only list commands. Record instance name/state/shape/OCPU/memory, non-terminated boot-volume name/size/VPUs, current A1 OCPU/GB-hour usage and slope, and paid-tenancy entitlement evidence. Expected current evidence is five 47-GB volumes (235 GB), 3,000/18,000 monthly A1 allowance, and the shapes/forecast in the requirements record; any change is reconciled before G1.

- [ ] **Step 6: Commit the baseline evidence**

```powershell
git add docs\evidence\2026-08-22-g0-baseline.md docs\racetime-z1rr\artifact-register.md
git commit -m "docs: record racetime contingency baseline"
```

## Task 3: Execute and accept the source-preservation plan

**Files:** See `docs/superpowers/plans/2026-08-22-z1rr-racetime-source-preservation.md`.

- [ ] **Step 1: Execute every source-preservation task with tracked checkboxes**

Expected: SRC-001 through SRC-006 have evidence; archives themselves remain outside Git.

- [ ] **Step 2: Restore into an empty temporary directory**

Run the exact restore test in the subsystem plan. Expected: restored `HEAD`, branches, tags, and checksum match the manifest.

- [ ] **Step 3: Request independent code/document review**

Use @superpowers:requesting-code-review against the source plan and SRC acceptance criteria.

- [ ] **Step 4: Mark source artifacts accepted**

Update only evidence links/status in `artifact-register.md` and commit:

```powershell
git commit -am "docs: accept racetime source preservation artifacts"
```

## Task 4: Execute the five G0 workstreams

**Files:** See the core/platform, Restream, TTPBot, LiveSplit, and operations subsystem plans.

- [ ] **Step 1: Execute the RaceTime core/platform plan through its G0 stop line**

Expected: APP-001–012 and PLT-001–008 are locally verified; no Terraform apply, public DNS, production app registration, or OCI mutation occurs except the separately authorized private G0 source-custody bucket and its four source-preservation objects.

- [ ] **Step 2: Execute the Restream provider plan**

Expected: RST-001–008 pass for both outcome fixtures and legacy database migration.

- [ ] **Step 3: Execute the TTPBot provider plan through its G0 stop line**

Expected: BOT-001–005 pass against mocks/local service; no production scheduler destination changes.

- [ ] **Step 4: Execute the LiveSplit plan through its G0 stop line**

Expected: LS-001–007 build/test locally; no public OAuth app, release, or update-feed publication.

- [ ] **Step 5: Execute Operations Tasks 1–2 through its explicit G0 stop line**

Expected: GOV-004 and OPS-001–004 are locally verified; `validate-evidence.py`, `validate-traceability.py`, the release-identity collector, and the qualification/fresh-production state machines exist and pass hermetic tests. Operations Task 3 or later is forbidden before its stated gate, and no OCI/DNS/external-app/qualification mutation occurs except the separately authorized private G0 source-custody bucket and its four source-preservation objects.

- [ ] **Step 6: Review each workstream independently**

Use @superpowers:requesting-code-review for each workstream change set, consolidating reviews that share the RaceTime repository without dropping either the core/platform or G0-operations acceptance criteria. No cross-repository integration begins with an open blocking review item.

## Task 5: Build the isolated local integration environment

**Files:**
- Create: `deploy/compose.integration.yml`
- Create: `deploy/env/integration.env.example`
- Create: `requirements-e2e.txt`
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/fixtures.py`
- Create: `tests/e2e/test_compose_isolation.py`
- Create: `tests/e2e/test_browser_race_lifecycle.py`
- Create: `tests/e2e/test_oauth_pkce.py`
- Create: `tests/e2e/test_provider_contract.py`
- Create: `scripts/integration-up.ps1`
- Create: `scripts/integration-down.ps1`

**Interface — consumes:** accepted core/platform images and bootstrap/settings contracts; fixture-only Discord/OAuth adapters; provider-qualified Restream/TTPBot origins and category `z1rr`.

**Interface — produces:** an isolated Compose project, `IntegrationEndpoints` fixture, deterministic browser/HTTP helpers, and test output consumed by Task 6 G0 evidence. It must expose no production secret or network mutation path.

`tests/e2e/fixtures.py` is an ordinary importable `unittest` support module. No pytest discovery hook or `conftest.py` is used.

- [ ] **Step 1: Write a failing topology test**

Create `ComposeIsolationTests` in `tests/e2e/test_compose_isolation.py`. It loads both production and integration Compose files and asserts unique project names, networks, ports, database volumes, Redis databases, and secrets. Keep provider contract assertions in `test_provider_contract.py`.

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.e2e.test_compose_isolation.ComposeIsolationTests -v
```

Expected: FAIL because `compose.integration.yml` does not exist.

- [ ] **Step 2: Add the isolated integration Compose stack**

Bind Caddy to loopback high ports, use fixture Discord/OAuth adapters, distinct database/Redis volumes, and local provider origins. Never read `.env.production` or TTPBot production state.

- [ ] **Step 3: Re-run the topology test**

Expected: PASS and rendered Compose has no `0.0.0.0:80`, `0.0.0.0:443`, production hostname, real webhook, or production client ID.

- [ ] **Step 4: Write the failing `unittest` browser lifecycle test**

Use Python `unittest` plus synchronous Playwright. Import helpers from `tests.e2e.fixtures`; do not depend on pytest fixtures. The test covers account creation through fixture Discord, selected name, race creation, second entrant, ready/start/chat/done, record, and leaderboard update through Chromium.

```python
class BrowserRaceLifecycleTests(unittest.TestCase):
    def test_two_entrants_finish_and_leaderboard_records(self):
        with chromium_page(IntegrationEndpoints.from_env()) as page:
            first = fixture_discord_account(page, subject="1001", display_name="Racer One")
            room = create_race(page, first, goal="Beat the game")
            second = join_with_fixture_discord(page, room, subject="1002", display_name="Racer Two")
            complete_two_entrant_race(page, room, first, second)
            assert_recorded_leaderboard(page, room, expected_names=("Racer One", "Racer Two"))
```

Expected: FAIL before the stack/helpers exist.

- [ ] **Step 5: Pin and install the E2E browser driver**

Create `requirements-e2e.txt` with exactly `playwright==1.62.0`. Install the dependency and its matching Chromium binary explicitly:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-e2e.txt
.\venv\Scripts\playwright.exe install chromium
```

The G0 integration runner performs both commands on a clean worker and caches only by the requirements file hash; browser binaries are never committed.

- [ ] **Step 6: Implement integration startup and ordinary unittest fixtures**

`integration-up.ps1` validates fixture-only environment, builds images, starts the stack, waits for health, migrates, and runs `bootstrap_z1rr --site-domain integration.racetime.test --site-name "Z1RR RaceTime Integration" --exclusive-public-category`. `integration-down.ps1` addresses only the explicit integration Compose project and preserves failure logs. `fixtures.py` exports `IntegrationEndpoints.from_env()`, `chromium_page(...)`, deterministic fixture-Discord account helpers, and bounded wait/assertion helpers; every helper raises `unittest`-readable errors and redacts OAuth material.

- [ ] **Step 7: Run core integration tests**

```powershell
.\scripts\integration-up.ps1
.\venv\Scripts\python.exe -m unittest discover -s tests\e2e -v
.\scripts\integration-down.ps1
```

Expected: all tests pass; no public network mutation.

- [ ] **Step 8: Commit the integration harness**

```powershell
git add deploy\compose.integration.yml deploy\env\integration.env.example requirements-e2e.txt tests\e2e scripts\integration-up.ps1 scripts\integration-down.ps1
git commit -m "test: add isolated racetime integration stack"
```

## Task 6: Qualify the complete G0 contingency package

**Files:**
- Create: `docs/evidence/<execution-date>-g0-readiness.md`
- Update: `docs/racetime-z1rr/launch-readiness-checklist.md`
- Update: `docs/racetime-z1rr/requirements-traceability.md`
- Use: `scripts/ops/validate-traceability.py`
- Use: `tests/operations/test_traceability.py`

- [ ] **Step 1: Run every repository's clean build/test/audit command**

Use each subsystem plan's final verification block. Expected: no skipped mandatory test, high/critical vulnerability, uncommitted generated artifact, or secret-scan finding.

- [ ] **Step 2: Run the approved-outcome configuration test**

Configure Restream and TTPBot for `https://racetime.gg` + `z1rr` against a fake provider contract. Expected: no self-hosted hostname or LiveSplit dependency is required.

- [ ] **Step 3: Run the self-hosted local configuration test**

Configure them for the local integration origin + `z1rr`. Expected: canonical URLs, WebSockets, state namespace, and historical persistence remain provider-qualified.

- [ ] **Step 4: Validate activation safeguards**

Static and behavior tests prove Terraform defaults to no apply, integration scripts reject production hostnames/secrets, deploy scripts require G1/G2 evidence, and release workflows cannot publish the LiveSplit component without a protected environment approval.

- [ ] **Step 5: Complete the G0 section of the launch checklist**

Every checked item links evidence. Unmet items stay unchecked; do not substitute narrative assurance.

- [ ] **Step 6: Update and validate requirement traceability**

Use the validator implemented and tested by Operations Task 1. Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.operations.test_traceability -v
.\venv\Scripts\python.exe scripts\ops\validate-traceability.py --gate G0
```

The tests cover unknown requirement/artifact IDs, duplicate rows, invalid status, terminal status without a Markdown evidence link, missing link target, a registered artifact absent from both requirement and architecture/control coverage, due `Planned` rows, and a valid gate-specific matrix. The command loads requirements, the artifact register, and the matrix; expands same-prefix ranges such as `SRC-001–006`; emits only safe IDs; and fails on any forward or reverse coverage mismatch.

For every G0-due row, replace `Planned` only with `Verified ([evidence](...))` or `Accepted exception (Council-ID, [evidence](...))`. Commit the matrix with the evidence it cites.

- [ ] **Step 7: Request a cross-repository readiness review**

Provide the requirements, artifact register, traceability matrix, diffs, test outputs, and G0 evidence. Expected: no P0/P1 item.

## Task 7: Stop for the outcome decision

**Files:**
- Create when decided: `docs/evidence/<decision-date>-outcome-decision.md`

- [ ] **Step 1: Present both deployable outcome configurations to the Council**

Include remaining external actions, cost, risks, lead time, canceled components, and last safe decision date.

- [ ] **Step 2: Record the explicit outcome**

The record must say one of:

```text
APPROVED_CATEGORY: use https://racetime.gg/z1rr; cancel Plan-B deployment.
PLAN_B_ACTIVATED: authorize G1 external prerequisites for https://racetime.z1rracing.com.
CONTINUE_WAITING: make no external changes; retain and periodically refresh G0 artifacts.
```

- [ ] **Step 3: Enforce the selected stop/continue path**

For `CONTINUE_WAITING`, schedule monthly dependency/inventory drift checks. For `PLAN_B_ACTIVATED`, continue with Task 8. For `APPROVED_CATEGORY`, complete Steps 4–10 below; do not execute Plan-B Tasks 8–10.

- [ ] **Step 4: Obtain and inventory Racetime.gg category access** (`APPROVED_CATEGORY` only)

Confirm the live `z1rr` category, Council owner/moderator access, goal configuration, and the minimum TTPBot confidential-client/category-bot credentials. Record credential owner, recovery route, permissions, redirect/callback values, and revocation path in the private access register without copying secrets into evidence. Acceptance: the primary technical operator can rotate credentials and Council category owners can administer the category without relying on the old `z1r` owners.

- [ ] **Step 5: Stage the approved provider configuration** (`APPROVED_CATEGORY` only)

Deploy the reviewed Restream and TTPBot release candidates to isolated staging. Set Restream's logical Z1RR source to provider `racetime-gg`, origin `https://racetime.gg`, category `z1rr`; keep pickup as `racetime.gg/z1r`. Set TTPBot origin/category to the same `z1rr` destination with staging credentials/state. Run both preflights and prove that no self-hosted hostname, self-hosted OAuth app, OCI RaceTime service, or Z1RR LiveSplit build is required.

- [ ] **Step 6: Rehearse approved-path cutover and rollback** (`APPROVED_CATEGORY` only)

Outside every room-open window, use a non-production schedule/webhook to prove: one scheduler lock, exactly one `racetime.gg/z1rr` room, one Discord announcement, Restream selection/persistence/reload, and browser completion/leaderboard. Rehearse rollback by stopping the new scheduler first, restoring the old release/config/state as one set, probing the prior destination, and refusing restart if a counterpart room already exists.

- [ ] **Step 7: Freeze releases and take deploy backups** (`APPROVED_CATEGORY` only)

Record exact Restream/TTPBot commits, dependency locks, configuration schema, and deployment target. Back up Restream data and TTPBot state/config without printing secrets. Confirm the next safe blackout, primary technical operator, Council go/no-go owner, and rollback authority.

- [ ] **Step 8: Deploy Restream, then move the TTPBot scheduler** (`APPROVED_CATEGORY` only)

Deploy Restream and verify both logical sources. Stop/disable the old scheduler, prove its process/lock absent, archive its state/env, atomically install the reviewed TTPBot release plus `https://racetime.gg`/`z1rr` credentials, run config and read-only provider/collision preflights, then start exactly one scheduler. Never run old and new scheduler instances concurrently.

- [ ] **Step 9: Observe acceptance and retain rollback readiness** (`APPROVED_CATEGORY` only)

For the first scheduled room, record canonical category/URL, goal/policy/time, one announcement, destination-bound state, browser join/completion, Restream provider identity, recorded result, and leaderboard. A duplicate/misdirected room, credential failure, incorrect announcement, or missing Restream result triggers the rehearsed rollback and status communication.

- [ ] **Step 10: Close the approved outcome** (`APPROVED_CATEGORY` only)

Create `docs/evidence/<date>-approved-category-cutover.md`, update the launch checklist's applicable integration/operations rows, and move every applicable traceability row to linked `Verified` status. Mark self-hosted-only rows `Accepted exception` with the outcome-decision ID, archive—not delete—the self-hosted RC manifests, and record that no OCI/DNS/Discord-identity/LiveSplit Plan-B artifact was activated or published.

## Task 8: Execute G1 and G2 qualification (Plan B only)

**Files:** See `2026-08-22-z1rr-racetime-operations-cutover.md`; update `docs/racetime-z1rr/requirements-traceability.md`.

- [ ] **Step 1: Execute the G1 external-prerequisite section**

Initialize `z1rr-production` at the recorded baseline, push/protect it with the prepared ruleset, set it as the repository default, merge the reviewed readiness feature through PR, and manually dispatch/verify `upstream-drift.yml`; its declared schedule is now active from the default branch. Expected: branch/default/protection evidence, the dedicated 1-OCPU/6-GB A1 plus 50-GB plan applied without changing Restream resources, canonical DNS/TLS-ALPN qualification, distinct qualification/production apps and state, recovery custody/account-access route, and G1 checklist evidence.

- [ ] **Step 2: Deploy immutable release candidates to restricted qualification**

Expected: exact same-commit ARM64/amd64 image and provider hashes recorded on disposable qualification volumes at `racetime.z1rracing.com`; no production scheduler, production credentials, public route, or public announcement.

- [ ] **Step 3: Execute pre-transition G2 functional, security, load, recovery, and failure tests**

Expected: core/browser/server-side qualification, default-shape ARM64 plus amd64 fallback load/recovery, security, and failure evidence pass; programmatic-client evidence remains intentionally pending.

- [ ] **Step 4: Execute fresh-production finalization and post-issuance integration**

Expected: qualification state is sealed and never promoted; fresh volumes/secrets/sessions are used; qualification credentials are revoked; production ACME is pinned and trusted; production Caddy state is backed up/restored; TTPBot, Restream, LiveSplit, and dress rehearsal pass with ordinary certificate validation.

- [ ] **Step 5: Rehearse G3 restriction/scheduler cutover and rollback, then sign or hold G2**

DNS remains unchanged. Record timing, operator commands, Caddy restriction/HSTS changes, old/new scheduler transitions, rollback communications, and duplicate prevention. Unchecked mandatory item means hold; risk acceptance is allowed only for documented P2 findings.

- [ ] **Step 6: Update the traceability matrix for G1/G2**

Link each verified row to immutable qualification, production-transition, production-certificate, post-issuance, load, and restore evidence. The gate validator must reject any G1/G2-due row still `Planned` or any accepted exception without its Council risk-acceptance ID.

## Task 9: Execute G3 public cutover (Plan B only)

**Files:**
- Create: `docs/evidence/<launch-date>-go-no-go.md`
- Create: `docs/evidence/<launch-date>-cutover-log.md`
- Update: `docs/racetime-z1rr/requirements-traceability.md`

- [ ] **Step 1: Freeze changes and record release identities**

- [ ] **Step 2: Take and verify the final backup**

- [ ] **Step 3: Complete the G3 checklist and Council go/no-go**

- [ ] **Step 4: Remove only the canonical-host source restriction, raise HSTS, and execute the operations plan's scheduler/publication sequence exactly; do not change DNS**

- [ ] **Step 5: Observe the first room end to end**

- [ ] **Step 6: Roll back immediately if a listed trigger occurs**

- [ ] **Step 7: Preserve the timestamped cutover log and evidence**

No step is batched with another operator action. The command, actor, start/end time, observed result, and rollback status are recorded before proceeding.

- [ ] **Step 8: Update and validate G3 traceability**

Every G3-due requirement has linked cutover evidence or a Council exception ID; the validator rejects a remaining `Planned` row.

## Task 10: Stabilize and close the launch project

**Files:**
- Create: `docs/evidence/<date>-stabilization.md`
- Update: `docs/racetime-z1rr/launch-readiness-checklist.md`
- Update: `docs/racetime-z1rr/requirements-traceability.md`

- [ ] **Step 1: Run daily launch-week service/capacity/backup/cost reviews**

- [ ] **Step 2: Complete one full scheduled TTP slate**

- [ ] **Step 3: Perform the launch access review**

- [ ] **Step 4: Record incidents and assign P2/P3 follow-ups**

- [ ] **Step 5: Obtain G4 approval**

- [ ] **Step 6: Close requirement traceability**

Link G4 evidence and verify no row remains `Planned`; all rows are `Verified` or carry a documented Council exception ID.

- [ ] **Step 7: Use @superpowers:finishing-a-development-branch for each repository**

Expected: reviewed changes are merged through the selected workflow, temporary worktrees are removed safely, release/source tags are preserved, and the legacy archive remains a separate post-launch project.

## Final verification commands

Run from the RaceTime readiness worktree after subsystem plans are complete:

```powershell
git status --short
.\venv\Scripts\python.exe manage.py test --settings=project.settings.test
# Run with healthy MariaDB/Redis services and CI fixture environment:
.\venv\Scripts\python.exe manage.py test --settings=project.settings.ci
.\venv\Scripts\python.exe manage.py check --settings=project.settings.production --deploy
npm ci
npm audit --omit=dev
docker compose --env-file deploy\env\ci.env -f deploy\compose.production.yml config
terraform -chdir=infra\oci fmt -check -recursive
terraform -chdir=infra\oci validate
```

Expected: clean intended worktree, non-zero substantive test count with all tests passing, clean deploy checks, no high/critical production dependency finding, valid Compose rendering, and valid/formatted Terraform. External credentials in the deploy check use documented CI fixture values and never production values.

Then run the Restream, TTPBot, and LiveSplit final verification blocks from their own plans. Do not claim the launch is complete until G4; G0 completion means only that the contingency package is ready.
