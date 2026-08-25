# Read the existing Bastion subnet only to inherit its shared route table and
# DHCP options. Terraform must not manage or mutate that subnet.
data "oci_core_subnet" "bastion" {
  subnet_id = var.subnet_ocid
}

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
