# Z1RR RaceTime Source Preservation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve a verifiable, independently restorable copy of the upstream Racetime application, named refs, tags, wiki state, fork relationship, and restoration instructions.

**Architecture:** A PowerShell tool creates archives from fresh bare mirrors rather than the working repository, writes a machine-readable baseline and SHA-256 manifest, and proves restoration into an empty directory. A separate scheduled workflow reports upstream ref drift without merging or deploying it.

**Tech Stack:** Git, PowerShell 7, Python `unittest`, GitHub CLI/Actions, SHA-256

---

## Control documents

**Spec:** [Plan-B RaceTime architecture](../specs/2026-08-12-plan-b-racetime-architecture-design.md)
**Requirements and gates:** [Requirements and decision record](../../racetime-z1rr/requirements-and-decisions.md)
**Artifact register:** [Launch artifact register](../../racetime-z1rr/artifact-register.md)
**Master plan:** [Contingency launch master plan](2026-08-22-z1rr-racetime-launch-master.md)
**Requirements owned:** NFR-OSS-001 plus the source/branch controls in architecture §6.

## Global Constraints

- G0 permits only local, non-public readiness work. OCI apply, DNS, production OAuth/apps, scheduler changes, publication, and cutover require their recorded G1–G3 gates.
- Preserve both outcome lanes: `racetime.gg/z1rr` and self-hosted `racetime.z1rracing.com/z1rr`. Do not alter ordinary `racetime.gg/z1r` pickup racing.
- RaceTime application work targets Django 5.2/Python 3.12 and produces same-commit immutable linux/arm64 and linux/amd64 images; A1 production runs ARM64 and the paid disaster-recovery fallback runs amd64. Provider work must preserve its plan's declared runtime.
- Production origins are one validated HTTPS origin with no path/query/userinfo; every REST/WSS/link derives from it and historical references remain provider-qualified.
- Discord is the sole public self-hosted login. Never persist Discord access/refresh tokens or grant category owners Django staff, host, database, secret, backup, or OCI access.
- Preserve GPL-3.0/upstream attribution and corresponding source for every deployed RaceTime build; LiveSplit work stays clean-room and copies no unlicensed legacy-provider code.

## File map

- Create `scripts/source/preserve-upstream.ps1`: clone/fetch bare source/wiki mirrors, create bundles, calculate manifest, and emit baseline JSON.
- Create `scripts/source/verify-upstream-archive.ps1`: verify hashes/bundles and restore the recorded commit into a caller-supplied empty directory.
- Create `scripts/source/check-remotes.ps1`: validate `origin`, `upstream`, and the disabled upstream push URL.
- Create `tests/source/test_source_scripts.py`: hermetic temporary Git repositories exercising success, tampering, missing wiki, and remote-guard cases.
- Create `docs/upstream/UPSTREAM_BASELINE.schema.json`: schema for committed baseline metadata.
- Create `docs/upstream/UPSTREAM_BASELINE.json`: generated public source metadata without workstation paths.
- Create `docs/upstream/SHA256SUMS`: generated archive hashes and sizes.
- Create `docs/upstream/RESTORE.md`: storage, verification, restore, fork recreation, and quarterly rehearsal procedure.
- Create `.github/workflows/upstream-drift.yml`: report changed upstream commit/refs; never merge.
- Modify `.gitignore`: ignore `artifacts/source/` and preservation scratch directories.

## Task 1: Lock the metadata contract

**Files:**
- Create: `docs/upstream/UPSTREAM_BASELINE.schema.json`
- Create: `tests/source/test_source_scripts.py`

- [ ] **Step 1: Write the failing baseline-schema test**

```python
def test_baseline_schema_requires_restore_fields(self):
    baseline = json.loads((ROOT / "docs/upstream/UPSTREAM_BASELINE.json").read_text())
    required = {
        "captured_at_utc", "upstream_url", "fork_url", "default_branch",
        "upstream_head", "branches", "tags", "source_bundle", "wiki",
    }
    self.assertEqual(set(baseline).intersection(required), required)
    self.assertRegex(baseline["upstream_head"], r"^[0-9a-f]{40}$")
    self.assertRegex(baseline["default_branch"], r"^[A-Za-z0-9._/-]+$")
    self.assertEqual(baseline["branches"][baseline["default_branch"]], baseline["upstream_head"])
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
.\venv\Scripts\python.exe -m unittest tests.source.test_source_scripts.SourceMetadataTests.test_baseline_schema_requires_restore_fields -v
```

Expected: FAIL because the metadata files do not exist.

- [ ] **Step 3: Add the JSON schema**

Define this complete top-level shape:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["captured_at_utc", "upstream_url", "fork_url", "default_branch", "upstream_head", "branches", "tags", "source_bundle", "wiki"],
  "properties": {
    "captured_at_utc": {"type": "string", "format": "date-time"},
    "upstream_url": {"const": "https://github.com/racetimeGG/racetime-app.git"},
    "fork_url": {"const": "https://github.com/BogieSmalls/racetime-app.git"},
    "upstream_head": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
    "default_branch": {"type": "string", "pattern": "^[A-Za-z0-9._/-]+$"},
    "branches": {"type": "object", "additionalProperties": {"type": "string", "pattern": "^[0-9a-f]{40}$"}},
    "tags": {"type": "object", "additionalProperties": {"type": "string", "pattern": "^[0-9a-f]{40}$"}},
    "source_bundle": {"$ref": "#/$defs/archive"},
    "wiki": {
      "oneOf": [
        {"type": "object", "required": ["status"], "properties": {"status": {"const": "absent"}}, "additionalProperties": false},
        {"allOf": [{"$ref": "#/$defs/archive"}, {"type": "object", "properties": {"status": {"const": "archived"}}, "required": ["status"]}]}
      ]
    }
  },
  "$defs": {
    "archive": {
      "type": "object",
      "required": ["file", "sha256", "bytes"],
      "properties": {
        "file": {"type": "string"},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "bytes": {"type": "integer", "minimum": 1}
      }
    }
  }
}
```

- [ ] **Step 4: Add a generated-fixture baseline for the test**

Use the current verified upstream commit in the first generated file; do not hand-maintain branch/tag values. The preservation script will replace the fixture.

- [ ] **Step 5: Run the metadata test**

Expected: PASS.

- [ ] **Step 6: Commit the contract**

```powershell
git add docs\upstream tests\source
git commit -m "test: define upstream preservation metadata"
```

## Task 2: Guard source remotes

**Files:**
- Create: `scripts/source/check-remotes.ps1`
- Modify: `tests/source/test_source_scripts.py`

- [ ] **Step 1: Write failing remote-guard tests**

Create temporary bare remotes covering: correct URLs/default branches with upstream push URL `DISABLED`; swapped origin/upstream; an HTTPS upstream push URL; missing upstream; upstream default ref whose commit differs from recorded `upstream_head`; and an origin default branch different from the gate-specific expectation. The script must exit zero only for the correct case.

- [ ] **Step 2: Run tests and observe failure**

```powershell
.\venv\Scripts\python.exe -m unittest tests.source.test_source_scripts.RemoteGuardTests -v
```

Expected: FAIL because the script is absent.

- [ ] **Step 3: Implement the remote guard**

The script accepts `-Repository`, `-MetadataPath`, and mandatory `-ExpectedForkDefaultBranch`. It reads:

```powershell
git -C $Repository remote get-url origin
git -C $Repository remote get-url upstream
git -C $Repository remote get-url --push upstream
git -C $Repository ls-remote --symref upstream HEAD
git -C $Repository ls-remote --symref origin HEAD
```

It requires the exact URLs in the schema, requires upstream push URL to equal `DISABLED`, parses each remote's advertised symbolic `HEAD`, and resolves the advertised commits. Upstream must advertise `refs/heads/<baseline.default_branch>` at `baseline.upstream_head`; origin must advertise `refs/heads/<ExpectedForkDefaultBranch>`. It writes only a pass/fail message, never credential-bearing URL details. Hermetic tests inject local bare URLs only through an explicit fixture switch.

- [ ] **Step 4: Configure the local checkout's upstream push guard**

```powershell
git remote set-url --push upstream DISABLED
pwsh scripts\source\check-remotes.ps1 -Repository . -MetadataPath docs\upstream\UPSTREAM_BASELINE.json -ExpectedForkDefaultBranch master
```

Expected: `PASS: origin/upstream source boundary is configured.`

- [ ] **Step 5: Run all remote tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add scripts\source\check-remotes.ps1 tests\source\test_source_scripts.py
git commit -m "chore: guard racetime upstream remotes"
```

## Task 3: Implement deterministic archive creation

**Files:**
- Create: `scripts/source/preserve-upstream.ps1`
- Modify: `tests/source/test_source_scripts.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing archive tests**

The hermetic fixture creates a bare upstream with two branches and two tags plus an optional bare wiki. Assert that the command:

- writes one source bundle and optional wiki bundle;
- records the default-branch name and proves `branches[default_branch] == upstream_head` while listing both branches/tags;
- records lowercase SHA-256 and byte size;
- writes sorted `SHA256SUMS`;
- leaves no partial final archive if Git fails; and
- records `{ "status": "absent" }` when `git ls-remote` reports no wiki.

- [ ] **Step 2: Run archive tests and observe failure**

```powershell
.\venv\Scripts\python.exe -m unittest tests.source.test_source_scripts.ArchiveCreationTests -v
```

Expected: FAIL because `preserve-upstream.ps1` is absent.

- [ ] **Step 3: Implement parameters and safety checks**

Use this public interface:

```powershell
param(
  [Parameter(Mandatory)][string]$UpstreamUrl,
  [Parameter(Mandatory)][string]$ForkUrl,
  [Parameter(Mandatory)][string]$OutputDirectory,
  [string]$WikiUrl,
  [string]$MetadataDirectory = "docs/upstream",
  [switch]$AllowNonGitHubFixture
)
```

Resolve both output paths, reject a repository root or `.git` as output, create a unique scratch directory under the output parent, and remove only that verified scratch directory in `finally`.

- [ ] **Step 4: Implement the source mirror and bundle**

Run a fresh `git clone --mirror`, `git fsck --full`, and `git bundle create <partial> --all`; then `git bundle verify`. Move the partial bundle to final only after verification. Use UTC filename `racetime-app-YYYYMMDDTHHMMSSZ.bundle`.

- [ ] **Step 5: Implement metadata generation**

Read refs with `git for-each-ref --format="%(refname:short) %(objectname)" refs/heads refs/tags`, resolve symbolic `HEAD` to a short `default_branch`, resolve that branch to `upstream_head`, and fail unless the branch dictionary contains the same commit at that key. Hash final files with `Get-FileHash -Algorithm SHA256`, and serialize JSON with stable key ordering and UTF-8 without secrets or absolute workstation paths.

- [ ] **Step 6: Implement wiki handling**

Probe with `git ls-remote`. If present, mirror/bundle/verify exactly as source. If absent, write the explicit absence object. Network/auth errors are failures, not proof of absence.

- [ ] **Step 7: Ignore local archives**

Add:

```gitignore
/artifacts/source/
/.source-preservation-scratch/
```

- [ ] **Step 8: Run archive tests**

Expected: all cases PASS.

- [ ] **Step 9: Commit**

```powershell
git add .gitignore scripts\source\preserve-upstream.ps1 tests\source\test_source_scripts.py
git commit -m "feat: create verifiable upstream source archives"
```

## Task 4: Implement restore verification

**Files:**
- Create: `scripts/source/verify-upstream-archive.ps1`
- Modify: `tests/source/test_source_scripts.py`

- [ ] **Step 1: Write failing restore/tamper tests**

Cover valid archive, one-byte tamper, wrong manifest hash, non-empty restore target, missing recorded branch, missing/wrong `default_branch`, a reachable but non-default `upstream_head`, and a default branch whose tip differs from `upstream_head`.

- [ ] **Step 2: Run tests and observe failure**

Expected: FAIL because verification is absent.

- [ ] **Step 3: Implement verification**

Use this interface:

```powershell
param(
  [Parameter(Mandatory)][string]$ArchiveDirectory,
  [Parameter(Mandatory)][string]$MetadataDirectory,
  [Parameter(Mandatory)][string]$RestoreDirectory
)
```

Require a missing or empty restore directory. Verify SHA-256/size first, run `git bundle verify`, clone from bundle, verify every recorded branch/tag object, explicitly checkout `baseline.default_branch`, and require `git symbolic-ref --short HEAD` to equal it and `git rev-parse HEAD` to equal `baseline.upstream_head`; mere reachability is insufficient. Also require `branches[default_branch] == upstream_head`. For wiki `absent`, do nothing; for `archived`, perform the same archive validation in a `wiki` child.

- [ ] **Step 4: Run verification tests**

Expected: valid case PASS; every tamper case exits non-zero before claiming restore.

- [ ] **Step 5: Commit**

```powershell
git add scripts\source\verify-upstream-archive.ps1 tests\source\test_source_scripts.py
git commit -m "test: verify racetime archive restoration"
```

## Task 5: Write restoration and custody instructions

**Files:**
- Create: `docs/upstream/RESTORE.md`
- Modify: `tests/source/test_source_scripts.py`

- [ ] **Step 1: Write a failing documentation-contract test**

Assert the runbook contains exact sections: prerequisites, create, verify, second copy, empty-directory restore, recreate GitHub fork, upstream remote guard, quarterly rehearsal, custody/access, and incident handling.

- [ ] **Step 2: Run and observe failure**

Expected: FAIL because `RESTORE.md` is absent/incomplete.

- [ ] **Step 3: Write the runbook**

Include exact script invocations, explain that bundle files are not committed, require two independently controlled copies (operator-held encrypted storage plus Council-approved off-workstation storage), and prohibit deleting the only verified prior archive before a replacement has passed restoration.

- [ ] **Step 4: Add GitHub fork recreation steps**

Document creating an empty repository, checking out the recorded upstream `default_branch` at the exact `upstream_head`, pushing restored named branches/tags, adding upstream, and reapplying branch protection. For a G0/neutral restore, set the fork default to the recorded upstream default (currently `master`). For a G1+ Plan-B restore, verify the restored protected `z1rr-production` branch and set it default while retaining upstream-only `master`. Run the remote guard with the gate-appropriate expected fork default. Never use `git push --mirror` against a non-empty destination without reviewed destructive authorization.

- [ ] **Step 5: Run documentation tests and link acceptance evidence**

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add docs\upstream\RESTORE.md tests\source\test_source_scripts.py
git commit -m "docs: add racetime source recovery runbook"
```

## Task 6: Add locally testable, non-mutating upstream drift reporting

**Files:**
- Create: `.github/workflows/upstream-drift.yml`
- Create: `scripts/source/compare-upstream-refs.py`
- Create: `tests/source/test_compare_upstream_refs.py`

- [ ] **Step 1: Write failing ref-diff tests**

Input two baseline dictionaries and assert deterministic `added`, `removed`, and `changed` branch/tag output plus changed default HEAD.

- [ ] **Step 2: Run and observe failure**

```powershell
.\venv\Scripts\python.exe -m unittest tests.source.test_compare_upstream_refs -v
```

Expected: FAIL because the comparator is absent.

- [ ] **Step 3: Implement the pure comparator**

The script reads current `UPSTREAM_BASELINE.json` plus a captured-ref JSON argument and emits Markdown. It never runs Git, pushes, edits baseline, merges, or opens a deployment.

- [ ] **Step 4: Add the locally testable, G1-activatable workflow**

Declare both `workflow_dispatch` and a monthly `schedule`, but do not claim either GitHub event can run at G0: GitHub dispatch and schedules require the workflow file on the default branch, while G0 default `master` remains an unmodified upstream mirror. At G0, run the comparator and workflow-contract tests locally against fixtures. After G1 merges the reviewed workflow into newly default `z1rr-production`, manually dispatch it once; the schedule is then active. It checks out read-only, fetches public upstream refs, builds current-ref JSON, runs tests/comparator, uploads a report artifact, and has only `contents: read`; a changed report fails without updating, merging, or deploying.

- [ ] **Step 5: Run tests and a local fixture workflow command**

Expected at G0: comparator and workflow-contract tests PASS locally and a changed fixture exits non-zero with a readable report. Expected at G1: manual dispatch from default `z1rr-production` uploads the artifact and a scheduled-event smoke verifies the default-branch path. No G0 GitHub dispatch is required or possible.

- [ ] **Step 6: Commit**

```powershell
git add .github\workflows\upstream-drift.yml scripts\source\compare-upstream-refs.py tests\source\test_compare_upstream_refs.py
git commit -m "ci: report racetime upstream drift"
```

## Task 7: Create and prove the first real archive

**Files:**
- Generate: `docs/upstream/UPSTREAM_BASELINE.json`
- Generate: `docs/upstream/SHA256SUMS`
- Create: `docs/evidence/<execution-date>-source-preservation.md`
- External: two verified archive copies

- [ ] **Step 1: Run the preservation command against public upstream/fork URLs**

```powershell
pwsh scripts\source\preserve-upstream.ps1 `
  -UpstreamUrl https://github.com/racetimeGG/racetime-app.git `
  -ForkUrl https://github.com/BogieSmalls/racetime-app.git `
  -WikiUrl https://github.com/racetimeGG/racetime-app.wiki.git `
  -OutputDirectory artifacts\source
```

Expected: source bundle verified; wiki either verified or explicitly recorded absent.

- [ ] **Step 2: Restore to a fresh temporary directory**

```powershell
$z1rrRestoreTarget = Join-Path ([System.IO.Path]::GetTempPath()) ("z1rr-racetime-restore-" + [guid]::NewGuid())
pwsh scripts\source\verify-upstream-archive.ps1 -ArchiveDirectory artifacts\source -MetadataDirectory docs\upstream -RestoreDirectory $z1rrRestoreTarget
```

Expected: PASS with exact recorded upstream HEAD and refs.

- [ ] **Step 3: Copy the verified archive set to independently controlled storage**

Use the approved encrypted destination. Re-download/re-read the second copy and compare SHA-256 to committed `SHA256SUMS`; a successful upload/copy alone is insufficient.

- [ ] **Step 4: Record evidence without private paths or credentials**

Record archive filenames/hashes/sizes, upstream commit, ref counts, wiki status, restore result, and custody roles. Do not record bucket secret, local user path, or auth material.

- [ ] **Step 5: Commit generated public metadata/evidence**

```powershell
git add docs\upstream\UPSTREAM_BASELINE.json docs\upstream\SHA256SUMS docs\evidence
git commit -m "docs: record verified racetime upstream archive"
```

## Final verification

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests\source -v
pwsh scripts\source\check-remotes.ps1 -Repository .
git bundle verify (Get-ChildItem artifacts\source\racetime-app-*.bundle | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
git status --short
```

Expected: all tests PASS, remote boundary PASS, bundle verifies, and only intended metadata/evidence changes remain. Use @superpowers:verification-before-completion before marking SRC-001–006 accepted.
