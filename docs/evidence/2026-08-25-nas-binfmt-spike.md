# Synology ARM64 binfmt capability spike — 2026-08-25

## Result

**NAS ARM64 runtime registration: NOT SUPPORTED by the tested path.**

The Synology remains clean and usable for native-amd64 Docker qualification,
but it cannot provide the design's host-registered ARM64 runtime smoke with the
tested modern `tonistiigi/binfmt` mechanism.

## Boundary

The operator authorized one host-key-pinned capability spike using password-
backed sudo through SSH standard input. No credential was printed, stored,
placed in an argument or environment variable, or retained in a helper.

Pinned inputs:

- `tonistiigi/binfmt:qemu-v10.2.3` manifest digest
  `sha256:400a4873b838d1b89194d982c45e5fb3cda4593fbfd7e08a02e76b03b21166f0`;
- `alpine:3.22` manifest digest
  `sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce`.

## Preflight

- SSH host-key verification passed.
- NAS architecture: `x86_64`.
- Docker client/server: `24.0.2`.
- Measured memory: 16,234,504 KiB total and approximately 14.9 million KiB
  available during the probes.
- The kernel advertises `binfmt_misc`.
- The NAS host namespace had no `binfmt_misc` mount and no handler.

## Execution

The spike mounted `binfmt_misc` only inside an ephemeral privileged helper,
snapshotted the empty/enabled table, and invoked the pinned installer with
`--install arm64`. The installer process returned success, but a separate
private-mount snapshot found no handler and the pinned image's status output
reported no emulator. The fail-closed assertion stopped before ARM64 workload
execution.

This behavior is consistent with the NAS's Linux 4.4 kernel lacking the
`fix_binary` support required by modern container QEMU registration.
[Docker's documented manual-QEMU prerequisites](https://docs.docker.com/build/building/multi-platform/#install-qemu-manually)
require kernel 4.8 or later and an `F`-flag registration.

## Cleanup proof

Each attempt:

- found no pre-existing handler;
- attempted removal only of `qemu-aarch64`;
- removed spike-pulled image references;
- compared the post-run private-mount snapshot with the pre-run snapshot; and
- verified the NAS host namespace still had no `binfmt_misc` mount.

The final independent read-only probe again reported:

```text
kernel_binfmt=yes
host_mount=no
status=unavailable
handler_count=0
```

Temporary local helpers were deleted. No container, project network, volume,
daemon setting, package, sudoers entry, persistent mount, source workspace,
OCI/DNS/OAuth resource, production credential, or G1 state was created or
changed.

## Disposition

Do not write the Synology G0 implementation plan against the original
host-registered ARM64 design. Select a modern Linux worker, or separately
redesign and review ARM64 runtime evidence before implementation.
