import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra" / "oci"
EXPECTED = {
    "versions.tf",
    "providers.tf",
    "variables.tf",
    "data.tf",
    "network.tf",
    "compute.tf",
    "storage.tf",
    "iam.tf",
    "monitoring.tf",
    "outputs.tf",
    "terraform.tfvars.example",
    "README.md",
}
ACTIVATION_TEST = INFRA / "tests" / "activation_gate.tftest.hcl"


def _hcl_block(text, declaration):
    match = re.search(rf"{re.escape(declaration)}\s*{{", text)
    if match is None:
        raise AssertionError(f"missing HCL block: {declaration}")

    opening_brace = text.index("{", match.start())
    depth = 0
    for index in range(opening_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[match.start() : index + 1]
    raise AssertionError(f"unterminated HCL block: {declaration}")


class TerraformContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = sorted(name for name in EXPECTED if not (INFRA / name).is_file())
        if missing:
            raise AssertionError(f"missing OCI artifacts: {', '.join(missing)}")
        cls.files = {
            name: (INFRA / name).read_text(encoding="utf-8")
            for name in EXPECTED
        }
        cls.tf = "\n".join(
            cls.files[name] for name in sorted(EXPECTED) if name.endswith(".tf")
        )

    def test_provider_backend_and_activation_gate_are_pinned(self):
        versions = self.files["versions.tf"]
        variables = self.files["variables.tf"]
        providers = self.files["providers.tf"]
        self.assertRegex(versions, r'required_version\s*=\s*">= 1\.12\.0, < 2\.0\.0"')
        self.assertRegex(versions, r'source\s*=\s*"oracle/oci"')
        self.assertRegex(versions, r'version\s*=\s*"= 8\.27\.0"')
        self.assertIn('backend "oci" {}', versions)
        activation = variables.split('variable "activation_record"', 1)[1].split(
            'variable "', 1
        )[0]
        self.assertNotIn("default", activation)
        self.assertIn("G1", activation)
        self.assertIn("var.activation_record", self.files["compute.tf"])
        self.assertIn("precondition", self.files["compute.tf"])
        activation_test = ACTIVATION_TEST.read_text(encoding="utf-8")
        self.assertIn("mock_provider \"oci\"", activation_test)
        self.assertIn("expect_failures = [var.activation_record]", activation_test)
        self.assertIn("dated_g1_activation_allows_mock_plan", activation_test)
        self.assertIn('variable "oci_config_file_profile"', variables)
        self.assertRegex(
            providers,
            r'config_file_profile\s*=\s*var\.oci_config_file_profile',
        )
        self.assertIn("oci_config_file_profile", self.files["terraform.tfvars.example"])

    def test_compute_is_dedicated_a1_with_guarded_balanced_boot(self):
        compute = self.files["compute.tf"]
        for name, value in (
            ("display_name", '"racetime"'),
            ("shape", '"VM.Standard.A1.Flex"'),
            ("ocpus", "1"),
            ("memory_in_gbs", "6"),
            ("source_type", '"image"'),
            ("source_id", "var.image_ocid"),
            ("boot_volume_size_in_gbs", "50"),
            ("boot_volume_vpus_per_gb", "10"),
            ("preserve_boot_volume", "true"),
            ("prevent_destroy", "true"),
            ("assign_public_ip", "true"),
        ):
            with self.subTest(name=name):
                self.assertRegex(compute, rf"(?m)^\s*{name}\s*=\s*{re.escape(value)}\s*$")
        self.assertIn("nsg_ids", compute)
        self.assertNotRegex(compute, r'data\s+"oci_core_images"')
        self.assertIn("VM.Standard.E5.Flex", self.files["README.md"])
        self.assertIn("1 OCPU / 6 GB", self.files["README.md"])

    def test_tenancy_root_and_ubuntu_bastion_contract_are_explicit(self):
        variables = self.files["variables.tf"]
        compartment = variables.split('variable "compartment_ocid"', 1)[1].split(
            'variable "', 1
        )[0]
        self.assertIn(r"ocid1\\.(?:compartment|tenancy)\\.", compartment)
        self.assertIn("root tenancy OCID", compartment)
        self.assertIn("ARM64 Ubuntu 24.04", variables)
        self.assertIn("arm64_ubuntu_24_04_image", self.files["terraform.tfvars.example"])

        compute = self.files["compute.tf"]
        self.assertNotRegex(compute, r'name\s*=\s*"Bastion"')
        self.assertIn("Bastion port-forwarding session", self.files["README.md"])
        self.assertIn("does not require the Bastion agent plugin", self.files["README.md"])

    def test_existing_restream_inventory_is_data_only(self):
        data = self.files["data.tf"]
        variables = self.files["variables.tf"]
        self.assertIn('data "oci_core_instance" "restream_inventory"', data)
        self.assertIn('data "oci_core_boot_volume" "restream_inventory"', data)
        self.assertIn('variable "existing_restream_instance_ids"', variables)
        self.assertIn('variable "existing_restream_boot_volume_ids"', variables)
        self.assertNotRegex(
            self.tf,
            r'resource\s+"oci_core_(?:instance|boot_volume)"\s+"restream',
        )
        self.assertNotIn('display_name = "z1rr-restream', self.tf)

    def test_network_exposes_only_http_https_and_uses_bastion_for_ssh(self):
        network = self.files["network.tf"]
        data = self.files["data.tf"]
        variables = self.files["variables.tf"]
        readme = self.files["README.md"]
        self.assertIn('resource "oci_core_network_security_group" "racetime"', network)
        self.assertRegex(network, r'source\s*=\s*"0\.0\.0\.0/0"')
        self.assertRegex(network, r"min\s*=\s*443[\s\S]*max\s*=\s*443")
        self.assertRegex(network, r"min\s*=\s*80[\s\S]*max\s*=\s*80")
        self.assertRegex(network, r'source\s*=\s*"::/0"')
        self.assertIn("enable_ipv6", network)
        self.assertIn('resource "oci_bastion_bastion" "racetime"', network)
        self.assertIn("private_endpoint_ip_address", network)
        self.assertRegex(network, r"min\s*=\s*22[\s\S]*max\s*=\s*22")
        public_ssh = re.findall(
            r'source\s*=\s*"(?:0\.0\.0\.0/0|::/0)"[\s\S]{0,280}?min\s*=\s*22',
            network,
        )
        self.assertEqual(public_ssh, [])

        self.assertEqual(
            re.findall(r'resource\s+"oci_core_subnet"\s+"([^"]+)"', self.tf),
            ["racetime"],
        )
        self.assertEqual(
            re.findall(
                r'resource\s+"oci_core_security_list"\s+"([^"]+)"', self.tf
            ),
            ["racetime"],
        )
        self.assertNotRegex(self.tf, r'resource\s+"oci_core_vcn"')
        self.assertNotRegex(
            self.tf,
            r'resource\s+"oci_core_[^"]*"\s+"[^"]*restream[^"]*"',
        )

        bastion_subnet = _hcl_block(data, 'data "oci_core_subnet" "bastion"')
        self.assertRegex(
            bastion_subnet,
            r"(?m)^\s*subnet_id\s*=\s*var\.subnet_ocid\s*$",
        )

        subnet = _hcl_block(network, 'resource "oci_core_subnet" "racetime"')
        for name, value in (
            ("cidr_block", "var.racetime_subnet_cidr"),
            ("display_name", '"racetime-public"'),
            ("dns_label", '"racetime"'),
            ("prohibit_public_ip_on_vnic", "false"),
            ("prohibit_internet_ingress", "false"),
            ("route_table_id", "data.oci_core_subnet.bastion.route_table_id"),
            ("dhcp_options_id", "data.oci_core_subnet.bastion.dhcp_options_id"),
            ("security_list_ids", "[oci_core_security_list.racetime.id]"),
        ):
            with self.subTest(subnet_argument=name):
                self.assertRegex(
                    subnet,
                    rf"(?m)^\s*{name}\s*=\s*{re.escape(value)}\s*$",
                )
        self.assertRegex(subnet, r"(?m)^\s*prevent_destroy\s*=\s*true\s*$")
        self.assertNotRegex(subnet, r"(?m)^\s*availability_domain\s*=")

        security_list = _hcl_block(
            network, 'resource "oci_core_security_list" "racetime"'
        )
        self.assertRegex(
            security_list,
            r'(?m)^\s*display_name\s*=\s*"racetime"\s*$',
        )
        self.assertNotRegex(security_list, r"(?m)^\s*ingress_security_rules\s*{")
        self.assertEqual(
            len(re.findall(r"(?m)^\s*egress_security_rules\s*{", security_list)),
            1,
        )
        for name, value in (
            ("destination", '"0.0.0.0/0"'),
            ("destination_type", '"CIDR_BLOCK"'),
            ("protocol", '"all"'),
            ("stateless", "false"),
        ):
            with self.subTest(egress_argument=name):
                self.assertRegex(
                    security_list,
                    rf"(?m)^\s*{name}\s*=\s*{re.escape(value)}\s*$",
                )
        self.assertRegex(
            security_list, r"(?m)^\s*prevent_destroy\s*=\s*true\s*$"
        )

        cidr_variable = _hcl_block(
            variables, 'variable "racetime_subnet_cidr"'
        )
        self.assertRegex(cidr_variable, r"(?m)^\s*type\s*=\s*string\s*$")
        self.assertNotRegex(cidr_variable, r"(?m)^\s*default\s*=")
        self.assertIn("can(cidrhost(var.racetime_subnet_cidr, 0))", cidr_variable)
        self.assertIn("can(cidrnetmask(var.racetime_subnet_cidr))", cidr_variable)

        self.assertIn(
            "racetime_subnet_cidr = \"10.1.1.0/24\"",
            self.files["terraform.tfvars.example"],
        )
        self.assertIn(
            "terraform -chdir=infra/oci import oci_core_security_list.racetime <security-list-ocid>",
            readme,
        )
        self.assertIn(
            "terraform -chdir=infra/oci import oci_core_subnet.racetime <subnet-ocid>",
            readme,
        )

    def test_bastion_case_normalization_ignore_is_exact_and_narrow(self):
        bastion = _hcl_block(
            self.files["network.tf"],
            'resource "oci_bastion_bastion" "racetime"',
        )
        self.assertRegex(
            bastion,
            r'(?m)^\s*bastion_type\s*=\s*"standard"\s*$',
        )
        lifecycle = _hcl_block(bastion, "lifecycle")
        self.assertRegex(lifecycle, r"(?m)^\s*prevent_destroy\s*=\s*true\s*$")
        ignored = re.findall(r"ignore_changes\s*=\s*\[([^\]]*)\]", lifecycle)
        self.assertEqual([value.strip() for value in ignored], ["bastion_type"])

    def test_backup_bucket_and_instance_principal_are_narrow(self):
        storage = self.files["storage.tf"]
        iam = self.files["iam.tf"]
        for name, value in (
            ("access_type", '"NoPublicAccess"'),
            ("versioning", '"Enabled"'),
            ("storage_tier", '"Standard"'),
            ("prevent_destroy", "true"),
        ):
            self.assertRegex(storage, rf"(?m)^\s*{name}\s*=\s*{re.escape(value)}\s*$")
        self.assertIn('instance.id = \'${oci_core_instance.racetime.id}\'', iam)
        self.assertIn("target.bucket.name", iam)
        self.assertIn("target.object.name='production/*'", iam)
        self.assertIn("to read buckets", iam)
        self.assertIn("to manage objects", iam)
        self.assertIn("target.metrics.namespace='z1rr_racetime'", iam)
        self.assertNotIn("manage object-family", iam)
        self.assertNotRegex(iam, r"instance\.compartment\.id\s*=")
        self.assertIn(
            'var.compartment_ocid == var.tenancy_ocid ? "in tenancy" : "in compartment id ${var.compartment_ocid}"',
            iam,
        )
        self.assertGreaterEqual(iam.count("${local.racetime_resource_scope}"), 3)

    def test_notifications_and_cost_controls_are_explicit(self):
        monitoring = self.files["monitoring.tf"]
        for token in (
            'resource "oci_ons_notification_topic" "operations"',
            'protocol       = "CUSTOM_HTTPS"',
            'protocol       = "EMAIL"',
            "A1ForecastWarning",
            "A1ProjectedMonthEndOCPUHours",
            "> 2900",
            "RetainedBootVolumeMonthlyCostUSD",
            "> 4.61",
            "> 6.61",
            "ObjectStorageEntitlementUtilizationPercent",
            "> 75",
            "> 90",
            "Restream sleep automation",
        ):
            with self.subTest(token=token):
                self.assertIn(token, monitoring)
        self.assertIn("forecast >= 2650", monitoring)
        self.assertIn("warning is suppressed", monitoring)

    def test_outputs_are_sensitive_and_examples_are_secret_free(self):
        outputs = self.files["outputs.tf"]
        self.assertGreaterEqual(
            len(re.findall(r"(?m)^\s*sensitive\s*=\s*true\s*$", outputs)), 4
        )
        example = self.files["terraform.tfvars.example"].lower()
        for forbidden in (
            "private_key",
            "password",
            "client_secret",
            "discord_webhook",
            "api_token",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, example)
        self.assertIn("replace_g1_activation_record", example)
        self.assertIn("ocid1.image", example)
        self.assertIn("existing_restream_instance_ids", example)

    def test_runbook_requires_saved_plan_review_and_account_recovery(self):
        readme = self.files["README.md"]
        for token in (
            "terraform -chdir=infra/oci init -backend=false",
            "terraform -chdir=infra/oci plan -input=false -out=",
            "terraform -chdir=infra/oci show -json",
            "terraform -chdir=infra/oci apply",
            "native OCI backend",
            "versioning",
            "OCI tenancy",
            "GitHub organization",
            "container registry",
            "authoritative DNS",
            "No G0 apply",
            "z1rr-restream-control-staging",
        ):
            with self.subTest(token=token):
                self.assertIn(token, readme)
        self.assertRegex(readme, r"create,\s+update, delete, or replace")


if __name__ == "__main__":
    unittest.main()
