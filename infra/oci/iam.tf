resource "oci_identity_dynamic_group" "racetime" {
  compartment_id = var.tenancy_ocid
  name           = "z1rr-racetime-instance"
  description    = "Only the dedicated Z1RR Raceroom instance"
  matching_rule  = "ALL {instance.id = '${oci_core_instance.racetime.id}'}"
  freeform_tags  = local.common_tags

  lifecycle {
    prevent_destroy = true
  }
}

locals {
  racetime_resource_scope = var.compartment_ocid == var.tenancy_ocid ? "in tenancy" : "in compartment id ${var.compartment_ocid}"
}

resource "oci_identity_policy" "racetime" {
  compartment_id = var.tenancy_ocid
  name           = "z1rr-racetime-instance"
  description    = "Narrow backup and custom-monitoring rights for RaceTime"
  freeform_tags  = local.common_tags

  statements = [
    "Allow dynamic-group ${oci_identity_dynamic_group.racetime.name} to read objectstorage-namespaces in tenancy",
    "Allow dynamic-group ${oci_identity_dynamic_group.racetime.name} to read buckets ${local.racetime_resource_scope} where target.bucket.name='${oci_objectstorage_bucket.backups.name}'",
    # ListObjects (OBJECT_INSPECT) cannot evaluate a per-object condition,
    # so the conditioned manage-objects statement below does not grant
    # listing. Retention enumerates manifests and needs this inspect grant.
    "Allow dynamic-group ${oci_identity_dynamic_group.racetime.name} to inspect objects ${local.racetime_resource_scope} where target.bucket.name='${oci_objectstorage_bucket.backups.name}'",
    "Allow dynamic-group ${oci_identity_dynamic_group.racetime.name} to manage objects ${local.racetime_resource_scope} where all {target.bucket.name='${oci_objectstorage_bucket.backups.name}', target.object.name='production/*'}",
    "Allow dynamic-group ${oci_identity_dynamic_group.racetime.name} to use metrics ${local.racetime_resource_scope} where target.metrics.namespace='z1rr_racetime'",
  ]

  lifecycle {
    prevent_destroy = true
  }
}
