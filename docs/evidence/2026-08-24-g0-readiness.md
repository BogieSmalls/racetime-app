# G0 contingency readiness evidence — 2026-08-24

## Result

**HOLD.** The implementation is materially complete at the source level, but G0 is not accepted. Mandatory container/service/browser qualification and the independently controlled second source-archive copy are still outstanding. No requirement or artifact is marked verified solely because its files exist.

No OCI resource, DNS record, production OAuth application, scheduler destination, public LiveSplit release, or `z1rr-production` branch was created or changed.

## Release identities reviewed in this run

| Component | Commit | State |
| --- | --- | --- |
| RaceTime | `0299306` | local G0 implementation branch; generated source-custody metadata intentionally uncommitted pending second custody copy |
| Restream | `8e3dcb15` | clean reviewed worktree |
| TTPBot | `db05a98` | clean reviewed worktree |
| LiveSplit | `0489b4f` | clean reviewed, reproducible, signed private G0 RC |

The release-identity collector returned `RELEASE_IDENTITIES=FAIL code=ReleaseIdentityError`, as designed, because the RaceTime source-custody metadata cannot be accepted or committed before the second archive copy is verified.

## Evidence that passed

### Source preservation implementation

- 32 source-preservation, complete-schema, restore, remote-boundary, drift-comparator, and workflow-contract tests passed.
- Independent re-review approved the implementation with no findings apart from the intentionally outstanding external custody step.
- The source archive restored an empty repository to upstream `master` at exact commit `4dbe61fb06d2a132f2e1212e34ac2ae3a6d18069`.
- Candidate source bundle: SHA-256 `f5d57276f281a7ed80c322aab8bf874df95d03366649329daf3e74b42644cb1e`, 1,859,653 bytes.
- Candidate wiki bundle: SHA-256 `d462e141ad5e772561251098e3a93110d56a5519bbeaedd40375b35dfee668b4`, 545,227 bytes.
- The archive files remain outside Git. `docs/upstream/UPSTREAM_BASELINE.json` and `docs/upstream/SHA256SUMS` remain unaccepted until custody is complete.

### RaceTime application and platform

- Django service-free suite: 301 passed, 12 skipped service-dependent cases.
- Operations tooling: 30 passed, including traceability, evidence-schema, release-identity, runbook, and qualification-state tests.
- Integration contracts: 8 passed; the substantive Chromium lifecycle test correctly skipped because no integration stack was running.
- Platform contract suite: 108 passed. The official Caddy 2.11.4 binary matched its pinned SHA-512 and all 8 adapted-config contracts passed.
- Terraform 1.12.2 matched pinned SHA-256 `0a1565ace9da37c2778868c2e97452d8fc25e40e530bafbbab97231e69b0a201`; `fmt`, offline initialization, and `validate` passed against OCI provider 8.27.0. No plan was applied.
- `npm audit --omit=dev` reported no production findings.
- The isolated integration topology and fixture-only origin/PKCE contracts passed static validation.

### Restream and TTPBot

- Restream typecheck, lint, production build, provider Playwright suite, and dependency audit passed; Vitest reported 3,885 passed and one intentionally disabled opt-in benchmark.
- Restream tests cover both `racetime.gg/z1rr` and the local self-hosted provider contract from the same build.
- TTPBot reported 67 passed; package validation and compile checks passed.
- TTPBot tests cover both provider origins, destination-bound state, URL derivation, migration, preflight, and one-scheduler safeguards without changing a production destination.

### LiveSplit private G0 RC

- Independent review approved the final UI/timer/socket lifecycle fix with no findings.
- Release build completed with zero warnings and zero errors; 165 tests passed (7 contract, 45 Windows/provider, 113 core/release).
- Clean-room, Gitleaks 8.30.1, five-project NuGet vulnerability, and stock/Z1RR side-by-side gates passed.
- Two independent clean builds and packages matched byte for byte for `0.1.0-rc.1`.
- Non-production Minisign public key ID: `54F9CD24CF12467F`.
- Signed package SHA-256: `002ffdaed908131e6e7a2b861ceffeda9798809d175ea8223e15acb76c16e643`.
- `SHA256SUMS` SHA-256: `de503b08976b91d25315ba3642b43e0ccd05b62f6aeb8b01927a34cc08f091b9`.
- `SHA256SUMS.minisig` SHA-256: `00b340bd3cadd30c4182c87be05fc9cbe6277144ff64e28a144fc0aebf3f25f1`.
- Signature verification passed. The one-time G0 secret-key directory was then removed and verified absent. Nothing was published.

### Source-control boundary

- GitHub default branch remains upstream-only `master` at `4dbe61fb06d2a132f2e1212e34ac2ae3a6d18069`.
- Administrators are subject to pull-request, linear-history, and conversation-resolution rules; force-push and deletion are disabled.
- A real direct-push attempt was rejected with `GH006`, and the remote SHA remained unchanged.
- Safe protection export: [2026-08-24-master-protection.json](2026-08-24-master-protection.json).
- No G1 `z1rr-production` rule or branch was applied.

## Open G0 blockers

1. **Second archive custody copy.** An approved independently controlled encrypted destination has not been supplied. Upload/copy, re-read, and SHA-256 comparison are still required before accepting SRC-001–006 or committing the generated public archive metadata.
2. **Container and service-backed qualification.** This workstation has no Docker/Podman engine and no installed WSL distribution. The MariaDB/Redis CI suite, both `linux/arm64` and `linux/amd64` image build/smoke/scan/SBOM jobs, production Compose behavior tests, and backup/restore container rehearsals remain mandatory.
3. **Substantive browser integration.** The isolated stack could not start without a container engine, so the two-entrant Chromium race lifecycle remains unexecuted.
4. **G0 traceability.** `validate-traceability.py --gate G0` correctly returns `TRACEABILITY=FAIL gate=G0 code=TraceabilityError` while due rows remain `Planned`. The matrix must not be advanced until the blockers above pass and dated evidence exists.

## Next safe actions

- Copy and re-verify both source bundles at the approved independent custody destination.
- Run the existing container and integration workflows on a clean Docker-capable worker without publishing images or changing production infrastructure.
- Rerun the repository release-identity collector, complete the checklist, attach mandatory evidence, advance only supported G0 traceability rows, and request the final cross-repository review.
