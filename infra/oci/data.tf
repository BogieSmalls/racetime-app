# Existing Restream resources are evidence-only inventory. Never convert these
# data sources to resources or discover mutable infrastructure by display name.
data "oci_core_instance" "restream_inventory" {
  for_each = var.existing_restream_instance_ids

  instance_id = each.value
}

data "oci_core_boot_volume" "restream_inventory" {
  for_each = var.existing_restream_boot_volume_ids

  boot_volume_id = each.value
}
