#!/usr/bin/env python3
"""Validate one immutable, secret-free Z1RR evidence manifest."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys


class EvidenceError(ValueError):
    pass


TOP_LEVEL = {
    "schema_version", "evidence_id", "environment", "started_at_utc",
    "completed_at_utc", "local_timezone", "operator", "reviewer", "components",
    "requirements", "artifacts", "commands", "attachments", "findings",
    "expires_at_utc", "result",
}
ENVIRONMENTS = {"local", "integration", "qualification", "production-restricted", "production"}
REQUIREMENT = re.compile(r"^(?:FR|NFR)-[A-Z]+-[0-9]{3}$")
ARTIFACT = re.compile(r"^[A-Z]{2,4}-[0-9]{3}$")
EVIDENCE_ID = re.compile(r"^[A-Z0-9][A-Z0-9._-]{5,79}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,79}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
TIMEZONE = re.compile(r"^[A-Za-z_]+(?:/[A-Za-z0-9_+.-]+)+$")
COUNCIL_ID = re.compile(r"^COUNCIL-[0-9]{4}-[0-9]{3,}$")
SECRET_KEY = re.compile(r"(?:authorization|cookie|credential|discord_id|password|secret|token|webhook)", re.I)
SECRET_VALUE = re.compile(
    r"(?:BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|"
    r"https://discord(?:app)?\.com/api/webhooks/|"
    r"(?:password|secret|token|authorization|cookie)\s*[=:]\s*\S+|"
    r"Bearer\s+\S+)",
    re.I,
)


def _object(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise EvidenceError(f"{label} fields are invalid")
    return value


def _string(value, label, *, minimum=1, maximum=1000):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise EvidenceError(f"{label} is invalid")
    return value


def _timestamp(value, label):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvidenceError(f"{label} must be UTC with a Z suffix")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise EvidenceError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise EvidenceError(f"{label} lacks a timezone")
    return parsed.astimezone(timezone.utc)


def _reject_secrets(value, path="$"):
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEY.search(str(key)):
                raise EvidenceError(f"secret-like field is prohibited at {path}")
            _reject_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secrets(item, f"{path}[{index}]")
    elif isinstance(value, str) and SECRET_VALUE.search(value):
        raise EvidenceError(f"secret-like value is prohibited at {path}")


def _unique_ids(values, pattern, label):
    if not isinstance(values, list) or not values:
        raise EvidenceError(f"{label} must be a non-empty list")
    if any(not isinstance(value, str) or not pattern.fullmatch(value) for value in values):
        raise EvidenceError(f"{label} contains an invalid ID")
    if len(values) != len(set(values)):
        raise EvidenceError(f"{label} contains a duplicate ID")
    return sorted(values)


def _validate_role(value, label):
    role = _object(value, {"role"}, label)
    _string(role["role"], f"{label}.role", minimum=3, maximum=100)


def _validate_components(values):
    if not isinstance(values, list) or not values:
        raise EvidenceError("components must be a non-empty list")
    names = set()
    keys = {"name", "commit", "image_digest", "dll_sha256", "config_sha256"}
    for index, component in enumerate(values):
        component = _object(component, keys, f"components[{index}]")
        name = _string(component["name"], "component name", maximum=50)
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,50}", name) or name in names:
            raise EvidenceError("component name is invalid or duplicated")
        names.add(name)
        if component["commit"] is not None and not COMMIT.fullmatch(component["commit"]):
            raise EvidenceError("component commit must be an exact object ID")
        if component["image_digest"] is not None and not IMAGE_DIGEST.fullmatch(component["image_digest"]):
            raise EvidenceError("component image must be digest-addressed")
        for field in ("dll_sha256", "config_sha256"):
            if component[field] is not None and not SHA256.fullmatch(component[field]):
                raise EvidenceError(f"component {field} is invalid")
        if all(component[field] is None for field in ("commit", "image_digest", "dll_sha256", "config_sha256")):
            raise EvidenceError("component has no immutable identity")


def _validate_commands(values):
    if not isinstance(values, list) or not values:
        raise EvidenceError("commands must be a non-empty list")
    seen = set()
    for index, command in enumerate(values):
        command = _object(
            command,
            {"id", "command", "expected", "observed", "exit_code", "status", "stdout_sha256"},
            f"commands[{index}]",
        )
        command_id = _string(command["id"], "command ID", maximum=80)
        if not SAFE_ID.fullmatch(command_id) or command_id in seen:
            raise EvidenceError("command ID is invalid or duplicated")
        seen.add(command_id)
        for field in ("command", "expected", "observed"):
            _string(command[field], f"command {field}")
        if not isinstance(command["exit_code"], int) or command["status"] not in {"pass", "fail"}:
            raise EvidenceError("command status/exit code is invalid")
        if not SHA256.fullmatch(str(command["stdout_sha256"])):
            raise EvidenceError("command stdout hash is invalid")
        if command["status"] != "pass" or command["exit_code"] != 0:
            raise EvidenceError("failed command prevents passing evidence")


def _validate_attachments(values, manifest_path):
    if not isinstance(values, list):
        raise EvidenceError("attachments must be a list")
    root = manifest_path.parent.resolve()
    seen = set()
    for index, attachment in enumerate(values):
        attachment = _object(attachment, {"path", "sha256", "redacted"}, f"attachments[{index}]")
        relative = Path(_string(attachment["path"], "attachment path", maximum=300))
        if relative.is_absolute() or ".." in relative.parts or attachment["redacted"] is not True:
            raise EvidenceError("attachment must be a redacted relative path")
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise EvidenceError("attachment escapes evidence directory") from exc
        if target in seen or not target.is_file() or target.is_symlink():
            raise EvidenceError("attachment is missing, duplicated, or unsafe")
        seen.add(target)
        expected = str(attachment["sha256"])
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if not SHA256.fullmatch(expected) or actual != expected:
            raise EvidenceError("attachment hash mismatch")


def _validate_findings(values):
    if not isinstance(values, list):
        raise EvidenceError("findings must be a list")
    seen = set()
    keys = {"id", "severity", "status", "owner", "due_date", "risk_acceptance_id"}
    for index, finding in enumerate(values):
        finding = _object(finding, keys, f"findings[{index}]")
        finding_id = _string(finding["id"], "finding ID", maximum=80)
        if not SAFE_ID.fullmatch(finding_id) or finding_id in seen:
            raise EvidenceError("finding ID is invalid or duplicated")
        seen.add(finding_id)
        severity = finding["severity"]
        if severity not in {"P0", "P1", "P2", "P3"} or finding["status"] not in {"open", "closed", "accepted"}:
            raise EvidenceError("finding severity/status is invalid")
        if severity in {"P0", "P1"}:
            raise EvidenceError("P0/P1 finding blocks evidence")
        owner = finding["owner"]
        due = finding["due_date"]
        if severity == "P2":
            if finding["status"] != "accepted" or not isinstance(finding["risk_acceptance_id"], str) or not COUNCIL_ID.fullmatch(finding["risk_acceptance_id"]):
                raise EvidenceError("P2 requires a Council risk-acceptance ID")
        if severity == "P3" and (not isinstance(owner, str) or not owner.strip() or not isinstance(due, str) or not due.strip()):
            raise EvidenceError("P3 requires owner and due date")
        if due:
            try:
                date.fromisoformat(due)
            except (TypeError, ValueError) as exc:
                raise EvidenceError("finding due date is invalid") from exc


def validate_manifest(path, *, now=None):
    manifest_path = Path(path).resolve()
    if not manifest_path.is_file() or manifest_path.is_symlink() or manifest_path.stat().st_size > 4 * 1024 * 1024:
        raise EvidenceError("evidence manifest is missing or unsafe")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("evidence manifest is not valid UTF-8 JSON") from exc
    _object(manifest, TOP_LEVEL, "manifest")
    _reject_secrets(manifest)
    if manifest["schema_version"] != 1:
        raise EvidenceError("unsupported evidence schema")
    if not isinstance(manifest["evidence_id"], str) or not EVIDENCE_ID.fullmatch(manifest["evidence_id"]):
        raise EvidenceError("evidence ID is invalid")
    if manifest["environment"] not in ENVIRONMENTS:
        raise EvidenceError("environment is invalid")
    if not isinstance(manifest["local_timezone"], str) or not TIMEZONE.fullmatch(manifest["local_timezone"]):
        raise EvidenceError("local timezone must be an IANA name")
    started = _timestamp(manifest["started_at_utc"], "started_at_utc")
    completed = _timestamp(manifest["completed_at_utc"], "completed_at_utc")
    if completed < started:
        raise EvidenceError("evidence completion precedes start")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise EvidenceError("validation clock must be timezone-aware")
    expires = manifest["expires_at_utc"]
    if expires is not None and _timestamp(expires, "expires_at_utc") <= current.astimezone(timezone.utc):
        raise EvidenceError("evidence is expired")
    _validate_role(manifest["operator"], "operator")
    _validate_role(manifest["reviewer"], "reviewer")
    _validate_components(manifest["components"])
    requirements = _unique_ids(manifest["requirements"], REQUIREMENT, "requirements")
    artifacts = _unique_ids(manifest["artifacts"], ARTIFACT, "artifacts")
    _validate_commands(manifest["commands"])
    _validate_attachments(manifest["attachments"], manifest_path)
    _validate_findings(manifest["findings"])
    if manifest["result"] != "pass":
        raise EvidenceError("evidence result is not pass")
    return {"evidence_id": manifest["evidence_id"], "requirements": requirements, "artifacts": artifacts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    args = parser.parse_args(argv)
    try:
        summary = validate_manifest(args.manifest)
    except EvidenceError as exc:
        sys.stderr.write(f"EVIDENCE=FAIL code={type(exc).__name__}\n")
        return 1
    requirements = ",".join(summary["requirements"])
    artifacts = ",".join(summary["artifacts"])
    print(f"EVIDENCE=PASS id={summary['evidence_id']} requirements={requirements} artifacts={artifacts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
