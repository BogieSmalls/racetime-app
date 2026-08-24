resource "oci_objectstorage_bucket" "backups" {
  compartment_id        = var.compartment_ocid
  namespace             = var.object_storage_namespace
  name                  = var.backup_bucket_name
  access_type           = "NoPublicAccess"
  object_events_enabled = true
  storage_tier          = "Standard"
  versioning            = "Enabled"
  freeform_tags         = local.common_tags

  metadata = {
    purpose = "Encrypted production RaceTime backups only"
  }

  lifecycle {
    prevent_destroy = true
  }
}
