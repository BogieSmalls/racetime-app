# Z1RR LiveSplit racetime.gg Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a clean-room, side-by-side LiveSplit provider for `raceroom.z1rracing.com` with correct public-client PKCE, safe token storage, racetime.gg race actions/chat/reconnect, and reproducible signed releases.

**Architecture:** A new repository references the official MIT-licensed LiveSplit 1.8.37 binaries/interfaces but copies no code from the unlicensed legacy racetime.gg provider. Protocol/authentication code is isolated from the Windows/LiveSplit adapter so deterministic unit and mock-server tests cover PKCE, REST/WSS, state transitions, reconnect, and timer actions before late-G2 restricted-production qualification.

**Tech Stack:** C#/.NET Framework 4.8.1, Windows Forms, `HttpClient`, `ClientWebSocket`, `TcpListener`, Windows Credential Manager P/Invoke, NUnit, MSBuild/dotnet, GitHub Actions Windows runners, CycloneDX, minisign

---

## Control documents

**Spec:** [Plan-B Raceroom architecture](../specs/2026-08-12-plan-b-racetime-architecture-design.md)
**Requirements and gates:** [Requirements and decision record](../../racetime-z1rr/requirements-and-decisions.md)
**Artifact register:** [Launch artifact register](../../racetime-z1rr/artifact-register.md)
**Master plan:** [Contingency launch master plan](2026-08-22-z1rr-racetime-launch-master.md)
**Requirements owned:** FR-LS-001–004, ADR-007, and the client half of NFR-PRIV-001/NFR-TEST-001.

## Global Constraints

- G0 permits only local, non-public readiness work. OCI apply, DNS, production OAuth/apps, scheduler changes, publication, and cutover require their recorded G1–G3 gates.
- Preserve both outcome lanes: `racetime.gg/z1rr` and self-hosted `raceroom.z1rracing.com/z1rr`. Do not alter ordinary `racetime.gg/z1r` pickup racing.
- racetime.gg application work targets Django 5.2/Python 3.12 and produces same-commit immutable linux/arm64 and linux/amd64 images; A1 production runs ARM64 and the paid disaster-recovery fallback runs amd64. Provider work must preserve its plan's declared runtime.
- Production origins are one validated HTTPS origin with no path/query/userinfo; every REST/WSS/link derives from it and historical references remain provider-qualified.
- Discord is the sole public self-hosted login. Never persist Discord access/refresh tokens or grant category owners Django staff, host, database, secret, backup, or OCI access.
- Preserve GPL-3.0/upstream attribution and corresponding source for every deployed Raceroom build; LiveSplit work stays clean-room and copies no unlicensed legacy-provider code.

## Repository boundary

Create a new repository at `D:\Projects\Streaming\Z1RR\LiveSplit.Racetime.Z1RR`. Do **not** fork/clone/vendor `steto-scope/LiveSplit.Racetime`; it declares no license. Official `LiveSplit/LiveSplit` has an MIT `LICENSE`, and released binary/interface metadata may be referenced with attribution.

Pin this compatibility baseline:

```text
LiveSplit release: 1.8.37
Asset: LiveSplit_1.8.37.zip
SHA-256: 14bc8ef8ded9ef4033fb2f0cb6a152386d393127da18a4de14f096c5347aa991
Plugin target: net481
Provider origin: https://raceroom.z1rracing.com
Category: z1rr
Loopback redirect: http://127.0.0.1:4888/
```

## File map

- Create `LiveSplit.Racetime.Z1RR.sln`.
- Create `src/LiveSplit.Racetime.Z1RR.Core/`: provider config, PKCE, token model/store interface, REST/WSS protocol, race state machine.
- Create `src/LiveSplit.Racetime.Z1RR/`: LiveSplit factory/API/settings/IRaceInfo adapters, Windows credential store, loopback UI/login, race window/controller.
- Create `tests/LiveSplit.Racetime.Z1RR.Core.Tests/`: pure protocol/auth/state tests.
- Create `tests/LiveSplit.Racetime.Z1RR.Windows.Tests/`: Windows credential/loopback/adapter tests.
- Create `tests/LiveSplit.Racetime.Z1RR.ContractTests/`: local HTTP/WSS fake server and end-to-end provider contract.
- Create `build/Get-LiveSplitReference.ps1`: verified official release download/extract.
- Create `build/Verify-CleanRoom.ps1`, `build/Package.ps1`, `build/Verify-Reproducible.ps1`.
- Create `release/update.z1rr-racetime.xml`, `release/SHA256SUMS`, `release/SHA256SUMS.minisig` templates/generated artifacts.
- Create `docs/clean-room-provenance.md`, `docs/protocol-contract.md`, `docs/install.md`, `docs/release.md`, `THIRD-PARTY-NOTICES.md`, `LICENSE`, `SECURITY.md`.
- Create `.github/workflows/ci.yml`, `release.yml`, `dependabot.yml`.

## Task 1: Establish the clean-room repository and provenance gate

**Files:**
- Create: `.gitignore`
- Create: `README.md`
- Create: `LICENSE`
- Create: `THIRD-PARTY-NOTICES.md`
- Create: `SECURITY.md`
- Create: `docs/clean-room-provenance.md`
- Create: `build/Verify-CleanRoom.ps1`
- Create: `tests/LiveSplit.Racetime.Z1RR.Core.Tests/CleanRoomContractTests.cs`

- [ ] **Step 1: Initialize an empty repository**

```powershell
New-Item -ItemType Directory D:\Projects\Streaming\Z1RR\LiveSplit.Racetime.Z1RR
Set-Location D:\Projects\Streaming\Z1RR\LiveSplit.Racetime.Z1RR
git init -b main
```

Do not run `git clone` against the legacy provider.

- [ ] **Step 2: Write the provenance record before implementation**

Record permitted inputs: Z1RR architecture/requirements; Z1RR Raceroom GPL API/WebSocket behavior; official LiveSplit MIT release/binary/interfaces/source; OAuth 2.0/PKCE standards; observed network fixtures produced by Z1RR-owned local/qualification environments. Prohibited input: source/assets/resources/update feed from the unlicensed legacy provider.

- [ ] **Step 3: Write a failing clean-room contract test/script**

Assert repository history/tree contains no legacy provider remote URL except the explanatory provenance line, no legacy namespaces/resource hashes copied as implementation, no downloaded legacy directory, and all third-party packages have recorded name/version/license/source.

- [ ] **Step 4: Add MIT license and notices**

The new original component uses MIT unless Council/legal review selects another permissive license before code. Include official LiveSplit MIT attribution and dependency notices; do not claim the legacy provider's copyright/license.

- [ ] **Step 5: Run clean-room verification**

Expected: PASS on empty scaffold.

- [ ] **Step 6: Commit**

```powershell
git add .
git commit -m "docs: establish Z1RR LiveSplit clean-room boundary"
```

## Task 2: Scaffold the solution and pin LiveSplit references

**Files:**
- Create: `LiveSplit.Racetime.Z1RR.sln`
- Create: `Directory.Build.props`
- Create: `Directory.Packages.props`
- Create: `src/LiveSplit.Racetime.Z1RR.Core/LiveSplit.Racetime.Z1RR.Core.csproj`
- Create: `src/LiveSplit.Racetime.Z1RR/LiveSplit.Racetime.Z1RR.csproj`
- Create: three test project files
- Create: `build/Get-LiveSplitReference.ps1`
- Create: `tests/LiveSplit.Racetime.Z1RR.Core.Tests/BuildContractTests.cs`

- [ ] **Step 1: Write failing reference acquisition tests**

Test bad SHA, partial download, missing `LiveSplit.Core.dll`/`UpdateManager.dll`, cached valid asset, and no network mode. Final reference directory is ignored and created only after archive SHA and ZIP structure pass.

- [ ] **Step 2: Implement verified acquisition**

Download the exact official asset above, compute SHA-256 before extraction, extract into `artifacts/livesplit/1.8.37`, and copy only required compile references into `artifacts/references/1.8.37`. Never commit the ZIP/binaries.

- [ ] **Step 3: Scaffold projects**

Core targets `netstandard2.0` with no LiveSplit/WinForms dependency. Plugin targets `net481`, uses Windows Forms, and references the pinned local `LiveSplit.Core.dll` and `UpdateManager.dll` with `Private=false`. Core tests target current .NET; Windows/contract tests target `net481` on Windows.

- [ ] **Step 4: Enable deterministic strict builds**

Set deterministic/continuous integration build, portable PDB, nullable, warnings as errors, locked package restore, path map, fixed assembly/file version from release input, and source link without embedding workstation paths.

- [ ] **Step 5: Add minimal assembly identities**

Assembly/root namespace/factory/menu/settings names all use `LiveSplit.Racetime.Z1RR`; no type or settings name equals the stock `LiveSplit.Racetime` component.

- [ ] **Step 6: Build and test scaffold**

```powershell
pwsh build\Get-LiveSplitReference.ps1 -Version 1.8.37
dotnet restore --locked-mode
dotnet build -c Release --no-restore
dotnet test -c Release --no-build
```

Expected: build succeeds and at least the contract test runs.

- [ ] **Step 7: Commit without binaries**

```powershell
git add .
git status --short
git commit -m "build: scaffold Z1RR LiveSplit provider"
```

Expected: `artifacts/` absent from staged files.

## Task 3: Define provider and racetime.gg protocol contracts

**Files:**
- Create: `src/LiveSplit.Racetime.Z1RR.Core/Provider/ProviderConfiguration.cs`
- Create: `src/LiveSplit.Racetime.Z1RR.Core/Protocol/Models.cs`
- Create: `src/LiveSplit.Racetime.Z1RR.Core/Protocol/RaceAction.cs`
- Create: `src/LiveSplit.Racetime.Z1RR.Core/Protocol/RaceSessionState.cs`
- Create: `docs/protocol-contract.md`
- Create: corresponding core tests

- [ ] **Step 1: Write failing configuration tests**

Require exact production origin/category/client ID/redirect; reject non-HTTPS, path/query/fragment/userinfo, wrong category, redirect other than loopback/4888/root, and any configured client secret. Test REST/WSS URI derivation.

- [ ] **Step 2: Implement immutable config**

```csharp
public sealed record ProviderConfiguration(
    Uri Origin,
    string Category,
    string ClientId,
    Uri RedirectUri);
```

Production defaults may include public origin/category/client ID only after G1 registration; no client secret field exists anywhere.

- [ ] **Step 3: Write failing JSON/protocol model tests**

Use sanitized Z1RR Raceroom fixtures for category/race/user/entrant/status, OAuth tokens/errors, and WebSocket `race.data`/chat/action messages. Cover unknown fields, missing required field, nullable timestamps, ISO durations, malformed JSON, and no dynamic execution.

- [ ] **Step 4: Implement minimal models/parser**

Model only fields required for listing, participation, status/timing, entrants, chat, actions, reconnect URLs, and user identity. Preserve unknown message types as ignored diagnostics, not fatal state mutation.

- [ ] **Step 5: Define state/action transitions**

Pure state machine maps open/invitational/pending/in-progress/finished/canceled and entrant invited/requested/joined/ready/done/DNF/DQ. Duplicate/reordered WebSocket snapshots are idempotent; impossible regressions request REST resync.

- [ ] **Step 6: Document endpoints/messages from Z1RR server contracts**

Link exact Z1RR Raceroom source paths/tests and official OAuth standard references. Do not cite/copy the legacy provider.

- [ ] **Step 7: Run tests and commit**

```powershell
dotnet test tests\LiveSplit.Racetime.Z1RR.Core.Tests -c Release
git add src tests docs\protocol-contract.md
git commit -m "feat: define Z1RR racetime.gg protocol contracts"
```

## Task 4: Implement S256 PKCE and loopback callback

**Files:**
- Create: `src/LiveSplit.Racetime.Z1RR.Core/Auth/PkceRequest.cs`
- Create: `src/LiveSplit.Racetime.Z1RR.Core/Auth/OAuthClient.cs`
- Create: `src/LiveSplit.Racetime.Z1RR.Core/Auth/OAuthTokens.cs`
- Create: `src/LiveSplit.Racetime.Z1RR/Auth/LoopbackCallbackListener.cs`
- Create: core/Windows auth tests

**Interface — consumes from Raceroom:** the server-owned sanitized fixtures and endpoints `GET /o/authorize`, `POST /o/token`, `POST /o/revoke_token`, and authenticated `GET /o/userinfo`; redirect exactly `http://127.0.0.1:4888/`; scopes exactly `read chat_message race_action`.

**Interface — produces for Raceroom qualification:** authorize query, token/refresh/revoke form bodies, loopback callback cases, and redacted success/error transcripts that the server contract suite replays. The component sends no client secret or `create_race` scope and does not infer alternate OAuth paths.

- [ ] **Step 1: Write failing PKCE vector tests**

Verify SHA-256 of ASCII verifier, base64url without `=`, challenge method exactly `S256`, verifier length/charset/entropy, fresh verifier/state per request, exact state comparison, and verifier retained from authorize through exchange. Include the RFC 7636 known vector.

- [ ] **Step 2: Write failing authorize/token tests**

Authorize query includes response type, client ID, exact redirect, scopes exactly `read chat_message race_action`, state/challenge/S256. `create_race` is deliberately excluded because this component joins and controls an existing race; adding creation later requires a separate approved requirement, threat review, UI, and tests. Token exchange includes code, grant type, client ID, exact redirect, same verifier, and **no** client secret/Authorization Basic. Cover exact-scope rejection, wrong state, missing code, denial, timeout, non-JSON, error body redaction, replay, refresh, revoke.

- [ ] **Step 3: Implement PKCE/OAuth core**

Use `RandomNumberGenerator`, `SHA256`, constant-time state comparison, `HttpClient` with bounded timeout, form encoding, one exchange attempt, and token model with expiry skew. No verifier/token appears in `ToString`, exception, or log.

- [ ] **Step 4: Write failing loopback listener tests**

Bind only `IPAddress.Loopback:4888` via `TcpListener`; accept one bounded HTTP GET to `/`; reject remote/non-GET/wrong path/oversized header/duplicate query; send a minimal success/error HTML response; stop on timeout/cancel. Occupied port returns a clear error and never selects an unregistered fallback.

- [ ] **Step 5: Implement the listener**

Parse only the request line/headers needed, cap bytes/time, close listener after one accepted callback, and pass query values to OAuth state validation. Do not use a wildcard `HttpListener` prefix or require URL ACL/admin rights.

- [ ] **Step 6: Run adversarial auth tests**

Expected: all PASS, including wrong verifier/state, replay, occupied port, browser cancel/denial, callback timeout, refresh/revoke without secret.

- [ ] **Step 7: Commit**

```powershell
git add src tests
git commit -m "feat: authenticate LiveSplit with S256 PKCE"
```

## Task 5: Store refresh credentials safely

**Files:**
- Create: `src/LiveSplit.Racetime.Z1RR.Core/Auth/ITokenStore.cs`
- Create: `src/LiveSplit.Racetime.Z1RR/Auth/WindowsCredentialTokenStore.cs`
- Create: `src/LiveSplit.Racetime.Z1RR.Core/Auth/InMemoryTokenStore.cs`
- Create: Windows credential tests

- [ ] **Step 1: Write failing token-store contract tests**

Store/read/overwrite/delete/absent/corrupt/oversize/error. Target name is exactly `Z1RR Raceroom/LiveSplit/OAuth/<client-id-hash>` and cannot collide with stock provider. Persist refresh token and minimum expiry/account metadata; access token may remain memory-only. `ToString`/logs expose no token.

- [ ] **Step 2: Implement interface/in-memory store**

Core logic depends only on `ITokenStore`; tests do not require Windows Credential Manager.

- [ ] **Step 3: Implement Windows Credential Manager wrapper**

Use documented `CredWriteW`, `CredReadW`, `CredDeleteW`, `CredFree` P/Invoke with generic credential/persistence appropriate to current Windows user. Marshal/free unmanaged memory in `finally`; zero managed byte buffers where practical.

- [ ] **Step 4: Run Windows tests under a unique test target and clean up**

Expected: PASS and test credential is deleted even on failure.

- [ ] **Step 5: Commit**

```powershell
git add src tests
git commit -m "feat: protect LiveSplit racetime.gg refresh tokens"
```

## Task 6: Implement REST and WebSocket clients

**Files:**
- Create: `src/LiveSplit.Racetime.Z1RR.Core/Protocol/RacetimeRestClient.cs`
- Create: `src/LiveSplit.Racetime.Z1RR.Core/Protocol/RacetimeWebSocketClient.cs`
- Create: `src/LiveSplit.Racetime.Z1RR.Core/Protocol/RaceSession.cs`
- Create: `tests/LiveSplit.Racetime.Z1RR.ContractTests/FakeRacetimeServer.cs`
- Create: protocol/contract tests

- [ ] **Step 1: Write failing REST tests**

Cover category/current race list, race detail, userinfo, join/leave/ready/unready/done/forfeit/split/chat endpoints/scopes/methods, bearer refresh-and-retry once on 401, 429 backoff signal, timeout/cancel, relative URL resolution, wrong-origin returned URLs, generic external errors, and idempotency rules (never blindly replay non-idempotent action after uncertain timeout).

- [ ] **Step 2: Write failing WebSocket tests**

Connect WSS endpoint from race data, authenticate as required by server contract, send `getrace`, parse snapshot/chat/action, ping/close, bounded exponential reconnect+jitter, REST resync after reconnect, cancellation/disposal, and no reconnect after logout/race finish. Wrong-origin socket is rejected.

- [ ] **Step 3: Implement REST client**

Inject `HttpMessageHandler`, clock, delay, token provider, logger interface. Require TLS production origin, bounded sizes/timeouts, sanitized exception categories, and serialized action gate to prevent double clicks.

- [ ] **Step 4: Implement WebSocket client**

Inject a socket factory for tests. Maintain one receive loop, cancellation token source, max message size, fragment reassembly, heartbeat, reconnect policy, and safe state callback marshaled by the adapter.

- [ ] **Step 5: Implement `RaceSession` coordinator**

Own current reference/state, REST actions, WebSocket subscription, refresh/resync, and event stream. Duplicate done/split callbacks are idempotently suppressed locally while server remains authority.

- [ ] **Step 6: Run mock-server contract suite**

Expected: PASS for normal lifecycle plus network loss, message reorder/duplication, token expiry, server restart, provider wrong-origin, and cancellation.

- [ ] **Step 7: Commit**

```powershell
git add src tests
git commit -m "feat: implement Z1RR racetime.gg protocol client"
```

## Task 7: Implement the side-by-side LiveSplit provider adapter

**Files:**
- Create: `src/LiveSplit.Racetime.Z1RR/Z1rrRaceProviderFactory.cs`
- Create: `src/LiveSplit.Racetime.Z1RR/Z1rrRaceProviderApi.cs`
- Create: `src/LiveSplit.Racetime.Z1RR/Z1rrRaceProviderSettings.cs`
- Create: `src/LiveSplit.Racetime.Z1RR/Z1rrRaceInfo.cs`
- Create: `src/LiveSplit.Racetime.Z1RR/ProviderIdentity.cs`
- Create: adapter tests

- [ ] **Step 1: Inspect interfaces from the pinned official MIT reference**

Use reflection/official LiveSplit source at the recorded release commit to record required members in `docs/protocol-contract.md`. Do not use legacy provider code as implementation guidance.

- [ ] **Step 2: Write failing adapter identity tests**

Assert assembly `LiveSplit.Racetime.Z1RR`, provider display `Z1RR Raceroom`, settings XML name `Z1RR.Racetime.Provider`, website `https://raceroom.z1rracing.com`, distinct credential target/update URL, and no collision when a fake stock provider is loaded.

- [ ] **Step 3: Write failing race-list/info tests**

Map core race model to `IRaceInfo` fields/state/start/entrants/streams/game/category/goal and participant lookup. Refresh callback fires once on UI context and provider failure retains last good list plus visible error.

- [ ] **Step 4: Implement factory/settings/API/info**

Implement only official interface members. Settings persist enabled state and safe UI preferences; never token/client secret. `Create` wires model/settings but does no blocking network work on UI thread.

- [ ] **Step 5: Run adapter tests against pinned LiveSplit binaries**

Expected: PASS and plugin loads through reflection without type/assembly resolution error.

- [ ] **Step 6: Commit**

```powershell
git add src tests docs\protocol-contract.md
git commit -m "feat: integrate Z1RR racetime.gg with LiveSplit"
```

## Task 8: Connect race lifecycle to the timer and UI

**Files:**
- Create: `src/LiveSplit.Racetime.Z1RR/UI/LoginController.cs`
- Create: `src/LiveSplit.Racetime.Z1RR/UI/RaceWindow.cs`
- Create: `src/LiveSplit.Racetime.Z1RR/UI/RaceWindow.Designer.cs`
- Create: `src/LiveSplit.Racetime.Z1RR/Timer/RaceTimerController.cs`
- Create: UI/timer tests

- [ ] **Step 1: Write failing login UI/controller tests**

Login opens system browser after listener binds, displays no tokens/code, handles denial/timeout/occupied port, supports logout/revoke/credential deletion, and refreshes username/races. All control updates marshal to UI thread.

- [ ] **Step 2: Write failing timer action tests**

Joining selects race; ready does not start timer early; authoritative race transition to in-progress starts/resets exactly once according to reviewed policy; server split triggers configured split behavior; done stops timer then posts action with bounded recovery; forfeit does not mark success; reconnect/resync does not double-start/split/finish. Define explicit handling if local timer action fails after server accepted.

- [ ] **Step 3: Implement controller/UI**

Race window shows provider/host, account, room/goal/status, entrants, chat, actions, and reconnect state. Disable actions while pending and according to server state. Never make closing the window abandon a race without confirmation.

- [ ] **Step 4: Implement timer coordination**

Depend on `ITimerModel` through a small adapter. Record last applied authoritative race version/event identity in memory to suppress duplicates. The server is race authority; the local timer remains user-visible timing state.

- [ ] **Step 5: Run UI/timer tests**

Expected: PASS including reconnect/reordered snapshot and timer-model exception.

- [ ] **Step 6: Manual local smoke in pinned LiveSplit**

Install debug DLL in a disposable LiveSplit copy, keep stock provider installed, open both providers, exercise fixture login/race, and verify menu/settings/credentials do not collide.

- [ ] **Step 7: Commit**

```powershell
git add src tests
git commit -m "feat: control Z1RR races from LiveSplit"
```

## Task 9: Create reproducible signed release artifacts

**Files:**
- Create: `build/Package.ps1`
- Create: `build/Verify-Reproducible.ps1`
- Create: `release/update.z1rr-racetime.xml`
- Create: `docs/install.md`
- Create: `docs/release.md`
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`
- Create: `.github/dependabot.yml`
- Create: release tests

- [ ] **Step 1: Write failing package/update tests**

Package contains only required DLL/PDB/license/notices/install metadata; no token, reference ZIP, absolute path, secret, debug config, or legacy provider file. Update XML has unique component name, HTTPS immutable version URL, exact version/size/SHA, and no stock-feed collision.

- [ ] **Step 2: Implement deterministic packaging**

Normalize timestamps/order, build twice in clean paths, compare DLL/package hashes after excluding signed manifest timestamp if necessary, create CycloneDX SBOM and `SHA256SUMS`, then sign checksum manifest with minisign protected environment secret. Record public verification key in repository/docs.

- [ ] **Step 3: Add CI**

Windows runner downloads/verifies LiveSplit asset, locked restore, build, all tests, clean-room check, secret/dependency scan, side-by-side load smoke, package, SBOM, reproducibility comparison. Pin action SHAs and use read-only permissions.

- [ ] **Step 4: Add protected release workflow**

Manual/signed tag plus `production` environment approval produces GitHub release artifacts/update XML/signed checksums. At G0 run package dry-run and upload private CI artifact only; public release job additionally requires `PLAN_B_ACTIVATED=true` protected variable and registered public client ID.

- [ ] **Step 5: Write install/rollback docs**

Back up LiveSplit, copy DLL/dependencies to `Components`, enable distinct provider, verify checksum/signature, authorize, and remove/restore on rollback. Stock provider remains installed and its credentials/settings untouched.

- [ ] **Step 6: Run two clean builds and verification**

```powershell
pwsh build\Verify-Reproducible.ps1 -Version 0.1.0-rc.1
pwsh build\Verify-CleanRoom.ps1
```

Expected: reproducible result or a documented deterministic-signing boundary; clean-room PASS.

- [ ] **Step 7: Commit**

```powershell
git add build release docs .github tests
git commit -m "build: package and verify Z1RR LiveSplit releases"
```

## Task 10: Qualify the G0 release candidate and stop before publication

**Files:**
- Create: `docs/evidence/<execution-date>-livesplit-provider-rc.md`

- [ ] **Step 1: Run all automated gates**

```powershell
dotnet restore --locked-mode
dotnet build -c Release --no-restore
dotnet test -c Release --no-build
pwsh build\Verify-CleanRoom.ps1
pwsh build\Verify-Reproducible.ps1 -Version 0.1.0-rc.1
```

Expected: PASS.

- [ ] **Step 2: Run adversarial OAuth/protocol list explicitly**

Record S256 vector, wrong verifier/state, replay, occupied port, denial/timeout, refresh/revoke, wrong-origin REST/WSS, token expiry, reconnect/reorder/duplicates, timer exceptions, and log canary results.

- [ ] **Step 3: Run side-by-side disposable LiveSplit smoke**

Expected: current stock provider and Z1RR provider both load; unique menu/settings/credential/update identities; no production OAuth/site dependency.

- [ ] **Step 4: Request code and provenance review**

Use @superpowers:requesting-code-review against FR-LS-001–004 and LS-001–007. Include a reviewer specifically checking the clean-room/license boundary.

- [ ] **Step 5: Record evidence and tag private RC only**

Commit evidence; an internal unsigned/signed test package may remain as protected CI artifact. Do not create a public release/update feed.

**G0 stop line:** No production OAuth client, public DLL/release, update XML publication, or user installation instruction announcement. LS-008 executes late in G2 against fresh restricted production only after the production certificate is trusted normally; no staging-root override or bypass is permitted.
