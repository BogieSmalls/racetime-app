# OCI subnet correction evidence

**Status:** IN PROGRESS — additive network boundary verified; exposed instance remains stopped and has not been terminated.

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
- Continuing post-transition baseline SHA-256: `bf8d0d1b67518b15d820d9ee4d5d7a9d7dbf091b2d4db1f80ca5054f4f7d6f3e`
- Both normalized inventories and the raw Audit response remain ignored local evidence.

The lifecycle transition is therefore classified as an independent duty-cycle action,
not a Terraform mutation. The post-transition inventory is the continuing baseline for
the replacement and no-drift checks; the original baseline remains retained for audit.

## Current gate

- Dedicated subnet/security list: created and live-verified
- Exposed RaceTime instance: still stopped; termination not started
- Restream infrastructure mutation by this correction: none
- DNS: unchanged
- Host bootstrap: not started

The next permitted action is the pre-termination Bastion/routing/target proof. Instance
termination remains blocked until that proof passes.
