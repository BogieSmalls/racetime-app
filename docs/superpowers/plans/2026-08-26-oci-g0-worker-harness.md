# OCI G0 Worker Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement, review, and run one fail-closed G0 qualification harness on the dedicated OCI `racetime` A1 instance without publishing images or enabling the public service.

**Architecture:** A Python controller owns closed-schema inputs, phase ordering, redacted evidence, and cleanup. Small shell/PowerShell adapters perform the narrow host and Bastion operations. Docker installation is governed by a separately reviewed package lock; all containers are protected by a persistent IMDS firewall guard; rootless BuildKit produces one dual-platform OCI layout per service; every selected image, scan, SBOM, test, recovery result, and release identity is cryptographically joined to the exact source commit.

**Tech Stack:** Python 3.13/stdlib, unittest, PowerShell 7, Bash, Docker CE/Compose, rootless BuildKit/Buildx remote driver, OCI Distribution manifests, iptables, binfmt/QEMU, Trivy, Syft, MariaDB 11.4, Redis 7.4, Terraform/OCI CLI read-only verification.

**Authoritative design:** [OCI A1 G0 worker harness design](../specs/2026-08-26-oci-g0-worker-harness-design.md)

---

## File map

- `scripts/g0/contracts.py` — closed schemas, safe identities, path and redaction rules.
- `scripts/g0/runner.py` — bounded subprocess execution and safe result capture.
- `scripts/g0/state.py` — phase state machine, evidence ledger, and LIFO cleanup registry.
- `scripts/g0/supervisor.py` — per-command containment, stream handling, and secure log finalization.
- `scripts/g0/prepare_inputs.py` — exact Git/archive/artifact custody manifests.
- `scripts/g0/registry.py` — OCI Registry v2 resolution and immutable platform identities.
- `scripts/g0/bootstrap_lock.py` — Docker key/repository/package lock resolution and verification.
- `scripts/g0/tool_lock.py` — complete binary/image/scanner/tool-layout lock creation and verification.
- `scripts/g0/bootstrap-docker.sh` — install only reviewed local packages and establish the persistent Docker baseline.
- `scripts/g0/imds-guard.sh` — idempotent ordered Docker IMDS/DNS firewall contract.
- `deploy/systemd/z1rr-docker-imds-guard.service` — persist/reapply the accepted guard after Docker starts.
- `scripts/g0/docker_runtime.py` — exact Docker resource, rootless BuildKit, port, mount, and privilege inspections.
- `scripts/g0/binfmt.py` — transactional amd64 handler snapshot, rehearsal, restoration, and comparison.
- `scripts/g0/images.py` — OCI layout, provenance, import, smoke, Trivy, and Syft identity joins.
- `scripts/g0/services.py` — MariaDB/Redis tests, fixture Compose render, real recovery, and systemd analysis.
- `scripts/g0/cross_repo.py` — candidate scans, inherited-history baseline, and retained artifact checks.
- `scripts/g0/worker.py` — nine-phase remote controller and cleanup owner.
- `scripts/g0/watchdog.py` — independent local lease monitor and exact-worker stop controller.
- `scripts/g0/invoke-oci-worker.ps1` — host-key-pinned Bastion transfer/invocation/evidence return.
- `deploy/g0/*.schema.json` and `deploy/g0/*.example.json` — closed machine contracts.
- `deploy/g0/docker-bootstrap-lock.json` — reviewed host-specific package lock created before installation.
- `deploy/g0/tool-lock.json` — reviewed immutable container/binary/scanner lock created before qualification.
- `deploy/g0/systemd-analysis.Dockerfile` and `deploy/g0/systemd-policy.json` — offline TTPBot unit evaluator.
- `tests/g0/*` — dependency-free behavioral tests and fake process/Docker/SSH fixtures.
- `scripts/ops/collect-release-identities.py` and `tests/operations/test_release_identity.py` — component-specific/commit-only identity correction.
- `docs/operations/release-paths.json` — logical, workspace-relative final identity configuration.

## Task 1: Lock the worker contracts

**Files:**
- Create: `scripts/g0/__init__.py`
- Create: `scripts/g0/contracts.py`
- Create: `deploy/g0/run-manifest.schema.json`
- Create: `deploy/g0/docker-bootstrap-lock.schema.json`
- Create: `deploy/g0/tool-lock.schema.json`
- Create: `deploy/g0/worker-evidence.schema.json`
- Create: `deploy/g0/restream-history.schema.json`
- Create: `deploy/g0/worker-disposal.schema.json`
- Create: `deploy/g0/run-manifest.example.json`
- Create: `tests/g0/__init__.py`
- Create: `tests/g0/test_contracts.py`

- [ ] **Step 1: Write failing closed-schema tests**

Cover exact top-level keys, schema version, 40-character commits, `sha256:` digests, UTC timestamps, run ID/project prefix, allowed absolute remote root, workspace-relative local paths, custody classes, exact nine-phase names, execution/cleanup/external-lease deadlines, 24-hour aggregate ceiling, the separate bootstrap/tool lock identities, the closed `WORKER_DISPOSAL_REQUIRED` control record, and rejection of unknown keys, symlinks, traversal, mutable tags, secret-like runtime fields, private paths, and unsafe output names.

- [ ] **Step 2: Run the focused test and capture RED**

Run:

    python -m unittest tests.g0.test_contracts -v

Expected: FAIL because `scripts.g0.contracts` and the schemas do not exist.

- [ ] **Step 3: Implement the minimal contract module**

Expose:

    class ContractError(ValueError): ...
    def load_json(path: Path, schema_name: str) -> dict: ...
    def load_run_manifest_with_sha256(path: Path) -> tuple[dict, str]: ...
    def load_worker_disposal(
        path: Path,
        *,
        previous: object | None,
        run_manifest_path: Path,
        previous_trusted_control: object | None,
        trusted_control_path: Path,
    ) -> dict: ...
    def validate_run_manifest(value: object) -> dict: ...
    def validate_tool_lock(value: object) -> dict: ...
    def validate_worker_evidence(value: object) -> dict: ...
    def validate_worker_disposal_transition(
        previous: object | None,
        candidate: object,
        *,
        run_manifest: object,
        run_manifest_sha256: object,
        previous_trusted_control: object | None,
        trusted_control: object,
        trusted_control_sha256: object,
    ) -> dict: ...
    def validate_restream_history(value: object) -> dict: ...
    def safe_relative_path(value: object, label: str) -> PurePosixPath: ...
    def safe_sha256(value: object, label: str) -> str: ...
    def redact_text(value: str, canaries: Sequence[str]) -> str: ...

Keep schemas closed with `additionalProperties: false`. Evidence must contain phase expected/observed result, command ID, exit status, duration, safe stdout/stderr hashes, retained artifact hashes, cleanup state, and no raw logs or matches.

The separate disposal schema contains only safe run/instance identities, last
heartbeat, failed proof classes, lease/disposal lifecycle status, and hashes
known complete before failure. It must reject phase PASS claims, incomplete
command hashes/log identities, and ordinary verified-clean status.

Generic `load_json` must reject worker-disposal input: structural parsing alone
is never qualification evidence. `load_worker_disposal` atomically and
boundedly loads the disposal, retained run manifest, and trusted control record,
binds the fixed manifest/control hashes to their exact file bytes, and performs
the complete trusted-context transition validation. Once the earliest mature
authenticated-remote, heartbeat-loss, or absolute-terminal trigger is latched,
its cause, exact nine-fractional-digit monotonic-seconds timestamp, and all
trigger-basis fields are immutable across later disposal transitions. The loader
that preserves exact bytes and the run-manifest validator establish one globally
unique custody leaf namespace across fixed control records, source artifacts, and
manifest outputs, even when colliding entries carry identical digests; disposal
validation repeats the check as defense in depth.

- [ ] **Step 4: Run GREEN and schema self-validation**

Run:

    python -m unittest tests.g0.test_contracts -v
    python -m json.tool deploy/g0/run-manifest.schema.json > NUL
    python -m json.tool deploy/g0/docker-bootstrap-lock.schema.json > NUL
    python -m json.tool deploy/g0/tool-lock.schema.json > NUL
    python -m json.tool deploy/g0/worker-evidence.schema.json > NUL
    python -m json.tool deploy/g0/restream-history.schema.json > NUL
    python -m json.tool deploy/g0/worker-disposal.schema.json > NUL

Expected: all pass.

- [ ] **Step 5: Commit**

    git add scripts/g0 deploy/g0 tests/g0
    git commit -m "test: define G0 worker contracts"

## Task 2: Build the bounded runner and cleanup state machine

**Files:**
- Create: `scripts/g0/runner.py`
- Create: `scripts/g0/state.py`
- Create: `scripts/g0/supervisor.py`
- Create: `tests/g0/test_runner.py`
- Create: `tests/g0/test_state.py`
- Create: `tests/g0/test_supervisor.py`

- [ ] **Step 1: Write failing runner tests**

Use temporary helper processes to prove: argv is a list; no shell; controlled cwd/env; every command runs through a dedicated operation supervisor; the manifest-bound execution timeout is 1–18,000 seconds and cleanup timeout is 5–600 seconds; execution plus cleanup fits the phase/aggregate reserve; timeout returns `TIMED_OUT` only after the command boundary is killed/reaped/proven empty, streams close, and logs finalize; stdout/stderr are hashed and size-bounded; secret canaries fail the command without being reproduced; exit status is checked; logs use secure retained-directory-handle traversal and mode `0600` on POSIX; and exceptions contain only safe command IDs.

On Linux require cgroup v2, `cgroup.kill`, procfs, subreaper support, retained
pidfds, one target cgroup, a supervisor outside that cgroup, fixed nonblocking
IPC, and exact cgroup removal after emptiness. On Windows require a retained
kill-on-close Job Object, blocked-child assignment before release, verified
termination/empty state, reparse-safe directory handles, and checked handle
closure. Missing capabilities fail before target launch.

Adversarial cases include a concurrent unrelated sibling, PID reuse, stalled
supervisor, nonempty cgroup/job, simulated kernel `D` state, lost control
channel, stalled log close/fsync/rename, ancestor/final symlink swaps, and
network log paths, bind-mount crossings, canary-log unlink/directory-fsync
failure, and local-filesystem identity mismatch. A proof failure produces `WORKER_DISPOSAL_REQUIRED`; no
daemon thread or mutation-capable callback may outlive an ordinary return.

- [ ] **Step 2: Write failing state-machine tests**

Require the exact phase order `preflight → setup → images → security → services → recovery → cross_repo → identities → cleanup`. Any failure blocks later promotion. Verified ordinary failures run LIFO, idempotent cleanup registered before mutation; safely bounded restoration failures produce ordinary `FAIL + cleanup failed`. A disposal-required failure closes cleanup as `unverifiable`, blocks later in-host callbacks, and delegates only external worker disposal. Cleanup catches and safely aggregates other `BaseException` subclasses, rejects reentrant close, but special-cases `WorkerDisposalRequired`: transition immediately to `unverifiable`, stop the remaining callbacks, and propagate disposal. It never turns a mandatory skip into pass.

- [ ] **Step 3: Capture RED**

    python -m unittest tests.g0.test_runner tests.g0.test_state tests.g0.test_supervisor -v

- [ ] **Step 4: Implement minimal interfaces**

    @dataclass(frozen=True)
    class CommandSpec:
        command_id: str
        argv: tuple[str, ...]
        cwd: Path
        execution_timeout_seconds: int
        cleanup_timeout_seconds: int
        environment: tuple[tuple[str, str], ...]
        secret_canaries: tuple[str, ...]
        stdout_limit: int
        stderr_limit: int
        log_directory: Path

    @dataclass(frozen=True)
    class CommandResult:
        command_id: str
        exit_code: int
        duration_ms: int
        stdout_sha256: str
        stderr_sha256: str

    class Runner:
        def run(self, spec: CommandSpec, *, input_bytes: bytes | None = None) -> CommandResult: ...

    class WorkerDisposalRequired(BaseException): ...

    class QualificationState:
        def begin(self, phase: str) -> None: ...
        def pass_phase(self, phase: str, evidence: dict) -> None: ...
        def fail_phase(self, phase: str, error_class: str) -> None: ...
        def register_cleanup(self, cleanup_id: str, callback: Callable[[], None]) -> None: ...
        def close(self) -> dict: ...

- [ ] **Step 5: Run GREEN and commit**

    python -m unittest tests.g0.test_runner tests.g0.test_state tests.g0.test_supervisor -v
    git add scripts/g0 tests/g0
    git commit -m "feat: add fail-closed worker state"

## Task 3: Prepare exact source and artifact custody

**Files:**
- Create: `scripts/g0/prepare_inputs.py`
- Create: `tests/g0/test_prepare_inputs.py`
- Modify: `deploy/g0/run-manifest.example.json`

- [ ] **Step 1: Write failing custody tests**

Create synthetic repositories with branches/tags and prove the preparer requires a clean non-shallow repository, declared branch/commit, complete verified bundle, tracked-file archive derived from the same commit, deterministic manifest, exact file counts/hashes, and an allowlisted destination. Reject ignored/untracked files, symlinks at boundaries, absolute/private paths, bundle/archive mismatch, missing refs, and artifacts that alter repository status.

- [ ] **Step 2: Add historical-source safety tests**

The exact complete Git bundle may contain only reviewed inactive historical findings or fixtures. Runtime env/config/artifact inputs receive no exception. A finding marked possibly-live blocks transfer until a separate non-secret rotation/revocation disposition exists. Raw matches never enter the manifest.

- [ ] **Step 3: Capture RED, implement, and run GREEN**

    python -m unittest tests.g0.test_prepare_inputs -v

The CLI is:

    python scripts/g0/prepare_inputs.py --workspace-root PATH --manifest deploy/g0/run-manifest.json --output-root PATH

It creates bundle/archive/artifact manifests only; it does not contact OCI.

- [ ] **Step 4: Commit**

    git add scripts/g0/prepare_inputs.py tests/g0/test_prepare_inputs.py deploy/g0/run-manifest.example.json
    git commit -m "feat: prepare G0 source custody"

## Task 4: Lock Docker bootstrap before installation

**Files:**
- Create: `scripts/g0/bootstrap_lock.py`
- Create: `scripts/g0/bootstrap-docker.sh`
- Create: `tests/g0/test_bootstrap_lock.py`
- Create: `tests/g0/test_bootstrap_script.py`
- Create later from resolver output: `deploy/g0/docker-bootstrap-lock.json`

- [ ] **Step 1: Write failing key/repository/package tests**

Synthetic fixtures must bind Docker signing-key URL, SHA-256 and fingerprint; exact Noble ARM64 repository text; `InRelease` URL and digest; host release/architecture; and every added/upgraded `.deb` name, version, origin, URL, size, and SHA-256. The same bootstrap lock also carries the minimal pre-install-resolvable Buildx asset plus rootless BuildKit and ordinary probe image index/platform digests required to accept the Docker/IMDS baseline before any other container runs. Reject unsigned metadata, changed dependency solutions, unlisted package bytes, duplicate names, another architecture/release, a mismatched bootstrap-tool identity, or a network fetch during install.

- [ ] **Step 2: Write failing bootstrap-script contract tests**

Require `set -Eeuo pipefail`, root, `sudo -n` caller preflight, local lock verification before `dpkg`, network-disabled package installation, Unix-only Docker socket, no insecure registries/listeners, no docker-group membership change, exact package delta, daemon/Compose health, and fail-closed partial-install evidence. The script must not uninstall or guess on failure.

- [ ] **Step 3: Capture RED, implement, and run GREEN**

    python -m unittest tests.g0.test_bootstrap_lock tests.g0.test_bootstrap_script -v

The resolver has separate commands:

    python scripts/g0/bootstrap_lock.py resolve --output PATH
    python scripts/g0/bootstrap_lock.py verify --lock PATH --package-root PATH

`resolve` is preparation only. `bootstrap-docker.sh` accepts only an already reviewed lock and local package directory.

- [ ] **Step 4: Commit without a fabricated lock**

    git add scripts/g0/bootstrap_lock.py scripts/g0/bootstrap-docker.sh tests/g0
    git commit -m "feat: lock Docker host bootstrap"

## Task 5: Enforce the persistent Docker IMDS boundary

**Files:**
- Create: `scripts/g0/imds-guard.sh`
- Create: `deploy/systemd/z1rr-docker-imds-guard.service`
- Create: `tests/g0/test_imds_guard.py`

- [ ] **Step 1: Write failing rule-parser and script tests**

Synthetic `iptables-save` fixtures prove the exact first `DOCKER-USER` jump, one dedicated Z1RR chain, ordered TCP/53 and UDP/53 permits to `169.254.169.254/32`, rejection of every other protocol/port to that address, and terminal return. Reject duplicate/reordered/broader rules, nft/legacy backend mismatch, host-network containers, and changed unrelated rules.

- [ ] **Step 2: Test lifecycle and restoration**

Prove pre-bootstrap raw+normalized snapshots, idempotent install, systemd reapply after Docker restart, container and builder DNS success, IMDSv1/v2 denial, ordinary locked fetch success, rollback of only Z1RR unit/chain/jump before baseline acceptance, and exact accepted-baseline restoration at run cleanup.

- [ ] **Step 3: Capture RED, implement, and run GREEN**

    python -m unittest tests.g0.test_imds_guard -v

The script supports exact verbs:

    snapshot
    install
    verify
    rollback-preaccept

It prints only status and hashes.

- [ ] **Step 4: Commit**

    git add scripts/g0/imds-guard.sh deploy/systemd/z1rr-docker-imds-guard.service tests/g0/test_imds_guard.py
    git commit -m "feat: deny Docker access to OCI metadata"

## Task 6: Lock tools, rootless BuildKit, and transactional amd64 emulation

**Files:**
- Create: `scripts/g0/registry.py`
- Create: `scripts/g0/tool_lock.py`
- Create: `scripts/g0/docker_runtime.py`
- Create: `scripts/g0/binfmt.py`
- Create: `tests/g0/test_registry.py`
- Create: `tests/g0/test_tool_lock.py`
- Create: `tests/g0/test_docker_runtime.py`
- Create: `tests/g0/test_binfmt.py`
- Create later from resolver output: `deploy/g0/tool-lock.json`

- [ ] **Step 1: Write failing OCI Registry resolution tests**

Use a fake registry transport to verify bearer-token flow, manifest media types, index/platform selection, immutable index/platform/config/layer digests, blob lengths/hashes, redirect constraints, and rejection of mutable execution references or cross-registry redirects.

- [ ] **Step 2: Write failing complete tool-lock tests**

`tool_lock.py` owns both creation and verification of `tool-lock.json`. Tests require the exact bootstrap-lock SHA-256; the identical Buildx/BuildKit/probe identities already accepted during bootstrap; Trivy image and DB OCI artifact bytes plus schema/version/update time/digest; Syft; binfmt installer and amd64 probe; inspector/importer; MariaDB; Redis; backup/archive helpers; and the digest/OCI-layout hash of the locally built systemd-analysis image. Resolve mode may download/build only under a preparation artifact root; verify mode is offline and rejects missing bytes, changed bootstrap identities, tags at execution, unjoined platform digests, or a systemd-analysis identity not derived from its locked base and Dockerfile hash.

Exact CLIs:

    python scripts/g0/tool_lock.py resolve --bootstrap-lock PATH --artifact-root PATH --output PATH
    python scripts/g0/tool_lock.py verify --bootstrap-lock PATH --artifact-root PATH --lock PATH

- [ ] **Step 3: Write failing rootless BuildKit inspection tests**

Require a manually created digest-pinned rootless BuildKit container connected by Buildx remote driver over `docker-container://`. Inspect and require: privileged false, capability drop all, no host network/PID/IPC/userns, no device/socket/host-path mount, no published port, one named writable state volume, read-only config, exact three unconfined security options, no insecure entitlements, run label/prefix, one-build concurrency, and IMDS guard membership. Rootless startup failure must not fall back or alter sysctls/AppArmor.

- [ ] **Step 4: Write failing binfmt transaction tests**

Cover absent/disabled table, compatible existing handler no-mutation branch, incompatible/ambiguous handler failure, exact raw+normalized snapshots, only locked `qemu-x86_64` registration, `F` flag, injected post-register failure, success/failure/signal/timeout cleanup, removal of only the added handler, and byte/metadata equality. Cycles, partial reads, changed unrelated handlers, or unverifiable cleanup fail.

- [ ] **Step 5: Capture RED, implement, and run GREEN**

    python -m unittest tests.g0.test_registry tests.g0.test_tool_lock tests.g0.test_docker_runtime tests.g0.test_binfmt -v

- [ ] **Step 6: Commit**

    git add scripts/g0 tests/g0
    git commit -m "feat: add locked multiarch worker runtime"

## Task 7: Qualify image provenance, smoke, scans, and SBOMs

**Files:**
- Create: `scripts/g0/images.py`
- Create: `tests/g0/test_images.py`
- Modify: `tests/platform/smoke_images.ps1` only if a shared machine-readable identity adapter is necessary

- [ ] **Step 1: Write failing layout/provenance tests**

Synthetic OCI layouts must contain exactly amd64/arm64 manifests for one service/source commit. Verify descriptor sizes/digests, config architecture/OS, layer digests, OCI revision label, BuildKit provenance subject/materials, and selected import identity. Reject second-build identities, missing/extra platforms, wrong commit, mutable base identity, and cross-service swaps.

- [ ] **Step 2: Write failing smoke tests**

For `web` and `racebot` on each platform, construct exact commands requiring UID 10001, read-only root, bounded tmpfs, expected command/port contract, embedded commit, no credential variable in history/config, and no external/public contact.

- [ ] **Step 3: Write failing Trivy/Syft joins**

Require pinned scanner/database identities, DB schema/version/update time/digest, HIGH/CRITICAL policy, SPDX JSON validation, and cryptographic joins from every report to the selected manifest/config/layers. Any vulnerability breach, scanner error, missing DB provenance, or report mismatch fails.

- [ ] **Step 4: Capture RED, implement, and run GREEN**

    python -m unittest tests.g0.test_images -v

- [ ] **Step 5: Commit**

    git add scripts/g0/images.py tests/g0/test_images.py
    git commit -m "feat: qualify immutable multiarch images"

## Task 8: Qualify services, recovery, Compose, and systemd

**Files:**
- Create: `scripts/g0/services.py`
- Create: `deploy/g0/systemd-analysis.Dockerfile`
- Create: `deploy/g0/systemd-policy.json`
- Create: `tests/g0/test_services.py`
- Modify: `tests/platform/test_backup_scripts.py` only for reusable real-rehearsal contracts

- [ ] **Step 1: Write failing MariaDB/Redis phase tests**

Require isolated digest-pinned native ARM64 services, internal networks, fixture-only credentials, no public ports, readiness before tests, exact Django CI command, zero service-dependent skips, and labeled teardown. A reachable unrelated local service must never satisfy readiness.

- [ ] **Step 2: Write failing Compose-render tests**

Render `deploy/compose.production.yml` with fixture-only values and inspect without `up`. Reject production names/credentials, public DB/Redis/admin, mutable images, host networking, unguarded publication, qualification/final volume collision, or value leakage.

- [ ] **Step 3: Write failing real recovery tests**

Use a local transport double and run-generated age key to prove representative DB/media/Caddy fixtures, real `mariadb-dump`, compression, encryption, archive manifest, destructive project-scoped volume recreation, decrypt/import/migrate, data/media validation, and exact cleanup. Never invoke OCI Object Storage or production secrets.

- [ ] **Step 4: Write failing offline systemd tests**

Require digest-pinned networkless analysis, machine-readable `systemd-analyze security --offline`, reviewed score ceiling, no writable path outside `/var/lib/ttpbot` and `/run/ttpbot/scheduler.lock`, exact lock/StateDirectory/restart identity, and no execution of the TTPBot service.

- [ ] **Step 5: Capture RED, implement, and run GREEN**

    python -m unittest tests.g0.test_services -v

- [ ] **Step 6: Commit**

    git add scripts/g0/services.py deploy/g0 tests/g0/test_services.py tests/platform/test_backup_scripts.py
    git commit -m "feat: qualify service and recovery gates"

## Task 9: Close cross-repository and release-identity defects

**Files:**
- Create: `scripts/g0/cross_repo.py`
- Create: `tests/g0/test_cross_repo.py`
- Modify: `scripts/ops/collect-release-identities.py`
- Modify: `tests/operations/test_release_identity.py`
- Modify: `docs/operations/release-paths.example.json`
- Create after exact artifacts exist: `docs/operations/release-paths.json`
- Create after local review: `deploy/g0/restream-history.json`

- [ ] **Step 1: Write failing history-baseline tests**

Require repository/base/candidate commits and exact metadata-only findings: rule, path, source commit, line, one-way fingerprint, classification, outside-candidate boolean, live-credential disposition, and non-secret evidence ID. Full-history metadata must equal the reviewed baseline and candidate range must be empty. Unknown/missing findings, raw matches, possible-live status, or an inherited-only rationale without credential disposition fails.

- [ ] **Step 2: Write failing release-identity tests**

Replace the global common-version assumption with exact expected commit/branch per component, component-specific structured version selectors, and explicit RaceTime `commit-only` policy. Require `--workspace-root` and logical relative paths. Reject synthesized/untracked version files, selector ambiguity, dirty repositories, mutable images, wrong source commit, or private paths. Preserve current artifact, migration, schema, signature, and safe-output checks.

- [ ] **Step 3: Capture RED**

    python -m unittest tests.g0.test_cross_repo tests.operations.test_release_identity -v

- [ ] **Step 4: Implement the minimal correction and phase**

The collector output remains schema-versioned/path-free and reports each component's independent version policy. The cross-repository phase invokes the checked-in RaceTime Gitleaks wrapper at exact final commit and the appropriate pinned scans for all four inputs.

- [ ] **Step 5: Run GREEN and commit code/example only**

    python -m unittest tests.g0.test_cross_repo tests.operations.test_release_identity -v
    git add scripts/g0/cross_repo.py tests/g0 scripts/ops/collect-release-identities.py tests/operations/test_release_identity.py docs/operations/release-paths.example.json
    git commit -m "fix: collect component release identities"

Do not fabricate `release-paths.json` or the Restream baseline before exact artifacts/history are reviewed.

## Task 10: Compose the remote controller and Bastion invocation

**Files:**
- Create: `scripts/g0/worker.py`
- Create: `scripts/g0/watchdog.py`
- Create: `scripts/g0/invoke-oci-worker.ps1`
- Create: `tests/g0/test_worker.py`
- Create: `tests/g0/test_watchdog.py`
- Create: `tests/g0/test_invoke_oci_worker.py`

- [ ] **Step 1: Write failing controller tests**

With fake adapters, exercise all nine phases, exact phase dependencies, one run root/label/prefix, command execution/cleanup budgets, 60–1,800-second final-cleanup reserve inside the 86,400-second aggregate, 15-second authenticated heartbeat, 90-second rolling lease, exact 86,490-second absolute terminal deadline, persistent-baseline vs transient cleanup, failure injection at every mutation, evidence hashes, `WORKER_QUALIFICATION=PASS` only after every gate, ordinary `FAIL` with `verified` or safely bounded `failed` cleanup, and the distinct `WORKER_DISPOSAL_REQUIRED` control path.

Pin these remote interfaces:

    python3 scripts/g0/worker.py run --run-manifest PATH --docker-bootstrap-lock PATH --tool-lock PATH --state PATH --evidence-root PATH
    python3 scripts/g0/worker.py cleanup --run-manifest PATH --state PATH --evidence-root PATH
    python3 scripts/g0/worker.py verify-clean --run-manifest PATH --state PATH --evidence-root PATH

`run` owns run-root creation, Docker/binfmt/service resources, phase evidence,
per-command supervisors, signal/timeout traps, heartbeats, and the first cleanup
attempt. `cleanup` is an idempotent recovery entry point bound to the same
manifest/state and may remove only recorded project resources plus a handler
that state proves this run added. It refuses in-host cleanup when state is
`unverifiable`. `verify-clean` is read-only. None accepts arbitrary commands,
resource names, secret values, or paths outside the manifest root.

- [ ] **Step 2: Write failing invocation tests**

Require clean exact commit, host-key pin, OCI Bastion target identity, `sudo -n true`, no production credential read, manifest/hash verification before move, no private input in argv/log/evidence, no direct public SSH, bounded session/listener, an independently supervised external heartbeat/terminal-response lease, redacted evidence allowlist on return, and session/listener cleanup on success/failure/interrupt.

Pin the local interface:

    pwsh -File scripts/g0/invoke-oci-worker.ps1 -Mode Prepare|Run|Cleanup|VerifyClean|RecoverDisposal -WorkspaceRoot PATH -RunManifest PATH -DockerBootstrapLock PATH -ToolLock PATH -EvidenceDestination PATH -OciProfile NAME -InstanceId VALUE -BastionId VALUE -TargetPrivateIp VALUE -SshHostKeyFingerprint VALUE -SshPrivateKeyPath PATH

Runtime OCI IDs, private IP, profile, key path, and host-key fingerprint are never committed or echoed. Preparation atomically creates two separate owner-only, no-reparse local files with exclusive-create semantics: a one-run 256-bit control-authentication key and a closed canonical runtime control record. The record binds run ID, frozen commit, authenticated SSH target/private IP, exact instance OCID, domain-separated instance fingerprint, and live read-only instance/VNIC identities, and carries an HMAC-SHA-256 over that complete tuple and schema version. Neither file may be supplied by an existing path, link, or network filesystem. Every later mode, heartbeat, watchdog action, and post-action live identity read verifies the HMAC and exact tuple before acting; mismatch fails without OCI mutation. Both files are ignored runtime custody, never tracked or echoed, and are removed only after a terminal verified state.

Before `Run`, the invoker launches `watchdog.py` as an independent local process with its private inputs read from those files rather than argv/logs. Arming atomically transfers custody of the exact Bastion session ID, listener PID/start identity/loopback port, and worker identity to the watchdog. The watchdog owns their external cleanup plus the rolling and absolute leases and remains able to delete only that session, stop only that listener, and force-stop only that worker if the PowerShell parent exits or stalls. Normal authenticated terminal disposition disarms it only after the invoker has completed and verified those same external cleanups. Lease loss monotonically creates/finalizes the disposal record; a late remote result cannot downgrade that state. Tests inject parent exit/stall before and after arming and require no Bastion session/listener residue.

Before arming, the invoker owns OCI Bastion session lifecycle, the localhost listener/SSH process, transfer staging, and evidence return. After arming, the watchdog owns the exact Bastion session, exact listener identity, external worker lease, and disposal action until authenticated disarm; the live invoker may coordinate cleanup but cannot reclaim, bypass, or independently disarm that ownership, and parent exit/stall leaves it intact. On an ordinary failure the invoker first requests remote `cleanup` if the authenticated channel is still available and coordinates verified external cleanup through the watchdog. On `WORKER_DISPOSAL_REQUIRED`, missing heartbeat, or missing terminal response, it performs no further in-host mutation; the watchdog deletes only its exact Bastion session/listener, then uses the exact bound OCI instance action `STOP --force` with a bounded `STOPPED` waiter. Reuse is a separate explicit `RecoverDisposal` operation: start the same exact instance, wait for `RUNNING`, create a new exact Bastion session, and run read-only `verify-clean` proving no G0 process/cgroup/job/container/project residue plus the accepted Docker/IMDS baseline. If stop/start or verification fails, it halts for operator direction; it never terminates/reprovisions the instance automatically. It never deletes a session it did not create. Persistent Docker packages and the accepted IMDS guard are never cleanup targets.

- [ ] **Step 3: Add static forbidden-action tests**

Reject registry push/login, Terraform apply/destroy, OCI mutation except Bastion session lifecycle and exact manifest-bound `racetime` stop/start for disposal recovery or idle shutdown, DNS/OAuth/Discord/Twitch calls, instance termination/reprovision, host/network mode, public port publication, Restream lifecycle calls, production env paths, and G1/G2 activation.

- [ ] **Step 4: Capture RED, implement, and run GREEN**

    python -m unittest tests.g0.test_worker tests.g0.test_watchdog tests.g0.test_invoke_oci_worker -v

- [ ] **Step 5: Commit**

    git add scripts/g0/worker.py scripts/g0/watchdog.py scripts/g0/invoke-oci-worker.ps1 tests/g0
    git commit -m "feat: orchestrate OCI G0 qualification"

## Task 11: Run local verification and review before remote preparation

**Files:**
- Modify only defects found by review

- [ ] **Step 1: Run the full harness and affected repository suites**

    python -m unittest discover -s tests/g0 -v
    python -m unittest discover -s tests/operations -v
    python -m unittest discover -s tests/platform -v
    python scripts/security/verify_gitleaks.py --repository . --base-ref master
    git diff --check

Expected: all mandatory local contracts pass. Tool-unavailable skips are permitted only where the remote phase is explicitly designed to supply the tool, and the test must fail when its `REQUIRE_*` environment flag is set.

- [ ] **Step 2: Run adversarial cleanup simulations**

Inject failure after package download, firewall mutation, builder create, binfmt registration, each image import, service start, backup destruction, and Bastion creation. Also inject stalled supervisor, nonempty containment, lost heartbeat/control channel, and log finalization stalls. Require exact pre/accepted state restoration for ordinary failures; require disposal state, blocked in-host callbacks, exact-instance stop/restart, and read-only clean proof for unverifiable failures.

- [ ] **Step 3: Request spec and code-quality reviews**

Review the exact clean commit against both worker designs and the authorization boundary. Fix Critical/Important findings under TDD; rerun affected and full suites.

- [ ] **Step 4: Commit any review fixes and freeze the preparation commit**

Record the exact commit in the future run manifest; no remote qualification evidence exists yet.

## Task 12: Resolve and review immutable locks in two remote preparation stages

**Files:**
- Create from exact resolver output: `deploy/g0/docker-bootstrap-lock.json`
- Create from exact resolver output: `deploy/g0/tool-lock.json`
- Create from exact reviewed inputs: `deploy/g0/restream-history.json`
- Create from exact artifacts: `docs/operations/release-paths.json`
- Create: `deploy/g0/run-manifest.json`

- [ ] **Step 1: Run read-only host/package and bootstrap-tool preflight through Bastion**

Capture Ubuntu/ARM64/apt/kernel/resource/firewall facts and run only the Docker bootstrap-lock resolver plus the host-side OCI Registry resolver. Download package/key/repository bytes and the minimal Buildx asset under the dedicated run root; resolve the rootless BuildKit and ordinary probe image index/platform digests without executing a container. Do not install or start Docker. Return the candidate lock, bytes, and hashes.

- [ ] **Step 2: Review and commit `docker-bootstrap-lock.json`**

Independently verify key fingerprint/digest, repository metadata signature/digest, package URLs/hashes/versions/origins/dependency closure, host identity, allowed delta, Buildx checksum, and BuildKit/probe index+ARM64 platform digests. Re-run local lock tests and obtain focused review.

- [ ] **Step 3: Install the exact locked Docker set and persistent IMDS guard**

From the reviewed commit, re-verify the package and bootstrap-tool bytes immediately, invoke `bootstrap-docker.sh`, install/reload the Z1RR guard unit, and restart Docker once. Use only the bootstrap-locked probe image, rootless BuildKit image, and Buildx binary to prove exact rule order, ordinary-container and BuildKit-network TCP/UDP DNS, IMDSv1/v2 denial, one rootless build step, Unix-only daemon, package set, no group membership change, no public ports, and unchanged OCI NSG. No other container may run before this accepted baseline. Stop and restore the preaccept state on any mismatch.

- [ ] **Step 4: Resolve container/binary/scanner locks without candidate qualification**

Invoke the exact `tool_lock.py resolve` interface. It must bind the reviewed bootstrap-lock SHA-256 and reuse the identical Buildx/BuildKit/probe identities, then resolve the amd64 binfmt installer/probe, inspector/importer, Trivy and DB bytes/metadata, Syft, MariaDB, Redis, and backup helpers. Build only the tool-owned systemd-analysis image from its locked base, export and retain its OCI layout, and record its resulting immutable identity. Do not build candidate images. Run `tool_lock.py verify` offline before returning the lock/artifact manifest, then clean all transient resolver resources.

- [ ] **Step 5: Review histories/artifacts and create final configs**

Complete the metadata-only Restream history disposition, rotate/revoke anything possibly live before transfer, and create exact logical release paths only after immutable artifacts exist. No raw match or private path may enter Git.

- [ ] **Step 6: Commit locks/configs, run all local tests, and freeze final qualification commit**

Any executable/config change after this point invalidates the pending run and requires a new frozen commit.

## Task 13: Execute the authorized OCI qualification and close G0

**Files:**
- Create after run: `docs/evidence/2026-08-26-oci-g0-worker-qualification.md`
- Modify after run only: `docs/evidence/2026-08-24-g0-readiness.md`
- Modify after run only: `docs/racetime-z1rr/launch-readiness-checklist.md`
- Modify after run only: `docs/racetime-z1rr/requirements-traceability.md`

- [ ] **Step 1: Reconfirm the exact authorization and live boundary**

Require the dedicated `racetime` instance, 1 OCPU/6GB/50GB, reserved address identity, dedicated subnet/security list/NSG, Bastion-only SSH, canonical `raceroom.z1rracing.com` A resolution matching that reserved identity with TTL 300 and no AAAA/CNAME, no application listener/TLS/OAuth state, no existing G0 project resources, accepted Docker/IMDS baseline, resource floor, and clean exact final commit. DNS presence is prepositioned addressing only and cannot satisfy a service or launch gate.

- [ ] **Step 2: Transfer exact inputs and run the nine phases**

Use `invoke-oci-worker.ps1`. The remote controller must emit `WORKER_QUALIFICATION=PASS` only after native arm64 and emulated amd64 images, provenance, smoke, Trivy, Syft, service-backed tests, Compose render, real recovery, offline systemd, cross-repository checks, release identities, and worker validators all pass.

- [ ] **Step 3: Prove cleanup before accepting evidence**

Require exact absence of transient builder/containers/networks/volumes/images/layouts/tools/test keys/source staging/Bastion session/listener and any added amd64 handler. Verify the exact prior binfmt state, exact accepted Docker firewall baseline, persistent Docker package/guard identity, no public ports, unchanged OCI boundary, and no production/G1 state.

If the run emits `WORKER_DISPOSAL_REQUIRED` or loses its external lease, accept
no qualification evidence. Exercise the Task 10 watchdog's pinned exact-session,
exact-listener, and exact-worker `STOP --force` path. Then invoke
`invoke-oci-worker.ps1 -Mode RecoverDisposal`; do not retry until its explicit
start, `RUNNING` waiter, new Bastion session, and read-only `verify-clean`
prove the worker boundary. A failed stop/start or clean proof halts for explicit
operator direction; automatic termination or reprovision is forbidden.

- [ ] **Step 4: Import only redacted retained evidence**

Verify every returned artifact hash and canary scan. The tracked evidence must contain no OCID, private/reserved IP, local private path, raw scanner match, credential, key, token, Terraform state, or raw log.

- [ ] **Step 5: Perform the docs-only closeout**

Update only the four designated evidence/checklist/traceability paths. Prove the qualified commit-to-closeout diff contains no executable/candidate-source change.

- [ ] **Step 6: Run final validators**

    python -m unittest discover -s tests/operations -v
    python scripts/ops/collect-release-identities.py --workspace-root PATH --config docs/operations/release-paths.json --output PATH
    python scripts/ops/validate-evidence.py --manifest PATH
    python scripts/ops/validate-traceability.py --gate G0
    python scripts/security/verify_gitleaks.py --repository . --base-ref master
    git diff --check

Expected: release identities, evidence, traceability, and secret scan pass; G0 changes from HOLD to Pass only if every requirement is supported. A failed gate leaves G0 HOLD with no waiver.

- [ ] **Step 7: Commit the docs-only closeout and stop the instance when idle**

Do not alter the prepositioned public DNS record, configure TLS, or start the racetime.gg application as part of G0. Record that the instance may be stopped between development sessions.
