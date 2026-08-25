# OCI subnet correction evidence

**Status:** IN PROGRESS — additive network boundary verified; exposed empty instance and its boot volume disposed; Terraform state reconciliation pending.

## Reason for correction

The first `racetime` instance inherited the existing Restream subnet's default security
list, which permits public TCP/22. OCI combines security-list and NSG allows, so the
RaceTime NSG's Bastion-only SSH rule could not override that inherited rule. The new,
unconfigured instance was stopped immediately after live verification. It remains stopped
at this evidence boundary.

The approved correction creates a RaceTime-only subnet and zero-ingress security list,
then disposes of the stopped empty instance and recreates it with a reserved IPv4 address.
Existing Restream resources remain read-only.

## Pre-mutation Restream baseline

- Captured: `2026-08-25T20:01:02.399737Z`
- Source commit: `04650a8dd72e8b259418f4b79ea4dfdce3d4377d`
- Raw normalized baseline: ignored local evidence only
- Raw baseline SHA-256: `c811904c262bbc6ac3b004c2c0edb0f780ce34b0b652f73f2038f2aaf4d29ed6`
- Explicit-ID inventory: 4 instances, 4 VNIC attachments, 4 VNICs, and 5 retained boot volumes
- Captured fields: lifecycle, shape/OCPU/RAM, availability domain, VNIC attachment and
  primary-VNIC identity, subnet/VCN/NSG/security-list/route/DHCP identity, public/private
  addressing, and boot attachment/size/VPU state

The baseline was built only from the explicit instance and boot-volume IDs in the ignored
production tfvars. No display-name discovery was used. Raw OCIDs, private addresses, and
CLI responses are not committed.

## Additive network plan and apply

- Plan source commit: `238f686173a5930654d871b8347cacd0beb23c18`
- Full diagnostic plan SHA-256: `1555527ff07b49204669bfbb17df8bca0ff91a61ced3dcb46b0eee6d63ef9f47`
- Full diagnostic JSON SHA-256: `ec54c7bfefd5d5d3ef7b2b5f0cb58e063ff71840942d836b0ef5414238c2fad8`
- Diagnostic action set: create only `oci_core_security_list.racetime` and
  `oci_core_subnet.racetime`, plus the previously classified in-transit-encryption
  update on the stopped disposable RaceTime instance. The diagnostic plan was never
  applied.
- Targeted saved-plan SHA-256: `6528816d8c9ca48d771f181fa444ecea823f35eff78a8853b25770a3b3f9eb3a`
- Targeted custody JSON SHA-256: `9145ab4d50b7cb8b32ab147101e2263f9aaa70f06fed23b260a00f1493240a9f`
- Saved-plan verifier: PASS immediately before apply; exactly two creates, zero drift,
  zero output changes, and no Restream action
- Apply: exit 0 from the exact verified saved plan; no full diagnostic plan was applied

## Live additive boundary

Seventeen fail-closed live checks passed against OCI API responses and Terraform state:

- Subnet is `AVAILABLE`, regional, `10.1.1.0/24`, DNS label `racetime`, and permits
  public VNIC assignment without inheriting the VCN default security list.
- The subnet retains the exact reviewed route-table and DHCP identities and references
  exactly one custom security list.
- The custom list has zero ingress and exactly one stateful, all-protocol IPv4 egress
  rule to `0.0.0.0/0` with `CIDR_BLOCK` destination type.
- Subnet identity SHA-256: `585b0f9a263017e6ed19b8b8c06f389d4935c15c7b4c5ff08af1b9669879c93f`
- Security-list identity SHA-256: `db1555e1e8615e69fcb7494394de78494d14082c4523dd5d7951e6cf2b58fdba`
- The original RaceTime instance remains `STOPPED`, 1 OCPU/6 GB, with one VNIC still
  on the original Restream subnet and its original 50-GB/10-VPU boot volume `AVAILABLE`.

## Independently audited Restream duty-cycle transition

The first post-apply recapture differed from the pre-mutation baseline in exactly one
field: `control_staging.state` changed from `RUNNING` to `STOPPED`. OCI Audit records a
successful `SOFTSTOP` `InstanceAction` at `2026-08-25T16:47:34.632-04:00`, 35 seconds
after the subnet apply completed. The caller was the existing Oracle Python SDK/CLI on
Linux automation family, not Terraform. Every other captured field across all four
instances, four VNIC attachments, four VNICs, five boot volumes, and their attachments
matched the original baseline exactly.

- Audited transition summary SHA-256: `3b4e9a9c3d1899a4852214b4ad71fa8e0f57740d84da4c94393d2e056a581cce`
- Raw OCI Audit response SHA-256: `b1a7130afaf5020e7ea36d3cc1c1bb878ba15b55e5104dbfadc7360b06041855`
- Continuing post-transition baseline SHA-256: `bf8d0d1b67518b15d820d9ee4d5d7a9d7dbf091b2d4db1f80ca5054f4f7d6f3e`
- Both normalized inventories and the raw Audit response remain ignored local evidence.

The lifecycle transition is therefore classified as an independent duty-cycle action,
not a Terraform mutation. The post-transition inventory is the continuing baseline for
the replacement and no-drift checks; the original baseline remains retained for audit.

## Pre-termination proof

The deletion target was resolved only from a fresh remote Terraform state pull at source
commit `9cb6c113709a1f46d267f9fc5a4b6bb5158da5ae`. The ignored state bytes have SHA-256
`72c1904f7eec4194c50f38dfbab3798a3cdbdcb368328ec252bea7d0a8a2048d`.

Fresh OCI API reads passed every fail-closed network gate before deletion:

- Bastion was `STANDARD` and `ACTIVE`, targeted the exact existing subnet, and retained
  the exact one-entry restricted operator CIDR allowlist. Neither world-open CIDR was
  present.
- The RaceTime NSG had four rules in total and exactly one rule that could reach SSH:
  stateful TCP/22 from the current Bastion private endpoint `/32`. No other public or
  private source could reach SSH through the NSG.
- The existing Bastion subnet's one security list retained stateful, all-protocol IPv4
  egress covering `10.1.1.0/24:22`.
- The inherited route table retained one `0.0.0.0/0` CIDR route to an enabled,
  `AVAILABLE` Internet Gateway in the same VCN. The route-table and DHCP identities
  exactly matched both Terraform state and the dedicated subnet.

The exact state instance then passed the target gate: display name `racetime`, lifecycle
`STOPPED`, shape `VM.Standard.A1.Flex`, 1 OCPU/6 GB, exactly one attached primary VNIC
on the original subnet, zero block-volume attachments, and exactly one attached,
`AVAILABLE` 50-GB/10-VPU boot volume created with the instance. The five retained
Restream boot-volume identities were distinct from the deletion target. There was no
application bootstrap metadata, extended metadata, iPXE bootstrap, application volume,
or application data.

Safe target identity hashes:

- Instance SHA-256: `1325ff401b450793a568ebc86a081669614bfeef7973d24cfca4f6ef72683450`
- Boot-volume SHA-256: `bf8b4fec4dbb1b65ab1669858b024ab21494ee3c5c7304b1b491346197d2ac30`
- Primary-VNIC SHA-256: `bfbdd3fab4b8f8a39cabb9d63bd1d5219b99446be0f6ef42ed4b72fcdb7eeb5b`

## Exposure window and risk boundary

- OCI instance creation: `2026-08-25T12:01:45.185-04:00`
- Audit-visible discovery sequence: exact VNIC read at `2026-08-25T12:06:55.519-04:00`,
  subnet read at `12:06:59.578-04:00`, and the inherited security-list read that
  confirmed the source rule at `12:07:02.759-04:00`
- Successful `STOP` request accepted: `2026-08-25T12:07:21.877-04:00`
- Conservative creation-to-stop exposure: 5 minutes, 36.692 seconds
- Raw early-window OCI Audit capture SHA-256:
  `0a3227c526356ee95bf30c45864073d629de2a2a987d30b90822dd76eac3cfa9`

The inherited source was the existing shared subnet's public TCP/22 rule. Access was
configured for SSH public keys only on an unconfigured Ubuntu image. No application
bootstrap ran; no application, production credential, secret, database, media, or user
data was present. The instance remained stopped from the recorded stop through disposal.

## ETag-protected disposal

Immediately before deletion, OCI re-reads reconfirmed the exact target as `STOPPED` with
one primary VNIC, no block-volume attachments, and the same attached 50-GB/10-VPU boot.
A raw regional Compute `GET` returned `200 OK`, the same exact identity and state, and an
ETag stored only in ignored evidence. Its SHA-256 was
`126132a40c8118e0e2c2062cf298754b1289d52156ea43087a752b132b2be439`.

The OCI CLI then terminated only that exact instance with the captured ETag,
`--preserve-boot-volume false`, `--force`, and a `TERMINATED` lifecycle waiter. The
waiter exited successfully. Independent post-wait reads proved:

- The exact instance is `TERMINATED`.
- The exact boot volume is `TERMINATED` in both its direct read and the availability-
  domain boot-volume list.
- All five retained Restream boot volumes remain readable by their exact state
  identities, and none is the disposed target.

Ignored evidence custody hashes:

- Final pre-delete summary:
  `fb8df24d35ce4b475db9eb0c171739353554777a2e1f8c1be00773c7c1d587e4`
- Raw pre-delete Compute response:
  `c9027d87bb80e7cfca23be6a5e1def13734567fad869b90a33aee4c5b1e48e46`
- Termination/waiter response:
  `14ab1c1e8b218bcd863857f626d1c8c2c3e3acdde0658c2bcd1eecc754501e06`
- Post-termination instance response:
  `0f78287b34393146c6d35ad7ce37bb3c2ffe2bfcdbe55568ea7acf70620ed54f`
- Post-termination boot list:
  `9bf66e5424910ad09d2a111d7d5790d65be8d18c82fd0d863a0e9455ec11c585`
- Post-termination direct boot response:
  `cb067fc6562f225041c8b73b6625a4665c8ad0981043dd8c358dde439bcf66f4`
- Redacted termination summary:
  `8e45819549362fe6688fd18f0cb0297bf558d5b4a9ef0d9826d4b21168ec6613`

No Terraform destroy, state refresh, `prevent_destroy` change, Restream mutation, DNS
change, Docker action, host bootstrap, or G1+ service action occurred in this task.

## Current gate

- Dedicated subnet/security list: created and live-verified
- Exposed RaceTime instance: terminated by exact state identity with ETag protection
- Exposed RaceTime boot volume: terminated; not preserved or orphaned
- Restream infrastructure mutation by this correction: none
- DNS: unchanged
- Host bootstrap: not started

The next permitted action is saved refresh-only state reconciliation. Replacement
planning remains blocked until the stale terminated instance is removed from Terraform
state by that reviewed refresh-only path.
