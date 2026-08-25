# Read the existing Bastion subnet only to inherit its shared route table and
# DHCP options. Terraform must not manage or mutate that subnet.
data "oci_core_subnet" "bastion" {
  subnet_id = var.subnet_ocid
}

# Resolve the replacement instance's unique primary private IP only inside the
# dedicated RaceTime subnet before attaching its stable public address.
data "oci_core_private_ips" "racetime" {
  subnet_id  = oci_core_subnet.racetime.id
  ip_address = oci_core_instance.racetime.private_ip
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
