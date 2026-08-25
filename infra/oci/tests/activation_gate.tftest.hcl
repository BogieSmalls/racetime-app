mock_provider "oci" {}

variables {
  tenancy_ocid         = "ocid1.tenancy.oc1..example"
  compartment_ocid     = "ocid1.compartment.oc1..example"
  region               = "us-ashburn-1"
  availability_domain  = "example:US-ASHBURN-AD-1"
  vcn_ocid             = "ocid1.vcn.oc1.iad.example"
  subnet_ocid          = "ocid1.subnet.oc1.iad.example"
  racetime_subnet_cidr = "10.1.1.0/24"
  image_ocid           = "ocid1.image.oc1.iad.example"

  ssh_authorized_keys = [
    "ssh-ed25519 AAAAexampleoperator operator",
    "ssh-ed25519 AAAAexamplerecovery recovery",
  ]

  object_storage_namespace = "examplenamespace"
  backup_bucket_name       = "z1rr-racetime-test-backups"
  bastion_client_cidr_allow_list = [
    "192.0.2.10/32",
  ]
}

run "blank_activation_is_rejected_before_plan" {
  command = plan

  variables {
    activation_record = ""
  }

  expect_failures = [var.activation_record]
}

run "dated_g1_activation_allows_mock_plan" {
  command = plan

  variables {
    activation_record = "G1-2026-08-24:operator-activation"
  }
}
