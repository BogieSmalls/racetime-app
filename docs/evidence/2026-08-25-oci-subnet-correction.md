# OCI subnet correction evidence

**Status:** IN PROGRESS — pre-apply baseline recorded; no corrective plan or apply has run.

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

## Current gate

- Corrective Terraform plan: not created
- Corrective Terraform apply: not run
- DNS: unchanged
- Host bootstrap: not started
- Existing Restream resources: not mutated

The next permitted action is a clean-source saved plan whose only mutable actions are
creation of `oci_core_security_list.racetime` and `oci_core_subnet.racetime`.
