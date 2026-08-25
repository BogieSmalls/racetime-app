# RaceTime Dedicated-Subnet Correction Design

**Date:** 2026-08-25  
**Status:** Approved by the technical operator  
**Scope:** Correct the inherited public-SSH exposure discovered immediately after the first OCI apply.

## Context and root cause

The first reviewed apply created the dedicated `racetime` A1 instance in the existing
`subnet-restream-public` subnet. The RaceTime network security group permits SSH only
from the OCI Bastion private endpoint, but the subnet's existing default security list
also permits TCP/22 from `0.0.0.0/0`. OCI combines security-list and NSG rules
additively, so the inherited rule makes the instance's public SSH port reachable.

The newly created instance was stopped as soon as this was verified. It contains no
application, credentials, or persistent user data.

## Considered approaches

1. **Dedicated RaceTime subnet (selected).** Create a `10.1.1.0/24` subnet in the
   existing `10.1.0.0/16` VCN. Give it a dedicated security list with no ingress and
   normal outbound access. Attach the RaceTime instance to that subnet; its NSG remains
   the only ingress policy and permits public HTTP/HTTPS plus Bastion-only SSH.
2. **Host firewall only.** Keep the shared subnet and rely on Ubuntu firewall rules to
   reject public SSH. This leaves the OCI network boundary misleading and permits
   unwanted traffic to reach the host.
3. **Modify the shared subnet security list.** Remove public SSH from the current
   Restream subnet. This could disrupt unrelated workloads and violates the existing
   read-only Restream boundary.

The dedicated subnet is the smallest change that gives RaceTime an independently
auditable network boundary without mutating existing Restream resources.

## Terraform design

- Continue consuming the existing VCN and current public subnet as data.
- Create one `oci_core_security_list` named `racetime` with no ingress rules and one
  stateful all-IPv4 egress rule.
- Create one regional `oci_core_subnet` named `racetime-public` at `10.1.1.0/24`.
  Reuse the existing subnet's route table and DHCP options so its public routing and DNS
  behavior remain consistent with the VCN. Set
  `security_list_ids = [oci_core_security_list.racetime.id]` explicitly so OCI cannot
  attach the VCN default security list. Set `prohibit_public_ip_on_vnic = false` and
  `dns_label = "racetime"`; the live VCN DNS label is `restream`, so the existing
  instance hostname contract resolves beneath `racetime.restream.oraclevcn.com`.
- Attach only the RaceTime instance VNIC to the new subnet and retain the existing
  RaceTime NSG.
- Set `create_vnic_details.assign_public_ip = false` on the replacement VNIC. Resolve
  its primary private-IP object with `data "oci_core_private_ips"`, constrained by both
  the new instance's private-IP address and the dedicated subnet ID. A lifecycle
  precondition requires exactly one result whose `is_primary` value is true. Create
  `oci_core_public_ip.racetime` with `lifetime = "RESERVED"` and `private_ip_id` set to
  that exact object's OCID. Protect the reserved address with `prevent_destroy` from its
  initial creation. DNS and TLS qualification use this stable address across later
  instance maintenance or replacement.
- Leave OCI Bastion in the existing subnet. Its private endpoint reaches the RaceTime
  private address within the same VCN, and the RaceTime NSG continues to authorize only
  that exact endpoint address for TCP/22.
- Keep IPv6 disabled. No AAAA record will be created.
- Protect the new subnet and security list with `prevent_destroy` from their initial
  creation and retain it throughout.

The dedicated subnet deliberately reuses the existing public route table and DHCP
options as read-only VCN plumbing. This is an accepted residual dependency: their live
IDs and default Internet Gateway route are verified before replacement, Terraform never
manages them, and any mismatch stops the correction. A dedicated route table would add
another resource without changing the ingress boundary that caused this incident.

## Corrective replacement

Because OCI cannot move a primary VNIC between subnets, the empty stopped instance must
be replaced once. `prevent_destroy` remains enabled throughout; the controlled sequence
never asks Terraform to destroy the instance:

1. Stage configuration that creates only the dedicated subnet and security list while
   leaving compute on the old subnet. Review and apply a saved full plan containing
   exactly those two additions. Both new resources have `prevent_destroy` from their
   first creation.
2. Before terminating anything, verify the unchanged Bastion subnet permits egress to
   `10.1.1.0/24:22`, and verify the inherited route table still has its expected public
   Internet Gateway route and DHCP options. A failure stops the correction without
   modifying Restream networking.
3. Pull the remote Terraform state into an ignored local evidence file, record its
   SHA-256, and verify the exact instance and boot-volume OCIDs, stopped/empty status,
   and absence of secondary VNICs or non-boot volume attachments.
4. Terminate only that stopped instance through OCI with boot-volume deletion selected.
   Wait for the instance to reach `TERMINATED`, then prove the exact boot volume is
   terminated and was not retained.
5. Create, review, and apply a saved `-refresh-only` plan that removes only the missing
   instance and derived outputs from Terraform state. Never use the automatically
   applied `terraform refresh` command.
6. Change the instance subnet reference to the dedicated subnet, disable ephemeral
   public-IP assignment, and add the reserved IPv4 attachment. Review and apply a saved
   normal plan containing one instance creation, one reserved public IP, the expected
   in-place RaceTime dynamic-group/CPU-alarm identity updates, and zero destroys or
   Restream changes. Change the Terraform public-IP output and every DNS/evidence
   consumer from the instance's ephemeral `public_ip` attribute to
   `oci_core_public_ip.racetime.ip_address`.
7. Prove that the live subnet's `security-list-ids` contains exactly the RaceTime list
   and excludes the VCN default list, the custom list has no ingress, the VNIC has only
   the RaceTime NSG, and the combined OCI rules expose no public SSH, MariaDB, or Redis.

Existing Restream instances, volumes, VNICs, subnet, route table, DHCP options, and
security list are never changed.

## Failure handling

- Keep the instance stopped until the safe-subnet plan has been reviewed.
- Reject any plan that changes or destroys an existing Restream resource.
- Reject any plan that exposes public TCP/22, 3306, or 6379.
- If the replacement cannot be created, retain the dedicated network resources and stop;
  do not weaken ingress or modify the shared subnet.
- Do not configure DNS until the safe replacement has a stable public IPv4 address.
- Record the exposure window in durable evidence: OCI instance creation time, the dated
  public-SSH discovery, the stop action, the key-only/no-application risk boundary, and
  the terminal instance and boot-volume proof.

## Verification

Tests and live checks must prove:

- Terraform owns exactly one dedicated subnet and security list for RaceTime.
- The dedicated security list contains zero ingress rules.
- The subnet uses the intended CIDR, exact custom security-list association, explicit
  public-VNIC setting, `racetime` DNS label, and inherited route/DHCP IDs.
- The instance VNIC uses the dedicated subnet and RaceTime NSG.
- The VNIC has no ephemeral public IP; the Terraform-managed reserved `racetime` IPv4
  address is attached to its primary private IP and is the only DNS target handed off.
  Live verification requires `lifetime=RESERVED`, `scope=REGION`, `state=ASSIGNED`,
  `assigned_entity_type=PRIVATE_IP`, and `assigned_entity_id` equal to the uniquely
  discovered primary private-IP OCID; an address that exists but remains unassigned
  fails the gate.
- Bastion remains active and its private endpoint is the sole SSH source in the NSG.
- The pre-termination Bastion egress proof is retained; after replacement, a time-limited
  port-forwarding session to the private IP completes a real SSH handshake and verifies
  its `racetime.racetime.restream.oraclevcn.com` private FQDN.
- Live effective-rule inspection finds no public TCP/22, 3306, or 6379.
- The replacement boot volume is exactly 50 GB Balanced at 10 VPUs/GB, and the original
  exposed boot volume is absent rather than retained or orphaned.
- A post-apply Terraform plan reports no drift.

The repository contract test that previously prohibited every Terraform-managed subnet
and security list is replaced with a narrower boundary: exactly one RaceTime subnet and
one RaceTime security list are required with the settings above, while Terraform remains
forbidden from managing or changing any Restream-named network resource.

Only after these checks pass may host bootstrap and the DNS handoff continue.
