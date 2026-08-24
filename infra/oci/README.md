# Z1RR RaceTime OCI infrastructure

This root module defines only the dedicated `racetime` platform and its direct
supporting resources. It consumes explicit IDs for the existing VCN, subnet,
ARM64 image, and read-only Restream inventory. It never discovers mutable
resources by display name.

## G0 boundary

**No G0 apply.** G0 is local formatting, static tests, and provider-schema
validation only. Do not run a credentialed plan, create a backend, query the
tenancy through Terraform, or change OCI, DNS, GitHub, Discord, or any live
service.

From the repository root:

```powershell
terraform -chdir=infra/oci fmt -check -recursive
terraform -chdir=infra/oci init -backend=false
terraform -chdir=infra/oci validate
terraform -chdir=infra/oci test
```

The required `activation_record` has no default. A non-interactive plan without
the dated G1 value fails before it can propose resources.

## Managed boundary

A reviewed first plan may create only:

- one `racetime` `VM.Standard.A1.Flex` instance, initially 1 OCPU / 6 GB;
- its image-created 50-GB Balanced boot volume at 10 VPUs/GB;
- one NSG and its explicit HTTP, HTTPS, Bastion SSH, and egress rules;
- one standard OCI Bastion;
- one private, versioned encrypted-backup bucket;
- one instance-only dynamic group and narrow backup/metric policy;
- one Notifications topic, configured subscriptions, and reviewed alarms.

The instance, embedded boot volume, NSG, Bastion, bucket, dynamic group, policy,
and topic are destruction-protected. OCI creates an image-backed boot volume as
part of instance launch; `prevent_destroy` on the instance, `preserve_boot_volume
= true`, and `is_preserve_boot_volume_enabled = true` protect that 50-GB volume.

`z1rr-restream-control`, `z1rr-restream-control-staging`, the encoders, and all
five retained boot volumes are data-only inventory. Any proposed change to one
of them stops the plan. In particular, `z1rr-restream-control-staging` remains
available for Restream staging.

TCP 443 stays open to `0.0.0.0/0` and optional `::/0` so unpredictable ACME
multi-perspective validators can complete TLS-ALPN-01. TCP 80 is Caddy redirect
or generic restricted-denial traffic only. The pre-G3 source restriction lives
in Caddy after the TLS handshake, never in an OCI NSG, security list, or host
firewall. Port 22 has no public rule; operators use time-limited OCI Bastion
sessions from explicitly listed client CIDRs.

## G1 preflight

After Plan B is activated, record and independently verify:

1. the dated activation reason and operator;
2. paid-tenancy status and the current 3,000 A1 OCPU-hour / 18,000 GB-hour
   allowance;
3. current-month usage, slope, and the dated combined RaceTime/Restream
   forecast;
4. the exact compartment, region, availability domain, VCN, subnet, ARM64 image,
   Object Storage namespace, and operator CIDR values;
5. the existing Restream instance and boot-volume IDs from read-only inventory;
6. A1 capacity and quota for the default shape;
7. the expected 744-hour RaceTime floor, retained-volume baseline of about
   $3.61/month, and Object Storage byte/request entitlement assumptions;
8. tested OCI tenancy, GitHub organization, container registry, and
   authoritative DNS account-recovery routes.

A mismatch is recorded and repriced. It does not silently change Terraform.

## Native OCI backend

Terraform 1.12 or newer provides the native OCI backend with state locking.
Create or designate a separate private, versioned state bucket under the
operator's infrastructure identity before initializing G1. Do not use the
application backup bucket from this module as its own backend.

Keep backend coordinates and authentication outside Git in a root-owned file:

```hcl
bucket              = "REPLACE_TERRAFORM_STATE_BUCKET"
namespace           = "REPLACE_NAMESPACE"
key                 = "z1rr-racetime/production.tfstate"
region              = "us-ashburn-1"
auth                = "SecurityToken"
config_file_profile = "Z1RR"
```

Initialize without putting credentials on the command line:

```powershell
terraform -chdir=infra/oci init -reconfigure -backend-config=C:\secure\z1rr-racetime-backend.hcl
```

Object Storage encrypts the state at rest; use a customer-managed KMS key when
the tenancy's recovery design supplies one. Restrict bucket access to the
primary operator and the verified account-recovery route. Versioning and native
locking are mandatory. Never store authentication material in configuration,
`.tfvars`, plan files, shell history, or repository artifacts.

## Saved-plan workflow

Copy `terraform.tfvars.example` to an ignored local file, replace every marker,
and keep the two public SSH keys distinct. Then:

```powershell
terraform -chdir=infra/oci fmt -check -recursive
terraform -chdir=infra/oci validate
terraform -chdir=infra/oci plan -input=false -out=racetime.tfplan
terraform -chdir=infra/oci show -json racetime.tfplan
```

The operator records the plan SHA-256 and reviews the JSON for every create,
update, delete, or replace action. Expected actions are only the managed
boundary above. Stop if the plan changes an existing Restream resource, selects
a shape other than the recorded shape, source-restricts 443, permits public SSH,
contains a secret, or deletes/replaces any protected resource.

Apply exactly the reviewed saved plan:

```powershell
terraform -chdir=infra/oci apply -input=false racetime.tfplan
```

Do not recreate a plan between approval and apply. After apply, record the plan
hash, Terraform/provider versions, resource IDs, boot size/VPUs, shape, NSG
rules, bucket privacy/versioning, Bastion source CIDRs, dynamic-group match,
policy statements, subscription confirmation state, alarms, usage forecast, and
Cost Analysis baseline. DNS and application deployment are later gated steps.

## Import and state recovery

The normal path creates new dedicated resources; it imports none of the
Restream inventory. If an interrupted first apply created a reviewed resource
but lost its state mapping, recover the remote state version first. Only if no
valid state version exists, compare the OCI resource field-by-field with the
saved plan and import to its exact address, for example:

```powershell
terraform -chdir=infra/oci import oci_core_instance.racetime ocid1.instance.oc1..REPLACE
terraform -chdir=infra/oci import oci_core_network_security_group.racetime ocid1.networksecuritygroup.oc1..REPLACE
terraform -chdir=infra/oci import oci_bastion_bastion.racetime ocid1.bastion.oc1..REPLACE
terraform -chdir=infra/oci import oci_objectstorage_bucket.backups n/REPLACE_NAMESPACE/b/REPLACE_BUCKET
terraform -chdir=infra/oci import oci_identity_dynamic_group.racetime ocid1.dynamicgroup.oc1..REPLACE
terraform -chdir=infra/oci import oci_identity_policy.racetime ocid1.policy.oc1..REPLACE
terraform -chdir=infra/oci import oci_ons_notification_topic.operations ocid1.onstopic.oc1..REPLACE
```

Import individual NSG rules, subscriptions, and alarms only with the exact import
form returned by their provider documentation and the recorded OCI IDs. Never
import the embedded boot volume as a standalone `oci_core_boot_volume`: the OCI
provider cannot represent an image-created volume that way reliably. Never
import a Restream resource into this state.

After any recovery, run a saved plan and require zero unreviewed actions before
resuming operations. A missing/ambiguous state mapping blocks apply.

## Resize and paid amd64 recovery

The standing default is 1 OCPU / 6 GB because RaceTime cannot duty-cycle. If the
G2 load gate misses, the primary technical operator chooses optimization or a
resize and records the reason, updated combined forecast, Terraform change, and
replacement load/restore evidence. There is no launch waiver.

For A1 capacity loss, rebuild from Git, the same release's `linux/amd64` image,
configuration, sealed recovery material, and verified Object Storage backups on
`VM.Standard.E5.Flex`, initially 1 OCPU / 6 GB. Record any different recovery
shape and run the same performance and restore gates. The fallback is not
provisioned by this module.

Infrastructure rollback means applying a separately reviewed prior
configuration or a forward repair. It never means destroying the protected
instance/bucket, restoring qualification data, or bypassing the load/restore
gates. If a shape change fails, stop the application, preserve and verify the
boot volume and backups, restore the last recorded shape in Terraform, generate
and review a new saved plan, apply it, and rerun recovery evidence.

## Account recovery

Before G1 apply, verify a route for a formally designated replacement to obtain
OCI tenancy administration, GitHub organization and container registry
ownership, and authoritative DNS control. This may be a second account owner,
sealed recovery material, or the platform's documented ownership-recovery
process. It grants no routine approval role. The sealed package separately
contains the recovery SSH credential and backup decryption material; using it
requires rotation, retest, and resealing.

## Primary references

- [OCI Compute instance Terraform resource](https://registry.terraform.io/providers/oracle/oci/latest/docs/resources/core_instance)
- [OCI NSG rule Terraform resource](https://registry.terraform.io/providers/oracle/oci/latest/docs/resources/core_network_security_group_security_rule)
- [OCI Bastion Terraform resource](https://registry.terraform.io/providers/oracle/oci/latest/docs/resources/bastion_bastion)
- [OCI Object Storage bucket Terraform resource](https://registry.terraform.io/providers/oracle/oci/latest/docs/resources/objectstorage_bucket)
- [Terraform native OCI backend](https://developer.hashicorp.com/terraform/language/backend/oci)
- [OCI Object Storage metrics](https://docs.oracle.com/en-us/iaas/Content/Object/Reference/objectstoragemetrics.htm)
- [OCI Object-level IAM policies](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/managingobjects.htm)
