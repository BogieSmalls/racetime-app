# G0 contingency readiness evidence — 2026-08-24

## Result

**HOLD.** Task 6 qualifies the source-level contingency package and closes the native-amd64 parser/browser integration gap, but it does not complete every mandatory G0 gate. In particular, there is no same-commit `linux/amd64` plus `linux/arm64` image build/smoke/Trivy/SBOM packet, the dedicated MariaDB/Redis CI job has not run successfully, and the release-identity collector has no complete identity configuration. No partial result below is promoted to a full G0 pass.

No production credential was used. During Task 6, no OCI, DNS, OAuth, scheduler, registry, public-release, or G1 state was created or changed, and the NAS was not contacted.

## Exact repositories and candidate boundary

| Component | Exact commit qualified | Task 6 state |
| --- | --- | --- |
| RaceTime runtime/parser candidate | `81ff60187ce1b7f310393636f9218fe8ea11e866` | native-amd64 NAS integration accepted; local source/application/platform/operations blocks rerun |
| RaceTime secret-scan policy | `ee6b49cfc508e7984245318bbea440e781d5a701` | narrow rule/path/commit/value-shape exception and negative controls committed after the runtime run |
| Restream | `8e3dcb156ad5b8a023a11358c047317b26a762ac` | local final block and both provider fixtures passed |
| TTPBot | `db05a9818384ab54da86775191218d007dd83385` | local final block and both provider fixtures passed |
| LiveSplit | `0489b4f4421ffdccbb1c976ce3d32944ca569862` | local final block, reproducibility, side-by-side, and retained signed RC verification passed |

The later RaceTime policy/evidence commits do not change the runtime code proven on the NAS, but the mandatory multi-platform packet must still identify one exact final RaceTime commit and prove that same identity in every image. The release-identity collector must not infer equivalence between different commits.

## Durable NAS acceptance

The final sanitized Task 5 packet is preserved at [2026-08-24-nas-task5-parser-acceptance.md](2026-08-24-nas-task5-parser-acceptance.md). Its imported source artifact has SHA-256 `f01458250a443777ea4ccd675e978a956dc85f1da095524f3a4cc2403937cd67`.

At exact RaceTime commit `81ff60187ce1b7f310393636f9218fe8ea11e866`:

- the git archive contained exactly 480 tracked regular files and matched every remote extracted hash;
- the unmodified `scripts/integration-up.ps1` exited `0`;
- native NAS web and racebot images built, all six Compose services were `running` / `healthy`, migrations reached `racetime.0082_externalidentity`, and HTTPS returned `200` with exact body `{"status":"ok"}`;
- `venv\Scripts\python.exe -m unittest discover -s tests\e2e -v` ran 13 tests in 39.548 seconds, all passed, with zero skips; the two-entrant Chromium lifecycle and dual-format health parser both completed;
- the unmodified `scripts/integration-down.ps1` exited `0`, and exact-project containers, networks, volumes, readiness files, tunnel, and transfer temporaries were proven absent.

This proves native Synology amd64 integration only. The NAS had Docker 24.0.2 and Compose 2.20.1 but no Buildx builder, QEMU, or binfmt support. No package, privileged registration, daemon setting, image publication, or unrelated NAS state was changed.

## Task 6 local verification

### RaceTime

- `venv\Scripts\python.exe manage.py test --settings=project.settings.test -v 2`: 310 tests, `OK (skipped=12)`, 218.039 seconds. The skips were service/browser/tool dependent; the browser lifecycle was subsequently closed by the linked NAS 13/13 run and the six Caddy cases were rerun with the pinned binary below.
- `venv\Scripts\python.exe -m unittest discover -s tests\platform -v`: 110 tests, `OK (skipped=6)`, 137.093 seconds. With pinned Caddy 2.11.4 and `REQUIRE_CADDY_TESTS=1`, `tests.platform.test_caddy_contract` passed 8/8 with zero skips.
- `venv\Scripts\python.exe -m unittest discover -s tests\operations -v`: 30/30 passed in 6.551 seconds.
- `venv\Scripts\python.exe -m unittest discover -s tests\source -v`: 32/32 passed in 52.310 seconds; the source remote guard also passed.
- `manage.py makemigrations --check --dry-run`, `manage.py check`, and fixture-only `manage.py check --deploy` all exited `0`.
- `manage.py test racetime.tests.site.test_bootstrap_z1rr --settings=project.settings.test -v 2`: 8/8 passed, including exact second-run equality and preservation of Council-managed fields unless explicit reconciliation is requested.
- `npm ci` completed and `npm audit --omit=dev` reported zero vulnerabilities.
- Pinned Terraform 1.12.2 matched SHA-256 `0a1565ace9da37c2778868c2e97452d8fc25e40e530bafbbab97231e69b0a201`; `fmt -check -recursive`, `init -backend=false`, and `validate` passed with cached OCI provider 8.27.0. `terraform -chdir=infra\oci test` passed 2/2 mocked activation-gate tests. No plan or apply ran.
- Gitleaks 8.30.1 policy contract passed 2/2. Its disposable repositories first prove the known fixture is detected without the exception, then prove the exception requires the exact rule, path, commit, and match shape; different value shape, key, path, or commit remains detected.
- The checksum-pinned `scripts/security/verify_gitleaks.py` gate passed at exact commit `2d0fcb3d6e8515eb3da95b6fce17f954363fd20e` against base `master`: policy 2/2; all history, 930 commits / about 2.80 MB; `master..HEAD`, 67 commits / about 1.49 MB; no leaks. It verified the official Gitleaks 8.30.1 Windows x64 asset against the checked-in SHA-256 before safe extraction, used the explicit repository policy with complete redaction, and failed closed around the clean repository/base/config/test boundaries.

The dedicated MariaDB/Redis command discovered the expected 310 tests but stopped during database setup because an unrelated local MariaDB rejected the fixture root password with error 1045. No service-backed case ran, and no local service or data was changed. `docker compose ... config --quiet` could not run because Docker is not installed locally. The accepted source bundle remains deliberately outside Git and was not present for a fresh local `git bundle verify`; durable custody proof remains at [2026-08-24-source-custody.md](2026-08-24-source-custody.md).

### Restream

- `npm ci`, `npm run typecheck`, `npm run lint`, and `npm run build` passed. The build emitted only the existing large-chunk advisory.
- `npm test -- --run`: 216 files passed; 3,885 tests passed; one opt-in benchmark was intentionally skipped.
- The plan's Windows positional path `e2e\racetime-providers.spec.ts` is interpreted as a Playwright regular expression and returned `No tests found`. The checked-in file and config are valid: `npx playwright test --list` found two tests, and the normalized command `npx playwright test e2e/racetime-providers.spec.ts` passed 2/2 in 11.3 seconds. No product behavior was changed for this prose-command mismatch.
- `npx vitest run server\race-info\racetime-outcomes.test.ts server\race-info\racetime-providers.test.ts server\race-info\racetime-realtime.test.ts`: 36/36 passed.
- Approved read-only fixture resolved `racetime-gg` to `https://racetime.gg` with categories `z1rr` and `z1r`; the self-hosted fixture resolved `z1rr-racetime` to `https://integration.racetime.test:8443` / `z1rr`, leaving pickup unchanged.
- Copied legacy SQLite qualification returned integrity `ok`, schema user-version `1`, and row counts `0` before/after with no quarantined references; the validated temporary directory was removed.
- `npm audit --omit=dev` reported zero vulnerabilities.
- Gitleaks 8.30.1 over the candidate-exclusive `origin/main..HEAD` range scanned 47 commits / about 648.51 KB and found no leaks. The full reachable history reports 41 inherited findings; they are not candidate-exclusive, but they remain baseline review debt and therefore do not support marking the cross-repository history requirement Verified.

### TTPBot

- `python -m unittest discover -s tests -v`: 67/67 passed with zero skips.
- `python setup.py check` and `python -m compileall -q ttpbot` passed.
- Targeted provider/preflight fixtures passed 16/16. Approved outcome resolved `https://racetime.gg|z1rr`; the self-hosted fixture resolved `https://integration.racetime.test:8443|z1rr`; both preflights returned success without probing production.
- Gitleaks 8.30.1 scanned full history with no leaks.
- Dynamic `systemd-analyze security` remains unexecuted because this workstation has no Linux/systemd environment. Static service security and locking contract tests passed.

### LiveSplit

- `dotnet restore --locked-mode`, Release build, clean-room verification, and side-by-side verification passed; the build had zero warnings and zero errors.
- `dotnet test -c Release --no-build`: 165/165 passed with zero skips (7 contract, 45 Windows/provider, 113 core/release).
- The explicit adversarial PKCE/OAuth/token/protocol/WebSocket/provider/loopback/login/timer subset passed 95 tests with zero skips.
- `build\Verify-Reproducible.ps1 -Version 0.1.0-rc.1` passed two independent clean builds/packages. `Verify-VulnerablePackages.ps1` passed all five projects. Gitleaks 8.30.1 scanned all 15 commits with no leaks.
- Retained private RC package SHA-256: `002ffdaed908131e6e7a2b861ceffeda9798809d175ea8223e15acb76c16e643`; `SHA256SUMS` SHA-256: `de503b08976b91d25315ba3642b43e0ccd05b62f6aeb8b01927a34cc08f091b9`; signature SHA-256: `00b340bd3cadd30c4182c87be05fc9cbe6277144ff64e28a144fc0aebf3f25f1`.
- Existing Minisign 0.12 verified the manifest and trusted comment `Z1RR LiveSplit 0.1.0-rc.1`; all 15 manifest entries recomputed with zero mismatches. The non-production public key ID is `54F9CD24CF12467F`. No signing secret was used and nothing was published.

## Gate validators and release identities

- `python -m unittest tests.operations.test_traceability -v`: 7/7 passed.
- `scripts\ops\validate-traceability.py --gate G0` correctly returns `TRACEABILITY=FAIL gate=G0 code=TraceabilityError` while mandatory rows remain `Planned`.
- `scripts\ops\collect-release-identities.py --config docs\operations\release-paths.json --output artifacts\g0-release-identities.json` correctly returns `RELEASE_IDENTITIES=FAIL code=ReleaseIdentityError`. The required config does not exist (only its example exists), the multi-platform image identities do not exist, and no output manifest was generated.

## Remaining mandatory G0 work

1. Build web and racebot from one exact final RaceTime commit for both `linux/amd64` and `linux/arm64`; smoke each image, prove its embedded commit, scan each with Trivy at the required HIGH/CRITICAL threshold, and generate the required Syft SPDX SBOM/provenance. The NAS native-amd64 images do not satisfy this dual-architecture requirement.
2. Run the dedicated Django CI suite against isolated MariaDB 11.4 and Redis 7.4 services with zero service-dependent skips.
3. On a non-production Linux/container worker, render the production Compose configuration without exposing values, run the remaining backup/restore container rehearsals, and run TTPBot's dynamic `systemd-analyze security` gate.
4. Review/baseline inherited Restream history findings without weakening the candidate-range gate.
5. Create `docs/operations/release-paths.json` only after immutable artifact paths/digests exist, rerun the collector, attach its output, and rerun the G0 traceability validator.

No compatible prepared qualification worker and no checked-in end-to-end G0 worker harness currently exist, so no external qualification run is presently executable, and no current authorization covers the required setup or host mutation. The preferred setup path is the already validated Synology DS718+, but that path requires **new explicit authorization** after a new fail-closed G0 worker harness is first implemented and tested locally. Buildx, scanner, and service resources must remain workspace/project scoped: a pinned standalone Buildx binary confined to the dedicated project workspace, pinned Trivy and Syft containers, and isolated MariaDB 11.4, Redis 7.4, and systemd-offline analysis containers. The new authorization must separately permit the pinned privileged binfmt/QEMU registration container as an explicitly authorized temporary **host-global kernel mutation**, not as a project-scoped resource. Before that mutation the harness must inventory all existing handlers and capture the exact prior handler bytes and metadata, add only the exact arm64 handler needed for qualification, trap cleanup on both success and failure, restore and byte/metadata-verify the exact prior handler state, abort before registration if exact restoration cannot be guaranteed, and fail the gate if cleanup or exact restoration cannot be proven. Workspace/project-scoped Buildx, scanner, and service resources must be removed after evidence capture.

The harness must run a clean checkout at the exact final commit and first invoke `python scripts/security/verify_gitleaks.py --repository . --base-ref master` at that commit. It must then cover same-commit `linux/amd64` and `linux/arm64` web/racebot build, runtime smoke, embedded-source-commit verification, Trivy, Syft SBOM, and provenance; isolated MariaDB 11.4/Redis 7.4 service-backed Django CI; secret-safe production Compose rendering; backup/restore rehearsal; offline `systemd-analyze security`; inherited Restream-history baseline review; release-identity collection; and final gate validation.

This authority would not include image registry publication, any public release, production credentials, unrelated NAS mutation, OCI/DNS/OAuth/scheduler changes, or any G1 action.

## Disposition

Task 6 package status: **IN_PROGRESS — BLOCKED_ON_QUALIFICATION**. Step 7 cross-repository review is complete, but Step 1 cannot close while mandatory external-worker verification remains absent and Step 6 cannot close while release-identity collection and the G0 traceability gate fail. Source/application/provider/client verification and native-amd64 browser integration are strongly evidenced, but G0 remains **HOLD**, with no waiver, until every item above passes and the immutable release-identity manifest validates.
