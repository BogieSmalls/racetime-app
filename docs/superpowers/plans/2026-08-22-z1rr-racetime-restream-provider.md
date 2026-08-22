# Z1RR Restream Racetime Provider Abstraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Z1RR.Restream consume Z1RR and pickup Z1R races from independently configured Racetime providers while preserving each race's original provider identity and URL forever.

**Architecture:** Introduce a validated provider/logical-source registry and a single `RaceReference` value carried through REST, UI, drafts, sync, crops, realtime, tracker/broadcast state, and history. Existing SQLite records migrate additively to `racetime-gg:z1r`; every client resolves HTTP/WSS against the reference's provider, never a global current host.

**Tech Stack:** Node 20+, TypeScript, Express, React 18, TanStack Query, better-sqlite3, WebSocket `ws`, Vitest, Playwright

---

## Control documents

**Spec:** [Plan-B RaceTime architecture](../specs/2026-08-12-plan-b-racetime-architecture-design.md)
**Requirements and gates:** [Requirements and decision record](../../racetime-z1rr/requirements-and-decisions.md)
**Artifact register:** [Launch artifact register](../../racetime-z1rr/artifact-register.md)
**Master plan:** [Contingency launch master plan](2026-08-22-z1rr-racetime-launch-master.md)
**Requirements owned:** FR-RESTREAM-001–005 and ADR-003/004, with NFR-TEST-001 verification for this repository.

## Global Constraints

- G0 permits only local, non-public readiness work. OCI apply, DNS, production OAuth/apps, scheduler changes, publication, and cutover require their recorded G1–G3 gates.
- Preserve both outcome lanes: `racetime.gg/z1rr` and self-hosted `racetime.z1rracing.com/z1rr`. Do not alter ordinary `racetime.gg/z1r` pickup racing.
- RaceTime application work targets Django 5.2/Python 3.12 and immutable ARM64 production images; provider work must preserve its plan's declared runtime.
- Production origins are one validated HTTPS origin with no path/query/userinfo; every REST/WSS/link derives from it and historical references remain provider-qualified.
- Discord is the sole public self-hosted login. Never persist Discord access/refresh tokens or grant category owners Django staff, host, database, secret, backup, or OCI access.
- Preserve GPL-3.0/upstream attribution and corresponding source for every deployed RaceTime build; LiveSplit work stays clean-room and copies no unlicensed legacy-provider code.

## Repository and file map

Work in `D:\Projects\Streaming\Z1RR\Z1RR.Restream\.worktrees\racetime-provider`.

- Modify `lib/racetime.js`: validated `baseUrl`, provider-aware error/result URL handling.
- Create `mini/server/race-info/racetime-providers.ts`: environment registry and client lookup.
- Create `mini/server/race-info/race-reference.ts`: canonical `RaceReference`, key, parsing and legacy conversion.
- Modify `mini/server/routes/races.ts`: multi-source current/past/detail/race-info routes and isolated errors.
- Modify `mini/server/race-info/racetime-realtime.ts`: provider-origin-aware WSS resolution/allowlist.
- Modify `mini/server/race-info/race-info.ts`, `broadcast-sync.ts`, `start-sync.ts`: carry the reference.
- Modify `mini/server/db/broadcast-drafts.ts`: additive provider/category/room/URL persistence/migration.
- Modify `mini/server/routes/broadcast-drafts.ts`, `mini/server/crops/missing.ts`, `mini/server/tracker-bridge.ts`, broadcast manager/state paths: propagate references.
- Modify `mini/client/src/lib/api.ts`: source/reference API contracts.
- Modify `mini/client/src/pages/BroadcastForChannel.tsx`: Z1RR-first source sections and reference selection.
- Modify `mini/client/src/components/RaceListItem.tsx`, `RaceDetail.tsx`, `BroadcastDraftReady.tsx`, draft/history pages: visible source/host and canonical links.
- Modify `mini/.env.example`, `mini/README.md`, `docs/internal/platform-configuration.md`: outcome-switch configuration/runbook.
- Add/modify colocated `*.test.ts(x)` plus `mini/e2e/racetime-providers.spec.ts`.

## Configuration contract

Use one JSON environment variable so provider origin and logical-source ordering change atomically:

```json
[
  {
    "sourceId": "z1rr",
    "label": "Z1RR organized racing",
    "providerId": "z1rr-racetime",
    "origin": "https://racetime.z1rracing.com",
    "category": "z1rr"
  },
  {
    "sourceId": "z1r",
    "label": "Z1R pickup racing",
    "providerId": "racetime-gg",
    "origin": "https://racetime.gg",
    "category": "z1r"
  }
]
```

For an approved Racetime.gg category, only the first source's provider/origin changes to `racetime-gg`/`https://racetime.gg`. The build does not change.

## Task 1: Make the low-level Racetime client origin-aware

**Files:**
- Modify: `lib/racetime.js`
- Modify: `mini/server/race-info/racetime-api.test.ts`

- [ ] **Step 1: Write failing client-origin tests**

```typescript
const api = new RacetimeApi({
  providerId: 'z1rr-racetime',
  baseUrl: 'https://racetime.z1rracing.com',
  category: 'z1rr',
});
await api.getRaceDetail('z1rr/example-room');
expect(fetch).toHaveBeenCalledWith(
  'https://racetime.z1rracing.com/z1rr/example-room/data',
  expect.any(Object),
);
```

Also reject path/query/fragment/userinfo origins, non-HTTPS except explicit loopback-test option, wrong-category slugs, encoded path traversal, and unsupported provider ID. Test relative `url`, `data_url`, and WebSocket URLs normalize against the configured origin.

- [ ] **Step 2: Run and verify failure**

```powershell
Set-Location mini
npx vitest run server\race-info\racetime-api.test.ts
```

Expected: FAIL because client hard-codes `https://racetime.gg` and lacks fields.

- [ ] **Step 3: Implement the constructor contract**

```javascript
new RacetimeApi({ providerId, baseUrl, category, allowInsecureLoopback = false })
```

Normalize origin with `new URL`, strip a single trailing slash, require an empty path other than `/`, and retain it as read-only getters. Build all requests with `new URL(path, origin)`, not string concatenation. Errors name the safe provider ID/status, never echo an untrusted response body.

- [ ] **Step 4: Preserve API response canonical URLs**

Sanitizers add a provider-qualified reference derived from configured provider/category and returned race `name`; absolute `url` is `new URL(raw.url, origin).toString()`. Reject a returned absolute URL whose origin differs from the configured provider.

- [ ] **Step 5: Run tests**

Expected: both racetime.gg and self-hosted fixtures PASS; clock correction still passes.

- [ ] **Step 6: Commit**

```powershell
git add lib\racetime.js mini\server\race-info\racetime-api.test.ts
git commit -m "feat: configure racetime provider origins"
```

## Task 2: Define `RaceReference` and provider/source registry

**Files:**
- Create: `mini/server/race-info/race-reference.ts`
- Create: `mini/server/race-info/race-reference.test.ts`
- Create: `mini/server/race-info/racetime-providers.ts`
- Create: `mini/server/race-info/racetime-providers.test.ts`

- [ ] **Step 1: Write failing reference tests**

The immutable shape is:

```typescript
export interface RaceReference {
  providerId: string;
  category: string;
  room: string;
  url: string;
}
```

Test `raceReferenceKey(ref) === 'z1rr-racetime:z1rr/example-room'`, JSON round trip, Unicode/encoded separator rejection, URL origin/category/room consistency, and legacy conversion from `raceSlug='z1r/foo'` plus existing URL. Existing URL wins for provider inference only when it matches an allowlisted configured provider; otherwise legacy defaults to `racetime-gg:z1r` and preserves the stored URL as evidence while marking migration warning.

- [ ] **Step 2: Run and observe failure**

- [ ] **Step 3: Implement the reference module**

Expose:

```typescript
normalizeRaceReference(input, providers): RaceReference
raceReferenceKey(ref): string
raceSlug(ref): string
referenceFromApiRace(race, source): RaceReference
legacyRaceReference({ raceSlug, raceUrl }, providers): RaceReference
```

Never parse provider by substring/regex such as `racetime.gg/`; use `URL.origin` and exact configured origins.

- [ ] **Step 4: Write failing registry tests**

Cover self-hosted and approved outcome JSON, source order, duplicate source/provider conflicts, missing fields, unknown properties, origin validation, duplicate provider ID with different origin, missing required `z1rr`/`z1r`, and default behavior. There is no silent production default: missing `RACETIME_SOURCES_JSON` fails startup outside test/development.

- [ ] **Step 5: Implement registry**

```typescript
export interface RacetimeSource {
  sourceId: 'z1rr' | 'z1r' | string;
  label: string;
  providerId: string;
  origin: string;
  category: string;
}

export class RacetimeProviderRegistry {
  sources(): readonly RacetimeSource[];
  source(id: string): RacetimeSource;
  provider(id: string): { providerId: string; origin: string };
  clientForSource(id: string): RacetimeApi;
  resolve(ref: RaceReference): RacetimeApi;
}
```

Preserve JSON order; require `z1rr` first in production validation.

- [ ] **Step 6: Run tests and commit**

```powershell
npx vitest run server\race-info\race-reference.test.ts server\race-info\racetime-providers.test.ts
git add mini\server\race-info
git commit -m "feat: define provider-qualified race references"
```

## Task 3: Replace the single-provider race routes

**Files:**
- Modify: `mini/server/routes/races.ts`
- Modify: `mini/server/routes/races.test.ts`
- Modify: `mini/client/src/lib/api.ts`
- Modify: `mini/client/src/lib/api.test.ts`

- [ ] **Step 1: Write failing route tests**

Contract:

```json
{
  "sources": [
    {"source": {"sourceId":"z1rr","label":"Z1RR organized racing","providerId":"z1rr-racetime","origin":"https://racetime.z1rracing.com","category":"z1rr"}, "races": [], "error": null},
    {"source": {"sourceId":"z1r","label":"Z1R pickup racing","providerId":"racetime-gg","origin":"https://racetime.gg","category":"z1r"}, "races": [], "error": null}
  ]
}
```

`GET /api/races/current` queries both concurrently with `Promise.allSettled`, returns each source independently, and preserves order. Past/detail/race-info require `sourceId` plus category/room reference fields; unknown provider/source/mismatch is 400. Provider rate limit is 429 only for that result; unexpected external error is a generic 502, not raw body.

- [ ] **Step 2: Run and observe failure**

```powershell
npx vitest run server\routes\races.test.ts client\src\lib\api.test.ts
```

- [ ] **Step 3: Refactor router creation for dependency injection**

Replace module-global `racetime` with `createRacesRouter({ registry, twitchFactory })`. Production index constructs one validated registry. Tests inject clients/failures without mutating global env.

- [ ] **Step 4: Implement source-isolated routes**

Detail route accepts serialized fields or an encoded `raceReferenceKey`; normalize server-side and never accept arbitrary origin from the browser. The registry supplies origin.

- [ ] **Step 5: Update client types/functions**

```typescript
fetchCurrentRaceSources(): Promise<RacetimeSourceResult[]>
fetchPastRaces(sourceId: string, page: number): Promise<RacetimePastRacesPage>
fetchRaceDetail(ref: RaceReference): Promise<RacetimeRace>
```

All returned races include `reference`.

- [ ] **Step 6: Run tests and commit**

```powershell
git add mini\server\routes\races.ts mini\server\routes\races.test.ts mini\client\src\lib
git commit -m "feat: serve independent racetime sources"
```

## Task 4: Migrate draft persistence additively

**Files:**
- Modify: `mini/server/db/broadcast-drafts.ts`
- Modify: `mini/server/db/broadcast-drafts.test.ts`

- [ ] **Step 1: Write failing fresh-schema tests**

Add columns:

```sql
race_provider_id TEXT,
race_category TEXT,
race_room TEXT,
race_url TEXT
```

Draft types expose `raceReference: RaceReference | null`; keep `raceSlug` as a transitional read-only compatibility field in API responses for one release, derived from reference.

- [ ] **Step 2: Write failing legacy migration tests**

Create the exact prior table schema, insert rows for `z1r/droois-shatty` with `raceInfo.raceUrl`, without URL, manual draft, and malformed legacy data. Opening the store must add columns once, backfill valid rows to `racetime-gg/z1r`, preserve exact existing absolute URL, leave manual null, quarantine/log malformed rows without crashing unrelated drafts, and be idempotent on second open.

- [ ] **Step 3: Run and observe failure**

```powershell
npx vitest run server\db\broadcast-drafts.test.ts
```

- [ ] **Step 4: Implement additive migration**

Follow the existing `PRAGMA table_info`/column-add pattern in this file. Perform updates in one transaction and record schema version in `PRAGMA user_version` or the repository's existing migration mechanism. Do not drop/rename `race_slug` in this release.

- [ ] **Step 5: Update normalization/read/write**

Require a complete normalized reference for live/historical drafts; manual drafts are null. Persist canonical URL separately from `race_info_json` so historical links survive later provider config changes.

- [ ] **Step 6: Run DB tests twice against a copied legacy fixture**

Expected: PASS and byte-stable logical contents after second migration/open.

- [ ] **Step 7: Commit**

```powershell
git add mini\server\db\broadcast-drafts.ts mini\server\db\broadcast-drafts.test.ts
git commit -m "feat: persist racetime provider identity in drafts"
```

## Task 5: Propagate references through server workflows

**Files:**
- Modify: `mini/server/race-info/race-info.ts`
- Modify: `mini/server/race-info/broadcast-sync.ts`
- Modify: `mini/server/race-info/start-sync.ts`
- Modify: `mini/server/routes/broadcast-drafts.ts`
- Modify: `mini/server/crops/missing.ts`
- Modify: `mini/server/tracker-bridge.ts`
- Modify: `mini/server/broadcasts/manager.ts`
- Modify: `mini/server/routes/broadcasts.ts`, `mini/server/routes/tracker-recordings.ts`
- Modify: `mini/server/tracker-recording/lifecycle.ts`
- Modify: the colocated manager/route/lifecycle persistence tests named by these paths
- Modify: all colocated tests

- [ ] **Step 1: Add a failing boundary matrix test**

Use a self-hosted reference and assert exact object/key/URL at these boundaries: draft create/update/read; swap resolution; staging; broadcast manager session; start-sync controller; current race-info fetch; crop missing discovery; tracker bridge payload; persisted history; and server restart/hydration.

- [ ] **Step 2: Run targeted tests and observe failures**

```powershell
npx vitest run server\routes\broadcast-drafts.test.ts server\race-info\broadcast-sync.test.ts server\tracker-bridge.test.ts server\db\broadcast-drafts.test.ts
```

- [ ] **Step 3: Add `raceReference` to `BroadcastRaceInfo`**

Normalize once at ingress. Transitional `raceName`/`raceSlug` remain derived display/compatibility fields; no function may choose a provider from them.

- [ ] **Step 4: Replace fetch signatures**

Every `fetchRaceDetail(slug)`/`startForBroadcast(session, slug)` becomes reference-based. Dependency interfaces accept `RaceReference`; resolve clients through registry. Delete module-global `new RacetimeApi({ category: ... })` instances from routes, crops, drafts, and sync.

- [ ] **Step 5: Preserve historical URL at every persistence point**

When hydrating old data, use stored `raceUrl`; when selecting new data, capture API canonical URL. Never run `new URL(currentOrigin + oldSlug)` for history.

- [ ] **Step 6: Run full server tests**

Expected: PASS; `rg "new RacetimeApi|RACETIME_CATEGORY|https://racetime.gg" mini/server lib/racetime.js` finds only registry construction, intentional legacy fixture/default documentation, or exact tests—not production hard-coding.

- [ ] **Step 7: Commit**

```powershell
git add mini\server
git commit -m "refactor: carry race provider identity through restream"
```

## Task 6: Make realtime provider-aware and fail independently

**Files:**
- Modify: `mini/server/race-info/racetime-realtime.ts`
- Modify: `mini/server/race-info/racetime-realtime.test.ts`
- Modify: `mini/server/race-info/broadcast-sync.ts`
- Modify: `mini/server/race-info/broadcast-sync.test.ts`

- [ ] **Step 1: Write failing URL-security tests**

For self-hosted reference, relative `/ws/z1rr/room` becomes `wss://racetime.z1rracing.com/ws/z1rr/room`; HTTP loopback test becomes WS; same-origin absolute WSS passes. A `wss://racetime.gg/...` URL returned by self-hosted provider, credentials, non-WS protocol, category mismatch, and encoded host confusion are rejected.

- [ ] **Step 2: Write failing isolation tests**

Two subscriptions run concurrently. Fail REST/WSS/reconnect for one provider; the other continues receiving snapshots. Timers/backoff/current socket are instance-local and errors identify safe provider ID.

- [ ] **Step 3: Run and observe failure**

- [ ] **Step 4: Pass provider origin/reference into subscription**

Remove `RACETIME_BASE_URL`. Constructor receives `reference` and `providerOrigin`; `toRacetimeWebSocketUrl(raw, origin, ref)` performs exact validation. REST refresh callback is already bound to the correct registry client.

- [ ] **Step 5: Run realtime/sync tests**

Expected: PASS with independent failure behavior and bounded reconnect.

- [ ] **Step 6: Commit**

```powershell
git add mini\server\race-info
git commit -m "fix: isolate racetime realtime providers"
```

## Task 7: Build the Z1RR-first race browser

**Files:**
- Modify: `mini/client/src/pages/BroadcastForChannel.tsx`
- Modify: `mini/client/src/pages/BroadcastForChannel.test.ts`
- Modify: `mini/client/src/components/RaceListItem.tsx`
- Modify: `mini/client/src/components/RaceDetail.tsx`
- Modify: `mini/client/src/components/BroadcastDraftReady.tsx`
- Modify: `mini/client/src/pages/BroadcastDraftEditor.tsx`
- Modify: `mini/client/src/pages/BroadcastDrafts.tsx`
- Modify: associated tests

- [ ] **Step 1: Write failing UI tests**

Assert Z1RR section renders first with label and host badge; Z1R pickup second; each has independent loading/error/empty/refresh; one provider error does not replace the page; selection uses `raceReferenceKey`; switching sources clears incompatible selection; detail/draft/history link uses canonical `reference.url` and shows external host.

- [ ] **Step 2: Run and observe failures**

```powershell
npx vitest run client\src\pages\BroadcastForChannel.test.ts client\src\components\BroadcastDraftReady.test.ts client\src\pages\BroadcastDraftEditor.test.ts
```

- [ ] **Step 3: Replace `selectedSlug` with `selectedRace`**

State type is `RaceReference | null`. TanStack query keys include provider ID/category/room; no cache collision between same room/category on different hosts.

- [ ] **Step 4: Render source sections and independent past browsing**

Keep one screen/tab. Each source gets current list and its own past pagination/filter state. Use neutral labels `RaceTime` rather than `RT.gg`; host badge/link prevents mistaken destination.

- [ ] **Step 5: Update draft/detail components**

Pass/store full reference. Absolute URL helper trusts only server-normalized canonical URL. Do not prepend `https://racetime.gg` to relative URLs in `RaceDetail.tsx`.

- [ ] **Step 6: Run client tests and accessibility smoke**

Expected: PASS; keyboard source/race selection and error announcements work.

- [ ] **Step 7: Commit**

```powershell
git add mini\client
git commit -m "feat: show Z1RR and pickup race sources"
```

## Task 8: Document and test both outcomes

**Files:**
- Modify: `mini/.env.example`
- Modify: `mini/README.md`
- Modify: `docs/internal/platform-configuration.md`
- Modify: `docs/user-guide/operator-guide.md`
- Create: `mini/server/race-info/racetime-outcomes.test.ts`

- [ ] **Step 1: Write failing outcome-fixture test**

One fixture configures `z1rr` on racetime.gg; the other on self-hosted. Assert same logical source/order and different provider/origin only; pickup remains racetime.gg/z1r. Invalid production missing JSON fails startup.

- [ ] **Step 2: Replace `RACETIME_CATEGORY` documentation**

Document `RACETIME_SOURCES_JSON`, exact approved/self-hosted examples, safe JSON quoting for systemd/env, validation command, provider failure behavior, rollback, and legacy migration backup requirement. Update the operator guide's race-selection, history-link, degraded-provider, preflight, cutover, and rollback procedures; documentation tests assert both logical sources and provider-qualified URLs appear there.

- [ ] **Step 3: Add configuration preflight**

Expose `npm run preflight:racetime` that parses registry, prints only source/provider/origin/category (no secrets exist), probes `/data` with timeouts in explicit `--probe` mode, and never mutates a provider.

- [ ] **Step 4: Run both fixture tests/preflight**

Expected: PASS without code rebuild between outcomes.

- [ ] **Step 5: Commit**

```powershell
git add mini\.env.example mini\README.md docs\internal\platform-configuration.md docs\user-guide\operator-guide.md mini\server\race-info
git commit -m "docs: configure restream racetime outcomes"
```

## Task 9: Qualify the Restream release candidate

**Files:**
- Create: `docs/superpowers/evidence/<execution-date>-racetime-provider-rc.md`
- Create: `mini/e2e/racetime-providers.spec.ts`

- [ ] **Step 1: Add Playwright cross-boundary test**

With two fake providers, select self-hosted race, save/reload draft, stage/start simulated broadcast, process WSS update, show missing crop, and open history link. Assert provider-qualified key and original URL at each server fixture. Then fail self-hosted provider and verify pickup source remains usable.

- [ ] **Step 2: Run the complete Mini quality suite**

```powershell
Set-Location mini
npm ci
npm run typecheck
npm run lint
npm test -- --run
npm run build
npx playwright test e2e\racetime-providers.spec.ts
```

Expected: PASS.

- [ ] **Step 3: Run legacy database migration on a copy**

Back up/copy production-like `broadcast-drafts.db`; run migration in an isolated directory; compare row counts, canonical historical URLs, manual drafts, and `PRAGMA integrity_check`. Never test against the live file.

- [ ] **Step 4: Run hard-code audit**

```powershell
rg -n "https://racetime\.gg|RACETIME_CATEGORY|raceSlug" lib mini\server mini\client\src
```

Expected: each match is a legacy compatibility field, fixture, approved default documentation, or provider registry—not host selection/reconstruction.

- [ ] **Step 5: Request review and record evidence**

Use @superpowers:requesting-code-review against FR-RESTREAM-001–005 and RST-001–008.

- [ ] **Step 6: Commit evidence**

```powershell
git add docs\superpowers\evidence mini\e2e
git commit -m "test: qualify restream racetime providers"
```

No production `RACETIME_SOURCES_JSON` change occurs in this plan. Outcome-specific configuration is an operations/cutover action.
