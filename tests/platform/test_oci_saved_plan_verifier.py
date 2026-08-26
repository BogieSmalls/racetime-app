"""Synthetic, offline tests for the OCI saved-plan safety gate."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts" / "oci" / "verify_saved_plan.py"
TERRAFORM_VERSION = "1.12.2"
OUTPUT_NAMES = {
    "instance_id",
    "instance_public_ip",
    "instance_private_ip",
    "boot_volume_id",
}


def load_verifier():
    spec = importlib.util.spec_from_file_location("verify_saved_plan", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load verify_saved_plan.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise AssertionError(f"fixture Git command failed: {' '.join(arguments)}")
    return result.stdout.strip()


def change(address: str, actions: list[str], after: dict | None = None) -> dict:
    before = None if actions == ["create"] else {"stable": "same"}
    parts = address.split(".")
    if parts[0] == "data":
        mode = "data"
        resource_type = parts[1]
        name = parts[2].split("[", 1)[0]
    else:
        mode = "managed"
        resource_type = parts[0]
        name = parts[1].split("[", 1)[0]
    return {
        "address": address,
        "mode": mode,
        "type": resource_type,
        "name": name,
        "provider_name": "registry.terraform.io/oracle/oci",
        "change": {
            "actions": actions,
            "before": before,
            "after": after,
            "after_unknown": {},
            "before_sensitive": False,
            "after_sensitive": False,
        },
    }


def output_changes(actions: list[str] | None = None) -> dict:
    return {
        name: {
            "actions": actions or ["update"],
            "before": "redacted-before",
            "after": None,
            "after_unknown": False,
        }
        for name in OUTPUT_NAMES
    }


def base_plan() -> dict:
    return {
        "format_version": "1.2",
        "terraform_version": TERRAFORM_VERSION,
        "applyable": True,
        "complete": True,
        "errored": False,
        "configuration": {"root_module": {"resources": []}},
        "planned_values": {"root_module": {"resources": []}},
        "resource_changes": [],
        "resource_drift": [],
        "output_changes": {},
    }


def subnet_plan() -> dict:
    plan = base_plan()
    security_list = change(
        "oci_core_security_list.racetime",
        ["create"],
        {
            "display_name": "racetime",
            "ingress_security_rules": [],
            "egress_security_rules": [
                {
                    "destination": "0.0.0.0/0",
                    "destination_type": "CIDR_BLOCK",
                    "protocol": "all",
                    "stateless": False,
                }
            ],
        },
    )
    subnet = change(
        "oci_core_subnet.racetime",
        ["create"],
        {
            "cidr_block": "10.0.50.0/24",
            "dns_label": "racetime",
            "prohibit_internet_ingress": False,
            "prohibit_public_ip_on_vnic": True,
            "route_table_id": "ocid1.routetable.expected",
            "dhcp_options_id": "ocid1.dhcpoptions.expected",
            "availability_domain": None,
            "security_list_ids": [None],
        },
    )
    subnet["change"]["after_unknown"] = {"security_list_ids": [True]}
    plan["resource_changes"] = [security_list, subnet]
    plan["planned_values"]["root_module"]["resources"] = [
        {
            "address": "oci_core_subnet.racetime",
            "mode": "managed",
            "type": "oci_core_subnet",
            "name": "racetime",
            "values": copy.deepcopy(subnet["change"]["after"]),
        }
    ]
    plan["configuration"]["root_module"]["resources"] = [
        {
            "address": "oci_core_security_list.racetime",
            "mode": "managed",
            "type": "oci_core_security_list",
            "name": "racetime",
            "expressions": {},
        },
        {
            "address": "oci_core_subnet.racetime",
            "mode": "managed",
            "type": "oci_core_subnet",
            "name": "racetime",
            "expressions": {
                "security_list_ids": {
                    "references": ["oci_core_security_list.racetime.id"]
                }
            },
        },
    ]
    return plan


def refresh_plan() -> dict:
    plan = base_plan()
    drift = change("oci_core_instance.racetime", ["delete"], None)
    drift["change"]["before"] = {"id": "redacted-instance"}
    plan["resource_drift"] = [drift]
    plan["output_changes"] = output_changes(["update"])
    return plan


def replacement_plan() -> dict:
    plan = base_plan()
    instance = change(
        "oci_core_instance.racetime",
        ["create"],
        {
            "create_vnic_details": [
                {
                    "subnet_id": "ocid1.subnet.expected",
                    "nsg_ids": ["ocid1.networksecuritygroup.expected"],
                    "assign_public_ip": "false",
                    "assign_ipv6ip": False,
                }
            ]
        },
    )
    public_ip = change(
        "oci_core_public_ip.racetime",
        ["create"],
        {
            "lifetime": "RESERVED",
            "private_ip_id": None,
        },
    )
    public_ip["change"]["after_unknown"] = {"private_ip_id": True}
    dynamic_group = change(
        "oci_identity_dynamic_group.racetime",
        ["update"],
        {"stable": "same", "matching_rule": "redacted-new-rule"},
    )
    dynamic_group["change"]["before"]["matching_rule"] = "redacted-old-rule"
    alarm = change(
        "oci_monitoring_alarm.instance_cpu",
        ["update"],
        {"stable": "same", "query": "redacted-new-query"},
    )
    alarm["change"]["before"]["query"] = "redacted-old-query"
    private_ips = change(
        "data.oci_core_private_ips.racetime",
        ["read"],
        {"private_ips": None},
    )
    private_ips["change"]["before"] = None
    private_ips["change"]["after_unknown"] = {"private_ips": True}
    plan["resource_changes"] = [
        instance,
        public_ip,
        dynamic_group,
        alarm,
        private_ips,
    ]
    plan["output_changes"] = {
        name: {
            "actions": ["update"],
            "before": None,
            "after": None,
            "after_unknown": True,
            "before_sensitive": True,
            "after_sensitive": True,
        }
        for name in OUTPUT_NAMES
    }
    plan["configuration"]["root_module"]["resources"] = [
        {
            "address": "oci_core_public_ip.racetime",
            "mode": "managed",
            "type": "oci_core_public_ip",
            "name": "racetime",
            "expressions": {
                "private_ip_id": {
                    "references": [
                        "data.oci_core_private_ips.racetime.private_ips",
                        "data.oci_core_private_ips.racetime",
                    ]
                }
            },
        }
    ]
    return plan


class PlanFixture:
    def __init__(self, verifier, plan: dict) -> None:
        self.verifier = verifier
        self.temporary = tempfile.TemporaryDirectory(prefix="racetime-plan-gate-")
        self.repository = Path(self.temporary.name)
        run_git(self.repository, "init", "-q")
        run_git(self.repository, "config", "user.email", "tests@example.invalid")
        run_git(self.repository, "config", "user.name", "Plan Gate Tests")
        (self.repository / ".gitignore").write_text("/.tmp/\n", encoding="utf-8")
        (self.repository / "marker.txt").write_text("fixture\n", encoding="utf-8")
        run_git(self.repository, "add", ".gitignore", "marker.txt")
        run_git(self.repository, "commit", "-q", "-m", "fixture")
        self.source_commit = run_git(self.repository, "rev-parse", "HEAD")
        self.inputs = self.repository / ".tmp"
        self.inputs.mkdir()
        self.plan_file = self.inputs / "saved.tfplan"
        self.plan_file.write_bytes(b"synthetic saved Terraform plan")
        self.plan_json = self.inputs / "saved-plan.json"
        self.terraform_show_json = self.inputs / "terraform-show.json"
        self.expected_json = self.inputs / "expected.json"
        self.terraform_bin = self.inputs / (
            "terraform-fixture.cmd" if os.name == "nt" else "terraform-fixture"
        )
        self.plan = copy.deepcopy(plan)
        addresses = {
            item.get("address") for item in self.plan.get("resource_changes", [])
        }
        if "oci_core_public_ip.racetime" in addresses:
            phase = "replacement"
        elif self.plan.get("resource_drift"):
            phase = "refresh-only"
        else:
            phase = "subnet-add"
        self.write_terraform_executable()
        self.expected = {
            "phase": phase,
            "source_commit": self.source_commit,
            "terraform_version": TERRAFORM_VERSION,
            "terraform_binary_sha256": hashlib.sha256(
                self.terraform_bin.read_bytes()
            ).hexdigest(),
            "plan_sha256": hashlib.sha256(self.plan_file.read_bytes()).hexdigest(),
            "subnet": {
                "cidr_block": "10.0.50.0/24",
                "dns_label": "racetime",
                "prohibit_public_ip_on_vnic": True,
                "route_table_id": "ocid1.routetable.expected",
                "dhcp_options_id": "ocid1.dhcpoptions.expected",
            },
            "replacement": {
                "subnet_id": "ocid1.subnet.expected",
                "network_security_group_ids": [
                    "ocid1.networksecuritygroup.expected"
                ],
                "private_ip_id": "ocid1.privateip.expected",
            },
        }
        self.write_inputs()

    def cleanup(self) -> None:
        self.temporary.cleanup()

    def write_terraform_executable(self, version: str = TERRAFORM_VERSION) -> None:
        version_json = json.dumps(
            {
                "terraform_version": version,
                "platform": "windows_amd64" if os.name == "nt" else "linux_amd64",
                "provider_selections": {"registry.terraform.io/oracle/oci": "8.27.0"},
                "terraform_outdated": False,
            },
            separators=(",", ":"),
        )
        if os.name == "nt":
            script = (
                "@echo off\r\n"
                'if /I not "%CD%\\"=="%~dp0" exit /b 3\r\n'
                'if "%~1"=="version" goto version\r\n'
                'if "%~1"=="show" goto show\r\n'
                "exit /b 2\r\n"
                ":version\r\n"
                'if not "%~2"=="-json" exit /b 4\r\n'
                'if not "%~3"=="" exit /b 4\r\n'
                f"echo {version_json}\r\n"
                "exit /b 0\r\n"
                ":show\r\n"
                'if not "%~2"=="-json" exit /b 4\r\n'
                'if not "%~3"=="saved.tfplan" exit /b 4\r\n'
                'if not "%~4"=="" exit /b 4\r\n'
                'type "%~dp0terraform-show.json"\r\n'
                "exit /b 0\r\n"
            )
        else:
            script = (
                "#!/bin/sh\n"
                'expected_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                '[ "$PWD" = "$expected_dir" ] || exit 3\n'
                'case "$1" in\n'
                f"  version) [ \"$#\" -eq 2 ] && [ \"$2\" = \"-json\" ] || exit 4; printf '%s\\n' '{version_json}' ;;\n"
                '  show) [ "$#" -eq 3 ] && [ "$2" = "-json" ] && [ "$3" = "saved.tfplan" ] || exit 4; cat "$(dirname "$0")/terraform-show.json" ;;\n'
                "  *) exit 2 ;;\n"
                "esac\n"
            )
        self.terraform_bin.write_text(script, encoding="utf-8", newline="")
        if os.name != "nt":
            self.terraform_bin.chmod(0o700)

    def plan_bytes(self) -> bytes:
        return (
            json.dumps(self.plan, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")

    def write_expected(self) -> None:
        self.expected_json.write_text(json.dumps(self.expected), encoding="utf-8")

    def write_inputs(self) -> None:
        plan_bytes = self.plan_bytes()
        self.plan_json.write_bytes(plan_bytes)
        self.terraform_show_json.write_bytes(plan_bytes)
        self.expected["plan_json_sha256"] = hashlib.sha256(plan_bytes).hexdigest()
        self.write_expected()

    def invoke(self, phase: str, source_commit: str | None = None):
        return self.verifier.verify_saved_plan(
            phase=phase,
            plan_file=self.plan_file,
            plan_json_path=self.plan_json,
            expected_json_path=self.expected_json,
            terraform_bin=self.terraform_bin,
            source_commit=source_commit or self.source_commit,
            terraform_version=TERRAFORM_VERSION,
            repository=self.repository,
        )

    def verify(self, phase: str, source_commit: str | None = None):
        self.write_inputs()
        return self.invoke(phase, source_commit)


class OciSavedPlanVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not VERIFIER_PATH.is_file():
            raise AssertionError(
                "scripts/oci/verify_saved_plan.py must be implemented"
            )
        cls.verifier = load_verifier()

    def fixture(self, plan: dict) -> PlanFixture:
        fixture = PlanFixture(self.verifier, plan)
        self.addCleanup(fixture.cleanup)
        return fixture

    def assert_rejected(self, fixture: PlanFixture, phase: str) -> None:
        with self.assertRaises(self.verifier.VerificationError):
            fixture.verify(phase)

    def test_repository_tmp_directory_is_ignored_without_broad_tf_exception(self) -> None:
        rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/.tmp/", rules)
        self.assertNotIn("!/.tmp/", rules)

    def test_accepts_exact_subnet_add_plan(self) -> None:
        fixture = self.fixture(subnet_plan())
        summary = fixture.verify("subnet-add")
        self.assertEqual(summary.resource_changes, 2)
        self.assertEqual(summary.resource_drift, 0)
        self.assertEqual(summary.output_changes, 0)

    def test_accepts_only_explicit_targeted_subnet_add_incomplete_plan(self) -> None:
        fixture = self.fixture(subnet_plan())
        fixture.plan["complete"] = False
        fixture.expected["targeted_plan"] = True
        summary = fixture.verify("subnet-add")
        self.assertEqual(summary.resource_changes, 2)

    def test_rejects_incomplete_subnet_add_without_true_target_marker(self) -> None:
        for marker in (None, False):
            with self.subTest(marker=marker):
                fixture = self.fixture(subnet_plan())
                fixture.plan["complete"] = False
                if marker is not None:
                    fixture.expected["targeted_plan"] = marker
                self.assert_rejected(fixture, "subnet-add")

    def test_rejects_complete_subnet_add_with_target_marker(self) -> None:
        fixture = self.fixture(subnet_plan())
        fixture.expected["targeted_plan"] = True
        self.assert_rejected(fixture, "subnet-add")

    def test_rejects_non_boolean_target_marker(self) -> None:
        for marker in ("true", 1, {}, []):
            with self.subTest(marker=marker):
                fixture = self.fixture(subnet_plan())
                fixture.plan["complete"] = False
                fixture.expected["targeted_plan"] = marker
                self.assert_rejected(fixture, "subnet-add")

    def test_rejects_incomplete_other_phases_without_target_escape(self) -> None:
        for phase, plan in (
            ("refresh-only", refresh_plan()),
            ("replacement", replacement_plan()),
        ):
            for marker in (None, False):
                with self.subTest(phase=phase, marker=marker):
                    fixture = self.fixture(plan)
                    fixture.plan["complete"] = False
                    if marker is not None:
                        fixture.expected["targeted_plan"] = marker
                    self.assert_rejected(fixture, phase)

    def test_rejects_target_marker_for_other_phases(self) -> None:
        for phase, plan in (
            ("refresh-only", refresh_plan()),
            ("replacement", replacement_plan()),
        ):
            with self.subTest(phase=phase):
                fixture = self.fixture(plan)
                fixture.expected["targeted_plan"] = True
                self.assert_rejected(fixture, phase)

    def test_accepts_bound_golden_terraform_1_12_show_json(self) -> None:
        fixture = self.fixture(subnet_plan())
        resource = fixture.plan["resource_changes"][0]
        self.assertEqual(resource["provider_name"], "registry.terraform.io/oracle/oci")
        self.assertEqual(resource["mode"], "managed")
        self.assertIn("before_sensitive", resource["change"])
        try:
            summary = fixture.verify("subnet-add")
        except (TypeError, self.verifier.VerificationError) as exc:
            self.fail(f"bound Terraform 1.12 golden JSON was rejected: {exc}")
        self.assertEqual(summary.terraform_version, TERRAFORM_VERSION)

    def test_runs_terraform_in_plan_parent_with_plan_basename(self) -> None:
        fixture = self.fixture(subnet_plan())
        try:
            fixture.verify("subnet-add")
        except self.verifier.VerificationError as exc:
            self.fail(f"behavioral Terraform fixture rejected invocation: {exc}")

    def test_rejects_saved_plan_path_outside_git_worktree(self) -> None:
        fixture = self.fixture(subnet_plan())
        outside = tempfile.TemporaryDirectory(prefix="racetime-plan-outside-")
        self.addCleanup(outside.cleanup)
        outside_dir = Path(outside.name)
        outside_plan = outside_dir / fixture.plan_file.name
        outside_show = outside_dir / fixture.terraform_show_json.name
        outside_terraform = outside_dir / fixture.terraform_bin.name
        outside_plan.write_bytes(fixture.plan_file.read_bytes())
        outside_show.write_bytes(fixture.terraform_show_json.read_bytes())
        outside_terraform.write_bytes(fixture.terraform_bin.read_bytes())
        if os.name != "nt":
            outside_terraform.chmod(0o700)

        with self.assertRaises(self.verifier.VerificationError):
            self.verifier.verify_saved_plan(
                phase="subnet-add",
                plan_file=outside_plan,
                plan_json_path=fixture.plan_json,
                expected_json_path=fixture.expected_json,
                terraform_bin=outside_terraform,
                source_commit=fixture.source_commit,
                terraform_version=TERRAFORM_VERSION,
                repository=fixture.repository,
            )

    def test_rejects_binary_version_custody_and_show_json_mismatches(self) -> None:
        fixture = self.fixture(subnet_plan())
        fixture.expected["terraform_binary_sha256"] = "0" * 64
        fixture.write_expected()
        with self.assertRaises(self.verifier.VerificationError):
            fixture.invoke("subnet-add")

        fixture = self.fixture(subnet_plan())
        fixture.write_terraform_executable("1.12.3")
        fixture.expected["terraform_binary_sha256"] = hashlib.sha256(
            fixture.terraform_bin.read_bytes()
        ).hexdigest()
        fixture.write_expected()
        with self.assertRaises(self.verifier.VerificationError):
            fixture.invoke("subnet-add")

        fixture = self.fixture(subnet_plan())
        fixture.plan_json.write_bytes(fixture.plan_json.read_bytes() + b" ")
        fixture.expected["plan_json_sha256"] = hashlib.sha256(
            fixture.plan_json.read_bytes()
        ).hexdigest()
        fixture.write_expected()
        with self.assertRaises(self.verifier.VerificationError):
            fixture.invoke("subnet-add")

        fixture = self.fixture(subnet_plan())
        fixture.terraform_show_json.write_bytes(
            fixture.terraform_show_json.read_bytes() + b" "
        )
        with self.assertRaises(self.verifier.VerificationError):
            fixture.invoke("subnet-add")

        fixture = self.fixture(subnet_plan())
        fixture.expected["plan_json_sha256"] = "0" * 64
        fixture.write_expected()
        with self.assertRaises(self.verifier.VerificationError):
            fixture.invoke("subnet-add")

    def test_expected_manifest_binds_phase_source_and_version(self) -> None:
        for field, value in (
            ("phase", "replacement"),
            ("source_commit", "0" * 40),
            ("terraform_version", "1.12.3"),
        ):
            with self.subTest(field=field):
                fixture = self.fixture(subnet_plan())
                fixture.expected[field] = value
                fixture.write_expected()
                with self.assertRaises(self.verifier.VerificationError):
                    fixture.invoke("subnet-add")

    def test_rejects_import_or_generated_config_before_noop_filtering(self) -> None:
        fixtures = []

        create = self.fixture(subnet_plan())
        create.plan["resource_changes"][0]["change"]["importing"] = {
            "id": "redacted"
        }
        fixtures.append(("import-bearing create", create, "subnet-add"))

        importing_update = self.fixture(replacement_plan())
        importing_update.plan["resource_changes"][2]["change"]["importing"] = {
            "id": "redacted"
        }
        fixtures.append(
            ("import-bearing update", importing_update, "replacement")
        )

        importing_noop = self.fixture(subnet_plan())
        importing_noop.plan["resource_changes"].append(
            change(
                "oci_core_vcn.main",
                ["no-op"],
                after={"stable": "same"},
            )
        )
        importing_noop.plan["resource_changes"][-1]["change"]["importing"] = {
            "id": "redacted"
        }
        fixtures.append(("import-bearing no-op", importing_noop, "subnet-add"))

        update = self.fixture(replacement_plan())
        update.plan["resource_changes"][2]["generated_config"] = (
            "resource \"oci_identity_dynamic_group\" \"racetime\" {}"
        )
        fixtures.append(("generated-config update", update, "replacement"))

        noop = self.fixture(subnet_plan())
        unchanged = {"id": "redacted"}
        noop.plan["resource_changes"].append(
            change(
                "oci_core_vcn.main",
                ["no-op"],
                after=unchanged,
            )
        )
        noop.plan["resource_changes"][-1]["change"]["before"] = unchanged
        noop.plan["resource_changes"][-1]["change"]["generated_config"] = (
            "resource \"oci_core_vcn\" \"main\" {}"
        )
        fixtures.append(("generated-config no-op", noop, "subnet-add"))

        for label, fixture, phase in fixtures:
            with self.subTest(label=label):
                self.assert_rejected(fixture, phase)

    def test_requires_terraform_plan_format_version_1_2(self) -> None:
        for value in (None, "2.0"):
            with self.subTest(format_version=value):
                fixture = self.fixture(subnet_plan())
                if value is None:
                    fixture.plan.pop("format_version")
                else:
                    fixture.plan["format_version"] = value
                self.assert_rejected(fixture, "subnet-add")

    def test_subnet_add_accepts_unknown_planned_availability_domain(self) -> None:
        fixture = self.fixture(subnet_plan())
        subnet = fixture.plan["resource_changes"][1]["change"]
        subnet["after"].pop("availability_domain")
        subnet["after_unknown"]["availability_domain"] = True
        fixture.plan["planned_values"]["root_module"]["resources"][0][
            "values"
        ].pop("availability_domain")
        fixture.verify("subnet-add")

    def test_subnet_add_rejects_unproven_planned_regionality(self) -> None:
        fixture = self.fixture(subnet_plan())
        fixture.plan["planned_values"]["root_module"]["resources"][0][
            "values"
        ].pop("availability_domain")
        self.assert_rejected(fixture, "subnet-add")

        fixture = self.fixture(subnet_plan())
        fixture.plan["planned_values"]["root_module"]["resources"][0]["values"][
            "availability_domain"
        ] = "redacted-ad"
        self.assert_rejected(fixture, "subnet-add")

        fixture = self.fixture(subnet_plan())
        fixture.plan["planned_values"] = {}
        self.assert_rejected(fixture, "subnet-add")

    def test_subnet_add_rejects_wrong_expected_network_values(self) -> None:
        mutations = {
            "cidr": lambda after: after.__setitem__("cidr_block", "10.0.99.0/24"),
            "dns": lambda after: after.__setitem__("dns_label", "wrong"),
            "public": lambda after: after.__setitem__(
                "prohibit_public_ip_on_vnic", False
            ),
            "route": lambda after: after.__setitem__("route_table_id", "wrong"),
            "dhcp": lambda after: after.__setitem__("dhcp_options_id", "wrong"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                fixture = self.fixture(subnet_plan())
                mutate(fixture.plan["resource_changes"][1]["change"]["after"])
                self.assert_rejected(fixture, "subnet-add")

    def test_subnet_add_requires_internet_ingress_flag_false(self) -> None:
        fixture = self.fixture(subnet_plan())
        fixture.plan["resource_changes"][1]["change"]["after"][
            "prohibit_internet_ingress"
        ] = True
        self.assert_rejected(fixture, "subnet-add")

    def test_subnet_add_rejects_non_live_expected_route_or_dhcp_identifiers(self) -> None:
        for field in ("route_table_id", "dhcp_options_id"):
            with self.subTest(field=field):
                fixture = self.fixture(subnet_plan())
                fixture.expected["subnet"][field] = None
                fixture.plan["resource_changes"][1]["change"]["after"][field] = None
                self.assert_rejected(fixture, "subnet-add")

    def test_subnet_add_rejects_default_or_wrong_security_list_reference(self) -> None:
        fixture = self.fixture(subnet_plan())
        subnet_change = fixture.plan["resource_changes"][1]["change"]
        subnet_change["after"]["security_list_ids"] = [
            "ocid1.securitylist.default"
        ]
        subnet_change["after_unknown"].pop("security_list_ids")
        self.assert_rejected(fixture, "subnet-add")

        references = (
            [],
            ["data.oci_core_security_lists.default.security_lists"],
            [
                "oci_core_security_list.racetime.id",
                "data.oci_core_security_lists.default.security_lists",
            ],
        )
        for value in references:
            with self.subTest(references=value):
                fixture = self.fixture(subnet_plan())
                expression = fixture.plan["configuration"]["root_module"][
                    "resources"
                ][1]["expressions"]["security_list_ids"]
                expression["references"] = value
                self.assert_rejected(fixture, "subnet-add")

    def test_subnet_add_rejects_configured_or_non_null_availability_domain(self) -> None:
        fixture = self.fixture(subnet_plan())
        expressions = fixture.plan["configuration"]["root_module"]["resources"][1][
            "expressions"
        ]
        expressions["availability_domain"] = {"constant_value": "redacted-ad"}
        self.assert_rejected(fixture, "subnet-add")

        fixture = self.fixture(subnet_plan())
        fixture.plan["resource_changes"][1]["change"]["after"][
            "availability_domain"
        ] = "redacted-ad"
        self.assert_rejected(fixture, "subnet-add")

    def test_subnet_add_rejects_extra_ingress_or_non_ipv4_all_egress(self) -> None:
        fixture = self.fixture(subnet_plan())
        rules = fixture.plan["resource_changes"][0]["change"]["after"]
        rules["ingress_security_rules"].append({"protocol": "6"})
        self.assert_rejected(fixture, "subnet-add")

        fixture = self.fixture(subnet_plan())
        egress = fixture.plan["resource_changes"][0]["change"]["after"][
            "egress_security_rules"
        ][0]
        egress["destination"] = "::/0"
        self.assert_rejected(fixture, "subnet-add")

        fixture = self.fixture(subnet_plan())
        egress = fixture.plan["resource_changes"][0]["change"]["after"][
            "egress_security_rules"
        ][0]
        egress["stateless"] = True
        self.assert_rejected(fixture, "subnet-add")

    def test_subnet_add_rejects_restream_or_other_extra_action(self) -> None:
        for address in (
            "oci_core_instance.restream",
            "oci_core_route_table.unexpected",
        ):
            with self.subTest(address=address):
                fixture = self.fixture(subnet_plan())
                fixture.plan["resource_changes"].append(
                    change(address, ["update"], {"stable": "changed"})
                )
                self.assert_rejected(fixture, "subnet-add")

    def test_accepts_exact_refresh_only_plan(self) -> None:
        fixture = self.fixture(refresh_plan())
        summary = fixture.verify("refresh-only")
        self.assertEqual(summary.resource_changes, 0)
        self.assertEqual(summary.resource_drift, 1)
        self.assertEqual(summary.output_changes, 4)

    def test_refresh_only_rejects_live_mutation(self) -> None:
        fixture = self.fixture(refresh_plan())
        fixture.plan["resource_changes"] = [
            change("oci_core_instance.racetime", ["update"], {"stable": "changed"})
        ]
        self.assert_rejected(fixture, "refresh-only")

    def test_refresh_only_rejects_wrong_drift_or_extra_output(self) -> None:
        fixture = self.fixture(refresh_plan())
        fixture.plan["resource_drift"][0]["change"]["actions"] = ["update"]
        self.assert_rejected(fixture, "refresh-only")

        fixture = self.fixture(refresh_plan())
        fixture.plan["output_changes"]["unexpected_output"] = {
            "actions": ["update"]
        }
        self.assert_rejected(fixture, "refresh-only")

        fixture = self.fixture(refresh_plan())
        fixture.plan["output_changes"]["instance_id"]["actions"] = ["delete"]
        self.assert_rejected(fixture, "refresh-only")

    def test_accepts_exact_replacement_plan(self) -> None:
        fixture = self.fixture(replacement_plan())
        summary = fixture.verify("replacement")
        self.assertEqual(summary.resource_changes, 5)
        self.assertEqual(summary.resource_drift, 0)
        self.assertEqual(summary.output_changes, 4)

    def test_replacement_requires_provider_native_public_ip_false(self) -> None:
        invalid_values = (
            False,
            True,
            "False",
            "true",
            " false",
            "false ",
            "",
            "0",
            0,
            1,
            None,
            [],
            {},
        )
        for value in invalid_values:
            with self.subTest(value=value):
                fixture = self.fixture(replacement_plan())
                fixture.plan["resource_changes"][0]["change"]["after"][
                    "create_vnic_details"
                ][0]["assign_public_ip"] = value
                self.assert_rejected(fixture, "replacement")

    def test_accepts_terraform_omitted_empty_change_collections(self) -> None:
        cases = (
            ("subnet-add", subnet_plan, ("resource_drift", "output_changes")),
            ("refresh-only", refresh_plan, ("resource_changes",)),
            ("replacement", replacement_plan, ("resource_drift",)),
        )
        for phase, build, omitted in cases:
            with self.subTest(phase=phase):
                fixture = self.fixture(build())
                for key in omitted:
                    fixture.plan.pop(key)
                try:
                    fixture.verify(phase)
                except self.verifier.VerificationError as exc:
                    self.fail(f"omitted Terraform collections were rejected: {exc}")

    def test_rejects_present_change_collections_with_wrong_types(self) -> None:
        cases = (
            ("subnet-add", subnet_plan, "resource_drift", {}),
            ("refresh-only", refresh_plan, "resource_changes", {}),
            ("replacement", replacement_plan, "output_changes", []),
        )
        for phase, build, key, value in cases:
            with self.subTest(phase=phase, key=key):
                fixture = self.fixture(build())
                fixture.plan[key] = value
                self.assert_rejected(fixture, phase)

    def test_ignores_valid_terraform_noop_resources_and_outputs(self) -> None:
        cases = (
            ("subnet-add", subnet_plan, (2, 0, 0)),
            ("refresh-only", refresh_plan, (0, 1, 4)),
            ("replacement", replacement_plan, (5, 0, 4)),
        )
        for phase, build, counts in cases:
            with self.subTest(phase=phase):
                fixture = self.fixture(build())
                fixture.plan["resource_changes"].append(
                    change(
                        'data.oci_core_instance.restream_inventory["resolved"]',
                        ["no-op"],
                        {"stable": "same"},
                    )
                )
                fixture.plan["output_changes"]["unchanged_output"] = {
                    "actions": ["no-op"],
                    "before": "same",
                    "after": "same",
                    "after_unknown": False,
                }
                try:
                    summary = fixture.verify(phase)
                except self.verifier.VerificationError as exc:
                    self.fail(f"Terraform no-op records were rejected: {exc}")
                self.assertEqual(
                    (
                        summary.resource_changes,
                        summary.resource_drift,
                        summary.output_changes,
                    ),
                    counts,
                )

    def test_rejects_malformed_resource_noop_before_filtering(self) -> None:
        mutations = {
            "previous-address": lambda entry: entry.__setitem__(
                "previous_address", "oci_core_instance.previous"
            ),
            "changed-after": lambda entry: entry["change"].__setitem__(
                "after", {"stable": "changed"}
            ),
            "unknown-after": lambda entry: entry["change"].__setitem__(
                "after_unknown", {"id": True}
            ),
            "missing-values": lambda entry: (
                entry["change"].pop("before"),
                entry["change"].pop("after"),
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                fixture = self.fixture(subnet_plan())
                noop = change(
                    "oci_core_instance.resolved_noop",
                    ["no-op"],
                    {"stable": "same"},
                )
                mutate(noop)
                fixture.plan["resource_changes"].append(noop)
                self.assert_rejected(fixture, "subnet-add")

    def test_rejects_previous_address_on_actionable_resource_changes(self) -> None:
        cases = (
            (
                "replacement update",
                replacement_plan,
                "replacement",
                2,
                "oci_identity_dynamic_group.restream",
            ),
            (
                "subnet create",
                subnet_plan,
                "subnet-add",
                0,
                "oci_core_security_list.restream",
            ),
            (
                "replacement read",
                replacement_plan,
                "replacement",
                4,
                "data.oci_core_private_ips.restream",
            ),
        )
        for label, build, phase, index, previous_address in cases:
            with self.subTest(label=label):
                fixture = self.fixture(build())
                fixture.plan["resource_changes"][index][
                    "previous_address"
                ] = previous_address
                self.assert_rejected(fixture, phase)

    def test_rejects_null_or_empty_previous_address_metadata(self) -> None:
        refresh = self.fixture(refresh_plan())
        refresh.plan["resource_drift"][0]["previous_address"] = None

        subnet = self.fixture(subnet_plan())
        unchanged = change(
            "oci_core_vcn.resolved_noop",
            ["no-op"],
            {"stable": "same"},
        )
        unchanged["previous_address"] = ""
        subnet.plan["resource_changes"].append(unchanged)

        for label, fixture, phase in (
            ("null drift", refresh, "refresh-only"),
            ("empty no-op", subnet, "subnet-add"),
        ):
            with self.subTest(label=label):
                self.assert_rejected(fixture, phase)

    def test_rejects_malformed_output_noop_before_filtering(self) -> None:
        malformed = (
            {
                "actions": ["no-op"],
                "before": "before",
                "after": "after",
                "after_unknown": False,
            },
            {
                "actions": ["no-op"],
                "before": "same",
                "after": "same",
                "after_unknown": True,
            },
            {
                "actions": ["no-op"],
                "after_unknown": False,
            },
        )
        for value in malformed:
            with self.subTest(value=value):
                fixture = self.fixture(subnet_plan())
                fixture.plan["output_changes"]["malformed_noop"] = value
                self.assert_rejected(fixture, "subnet-add")

    def test_rejects_extra_noop_restream_drift_in_every_phase(self) -> None:
        for phase, build in (
            ("subnet-add", subnet_plan),
            ("refresh-only", refresh_plan),
            ("replacement", replacement_plan),
        ):
            with self.subTest(phase=phase):
                fixture = self.fixture(build())
                fixture.plan["resource_drift"].append(
                    change(
                        'oci_core_instance.restream_inventory["resolved"]',
                        ["no-op"],
                        {"stable": "same"},
                    )
                )
                self.assert_rejected(fixture, phase)

    def test_refresh_only_rejects_previous_address_drift_move(self) -> None:
        fixture = self.fixture(refresh_plan())
        fixture.plan["resource_drift"][0]["previous_address"] = (
            "oci_core_instance.racetime_previous"
        )
        self.assert_rejected(fixture, "refresh-only")

    def test_accepts_phase_specific_terraform_data_reads(self) -> None:
        fixture = self.fixture(subnet_plan())
        fixture.plan["resource_changes"].append(
            change(
                "data.oci_core_subnet.bastion",
                ["read"],
                {"id": "redacted-subnet"},
            )
        )
        try:
            fixture.verify("subnet-add")
        except self.verifier.VerificationError as exc:
            self.fail(f"expected subnet data read was rejected: {exc}")

        fixture = self.fixture(replacement_plan())
        try:
            fixture.verify("replacement")
        except self.verifier.VerificationError as exc:
            self.fail(f"expected private-IP data read was rejected: {exc}")

    def test_replacement_requires_private_ip_data_read(self) -> None:
        fixture = self.fixture(replacement_plan())
        fixture.plan["resource_changes"] = [
            item
            for item in fixture.plan["resource_changes"]
            if item["address"] != "data.oci_core_private_ips.racetime"
        ]
        self.assert_rejected(fixture, "replacement")

    def test_rejects_unexpected_actionable_data_read_in_every_phase(self) -> None:
        for phase, build in (
            ("subnet-add", subnet_plan),
            ("refresh-only", refresh_plan),
            ("replacement", replacement_plan),
        ):
            with self.subTest(phase=phase):
                fixture = self.fixture(build())
                fixture.plan["resource_changes"].append(
                    change(
                        'data.oci_core_instance.restream_inventory["unexpected"]',
                        ["read"],
                        {"id": "redacted-restream"},
                    )
                )
                self.assert_rejected(fixture, phase)

    def test_replacement_rejects_unexpected_output_action(self) -> None:
        for actions in (["create"], ["delete"], ["no-op"], ["delete", "create"]):
            with self.subTest(actions=actions):
                fixture = self.fixture(replacement_plan())
                fixture.plan["output_changes"]["instance_id"]["actions"] = actions
                self.assert_rejected(fixture, "replacement")

    def test_replacement_requires_exact_deferred_output_shape(self) -> None:
        mutations = {
            "known-before": lambda change: change.__setitem__(
                "before", "injected"
            ),
            "known-after": lambda change: change.__setitem__("after", "injected"),
            "not-unknown": lambda change: change.__setitem__(
                "after_unknown", False
            ),
            "before-not-sensitive": lambda change: change.__setitem__(
                "before_sensitive", False
            ),
            "after-not-sensitive": lambda change: change.__setitem__(
                "after_sensitive", False
            ),
            "extra-field": lambda change: change.__setitem__("unexpected", True),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                fixture = self.fixture(replacement_plan())
                mutate(fixture.plan["output_changes"]["instance_id"])
                self.assert_rejected(fixture, "replacement")

        fixture = self.fixture(replacement_plan())
        fixture.plan["output_changes"].pop("instance_id")
        self.assert_rejected(fixture, "replacement")

        fixture = self.fixture(replacement_plan())
        fixture.plan["output_changes"]["unexpected"] = {
            "actions": ["update"],
            "before": None,
            "after": None,
            "after_unknown": True,
            "before_sensitive": True,
            "after_sensitive": True,
        }
        self.assert_rejected(fixture, "replacement")

    def test_replacement_rejects_extra_updated_field(self) -> None:
        fixture = self.fixture(replacement_plan())
        dynamic_group = fixture.plan["resource_changes"][2]["change"]
        dynamic_group["before"]["description"] = "old"
        dynamic_group["after"]["description"] = "new"
        self.assert_rejected(fixture, "replacement")

    def test_replacement_rejects_wrong_vnic_or_public_ip_contract(self) -> None:
        mutations = {
            "subnet": lambda plan: plan["resource_changes"][0]["change"]["after"][
                "create_vnic_details"
            ][0].__setitem__("subnet_id", "wrong"),
            "nsg": lambda plan: plan["resource_changes"][0]["change"]["after"][
                "create_vnic_details"
            ][0].__setitem__("nsg_ids", ["wrong"]),
            "public-vnic": lambda plan: plan["resource_changes"][0]["change"][
                "after"
            ]["create_vnic_details"][0].__setitem__("assign_public_ip", True),
            "ipv6-vnic": lambda plan: plan["resource_changes"][0]["change"]["after"][
                "create_vnic_details"
            ][0].__setitem__("assign_ipv6ip", True),
            "lifetime": lambda plan: plan["resource_changes"][1]["change"][
                "after"
            ].__setitem__("lifetime", "EPHEMERAL"),
            "private-ip": lambda plan: plan["resource_changes"][1]["change"][
                "after"
            ].__setitem__("private_ip_id", "wrong"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                fixture = self.fixture(replacement_plan())
                mutate(fixture.plan)
                self.assert_rejected(fixture, "replacement")

    def test_replacement_requires_private_ip_data_reference(self) -> None:
        attribute = "data.oci_core_private_ips.racetime.private_ips"
        root = "data.oci_core_private_ips.racetime"
        invalid_references = (
            [attribute],
            [root],
            ["oci_core_instance.racetime.private_ip"],
            [attribute, root, "data.oci_core_private_ips.unrelated"],
            [],
            [attribute, root, root],
            [root, attribute],
        )
        for references in invalid_references:
            with self.subTest(references=references):
                fixture = self.fixture(replacement_plan())
                expression = fixture.plan["configuration"]["root_module"][
                    "resources"
                ][0]["expressions"]["private_ip_id"]
                expression["references"] = references
                self.assert_rejected(fixture, "replacement")

    def test_replacement_rejects_non_live_expected_subnet_identifier(self) -> None:
        fixture = self.fixture(replacement_plan())
        fixture.expected["replacement"]["subnet_id"] = None
        fixture.plan["resource_changes"][0]["change"]["after"][
            "create_vnic_details"
        ][0]["subnet_id"] = None
        self.assert_rejected(fixture, "replacement")

    def test_replacement_requires_deferred_private_ip_value(self) -> None:
        fixture = self.fixture(replacement_plan())
        public_ip = fixture.plan["resource_changes"][1]["change"]
        public_ip["after"]["private_ip_id"] = "ocid1.privateip.expected"
        public_ip["after_unknown"].pop("private_ip_id")
        self.assert_rejected(fixture, "replacement")

        fixture = self.fixture(replacement_plan())
        fixture.plan["resource_changes"][1]["change"]["after_unknown"].pop(
            "private_ip_id"
        )
        self.assert_rejected(fixture, "replacement")

    def test_rejects_malformed_incomplete_errored_or_wrong_version_plan(self) -> None:
        fixture = self.fixture(subnet_plan())
        fixture.plan_json.write_text("{malformed", encoding="utf-8")
        with self.assertRaises(self.verifier.VerificationError):
            self.verifier.verify_saved_plan(
                phase="subnet-add",
                plan_file=fixture.plan_file,
                plan_json_path=fixture.plan_json,
                expected_json_path=fixture.expected_json,
                terraform_bin=fixture.terraform_bin,
                source_commit=fixture.source_commit,
                terraform_version=TERRAFORM_VERSION,
                repository=fixture.repository,
            )

        mutations = {
            "not-applyable": ("applyable", False),
            "incomplete": ("complete", False),
            "errored": ("errored", True),
            "wrong-version": ("terraform_version", "1.12.1"),
        }
        for label, (key, value) in mutations.items():
            with self.subTest(label=label):
                fixture = self.fixture(subnet_plan())
                fixture.plan[key] = value
                self.assert_rejected(fixture, "subnet-add")

    def test_rejects_unpinned_version_even_when_caller_and_plan_agree(self) -> None:
        fixture = self.fixture(subnet_plan())
        fixture.plan["terraform_version"] = "1.12.3"
        fixture.write_inputs()
        with self.assertRaises(self.verifier.VerificationError):
            self.verifier.verify_saved_plan(
                phase="subnet-add",
                plan_file=fixture.plan_file,
                plan_json_path=fixture.plan_json,
                expected_json_path=fixture.expected_json,
                terraform_bin=fixture.terraform_bin,
                source_commit=fixture.source_commit,
                terraform_version="1.12.3",
                repository=fixture.repository,
            )

    def test_rejects_binary_hash_or_source_commit_mismatch(self) -> None:
        fixture = self.fixture(subnet_plan())
        fixture.plan_file.write_bytes(b"different binary plan")
        self.assert_rejected(fixture, "subnet-add")

        fixture = self.fixture(subnet_plan())
        with self.assertRaises(self.verifier.VerificationError):
            fixture.verify("subnet-add", source_commit="0" * 40)

    def test_rejects_non_ignored_untracked_terraform_file(self) -> None:
        fixture = self.fixture(subnet_plan())
        (fixture.repository / "unexpected.tf").write_text(
            "# must make Git dirty\n", encoding="utf-8"
        )
        self.assert_rejected(fixture, "subnet-add")

    def test_cli_output_contains_only_redacted_metadata(self) -> None:
        fixture = self.fixture(subnet_plan())
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER_PATH),
                "--phase",
                "subnet-add",
                "--plan-file",
                str(fixture.plan_file),
                "--plan-json",
                str(fixture.plan_json),
                "--expected-json",
                str(fixture.expected_json),
                "--terraform-bin",
                str(fixture.terraform_bin),
                "--source-commit",
                fixture.source_commit,
                "--terraform-version",
                TERRAFORM_VERSION,
            ],
            cwd=fixture.repository,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        digest = fixture.expected["plan_sha256"]
        self.assertEqual(
            result.stdout.strip(),
            "OCI_SAVED_PLAN_VERIFY=PASS "
            f"phase=subnet-add source_commit={fixture.source_commit} "
            f"plan_sha256={digest} terraform_version={TERRAFORM_VERSION} "
            "resource_changes=2 resource_drift=0 output_changes=0",
        )
        for raw_value in (
            "10.0.50.0/24",
            "ocid1.routetable.expected",
            "ocid1.dhcpoptions.expected",
            "synthetic saved Terraform plan",
        ):
            self.assertNotIn(raw_value, result.stdout)
            self.assertNotIn(raw_value, result.stderr)

    def test_cli_failure_does_not_echo_plan_values(self) -> None:
        fixture = self.fixture(subnet_plan())
        secret_value = "do-not-echo-this-cidr"
        fixture.plan["resource_changes"][1]["change"]["after"][
            "cidr_block"
        ] = secret_value
        fixture.write_inputs()
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER_PATH),
                "--phase",
                "subnet-add",
                "--plan-file",
                str(fixture.plan_file),
                "--plan-json",
                str(fixture.plan_json),
                "--expected-json",
                str(fixture.expected_json),
                "--terraform-bin",
                str(fixture.terraform_bin),
                "--source-commit",
                fixture.source_commit,
                "--terraform-version",
                TERRAFORM_VERSION,
            ],
            cwd=fixture.repository,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr.strip(), "OCI_SAVED_PLAN_VERIFY=FAIL phase=subnet-add"
        )
        self.assertEqual(result.stdout, "")
        self.assertNotIn(secret_value, result.stderr)


if __name__ == "__main__":
    unittest.main()
