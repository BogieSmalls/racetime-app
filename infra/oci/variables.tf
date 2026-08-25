variable "activation_record" {
  description = "Dated G1 Plan-B activation record. Required; never set during G0."
  type        = string

  validation {
    condition     = can(regex("^G1-[0-9]{4}-[0-9]{2}-[0-9]{2}:[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$", var.activation_record))
    error_message = "activation_record must identify a dated G1 activation and operator record."
  }
}

variable "tenancy_ocid" {
  description = "OCI tenancy OCID used for the instance-principal dynamic group."
  type        = string

  validation {
    condition     = can(regex("^ocid1\\.tenancy\\.", var.tenancy_ocid))
    error_message = "tenancy_ocid must be an OCI tenancy OCID."
  }
}

variable "compartment_ocid" {
  description = "Existing compartment or root tenancy for the dedicated RaceTime resources."
  type        = string

  validation {
    condition     = can(regex("^ocid1\\.(?:compartment|tenancy)\\.", var.compartment_ocid))
    error_message = "compartment_ocid must be an OCI compartment OCID or the root tenancy OCID."
  }
}

variable "region" {
  description = "OCI region identifier."
  type        = string

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+-[0-9]+$", var.region))
    error_message = "region must be an OCI region identifier."
  }
}

variable "oci_config_file_profile" {
  description = "Local OCI SDK configuration profile used by Terraform."
  type        = string
  default     = "DEFAULT"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{1,64}$", var.oci_config_file_profile))
    error_message = "oci_config_file_profile must be a simple OCI profile name."
  }
}

variable "availability_domain" {
  description = "Explicit availability domain chosen after the G1 capacity check."
  type        = string

  validation {
    condition     = length(trimspace(var.availability_domain)) >= 5
    error_message = "availability_domain must be explicit."
  }
}

variable "vcn_ocid" {
  description = "Existing VCN OCID. Terraform does not mutate the VCN."
  type        = string

  validation {
    condition     = can(regex("^ocid1\\.vcn\\.", var.vcn_ocid))
    error_message = "vcn_ocid must be an OCI VCN OCID."
  }
}

variable "subnet_ocid" {
  description = "Existing public subnet OCID used by RaceTime and OCI Bastion."
  type        = string

  validation {
    condition     = can(regex("^ocid1\\.subnet\\.", var.subnet_ocid))
    error_message = "subnet_ocid must be an OCI subnet OCID."
  }
}

variable "racetime_subnet_cidr" {
  description = "IPv4 CIDR for the dedicated regional RaceTime public subnet."
  type        = string

  validation {
    condition = (
      can(cidrhost(var.racetime_subnet_cidr, 0)) &&
      can(cidrnetmask(var.racetime_subnet_cidr))
    )
    error_message = "racetime_subnet_cidr must be a valid IPv4 CIDR."
  }
}

variable "image_ocid" {
  description = "Explicit current standard ARM64 Ubuntu 24.04 image OCID verified at G1."
  type        = string

  validation {
    condition     = can(regex("^ocid1\\.image\\.", var.image_ocid))
    error_message = "image_ocid must be an explicit OCI image OCID."
  }
}

variable "ssh_authorized_keys" {
  description = "Operator and sealed-recovery SSH public keys. Never put private material in tfvars."
  type        = list(string)

  validation {
    condition = (
      length(var.ssh_authorized_keys) >= 2 &&
      alltrue([for key in var.ssh_authorized_keys : can(regex("^(ssh-|ecdsa-)", key))])
    )
    error_message = "Provide at least the operator and sealed-recovery SSH public keys."
  }
}

variable "object_storage_namespace" {
  description = "Explicit Object Storage namespace."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{3,64}$", var.object_storage_namespace))
    error_message = "object_storage_namespace must be explicit."
  }
}

variable "backup_bucket_name" {
  description = "Globally unique private bucket name for encrypted RaceTime backups."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]{2,127}$", var.backup_bucket_name))
    error_message = "backup_bucket_name must be a valid non-secret bucket name."
  }
}

variable "bastion_client_cidr_allow_list" {
  description = "Operator source CIDRs allowed to open ephemeral OCI Bastion sessions."
  type        = set(string)

  validation {
    condition = (
      length(var.bastion_client_cidr_allow_list) > 0 &&
      !contains(var.bastion_client_cidr_allow_list, "0.0.0.0/0") &&
      !contains(var.bastion_client_cidr_allow_list, "::/0")
    )
    error_message = "Bastion clients must be explicitly restricted; public CIDRs are forbidden."
  }
}

variable "enable_ipv6" {
  description = "Enable public IPv6 HTTP/HTTPS only after the existing subnet is verified IPv6-ready."
  type        = bool
  default     = false
}

variable "alert_relay_endpoint" {
  description = "Optional authenticated coop-relay CUSTOM_HTTPS notification endpoint; no credentials in the URL."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.alert_relay_endpoint == null ||
      can(regex("^https://[^/?#]+/[^?#]+$", var.alert_relay_endpoint))
    )
    error_message = "alert_relay_endpoint must be an HTTPS URL without query credentials."
  }
}

variable "fallback_email_endpoint" {
  description = "Optional operator email for OCI Notifications fallback."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.fallback_email_endpoint == null ||
      can(regex("^[^@[:space:]]+@[^@[:space:]]+$", var.fallback_email_endpoint))
    )
    error_message = "fallback_email_endpoint must be a valid email address."
  }
}

variable "existing_restream_instance_ids" {
  description = "Read-only keyed inventory of existing Restream instance OCIDs."
  type        = map(string)
  default     = {}
}

variable "existing_restream_boot_volume_ids" {
  description = "Read-only keyed inventory of retained Restream boot-volume OCIDs."
  type        = map(string)
  default     = {}
}

variable "freeform_tags" {
  description = "Additional non-secret OCI freeform tags."
  type        = map(string)
  default     = {}
}
