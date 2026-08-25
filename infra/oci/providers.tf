provider "oci" {
  region              = var.region
  config_file_profile = var.oci_config_file_profile
}

locals {
  common_tags = merge(
    {
      "managed-by" = "terraform"
      "service"    = "z1rr-racetime"
    },
    var.freeform_tags,
  )
}
