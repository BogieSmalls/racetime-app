#!/usr/bin/env python3
"""Fail closed unless a saved OCI Terraform plan matches an approved shape."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


PHASES = ("subnet-add", "refresh-only", "replacement")
PINNED_TERRAFORM_VERSION = "1.12.2"
SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
OUTPUT_NAMES = {
    "instance_id",
    "instance_public_ip",
    "instance_private_ip",
    "boot_volume_id",
}


class VerificationError(RuntimeError):
    """Raised when saved-plan verification cannot prove the plan is safe."""


@dataclass(frozen=True)
class VerificationSummary:
    phase: str
    source_commit: str
    plan_sha256: str
    terraform_version: str
    resource_changes: int
    resource_drift: int
    output_changes: int


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        if not path.is_file() or path.is_symlink():
            raise VerificationError(f"{label} is not a regular file")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be an object")
    return value


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        if not path.is_file() or path.is_symlink():
            raise VerificationError(f"{label} is not a regular file")
        return path.read_bytes()
    except OSError as exc:
        raise VerificationError(f"{label} cannot be read") from exc


def _parse_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(_read_bytes(path, "hashed file")).hexdigest()


def _expected_sha256(expected: dict[str, Any], key: str) -> str:
    value = expected.get(key)
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise VerificationError("expected JSON contains an invalid digest")
    return value


def _run_terraform(
    terraform_bin: Path, repository: Path, *arguments: str
) -> bytes:
    try:
        result = subprocess.run(
            [str(terraform_bin), *arguments],
            cwd=repository,
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError("Terraform execution failed") from exc
    if result.returncode != 0:
        raise VerificationError("Terraform execution failed")
    return result.stdout


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        raise VerificationError("Git cannot be executed") from exc


def _verify_repository(repository: Path, source_commit: str) -> Path:
    if SOURCE_COMMIT.fullmatch(source_commit) is None:
        raise VerificationError("source commit is invalid")
    try:
        candidate = repository.resolve(strict=True)
    except OSError as exc:
        raise VerificationError("repository is unavailable") from exc
    if not candidate.is_dir():
        raise VerificationError("repository is unavailable")

    top_level = _git(candidate, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        raise VerificationError("repository is not a Git worktree")
    try:
        root = Path(top_level.stdout.strip()).resolve(strict=True)
    except OSError as exc:
        raise VerificationError("Git worktree root is invalid") from exc

    head = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
    if head.returncode != 0 or head.stdout.strip() != source_commit:
        raise VerificationError("source commit does not match HEAD")
    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    if status.returncode != 0 or status.stdout != "":
        raise VerificationError("Git worktree is not clean")
    return root


def _resolve_saved_plan(plan_file: Path, repository_root: Path) -> Path:
    try:
        lexical_path = plan_file.absolute()
        resolved_path = plan_file.resolve(strict=True)
    except OSError as exc:
        raise VerificationError("saved plan path cannot be resolved") from exc
    if lexical_path != resolved_path or not resolved_path.is_file():
        raise VerificationError("saved plan path is ambiguous")
    try:
        resolved_path.relative_to(repository_root)
    except ValueError as exc:
        raise VerificationError("saved plan is outside the Git worktree") from exc
    return resolved_path


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise VerificationError(f"{label} must be a list")
    return value


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be an object")
    return value


def _validate_noop(change: dict[str, Any], label: str) -> None:
    after_unknown = change.get("after_unknown")
    unknown_is_empty = (
        after_unknown is None
        or after_unknown is False
        or after_unknown == {}
        or after_unknown == []
    )
    if (
        "before" not in change
        or "after" not in change
        or change["before"] != change["after"]
        or not unknown_is_empty
    ):
        raise VerificationError(f"{label} contains a malformed no-op")


def _has_nonempty_metadata(container: dict[str, Any], key: str) -> bool:
    if key not in container:
        return False
    value = container[key]
    return value is not None and value != "" and value != {} and value != []


def _change_map(
    plan: dict[str, Any],
    key: str,
    *,
    filter_noop: bool = True,
    reject_previous_address: bool = False,
) -> dict[str, dict[str, Any]]:
    entries = _require_list(plan.get(key, []), key)
    result: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for entry_value in entries:
        entry = _require_mapping(entry_value, key)
        address = entry.get("address")
        if not isinstance(address, str) or not address or address in seen:
            raise VerificationError(f"{key} contains an invalid address")
        seen.add(address)
        if reject_previous_address and "previous_address" in entry:
            raise VerificationError(f"{key} contains a previous address")
        change = _require_mapping(entry.get("change"), key)
        if any(
            _has_nonempty_metadata(container, metadata_key)
            for container in (entry, change)
            for metadata_key in ("importing", "generated_config")
        ):
            raise VerificationError(f"{key} contains import metadata")
        actions = change.get("actions")
        if (
            not isinstance(actions, list)
            or not actions
            or any(not isinstance(action, str) for action in actions)
        ):
            raise VerificationError(f"{key} contains invalid actions")
        if filter_noop and actions == ["no-op"]:
            if "previous_address" in entry:
                raise VerificationError(f"{key} no-op contains a previous address")
            _validate_noop(change, key)
            continue
        result[address] = change
    return result


def _output_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    outputs = _require_mapping(plan.get("output_changes", {}), "output_changes")
    result: dict[str, dict[str, Any]] = {}
    for name, value in outputs.items():
        if not isinstance(name, str) or not name:
            raise VerificationError("output_changes contains an invalid name")
        change = _require_mapping(value, "output_changes")
        actions = change.get("actions")
        if (
            not isinstance(actions, list)
            or not actions
            or any(not isinstance(action, str) for action in actions)
        ):
            raise VerificationError("output_changes contains invalid actions")
        if actions == ["no-op"]:
            _validate_noop(change, "output_changes")
            continue
        result[name] = change
    return result


def _require_actions(
    actual: dict[str, dict[str, Any]], expected: dict[str, list[str]], label: str
) -> None:
    if set(actual) != set(expected):
        raise VerificationError(f"{label} has an unexpected address")
    for address, actions in expected.items():
        if actual[address].get("actions") != actions:
            raise VerificationError(f"{label} has an unexpected action")


def _configuration_resources(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    configuration = _require_mapping(plan.get("configuration"), "configuration")
    root = _require_mapping(configuration.get("root_module"), "configuration")
    found: dict[str, dict[str, Any]] = {}

    def visit(module: dict[str, Any]) -> None:
        for value in _require_list(module.get("resources", []), "configuration"):
            resource = _require_mapping(value, "configuration")
            address = resource.get("address")
            if not isinstance(address, str) or not address or address in found:
                raise VerificationError("configuration contains an invalid address")
            found[address] = resource
        module_calls = module.get("module_calls", {})
        if isinstance(module_calls, dict):
            calls = module_calls.values()
        elif isinstance(module_calls, list):
            calls = module_calls
        else:
            raise VerificationError("configuration module calls are invalid")
        for value in calls:
            call = _require_mapping(value, "configuration")
            child = call.get("module")
            if child is not None:
                visit(_require_mapping(child, "configuration"))

    visit(root)
    return found


def _planned_resource_values(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    planned_values = _require_mapping(plan.get("planned_values"), "planned_values")
    root = _require_mapping(planned_values.get("root_module"), "planned_values")
    found: dict[str, dict[str, Any]] = {}

    def visit(module: dict[str, Any]) -> None:
        for value in _require_list(module.get("resources", []), "planned_values"):
            resource = _require_mapping(value, "planned_values")
            address = resource.get("address")
            if not isinstance(address, str) or not address or address in found:
                raise VerificationError("planned_values contains an invalid address")
            found[address] = _require_mapping(resource.get("values"), "planned_values")
        for value in _require_list(
            module.get("child_modules", []), "planned_values"
        ):
            visit(_require_mapping(value, "planned_values"))

    visit(root)
    return found


def _expressions(resource: dict[str, Any]) -> dict[str, Any]:
    return _require_mapping(resource.get("expressions", {}), "configuration")


def _references(expression: Any) -> list[str]:
    value = _require_mapping(expression, "configuration").get("references")
    references = _require_list(value, "configuration")
    if not references or any(not isinstance(item, str) for item in references):
        raise VerificationError("configuration contains invalid references")
    return references


def _expected_section(expected: dict[str, Any], name: str) -> dict[str, Any]:
    section = expected.get(name)
    if section is None:
        return expected
    return _require_mapping(section, "expected JSON")


def _expected_value(
    expected: dict[str, Any], section_name: str, *names: str
) -> Any:
    section = _expected_section(expected, section_name)
    for name in names:
        if name in section:
            return section[name]
    if section is not expected:
        for name in names:
            if name in expected:
                return expected[name]
    raise VerificationError("expected JSON is missing a required field")


def _after(change: dict[str, Any]) -> dict[str, Any]:
    return _require_mapping(change.get("after"), "resource change")


def _verify_subnet_add(
    plan: dict[str, Any],
    expected: dict[str, Any],
    resources: dict[str, dict[str, Any]],
    drift: dict[str, dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
    planned_resources: dict[str, dict[str, Any]],
) -> None:
    expected_actions = {
        "oci_core_security_list.racetime": ["create"],
        "oci_core_subnet.racetime": ["create"],
    }
    if "data.oci_core_subnet.bastion" in resources:
        expected_actions["data.oci_core_subnet.bastion"] = ["read"]
    _require_actions(
        resources,
        expected_actions,
        "resource_changes",
    )
    if drift or outputs:
        raise VerificationError("subnet-add contains an unexpected change")

    security = _after(resources["oci_core_security_list.racetime"])
    ingress = _require_list(
        security.get("ingress_security_rules"), "ingress security rules"
    )
    egress = _require_list(
        security.get("egress_security_rules"), "egress security rules"
    )
    if ingress != [] or len(egress) != 1:
        raise VerificationError("security-list rules do not match the contract")
    rule = _require_mapping(egress[0], "egress security rule")
    if (
        rule.get("destination") != "0.0.0.0/0"
        or rule.get("destination_type") != "CIDR_BLOCK"
        or rule.get("protocol") != "all"
        or rule.get("stateless") is not False
    ):
        raise VerificationError("security-list rules do not match the contract")

    subnet_change = resources["oci_core_subnet.racetime"]
    subnet = _after(subnet_change)
    expected_fields = {
        "cidr_block": _expected_value(expected, "subnet", "cidr_block"),
        "dns_label": _expected_value(expected, "subnet", "dns_label"),
        "prohibit_public_ip_on_vnic": _expected_value(
            expected, "subnet", "prohibit_public_ip_on_vnic"
        ),
        "route_table_id": _expected_value(expected, "subnet", "route_table_id"),
        "dhcp_options_id": _expected_value(
            expected, "subnet", "dhcp_options_id"
        ),
    }
    for name in ("route_table_id", "dhcp_options_id"):
        value = expected_fields[name]
        if not isinstance(value, str) or not value:
            raise VerificationError("expected JSON contains an invalid live identifier")
    if any(subnet.get(name) != value for name, value in expected_fields.items()):
        raise VerificationError("subnet values do not match the contract")
    if subnet.get("prohibit_internet_ingress") is not False:
        raise VerificationError("subnet internet-ingress flag does not match")
    if subnet.get("availability_domain") is not None:
        raise VerificationError("subnet availability domain is not regional")
    after_unknown = _require_mapping(
        subnet_change.get("after_unknown"), "resource change"
    )
    planned_subnet = planned_resources.get("oci_core_subnet.racetime")
    if planned_subnet is None:
        raise VerificationError("planned subnet values are missing")
    if "availability_domain" in planned_subnet:
        if planned_subnet["availability_domain"] is not None:
            raise VerificationError("planned subnet is not regional")
    elif after_unknown.get("availability_domain") is not True:
        raise VerificationError("planned subnet regionality is not proven")
    planned_security_lists = subnet.get("security_list_ids")
    unknown_security_lists = after_unknown.get("security_list_ids")
    if (
        planned_security_lists not in (None, [None])
        or (
            unknown_security_lists is not True
            and unknown_security_lists != [True]
        )
    ):
        raise VerificationError("subnet does not plan one dedicated security list")

    configuration = _configuration_resources(plan)
    configured_subnet = configuration.get("oci_core_subnet.racetime")
    if configured_subnet is None:
        raise VerificationError("subnet configuration is missing")
    expressions = _expressions(configured_subnet)
    if "availability_domain" in expressions:
        raise VerificationError("subnet availability domain is configured")
    references = _references(expressions.get("security_list_ids"))
    allowed = {
        "oci_core_security_list.racetime",
        "oci_core_security_list.racetime.id",
    }
    if (
        "oci_core_security_list.racetime.id" not in references
        or any(reference not in allowed for reference in references)
    ):
        raise VerificationError("subnet security-list reference is not dedicated")


def _verify_refresh_only(
    resources: dict[str, dict[str, Any]],
    drift: dict[str, dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
) -> None:
    if resources:
        raise VerificationError("refresh-only contains a live mutation")
    _require_actions(
        drift,
        {"oci_core_instance.racetime": ["delete"]},
        "resource_drift",
    )
    if set(outputs) != OUTPUT_NAMES:
        raise VerificationError("refresh-only has an unexpected output")
    if any(change.get("actions") != ["update"] for change in outputs.values()):
        raise VerificationError("refresh-only has an unexpected output action")


def _truthy_unknown_fields(value: Any) -> set[str]:
    if not isinstance(value, dict):
        return set()
    return {name for name, unknown in value.items() if unknown}


def _changed_fields(change: dict[str, Any]) -> set[str]:
    before = _require_mapping(change.get("before"), "update before value")
    after = _require_mapping(change.get("after"), "update after value")
    names = set(before) | set(after)
    changed = {name for name in names if before.get(name) != after.get(name)}
    return changed | _truthy_unknown_fields(change.get("after_unknown", {}))


def _verify_replacement(
    plan: dict[str, Any],
    expected: dict[str, Any],
    resources: dict[str, dict[str, Any]],
    drift: dict[str, dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
) -> None:
    _require_actions(
        resources,
        {
            "oci_core_instance.racetime": ["create"],
            "oci_core_public_ip.racetime": ["create"],
            "oci_identity_dynamic_group.racetime": ["update"],
            "oci_monitoring_alarm.instance_cpu": ["update"],
            "data.oci_core_private_ips.racetime": ["read"],
        },
        "resource_changes",
    )
    if drift:
        raise VerificationError("replacement contains unexpected drift")
    if not set(outputs).issubset(OUTPUT_NAMES):
        raise VerificationError("replacement has an unexpected output")
    if any(change.get("actions") != ["create"] for change in outputs.values()):
        raise VerificationError("replacement has an unexpected output action")
    if _changed_fields(resources["oci_identity_dynamic_group.racetime"]) != {
        "matching_rule"
    }:
        raise VerificationError("dynamic-group update exceeds the contract")
    if _changed_fields(resources["oci_monitoring_alarm.instance_cpu"]) != {"query"}:
        raise VerificationError("alarm update exceeds the contract")

    instance = _after(resources["oci_core_instance.racetime"])
    vnic_value = instance.get("create_vnic_details")
    if isinstance(vnic_value, list) and len(vnic_value) == 1:
        vnic = _require_mapping(vnic_value[0], "create_vnic_details")
    elif isinstance(vnic_value, dict):
        vnic = vnic_value
    else:
        raise VerificationError("instance VNIC contract is missing")

    expected_nsgs = _expected_value(
        expected,
        "replacement",
        "network_security_group_ids",
        "nsg_ids",
        "network_security_group_id",
        "nsg_id",
    )
    if isinstance(expected_nsgs, str):
        expected_nsgs = [expected_nsgs]
    if (
        not isinstance(expected_nsgs, list)
        or len(expected_nsgs) != 1
        or any(not isinstance(item, str) or not item for item in expected_nsgs)
    ):
        raise VerificationError("expected JSON contains invalid NSG identifiers")
    expected_subnet_id = _expected_value(expected, "replacement", "subnet_id")
    if not isinstance(expected_subnet_id, str) or not expected_subnet_id:
        raise VerificationError("expected JSON contains an invalid subnet identifier")
    if (
        vnic.get("subnet_id") != expected_subnet_id
        or vnic.get("nsg_ids") != expected_nsgs
        or vnic.get("assign_public_ip") is not False
        or vnic.get("assign_ipv6ip") is not False
    ):
        raise VerificationError("instance VNIC does not match the contract")

    public_ip_change = resources["oci_core_public_ip.racetime"]
    public_ip = _after(public_ip_change)
    public_ip_unknown = _require_mapping(
        public_ip_change.get("after_unknown"), "resource change"
    )
    if (
        public_ip.get("lifetime") != "RESERVED"
        or public_ip.get("private_ip_id") is not None
        or public_ip_unknown.get("private_ip_id") is not True
    ):
        raise VerificationError("reserved public-IP value is not safely deferred")

    configuration = _configuration_resources(plan)
    configured_public_ip = configuration.get("oci_core_public_ip.racetime")
    if configured_public_ip is None:
        raise VerificationError("public-IP configuration is missing")
    expression = _expressions(configured_public_ip).get("private_ip_id")
    references = _references(expression)
    if references != ["data.oci_core_private_ips.racetime.private_ips"]:
        raise VerificationError("public IP does not use the private-IP data source")


def verify_saved_plan(
    *,
    phase: str,
    plan_file: Path,
    plan_json_path: Path,
    expected_json_path: Path,
    terraform_bin: Path,
    source_commit: str,
    terraform_version: str,
    repository: Path | None = None,
) -> VerificationSummary:
    if phase not in PHASES:
        raise VerificationError("phase is invalid")
    expected = _load_json(expected_json_path, "expected JSON")
    if (
        expected.get("phase") != phase
        or expected.get("source_commit") != source_commit
        or expected.get("terraform_version") != PINNED_TERRAFORM_VERSION
        or terraform_version != PINNED_TERRAFORM_VERSION
    ):
        raise VerificationError("expected manifest metadata does not match")

    repository_root = _verify_repository(repository or Path.cwd(), source_commit)
    resolved_plan_file = _resolve_saved_plan(plan_file, repository_root)
    plan_digest = _sha256(resolved_plan_file)
    expected_digest = _expected_sha256(expected, "plan_sha256")
    if plan_digest != expected_digest:
        raise VerificationError("saved plan digest does not match")
    try:
        resolved_terraform_bin = terraform_bin.resolve(strict=True)
    except OSError as exc:
        raise VerificationError("saved plan inputs cannot be resolved") from exc

    terraform_digest = _sha256(terraform_bin)
    if terraform_digest != _expected_sha256(
        expected, "terraform_binary_sha256"
    ):
        raise VerificationError("Terraform binary digest does not match")
    version_output = _run_terraform(
        resolved_terraform_bin,
        resolved_plan_file.parent,
        "version",
        "-json",
    )
    version_info = _parse_json_bytes(version_output, "Terraform version output")
    if version_info.get("terraform_version") != PINNED_TERRAFORM_VERSION:
        raise VerificationError("Terraform executable version does not match")

    custody_json = _read_bytes(plan_json_path, "custody plan JSON")
    expected_plan_json_digest = _expected_sha256(expected, "plan_json_sha256")
    if hashlib.sha256(custody_json).hexdigest() != expected_plan_json_digest:
        raise VerificationError("custody plan JSON digest does not match")
    terraform_json = _run_terraform(
        resolved_terraform_bin,
        resolved_plan_file.parent,
        "show",
        "-json",
        resolved_plan_file.name,
    )
    if (
        terraform_json != custody_json
        or hashlib.sha256(terraform_json).hexdigest() != expected_plan_json_digest
    ):
        raise VerificationError("Terraform show JSON does not match custody")
    plan = _parse_json_bytes(terraform_json, "Terraform show JSON")
    if plan.get("format_version") != "1.2":
        raise VerificationError("Terraform plan format version does not match")
    if (
        plan.get("applyable") is not True
        or plan.get("complete") is not True
        or plan.get("errored") is not False
    ):
        raise VerificationError("plan is not complete and applyable")
    if plan.get("terraform_version") != PINNED_TERRAFORM_VERSION:
        raise VerificationError("Terraform version does not match")

    resources = _change_map(plan, "resource_changes")
    drift = _change_map(
        plan,
        "resource_drift",
        filter_noop=False,
        reject_previous_address=True,
    )
    outputs = _output_map(plan)
    planned_resources = _planned_resource_values(plan)
    if phase == "subnet-add":
        _verify_subnet_add(
            plan, expected, resources, drift, outputs, planned_resources
        )
    elif phase == "refresh-only":
        _verify_refresh_only(resources, drift, outputs)
    else:
        _verify_replacement(plan, expected, resources, drift, outputs)

    return VerificationSummary(
        phase=phase,
        source_commit=source_commit,
        plan_sha256=plan_digest,
        terraform_version=terraform_version,
        resource_changes=len(resources),
        resource_drift=len(drift),
        output_changes=len(outputs),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify an OCI saved plan against a fail-closed phase contract"
    )
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--plan-file", type=Path, required=True)
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--expected-json", type=Path, required=True)
    parser.add_argument("--terraform-bin", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--terraform-version", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = verify_saved_plan(
            phase=args.phase,
            plan_file=args.plan_file,
            plan_json_path=args.plan_json,
            expected_json_path=args.expected_json,
            terraform_bin=args.terraform_bin,
            source_commit=args.source_commit,
            terraform_version=args.terraform_version,
        )
    except VerificationError:
        print(f"OCI_SAVED_PLAN_VERIFY=FAIL phase={args.phase}", file=sys.stderr)
        return 1
    print(
        "OCI_SAVED_PLAN_VERIFY=PASS "
        f"phase={summary.phase} source_commit={summary.source_commit} "
        f"plan_sha256={summary.plan_sha256} "
        f"terraform_version={summary.terraform_version} "
        f"resource_changes={summary.resource_changes} "
        f"resource_drift={summary.resource_drift} "
        f"output_changes={summary.output_changes}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
