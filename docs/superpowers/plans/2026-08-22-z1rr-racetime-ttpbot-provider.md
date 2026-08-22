# TTPBot Racetime Provider-Safe Destination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TTPBot switch safely between `racetime.gg/z1rr` and `racetime.z1rracing.com/z1rr` by configuration while preserving schedule behavior and preventing duplicate rooms, webhooks, or concurrent schedulers.

**Architecture:** Replace separate host/scheme assumptions with one validated provider origin plus category. Encapsulate absolute URL resolution and version all idempotency state with a destination key; state mismatch fails closed and cutover requires an explicit migration/archive operation plus a host-level single-scheduler lock.

**Tech Stack:** Python 3.9+, `racetime_bot` 2.x, aiohttp, systemd, `unittest`, JSON state, Linux `flock`

---

## Control documents

**Spec:** [Plan-B RaceTime architecture](../specs/2026-08-12-plan-b-racetime-architecture-design.md)
**Requirements and gates:** [Requirements and decision record](../../racetime-z1rr/requirements-and-decisions.md)
**Artifact register:** [Launch artifact register](../../racetime-z1rr/artifact-register.md)
**Master plan:** [Contingency launch master plan](2026-08-22-z1rr-racetime-launch-master.md)
**Requirements owned:** FR-BOT-001–005 and ADR-004, with NFR-TEST-001 verification for this repository.

## Global Constraints

- G0 permits only local, non-public readiness work. OCI apply, DNS, production OAuth/apps, scheduler changes, publication, and cutover require their recorded G1–G3 gates.
- Preserve both outcome lanes: `racetime.gg/z1rr` and self-hosted `racetime.z1rracing.com/z1rr`. Do not alter ordinary `racetime.gg/z1r` pickup racing.
- RaceTime application work targets Django 5.2/Python 3.12 and immutable ARM64 production images; provider work must preserve its plan's declared runtime.
- Production origins are one validated HTTPS origin with no path/query/userinfo; every REST/WSS/link derives from it and historical references remain provider-qualified.
- Discord is the sole public self-hosted login. Never persist Discord access/refresh tokens or grant category owners Django staff, host, database, secret, backup, or OCI access.
- Preserve GPL-3.0/upstream attribution and corresponding source for every deployed RaceTime build; LiveSplit work stays clean-room and copies no unlicensed legacy-provider code.

## Repository and file map

Work in `D:\Projects\Streaming\Z1RR\TTPBot\.worktrees\racetime-provider`.

- Create `ttpbot/provider.py`: validated origin/category, REST/WSS/absolute URL helpers, destination key.
- Create `ttpbot/state.py`: versioned destination-bound atomic state stores and legacy migration.
- Create `ttpbot/preflight.py`: config/category/OAuth/state/scheduler read-only checks.
- Modify `ttpbot/runtime_config.py`: first-class provider and Discord announcement configuration.
- Modify `ttpbot/__init__.py`: CLI/env resolution, check/probe modes, racetime-bot class configuration.
- Modify `ttpbot/bot.py`: provider-derived room creation/results, injected state, generic naming.
- Modify `ttpbot/config.py`, `ttpbot/handler.py`: remove Z1R-specific environment/wording where it means destination rather than game.
- Modify `deploy/ttpbot.env.example`, `deploy/ttpbot.service`: new contract, single instance, hardening.
- Create `deploy/ttpbot-preflight`: operator wrapper.
- Modify `README.md`, `docs/oci-service-runbook.md`: both outcomes and exact cutover/rollback.
- Add `tests/test_provider.py`, `test_state.py`, `test_preflight.py`, and extend existing tests.

## Runtime contract

```text
TTPBOT_RACETIME_ORIGIN=https://racetime.gg
TTPBOT_CATEGORY_SLUG=z1rr
TTPBOT_RACETIME_CLIENT_ID=
TTPBOT_RACETIME_CLIENT_SECRET=
TTPBOT_DISCORD_WEBHOOK_URL=
TTPBOT_RACE_SEEKERS_ROLE_ID=
TTPBOT_DATA_DIR=/var/lib/ttpbot
```

Plan B changes only `TTPBOT_RACETIME_ORIGIN` and credentials. The approved-category outcome leaves origin at Racetime.gg. `TTPBOT_ALLOW_INSECURE_LOOPBACK=true` exists only for tests/local development and is rejected when service environment is `production`.

## Task 1: Add the canonical provider contract

**Files:**
- Create: `ttpbot/provider.py`
- Create: `tests/test_provider.py`

- [ ] **Step 1: Write failing origin validation tests**

```python
provider = RacetimeProvider(
    origin="https://racetime.z1rracing.com",
    category="z1rr",
)
self.assertEqual(provider.host, "racetime.z1rracing.com")
self.assertTrue(provider.secure)
self.assertEqual(provider.destination_key, "https://racetime.z1rracing.com|z1rr")
```

Reject blank, non-HTTPS production, path other than `/`, query, fragment, username/password, IP-literal production origin, malformed/uppercase/unsafe category, and trailing host confusion. Accept and normalize one trailing slash. Accept HTTP only for `localhost`/`127.0.0.1` when explicitly allowed.

- [ ] **Step 2: Write failing URL-resolution tests**

Test relative `/z1rr/room`, same-origin absolute URL, wrong-origin absolute URL, missing/malformed `Location`, REST `/o/z1rr/startrace`, and WS/WSS helper behavior. Wrong origin is an error, not silently rewritten.

- [ ] **Step 3: Run and verify failure**

```powershell
python -m unittest tests.test_provider -v
```

Expected: module import failure.

- [ ] **Step 4: Implement immutable provider**

Implement frozen `RacetimeProvider(origin, category, allow_insecure_loopback=False)` with read-only `host`, `secure`, and `destination_key` properties plus `http_url(path)`, `websocket_url(path)`, and `resolve_location(location)` methods.

Normalize once with `urllib.parse.urlsplit`; join relative paths with `urljoin`; compare scheme/host/port exactly before accepting an absolute or returned `Location`; derive `destination_key` from canonical origin plus category. Do not log `repr` of untrusted URLs with userinfo.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m unittest tests.test_provider -v
git add ttpbot\provider.py tests\test_provider.py
git commit -m "feat: define TTPBot racetime providers"
```

## Task 2: Make provider configuration first-class

**Files:**
- Modify: `ttpbot/runtime_config.py`
- Modify: `ttpbot/__init__.py`
- Modify: `tests/test_runtime_config.py`
- Modify: `setup.py`

- [ ] **Step 1: Write failing configuration precedence tests**

CLI explicit values override env; env supplies normal service values; blank is missing. Required names include origin, category, client ID/secret, data directory. Webhook/role must be both set or both absent in non-announcing test mode. Production rejects insecure-loopback. Secret values never appear in error/`repr`.

- [ ] **Step 2: Run and observe failure**

```powershell
python -m unittest tests.test_runtime_config -v
```

- [ ] **Step 3: Extend `BotRuntimeConfig`**

```python
@dataclass(frozen=True)
class BotRuntimeConfig:
    provider: RacetimeProvider
    client_id: str
    client_secret: str
    discord_webhook_url: Optional[str]
    race_seekers_role_id: Optional[str]
    data_dir: str
    environment: str
```

Validate Discord webhook exact allowlisted Discord API origin/path and numeric role ID; never display webhook URL.

- [ ] **Step 4: Replace debug host flags**

Add `--origin`, `--category`, `--check-config`, and `--probe`. Retain `--host/--insecure` for one release only as development-only deprecated aliases that cannot run with `environment=production`; tests cover the rejection.

- [ ] **Step 5: Configure `racetime_bot.Bot` from provider**

Before constructing `TTPBot`, set `TTPBot.racetime_host = provider.host` and `TTPBot.racetime_secure = provider.secure`. Pass the provider instance into `TTPBot`; no later code rereads environment.

- [ ] **Step 6: Pin dependencies precisely enough for reproducibility**

Keep `racetime_bot>=2.3,<3` only if its current tested version is captured in a lock/constraints file. Add `requirements.lock` generated from the verified environment and CI installs it. Do not silently upgrade during cutover.

- [ ] **Step 7: Run tests and commit**

```powershell
python -m unittest tests.test_runtime_config -v
git add ttpbot\runtime_config.py ttpbot\__init__.py tests\test_runtime_config.py setup.py requirements.lock
git commit -m "feat: configure TTPBot destination by origin"
```

## Task 3: Version and bind idempotency state to destination

**Files:**
- Create: `ttpbot/state.py`
- Create: `tests/test_state.py`
- Modify: `ttpbot/bot.py`
- Modify: `ttpbot/paths.py`
- Modify: `tests/test_runtime_state_paths.py`

- [ ] **Step 1: Write failing v2 state tests**

Both created-race and sent-webhook documents use:

```json
{
  "schema_version": 2,
  "destination_key": "https://racetime.z1rracing.com|z1rr",
  "entries": {}
}
```

Test missing file, valid restart, atomic temp/write/fsync/replace, corrupt JSON quarantine+fail, unsupported schema fail, destination mismatch fail, permissions, cleanup cutoff, and injected write failure preserving prior file.

- [ ] **Step 2: Write failing legacy migration tests**

Current `created_races.json` dict and `sent_webhooks.json` list migrate only when operator supplies exact `--legacy-origin` and `--legacy-category` matching the intended archive source. Default startup does not guess; it exits with recovery instructions. Migration copies originals to timestamped read-only backups and is idempotent.

- [ ] **Step 3: Run and observe failure**

```powershell
python -m unittest tests.test_state -v
```

- [ ] **Step 4: Implement `DestinationStateStore`**

Implement `DestinationStateStore(path, destination_key, entry_kind)` with validated `load()`, atomic `save(entries)`, and explicit `migrate_legacy(legacy_path, asserted_destination_key)`. Reject schema/entry-kind/destination mismatch, symlinks, and paths outside resolved `TTPBOT_DATA_DIR`; write through a same-directory temporary file plus flush/fsync/`os.replace`, and set files owner-read/write only on POSIX.

- [ ] **Step 5: Inject stores into `TTPBot`**

Remove import-time `CREATED_RACES_FILE`/`SENT_WEBHOOKS_FILE`. Bot constructor receives state stores or constructs them from runtime config, then uses explicit load/save methods.

- [ ] **Step 6: Run all state/restart tests**

Expected: same destination restarts exactly; mismatch cannot enter scheduler loop.

- [ ] **Step 7: Commit**

```powershell
git add ttpbot\state.py ttpbot\bot.py ttpbot\paths.py tests\test_state.py tests\test_runtime_state_paths.py
git commit -m "feat: bind TTPBot state to its destination"
```

## Task 4: Remove hard-coded room and announcement destinations

**Files:**
- Modify: `ttpbot/bot.py`
- Modify: `ttpbot/config.py`
- Modify: `ttpbot/handler.py`
- Modify: `tests/test_bot_room_policy.py`
- Create: `tests/test_room_creation.py`

- [ ] **Step 1: Write failing room-creation tests for both outcomes**

Mock token and `aiohttp.request`. For approved outcome assert POST to `https://racetime.gg/o/z1rr/startrace` and returned/announced `https://racetime.gg/z1rr/room`. For Plan B assert the self-hosted equivalents. Verify category, goal/info, room policy, authorization header, form body, timeout, status handling, and same-origin `Location` validation.

- [ ] **Step 2: Write failing announcement tests**

Use configured webhook/role ID; assert exactly one allowed role mention and canonical provider URL. Missing webhook+role explicitly disables announcements with a generic warning. One missing value is configuration failure. Remove `Z1R_DISCORD_WEBHOOK_URL` and hard-coded role ID from production code.

- [ ] **Step 3: Run and observe failures**

- [ ] **Step 4: Implement provider URL resolution**

Use `self.http_uri(...)` for authenticated request only after racetime-bot is configured, then `self.provider.resolve_location(resp.headers['Location'])` for returned URL. Never return `f'https://racetime.gg{location}'`.

- [ ] **Step 5: Make messages destination-neutral**

Descriptions say `Racetime provider` or `Z1RR racing`, not `racetime.gg Z1R`, where referring to infrastructure. Keep `Zelda 1 Randomizer` where referring to the game.

- [ ] **Step 6: Run room/policy/handler tests**

Expected: PASS for both origins and no behavior change to schedule/seed/chat logic.

- [ ] **Step 7: Hard-code audit**

```powershell
rg -n "https://racetime\.gg|Z1R_DISCORD_WEBHOOK|1494076623442542735|category_slug.*z1r" ttpbot deploy README.md docs
```

Expected: only outcome examples/legacy documentation/tests, never URL construction or production role selection.

- [ ] **Step 8: Commit**

```powershell
git add ttpbot tests
git commit -m "fix: derive TTPBot links and announcements from provider"
```

## Task 5: Add read-only preflight and single-scheduler enforcement

**Files:**
- Create: `ttpbot/preflight.py`
- Create: `tests/test_preflight.py`
- Create: `deploy/ttpbot-preflight`
- Modify: `deploy/ttpbot.service`
- Modify: `tests/test_paths.py`

- [ ] **Step 1: Write failing preflight tests**

Check config, state destination/schema/integrity, writable data directory, OAuth token acquisition, category data/slug, bot permission/credential validity, clock skew, current-room collision for the next slate, and announcement configuration. `--probe` performs only GET/token calls; it never POSTs `startrace` or Discord.

- [ ] **Step 2: Write failing service contract tests**

Assert `ExecStart` is wrapped in `/usr/bin/flock --nonblock /run/ttpbot/scheduler.lock`, runtime/state directories are explicit, service has one instance name, restart/hardening remains, and no secret is on command line.

- [ ] **Step 3: Run and observe failure**

- [ ] **Step 4: Implement preflight**

Return machine-readable JSON with booleans/safe destination ID and human mode. Catch provider errors without body/token. Clock skew threshold is 30 seconds. Current-room collision uses provider category current-race data and existing TTP room recognition.

- [ ] **Step 5: Implement host lock**

Add `RuntimeDirectory=ttpbot`, `RuntimeDirectoryMode=0750`, and `flock` before Python. A second service/manual scheduler exits non-zero. Preflight reports lock held but never breaks it.

- [ ] **Step 6: Run tests and a two-process local lock smoke**

Expected: first holds lock; second exits immediately; stopping first releases it.

- [ ] **Step 7: Commit**

```powershell
git add ttpbot\preflight.py tests\test_preflight.py deploy\ttpbot-preflight deploy\ttpbot.service
git commit -m "feat: preflight and lock the TTP scheduler"
```

## Task 6: Update deployment configuration and cutover runbook

**Files:**
- Modify: `deploy/ttpbot.env.example`
- Modify: `README.md`
- Modify: `docs/oci-service-runbook.md`
- Create: `tests/test_deploy_contract.py`

- [ ] **Step 1: Write failing documentation/config tests**

Assert every runtime variable, approved and Plan-B examples, root ownership/mode, validation/probe, explicit legacy state migration, one-scheduler sequence, room-open blackout, credential rotation, first-room observation, rollback without deletion, and secret redaction.

- [ ] **Step 2: Replace env example**

Use the runtime contract above with empty credentials/webhook/role, `TTPBOT_ENVIRONMENT=production`, and no usable default. Document exact file mode `root:ttpbot 0640`.

- [ ] **Step 3: Write the cutover sequence**

Exact order:

1. choose a window outside `ROOM_OPEN_MINUTES_BEFORE + 10`;
2. stop/disable old service and verify process/lock absent;
3. back up v1/v2 state and env without displaying secrets;
4. install tested release;
5. migrate/archive state explicitly for old destination and initialize new destination state;
6. write new origin/category/credentials atomically;
7. run config then probe preflight;
8. enable/start one service and verify lock;
9. observe next room creation and one announcement;
10. keep old env/state encrypted for rollback; do not start both.

- [ ] **Step 4: Write rollback sequence**

Stop new scheduler first, verify lock released, restore prior release/env/state as one set, probe old destination, then start old scheduler only if no new-destination room exists for the upcoming slot. If one exists, operators cancel/communicate manually; the bot never creates a counterpart automatically.

- [ ] **Step 5: Run documentation tests and commit**

```powershell
git add deploy\ttpbot.env.example README.md docs\oci-service-runbook.md tests\test_deploy_contract.py
git commit -m "docs: define TTPBot provider cutover"
```

## Task 7: Add provider integration tests

**Files:**
- Create: `tests/fakes/racetime_provider.py`
- Create: `tests/test_provider_integration.py`

- [ ] **Step 1: Build a local fake provider**

Support OAuth token, category current data, `startrace` returning relative `Location`, race data, and WSS endpoints necessary to prove configured host/category. Record requests and allow injected timeout/429/500/wrong-origin location/restart timing.

- [ ] **Step 2: Write approved-outcome integration test**

Run scheduler check for fake origin/category `z1rr`, advance clock into one opening window, assert one POST, one canonical URL, one state entry, one webhook payload, restart process, and assert no duplicate.

- [ ] **Step 3: Write self-hosted-outcome integration test**

Repeat with a second origin; assert no request/URL/state from the first origin leaks.

- [ ] **Step 4: Write failure/recovery tests**

Inject token failure, room POST timeout with uncertain result, wrong-origin Location, state write failure, restart before webhook, restart after webhook, and destination mismatch. For uncertain room creation, refresh provider current races before retry and fail closed if identity cannot be proven; do not blindly duplicate.

- [ ] **Step 5: Run full suite**

```powershell
python -m unittest discover -s tests -v
```

Expected: all existing and new tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add tests\fakes tests\test_provider_integration.py
git commit -m "test: prove TTPBot provider cutover safety"
```

## Task 8: Qualify and stop before production destination change

**Files:**
- Create: `docs/superpowers/evidence/<execution-date>-racetime-provider-rc.md`

- [ ] **Step 1: Run complete tests and package check**

```powershell
python -m unittest discover -s tests -v
python setup.py check
python -m compileall -q ttpbot
```

Expected: PASS.

- [ ] **Step 2: Run both config/preflight fixtures**

Expected: approved and self-hosted safe summaries differ only in destination/provider credentials; both pass against fake/local provider.

- [ ] **Step 3: Verify service security**

Run `systemd-analyze security deploy/ttpbot.service` on Linux or a CI container plus contract tests. Review remaining exposure; no writable path outside `/var/lib/ttpbot` and runtime lock.

- [ ] **Step 4: Request review**

Use @superpowers:requesting-code-review against FR-BOT-001–005 and BOT-001–005.

- [ ] **Step 5: Commit evidence**

```powershell
git add docs\superpowers\evidence
git commit -m "docs: qualify TTPBot provider release candidate"
```

**G0 stop line:** Do not edit `/etc/ttpbot.env`, stop/start the production service, rotate OAuth credentials, create a production room, or send a production Discord webhook. BOT-006 is executed only in isolated staging at G2.
