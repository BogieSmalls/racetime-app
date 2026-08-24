resource "oci_identity_dynamic_group" "racetime" {
  compartment_id = var.tenancy_ocid
  name           = "z1rr-racetime-instance"
  description    = "Only the dedicated Z1RR RaceTime instance"
  matching_rule  = "ALL {instance.id = '${oci_core_instance.racetime.id}'}"
  freeform_tags  = local.common_tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_identity_policy" "racetime" {
  compartment_id = var.tenancy_ocid
  name           = "z1rr-racetime-instance"
  description    = "Narrow backup and custom-monitoring rights for RaceTime"
  freeform_tags  = local.common_tags

  statements = [
    "Allow dynamic-group ${oci_identity_dynamic_group.racetime.name} to read objectstorage-namespaces in tenancy",
    "Allow dynamic-group ${oci_identity_dynamic_group.racetime.name} to read buckets in compartment id ${var.compartment_ocid} where target.bucket.name='${oci_objectstorage_bucket.backups.name}'",
    "Allow dynamic-group ${oci_identity_dynamic_group.racetime.name} to manage objects in compartment id ${var.compartment_ocid} where all {target.bucket.name='${oci_objectstorage_bucket.backups.name}', target.object.name='production/*'}",
    "Allow dynamic-group ${oci_identity_dynamic_group.racetime.name} to use metrics in compartment id ${var.compartment_ocid} where target.metrics.namespace='z1rr_racetime'",
  ]

  lifecycle {
    prevent_destroy = true
  }
}
