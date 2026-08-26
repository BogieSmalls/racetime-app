resource "oci_core_instance" "racetime" {
  availability_domain                 = var.availability_domain
  compartment_id                      = var.compartment_ocid
  display_name                        = "racetime"
  shape                               = "VM.Standard.A1.Flex"
  preserve_boot_volume                = true
  is_pv_encryption_in_transit_enabled = true
  freeform_tags                       = local.common_tags

  shape_config {
    ocpus         = 1
    memory_in_gbs = 6
  }

  source_details {
    source_type                     = "image"
    source_id                       = var.image_ocid
    boot_volume_size_in_gbs         = 50
    boot_volume_vpus_per_gb         = 10
    is_preserve_boot_volume_enabled = true
  }

  create_vnic_details {
    assign_public_ip          = false
    assign_ipv6ip             = false
    assign_private_dns_record = true
    display_name              = "racetime-primary"
    hostname_label            = "racetime"
    nsg_ids                   = [oci_core_network_security_group.racetime.id]
    subnet_id                 = oci_core_subnet.racetime.id
  }

  metadata = {
    ssh_authorized_keys = join("\n", var.ssh_authorized_keys)
  }

  agent_config {
    are_all_plugins_disabled = false
    is_management_disabled   = false
    is_monitoring_disabled   = false

    plugins_config {
      desired_state = "ENABLED"
      name          = "Compute Instance Monitoring"
    }

  }

  availability_config {
    recovery_action = "RESTORE_INSTANCE"
  }

  launch_options {
    is_pv_encryption_in_transit_enabled = true
    network_type                        = "PARAVIRTUALIZED"
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [is_pv_encryption_in_transit_enabled]

    precondition {
      condition     = length(trimspace(var.activation_record)) > 0
      error_message = "A dated G1 activation_record is required before OCI planning or apply."
    }
  }
}

# The boot volume is created by the instance source_details block because OCI
# cannot create a standalone boot volume from an image. Its explicit 50-GB,
# 10-VPU/GB contract is protected by instance prevent_destroy plus both OCI
# boot-preservation flags above.
