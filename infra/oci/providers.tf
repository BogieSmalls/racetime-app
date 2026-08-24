provider "oci" {
  region = var.region
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
