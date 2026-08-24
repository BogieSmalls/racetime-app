terraform {
  required_version = ">= 1.12.0, < 2.0.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "= 8.27.0"
    }
  }

  # G0 uses `terraform init -backend=false`. At G1, initialize this partial
  # native OCI backend with a root-owned backend file kept outside Git.
  backend "oci" {}
}
