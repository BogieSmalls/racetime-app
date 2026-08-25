output "instance_id" {
  value       = oci_core_instance.racetime.id
  description = "Dedicated RaceTime instance OCID."
  sensitive   = true
}

output "instance_public_ip" {
  value       = oci_core_public_ip.racetime.ip_address
  description = "Canonical DNS target after G1 verification."
  sensitive   = true
}

output "instance_private_ip" {
  value       = oci_core_instance.racetime.private_ip
  description = "Bastion target address."
  sensitive   = true
}

output "boot_volume_id" {
  value       = oci_core_instance.racetime.boot_volume_id
  description = "Protected 50-GB Balanced boot volume OCID."
  sensitive   = true
}

output "backup_bucket_name" {
  value       = oci_objectstorage_bucket.backups.name
  description = "Private encrypted-backup bucket name."
  sensitive   = true
}

output "bastion_id" {
  value       = oci_bastion_bastion.racetime.id
  description = "Managed Bastion used for ephemeral SSH sessions."
  sensitive   = true
}

output "notification_topic_id" {
  value       = oci_ons_notification_topic.operations.id
  description = "Operations notification topic OCID."
  sensitive   = true
}
