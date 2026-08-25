# Synology G0 Worker Harness Design

**Status:** Approved architecture; implementation pending

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
named in the run manifest. Git history required for secret scanning is
transferred as verified bundles, not fetched with production credentials.

The controller refuses paths outside the dedicated root, unexpected dirty
source, commit mismatches, pre-existing same-name project resources, mutable
tool references, or production-like environment material. Password-backed
sudo is supplied only through SSH standard input and is never written,
printed, placed in arguments, or stored in environment variables.

## Tool lock

A checked-in lock document records, at minimum:

- Buildx release asset URL and SHA-256;
- the BuildKit image digest used by the dedicated builder;
- the `tonistiigi/binfmt` image digest and expected ARM64 interpreter name;
- Trivy and Syft image digests;
- MariaDB 11.4 and Redis 7.4 image digests;
- the pinned base and resulting immutable ID for the local systemd-analysis
  image; and
- any helper image used for OCI-layout or provenance inspection.

The controller downloads or pulls only these identities, verifies the Buildx
checksum before making it executable, records resolved platform digests, and
fails on a mutable tag at the execution boundary. Nothing is pushed.

## `binfmt_misc` transaction

Before privileged execution the harness:

1. records whether `binfmt_misc` is available/enabled and captures every
   existing handler name and raw kernel-reported definition;
2. records the normalized semantic metadata for each handler: enabled state,
   interpreter, flags, offset, magic, and mask;
3. proves no ambiguous or incompatible ARM64 handler must be overwritten;
4. proves its cleanup command can target only the handler it will add; and
5. installs cleanup traps before registration.

If a usable ARM64 handler already exists, the harness leaves it untouched and
later proves the entire table unchanged. Otherwise it installs only the exact
ARM64 handler, proves an ARM64 container executes, and records the added name.
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
3. **Images:** build `web` and `racebot` from one RaceTime commit for
   `linux/amd64` and `linux/arm64`; create a local multi-platform OCI layout
   with BuildKit provenance; load per-architecture tags for smoke execution;
   verify platform, non-root runtime, process contract, and embedded commit.
4. **Security and SBOM:** scan every target/platform with pinned Trivy using
   the repository's HIGH/CRITICAL policy, generate SPDX JSON with pinned Syft,
   and validate that every report names the expected image identity.
5. **Services and configuration:** run the complete Django CI suite against
   isolated digest-pinned MariaDB 11.4 and Redis 7.4 with zero mandatory skips,
   then render production Compose with fixture-only values and inspect it
   without starting a production stack.
6. **Recovery and service hardening:** run the existing hermetic backup,
   decrypt, verify, restore, and failure-path behavior tests in containers; run
   `systemd-analyze security --offline` against TTPBot's exact unit in a pinned
   analysis image. No OCI endpoint or real backup key is used.
7. **Cross-repository evidence:** re-run candidate secret scans; compare the
   inherited Restream full-history findings with a reviewed metadata-only
   baseline without weakening the zero-finding candidate-range gate; verify
   the retained LiveSplit and provider artifacts already named by Task 6.
8. **Identities and gates:** create run-local immutable image identity input,
   run the checked-in release-identity collector, validate the evidence and
   traceability matrix, and report `PASS` only if every G0-due requirement is
   genuinely supportable. The harness does not fabricate version files,
   rewrite branches, or waive a collector mismatch.
9. **Cleanup:** remove only the dedicated builder, containers, networks,
   volumes, images designated transient by the run manifest, tool downloads,
   and readiness sentinels; restore/verify `binfmt_misc`; preserve only the
   source workspace and redacted evidence explicitly designated for custody.

## Evidence and provenance

The run produces a machine-readable JSON record plus a concise Markdown
summary. They contain exact source commits, tool versions/digests, OCI-layout
index and per-platform image digests, embedded revisions, scan/SBOM hashes,
test counts and skips, Compose hash, recovery/systemd results, prior/post
`binfmt` snapshot hashes, cleanup inventory, and final gate output. Logs are
captured per phase, scanned for credential canaries, reduced to safe summaries,
and not committed wholesale.

The final evidence is bound to one exact harness commit. Any executable harness
change after the remote run requires rerunning the affected live acceptance
path before G0 can pass.

## Failure behavior

- Every command has a timeout and checked exit status.
- Cleanup is registered before any Docker or kernel mutation.
- Evidence records `FAIL`, the phase, a safe error class, and cleanup result;
  it never records a phase as verified merely because an artifact exists.
- Failure to restore exact prior `binfmt` state is reported separately and is
  never hidden by the original failure.
- A failed cleanup, vulnerability threshold, mandatory skip, identity mismatch,
  dirty tree, missing digest, or validator failure leaves G0 at `HOLD`.

## Test strategy

Implementation follows TDD. Local tests use fake Docker/SSH/process adapters
and synthetic `binfmt` files to cover preflight, tool checksum/digest pinning,
command construction, both pre-existing-handler branches, success/failure/
signal cleanup, exact state comparison, project scoping, secret redaction,
artifact identity, phase ordering, and fail-closed evidence. Static contract
tests prove no publication or G1 command exists.

After local review, the authorized Synology acceptance run executes the real
controller from the exact commit, including an injected post-registration
failure rehearsal that proves restoration before the full run. Acceptance
requires all requested phases to pass, no mandatory skip, exact project
teardown, no tunnel/readiness residue, and exact prior `binfmt` state restored.

## Non-goals

This work does not publish images, create a public multi-platform manifest,
deploy RaceTime, use production credentials, contact production RaceTime or
Discord/Twitch endpoints, change NAS daemon configuration, create OCI/DNS/OAuth
resources, move schedulers, authorize G1, or alter unrelated NAS resources.
