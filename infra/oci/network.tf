resource "oci_core_network_security_group" "racetime" {
  compartment_id = var.compartment_ocid
  display_name   = "racetime"
  vcn_id         = var.vcn_ocid
  freeform_tags  = local.common_tags

  lifecycle {
    prevent_destroy = true
  }
}

# TCP 443 must remain reachable from unpredictable ACME validation addresses.
# Qualification source restriction is an HTTP-handler concern in Caddy, after
# the TLS-ALPN-01 handshake; never copy the Caddy allowlist into this NSG.
resource "oci_core_network_security_group_security_rule" "https_ipv4" {
  network_security_group_id = oci_core_network_security_group.racetime.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = "0.0.0.0/0"
  source_type               = "CIDR_BLOCK"
  stateless                 = false
  description               = "Public HTTPS and TLS-ALPN-01"

  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_network_security_group_security_rule" "http_ipv4" {
  network_security_group_id = oci_core_network_security_group.racetime.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = "0.0.0.0/0"
  source_type               = "CIDR_BLOCK"
  stateless                 = false
  description               = "Caddy HTTP redirect or restricted denial only"

  tcp_options {
    destination_port_range {
      min = 80
      max = 80
    }
  }
}

resource "oci_core_network_security_group_security_rule" "https_ipv6" {
  count = var.enable_ipv6 ? 1 : 0

  network_security_group_id = oci_core_network_security_group.racetime.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = "::/0"
  source_type               = "CIDR_BLOCK"
  stateless                 = false
  description               = "Public IPv6 HTTPS and TLS-ALPN-01"

  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_network_security_group_security_rule" "http_ipv6" {
  count = var.enable_ipv6 ? 1 : 0

  network_security_group_id = oci_core_network_security_group.racetime.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = "::/0"
  source_type               = "CIDR_BLOCK"
  stateless                 = false
  description               = "Caddy IPv6 redirect or restricted denial only"

  tcp_options {
    destination_port_range {
      min = 80
      max = 80
    }
  }
}

resource "oci_bastion_bastion" "racetime" {
  bastion_type                 = "standard"
  compartment_id               = var.compartment_ocid
  target_subnet_id             = var.subnet_ocid
  client_cidr_block_allow_list = sort(tolist(var.bastion_client_cidr_allow_list))
  max_session_ttl_in_seconds   = 10800
  name                         = "racetime"
  freeform_tags                = local.common_tags

  lifecycle {
    prevent_destroy = true
  }
}

# Port 22 is reachable only from the managed Bastion private endpoint. There is
# deliberately no 0.0.0.0/0 or ::/0 SSH rule.
resource "oci_core_network_security_group_security_rule" "ssh_from_bastion" {
  network_security_group_id = oci_core_network_security_group.racetime.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = "${oci_bastion_bastion.racetime.private_endpoint_ip_address}/32"
  source_type               = "CIDR_BLOCK"
  stateless                 = false
  description               = "Ephemeral operator SSH through OCI Bastion only"

  tcp_options {
    destination_port_range {
      min = 22
      max = 22
    }
  }
}

resource "oci_core_network_security_group_security_rule" "egress_ipv4" {
  network_security_group_id = oci_core_network_security_group.racetime.id
  direction                 = "EGRESS"
  protocol                  = "all"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  stateless                 = false
  description               = "Outbound package, identity, image, backup, and monitoring APIs"
}

resource "oci_core_network_security_group_security_rule" "egress_ipv6" {
  count = var.enable_ipv6 ? 1 : 0

  network_security_group_id = oci_core_network_security_group.racetime.id
  direction                 = "EGRESS"
  protocol                  = "all"
  destination               = "::/0"
  destination_type          = "CIDR_BLOCK"
  stateless                 = false
  description               = "Optional outbound IPv6"
}
