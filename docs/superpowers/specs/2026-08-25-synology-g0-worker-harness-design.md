# Synology G0 Worker Harness Design

**Status:** Worker selection blocked after Synology capability spike

**Date:** 2026-08-25

**Control documents:**

- [Architecture specification](2026-08-12-plan-b-racetime-architecture-design.md)
- [Requirements and decisions](../../racetime-z1rr/requirements-and-decisions.md)
- [Launch master plan](../plans/2026-08-22-z1rr-racetime-launch-master.md)
- [Current G0 evidence](../../evidence/2026-08-24-g0-readiness.md)

## Purpose

Implement and run one fail-closed G0 qualification harness on the dedicated
Synology DS718+ workspace. The run closes, or precisely re-evidences, the
remaining Master Task 6 worker-dependent gates without publishing images or
changing OCI, DNS, OAuth, schedulers, production credentials, or G1 state.

## Selected approach

Use the already-qualified Synology Docker Engine as a private disposable
worker. A workspace-local, checksum-pinned Buildx CLI controls a dedicated
BuildKit container. Pinned containers provide emulation registration,
Trivy, Syft, MariaDB, Redis, and offline systemd analysis.

Alternatives considered:

1. Multiple GitHub Actions runs would require default-branch workflow
   publication and still would not provide one coherent backup/systemd and
   cleanup transaction.
2. A new Linux or native ARM64 worker would avoid emulation but add external
   infrastructure and authority that G0 does not require.

The Synology path is the smallest authorized path and exercises the Docker
Engine already used for the accepted native-amd64 integration run.

### Capability-spike result

The authorized 2026-08-25 spike found that the DSM kernel advertises
`binfmt_misc`, but the digest-pinned installer could not create a usable
ARM64 handler. It returned success while an independent private-mount snapshot
remained empty and the installer status reported no emulator. This is
consistent with the NAS's Linux 4.4 kernel being older than the 4.8 minimum
required for the `fix_binary` registration used by modern container QEMU.
Every attempt restored and re-verified the original empty, unmounted table.
See [the spike evidence](../../evidence/2026-08-25-nas-binfmt-spike.md).

The Synology design therefore cannot proceed unchanged. Worker selection must
choose either a modern disposable Linux/WSL2 worker that can satisfy the exact
runtime-smoke contract, or a separately reviewed BuildKit-only NAS design with
a different ARM64 runtime-evidence contract.

## Container and host boundary

All builds, scans, services, smokes, backup doubles, and systemd analysis run
in Docker containers or a Docker BuildKit builder. The Buildx executable and
the Python controller are ordinary files inside the dedicated workspace.

The sole host-global mutation is the Linux `binfmt_misc` ARM64 handler. A
privileged, digest-pinned registration container changes the NAS kernel's
handler table even though the command is launched through Docker. The harness
must therefore treat registration as a transaction, not as a project-scoped
container side effect.

## Workspace and scope

The remote run uses a new absolute directory beneath
`/volume1/docker/z1rr-racetime-g0-<commit>` and Docker resources carrying a
`z1rr-racetime-g0` prefix and qualification labels. It receives tracked-file
archives for the exact clean RaceTime, Restream, TTPBot, and LiveSplit commits
named in the run manifest. Each archive is derived from and compared with a
complete verified Git bundle containing every ref needed to reconstruct the
declared candidate and scan range. Git history is not fetched with production
credentials.

Untracked build artifacts required by the collector are transferred separately
under a signed/hash-listed artifact manifest. That manifest covers the retained
Restream build, LiveSplit DLL/package/update/signature material, and any prior
review record. The harness verifies each artifact hash before use and never
allows an artifact to alter a reconstructed source tree's clean Git status.

The controller refuses paths outside the dedicated root, unexpected dirty
source, commit mismatches, pre-existing same-name project resources, mutable
tool references, or production-like environment material. Password-backed
sudo is supplied only through SSH standard input and is never written,
printed, placed in arguments, or stored in environment variables.

Preflight requires at least 12 GiB total memory, 8 GiB currently available,
and 20 GiB free in the workspace filesystem unless a measured artifact-size
study raises those floors. Native image phases receive a 60-minute per-target
budget; emulated ARM64 phases receive a separate 240-minute budget. The run
manifest records actual resources and every phase-specific timeout.

## Tool lock

A checked-in lock document records, at minimum:

- Buildx release asset URL and SHA-256;
- the BuildKit image digest used by the dedicated builder;
- the `tonistiigi/binfmt` image digest and expected ARM64 interpreter name;
- Trivy and Syft image digests;
- MariaDB 11.4 and Redis 7.4 image digests;
- the pinned base and resulting immutable ID for the local systemd-analysis
  image; and
- the digest-pinned OCI-layout inspector/importer used to select manifests and
  copy those exact manifests into the daemon.

The controller downloads or pulls only these identities, verifies the Buildx
checksum before making it executable, records resolved platform digests, and
fails on a mutable tag at the execution boundary. Nothing is pushed.
Trivy evidence also records the vulnerability database schema/version,
downloaded/updated timestamp, and database digest used for every scan; pinning
the scanner image alone is not treated as reproducible scan provenance.

## `binfmt_misc` transaction

Before privileged execution the harness:

1. records whether `binfmt_misc` is available/enabled and captures every
   existing handler name and raw kernel-reported definition;
2. records the normalized semantic metadata for each handler: enabled state,
   interpreter, flags, offset, magic, and mask;
3. proves no ambiguous or incompatible ARM64 handler must be overwritten;
4. proves its cleanup command can target only the handler it will add; and
5. installs cleanup traps before registration.

If the table is not mounted in the NAS host namespace, the helper may mount it
only inside its own ephemeral mount namespace to inspect the global registry;
that mount disappears with the helper. A globally disabled registry or a
kernel that cannot expose the registry without changing the host mount table
fails preflight. The harness never changes the global enabled/disabled state
and never installs a persistent host mount.

If a usable ARM64 handler already exists, the harness leaves it untouched,
runs a real no-mutation qualification branch, and later proves the entire table
unchanged. Otherwise it installs only a uniquely locked ARM64 handler, proves
an ARM64 container executes, and records the added name. The mandatory injected
failure rehearsal is run only in the install branch; the existing-handler
branch instead proves that the failure path performs no registration or
unregistration.
On success, failure, signal, or timeout it unregisters only that added handler,
removes the registration container, and re-snapshots the table. Cleanup passes
only when availability/enabled state, handler names, raw definitions, and
normalized metadata equal the pre-run snapshot. A mismatch is a failed gate
and leaves an explicit recovery record; the harness never attempts to reset or
replace unrelated handlers.

## Qualification phases

The controller runs ordered phases and writes a redacted result for every
phase. A failed phase prevents later evidence from being promoted, while the
cleanup phase always runs.

1. **Preflight:** verify exact commits, clean trees, source bundle hashes,
   Docker/Compose compatibility, free disk/memory, loopback ports, no conflicting
   project resources, tool locks, and the RaceTime fail-closed Gitleaks runner.
2. **Worker setup:** install the workspace-local Buildx plugin, create one
   labeled Docker-container builder with pinned BuildKit, and perform the
   transactional ARM64 registration.
3. **Images:** build separate `web` and `racebot` multi-platform OCI
   layouts from one RaceTime commit for `linux/amd64` and `linux/arm64`,
   with BuildKit provenance. A digest-pinned inspector selects each platform
   manifest and copies that exact manifest into the Docker daemon; no second
   build is permitted. The harness verifies that the daemon config and layer
   digests equal the selected layout manifest before checking platform,
   non-root runtime, process contract, and embedded commit.
4. **Security and SBOM:** scan every target/platform with pinned Trivy using
   the repository's HIGH/CRITICAL policy, generate SPDX JSON with pinned Syft,
   and validate that every report names the selected layout manifest/config
   identity. Scanner input may be the exact daemon import or layout, but its
   recorded identity must cryptographically join back to the layout.
5. **Services and configuration:** run the complete Django CI suite against
   isolated digest-pinned MariaDB 11.4 and Redis 7.4 with zero mandatory skips,
   then render production Compose with fixture-only values and inspect it
   without starting a production stack.
6. **Recovery and service hardening:** retain the existing fake-command
   failure tests, then run a real Docker rehearsal with digest-pinned MariaDB
   and application images, representative account/category/race/ranking/media/
   Caddy fixture data, real `mariadb-dump`, `age`, `zstd`, archive,
   decrypt, volume recreation, database import, migration, and data validation.
   A run-generated test-only age key and local filesystem Object Storage
   transport double replace only external OCI transport; neither a real key nor
   an external endpoint is used. Run `systemd-analyze security --offline`
   against TTPBot's exact unit in a read-only, `--network none`, digest-pinned
   analysis image. Acceptance requires valid machine-readable analysis, overall
   exposure at or below a checked-in reviewed ceiling, no writable path outside
   `/var/lib/ttpbot` and `/run/ttpbot/scheduler.lock`, and the exact runtime
   lock/StateDirectory contract.
7. **Cross-repository evidence:** re-run candidate secret scans; compare the
   inherited Restream full-history findings with a reviewed metadata-only
   baseline without weakening the zero-finding candidate-range gate; verify
   the retained LiveSplit and provider artifacts already named by Task 6. The
   baseline schema records repository/base/candidate commits plus, for every
   inherited finding, rule, path, source commit, line, a one-way finding
   fingerprint, classification, and disposition evidence—but never the match
   or secret. Disposition records separately whether a finding is outside the
   candidate range and whether it represents a live credential; any credential
   that may still be valid is rotated independently of G0 classification. The
   full-history metadata set must equal the reviewed baseline exactly and the
   candidate range must remain empty.
8. **Identities and gates:** create run-local immutable image identity input,
   run the checked-in release-identity collector, validate the evidence and
   current traceability matrix, and report `WORKER_QUALIFICATION=PASS` only if
   every worker-side G0 requirement is genuinely supportable.
9. **Cleanup:** remove only the dedicated builder, containers, networks,
   volumes, images designated transient by the run manifest, tool downloads,
   and readiness sentinels; restore/verify `binfmt_misc`; preserve only the
   source workspace and redacted evidence explicitly designated for custody.

### Release-identity correction

The collector's purpose is to prove that all four artifacts come from declared
clean commits and match their component's own embedded identity. Its current
requirement that independent repositories share one common version represented
by whole-file tokens is a defect, not a security property. The implementation
may correct that G0 tool under TDD, while preserving its existing safety
properties, to accept:

- one exact expected commit and actual expected branch per component;
- component-specific version evidence from tracked JSON, Python, XML, or raw
  files; and
- an explicit `commit-only` policy for a component such as RaceTime that has
  no embedded release version.

The durable config uses logical workspace-relative repository/artifact paths
resolved by an explicit `--workspace-root`; it contains no workstation or NAS
private path. Version sources must be tracked at the expected commit, structured
selectors must match exactly once, and no source/version file or branch may be
synthesized or rewritten. The output remains path-free and identifies the
actual per-component version or `commit-only` policy.

## Evidence and provenance

The worker run produces a machine-readable JSON record plus a concise Markdown
summary. They contain exact source commits, tool versions/digests, OCI-layout
index and per-platform image digests, embedded revisions, scan/SBOM hashes,
test counts and skips, Compose hash, recovery/systemd results, prior/post
`binfmt` snapshot hashes, cleanup inventory, and final gate output. Logs are
captured per phase, scanned for credential canaries, reduced to safe summaries,
and not committed wholesale.

The versioned run manifest assigns every output a custody class. Retained:
source/artifact manifests, extracted provenance attestations, selected
manifest/config/layer identities, Trivy reports, SPDX SBOMs, safe test
summaries, release identities, `binfmt` snapshot hashes, and cleanup proof.
Transient: OCI layer blobs/layout archives, daemon images, builder/cache,
service volumes, raw logs, downloaded tools, and test keys. Transient material
is deleted only after the retained hashes and summaries validate.

G0 closes in two stages. First, the exact frozen harness/candidate commit
produces `WORKER_QUALIFICATION=PASS`; the remote run does not claim final G0.
Second, the operator imports the redacted evidence, updates only designated
evidence/checklist/traceability files, commits that closeout, proves the diff
from the qualified commit contains no executable/source change, and runs the
final validators locally. Unaffected live phases do not rerun for that
docs-only closeout. Any executable or candidate-source change does require the
affected remote acceptance path to rerun.

## Failure behavior

- Every command has a timeout and checked exit status.
- Cleanup is registered before any Docker or kernel mutation.
- Evidence records `FAIL`, the phase, a safe error class, and cleanup result;
  it never records a phase as verified merely because an artifact exists.
- Failure to restore exact prior `binfmt` state is reported separately and is
  never hidden by the original failure.
- A failed cleanup, vulnerability threshold, mandatory skip, identity mismatch,
  dirty tree, missing digest, worker qualification, docs-only diff proof, or
  final validator leaves G0 at `HOLD`.

## Test strategy

Implementation follows TDD. Local tests use fake Docker/SSH/process adapters
and synthetic `binfmt` files to cover preflight, tool checksum/digest pinning,
command construction, both pre-existing-handler branches, success/failure/
signal cleanup, exact state comparison, project scoping, secret redaction,
artifact identity, phase ordering, and fail-closed evidence. Static contract
tests prove no publication or G1 command exists.

After local review, the authorized Synology acceptance run executes the real
controller from the exact commit. When the harness adds an ARM64 handler it
first performs an injected post-registration failure rehearsal that proves
restoration; when it reuses a compatible existing handler it performs the
equivalent real no-mutation failure branch. Acceptance requires all requested
phases to pass, no mandatory skip, exact project teardown, no tunnel/readiness
residue, and exact prior `binfmt` state restored.

## Non-goals

This work does not publish images, create a public multi-platform manifest,
deploy RaceTime, use production credentials, contact production RaceTime or
Discord/Twitch endpoints, change NAS daemon configuration, create OCI/DNS/OAuth
resources, move schedulers, authorize G1, or alter unrelated NAS resources.
