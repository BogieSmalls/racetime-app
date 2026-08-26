# OCI A1 G0 Worker Harness Design

**Status:** Selected and operator-authorized

**Date:** 2026-08-26

**Supersedes for worker selection:**
[Synology G0 worker harness design](2026-08-25-synology-g0-worker-harness-design.md)

**Control documents:**

- [Architecture specification](2026-08-12-plan-b-racetime-architecture-design.md)
- [Requirements and decisions](../../racetime-z1rr/requirements-and-decisions.md)
- [Launch master plan](../plans/2026-08-22-z1rr-racetime-launch-master.md)
- [Current G0 evidence](../../evidence/2026-08-24-g0-readiness.md)
- [Dedicated-subnet correction](2026-08-25-racetime-dedicated-subnet-correction-design.md)

## Decision

Use the dedicated `racetime` OCI instance as the G0 qualification worker before
it hosts public RaceTime traffic. The instance is a native ARM64
`VM.Standard.A1.Flex` with 1 OCPU, 6 GB RAM, a 50-GB Balanced boot volume, a
reserved IPv4 address, and the independently verified dedicated subnet and NSG
boundary. Public DNS, TLS, OAuth, RaceTime application state, and production
credentials remain absent during G0.

This choice follows the operator's explicit rejection of Docker on the Windows
workstation and the Synology spike's proof that DSM's older kernel cannot
provide the required modern `binfmt_misc` runtime contract. GitHub-hosted CI
would still split the evidence across workflows and would not supply the real
backup/restore and cleanup transaction.

The earlier Synology design remains authoritative for the qualification phases,
artifact linkage, release-identity correction, evidence schema, and two-stage
closeout. This design replaces only its worker, host bootstrap, architecture,
resource floor, transport, and `binfmt_misc` sections.

## Host boundary

Docker Engine is a persistent prerequisite for the eventual RaceTime service,
not a disposable G0 tool. Install the pinned Docker CE engine, CLI, containerd,
and Compose plugin from Docker's signed Ubuntu Noble ARM64 repository. Record
the repository key digest, source definition, exact package versions, daemon
version, and Compose version. Do not use the convenience script, expose a TCP
Docker API, add the operator account to the root-equivalent `docker` group, or
change OCI security rules. Docker commands run through `sudo`.

The bootstrap validates that Docker uses a Unix socket, the daemon has no
insecure registry or remote listener, forwarding uses a supported iptables
backend, and no existing host port conflicts with the qualification manifest.
The harness forbids public port publication. A container may publish a port
only to an explicitly declared loopback address and high port; the service and
backup phases normally use internal Docker networks with no published port.
The OCI NSG remains a separate outer boundary and is rechecked after bootstrap
and cleanup.

All other G0 tooling is workspace- or project-scoped. The run root is
`/var/lib/z1rr-racetime/g0/<run-id>`, owned by root and not reused across
commits. The source staging directory may begin under the operator's home for
SCP, but the bootstrap verifies its manifest before an exact move into the run
root. Docker builders, containers, networks, volumes, cache, and images use the
`z1rr-racetime-g0-<run-id>` prefix and qualification labels.

## Native and emulated architectures

The host builds and runs `linux/arm64` natively. Only `linux/amd64` requires
emulation. A workspace-local checksum-pinned Buildx CLI controls a dedicated
digest-pinned Docker-container BuildKit builder. The builder exports one
multi-platform OCI layout for each of `web` and `racebot`; nothing is pushed.

Before any privileged emulator registration, the harness snapshots the host's
complete `binfmt_misc` state in raw and normalized form and installs cleanup
traps. If a compatible enabled `qemu-x86_64` handler with the `F` flag already
exists, it is used without mutation and the entire table must remain unchanged.
Otherwise a digest-pinned `tonistiigi/binfmt` container may add only the locked
amd64 handler. The harness proves a pinned amd64 container reports `x86_64`
before building. It never installs `all`, changes the table's enabled state,
mounts `binfmt_misc` persistently, or touches another handler.

The install branch performs one injected post-registration failure rehearsal
before qualification. Success, failure, signal, and timeout cleanup removes
only the added handler and proves the exact pre-run raw bytes, normalized
metadata, handler names, mount/enabled state, and flags are restored. Cleanup
failure is a separate failed gate. Registration is temporary host-global
kernel state even though Docker starts the installer.

## Resource and timing contract

Preflight records kernel, architecture, CPU, memory, swap, filesystem, and
Docker storage facts. It requires at least 5.5 GiB total memory, 3.5 GiB
currently available, and 24 GiB free under the Docker/run-root filesystem.
BuildKit concurrency is one. The harness does not create swap or resize the VM;
resource failure stops qualification and is evidence for an operator sizing
decision.

Native ARM64 build/smoke phases receive 90 minutes per image. Emulated amd64
build/smoke phases receive 300 minutes per image. Scanner, service-backed test,
backup/restore, systemd, and cross-repository phases each have explicit budgets
in the run manifest, with an overall worker maximum of 12 hours. A timeout is a
failure followed by cleanup, never a skip.

## Inputs and transport

The workstation creates tracked-file archives and complete verified Git bundles
for the exact clean RaceTime, Restream, TTPBot, and LiveSplit commits. A
machine-readable transfer manifest contains repository name, branch, commit,
bundle/archive SHA-256, file count, and allowed destination. Required retained
artifacts travel under a separate hash-listed manifest. No GitHub, registry, or
production application credential is copied to the host.

The invoke script uses the existing OCI Bastion path and host-key-pinned SSH/SCP.
It accepts instance, Bastion, key, and run identifiers as runtime inputs; none
are committed. SSH credentials remain in the operator's existing local key
store. Temporary Bastion sessions and local listeners are created only after
cleanup traps are active and must be absent at the end.

The remote controller refuses dirty or shallow source, commit/branch mismatch,
unverified bundles or archives, paths outside the run root, symlinks at custody
boundaries, mutable tool references, production-like secrets, existing
same-name Docker resources, and unapproved host publications.

## Tool lock and supply chain

A checked-in JSON lock records exact versions, download URLs, SHA-256 values,
and image index/platform digests for:

- the workspace-local Buildx binary and pinned BuildKit image;
- the amd64 `binfmt` installer and runtime probe;
- the OCI-layout inspector/importer;
- Trivy plus its database schema/version/update time/digest;
- Syft;
- MariaDB 11.4 and Redis 7.4;
- the backup/restore runner and offline systemd-analysis image; and
- any small runtime probe image.

The controller verifies a downloaded binary before extraction or execution and
resolves every container reference to a platform digest before use. A tag is
informational only; the execution boundary uses the locked digest. Tool-lock
resolution is a separate read-only preparation command and never silently
updates the lock during a qualification run.

## Qualification phases

The ordered nine-phase model from the Synology design remains in force, with
these OCI-native refinements:

1. **Preflight:** also prove the exact reviewed OCI instance/network identity,
   persistent Docker bootstrap contract, native ARM64 host, resource floor,
   transfer custody, and RaceTime Gitleaks gate.
2. **Worker setup:** use native ARM64 BuildKit plus the transactional amd64
   handler; do not install an ARM64 handler.
3. **Images:** build each service once into a dual-platform OCI layout with
   provenance. Select and import the exact platform manifests from that layout;
   no second smoke build is allowed.
4. **Security and SBOM:** join every Trivy and SPDX result cryptographically to
   the selected layout manifest/config/layers and record Trivy DB provenance.
5. **Services and configuration:** run all service-dependent Django tests
   against isolated digest-pinned native ARM64 MariaDB/Redis with zero mandatory
   skips, then render production Compose using fixtures without starting it.
6. **Recovery and service hardening:** run a real isolated MariaDB dump,
   encrypt/compress/archive, destroy/recreate/import/migrate/validate rehearsal
   with a run-generated test key and local transport double; run offline
   `systemd-analyze security` for TTPBot in a networkless pinned container.
7. **Cross-repository evidence:** run candidate secret scans, reconcile the
   metadata-only Restream inherited-history baseline, and verify retained
   TTPBot/LiveSplit/Restream artifacts without exposing matches or credentials.
8. **Identities and gates:** use component-specific versions or RaceTime's
   explicit `commit-only` policy, collect release identities, validate evidence
   and traceability, and emit `WORKER_QUALIFICATION=PASS` only if every worker
   gate passes.
9. **Cleanup:** remove exact G0 Docker resources, transient OCI layouts/blobs,
   tools, test keys, source staging, Bastion session/listener, and any added
   amd64 handler. Preserve only declared retained evidence/source custody.
   Docker Engine remains installed for the later RaceTime deployment.

## Evidence and closeout

The worker writes a machine-readable run record and redacted Markdown summary
under the run root. In addition to the inherited evidence fields, record Docker
package identities, native host facts, selected amd64/arm64 identities,
per-platform elapsed time, complete pre/post `binfmt_misc` snapshots, exact
cleanup inventory, and post-run OCI network recheck.

The remote run ends with `WORKER_QUALIFICATION=PASS` or a failed phase plus
cleanup status; it does not mark G0 complete. The operator imports only the
declared redacted evidence, performs a docs/checklist/traceability closeout
commit, proves that the qualified commit to closeout diff contains no executable
or candidate-source change, and reruns final validators. Any executable change
invalidates the affected remote evidence.

## Failure behavior

- Install cleanup before Docker project or `binfmt_misc` mutation.
- Check every exit status and timeout; never convert a skip into a pass.
- Keep Docker bootstrap failure separate from qualification cleanup. If a
  partially installed engine cannot meet the persistent host contract, stop and
  report exact package/service state rather than improvising removal.
- Preserve enough redacted evidence to diagnose a gate, but never raw secrets,
  repository credentials, Discord/OAuth tokens, private keys, or unredacted
  scanner matches.
- Do not continue to public DNS/TLS/application qualification on a G0 failure.

## Non-goals

This phase does not publish images, push a manifest, start the public or
restricted RaceTime stack, create application data, issue TLS, configure DNS,
create OAuth applications, use production credentials, move schedulers, alter
Restream infrastructure, resize the VM, add swap, open OCI ports, or authorize
G2/G3. It does not uninstall Docker after G0 because Docker is part of the
approved RaceTime host architecture.
