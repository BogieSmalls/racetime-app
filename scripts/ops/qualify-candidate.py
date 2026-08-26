#!/usr/bin/env python3
"""Run and record the fail-closed Z1RR restricted-qualification state machine."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


class QualificationError(ValueError):
    """Qualification state, evidence, or an adapter is unsafe or incomplete."""


STAGE_DEPENDENCIES = {
    "release_identity": (),
    "qualification_core": ("release_identity",),
    "governance": ("release_identity",),
    "failure": ("qualification_core", "governance"),
    "security": ("qualification_core", "governance"),
    "load": ("qualification_core", "governance"),
    "backup_restore": ("qualification_core", "governance"),
    "fresh_production": ("failure", "security", "load", "backup_restore"),
    "post_issuance_ttpbot": ("fresh_production",),
    "post_issuance_restream": ("fresh_production",),
    "post_issuance_livesplit": ("fresh_production",),
    "dress_rehearsal": (
        "post_issuance_ttpbot", "post_issuance_restream", "post_issuance_livesplit"
    ),
    "cutover_rehearsal": ("dress_rehearsal",),
}
FINAL_STAGE = "cutover_rehearsal"
FRESH_PRODUCTION_CLAIMS = {
    "certificate_environment": "production",
    "ordinary_trust": True,
    "state_generation": "fresh-production",
    "public_mode": False,
}
STATE_FIELDS = {
    "schema_version", "environment", "release_identity_path",
    "release_identity_sha256", "created_at_utc", "updated_at_utc", "attempts",
    "chain_sha256",
}
ATTEMPT_FIELDS = {
    "stage", "attempt", "status", "evidence_path", "evidence_sha256", "claims",
    "blocker_severities", "recorded_at_utc", "previous_hash", "record_hash",
}
ADAPTER_FIELDS = {
    "schema_version", "environment", "state_path", "release_identity_path",
    "evidence_directory", "working_directory", "components", "stages",
}
STAGE_ADAPTER_FIELDS = {
    "command", "mutates", "environment_overrides", "requirements", "artifacts", "expected",
}
ACTIVATION_FIELDS = {
    "schema_version", "gate", "activation_id", "activated_at_utc", "canonical_origin",
    "allowlist_record_sha256",
}
ALLOWED_ENVIRONMENT_OVERRIDES = {"REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
ACTIVATION_ID = re.compile(r"^[A-Z0-9][A-Z0-9._-]{5,79}$")
SECRET_TEXT = re.compile(
    r"(?:BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|Bearer\s+\S+|"
    r"(?:password|secret|token|authorization|cookie)\s*[=:]\s*\S+|"
    r"discord(?:app)?\.com/api/webhooks/)",
    re.IGNORECASE,
)
MAX_JSON_BYTES = 4 * 1024 * 1024


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _timestamp(value, label):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise QualificationError(f"{label} must be a UTC timestamp")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise QualificationError(f"{label} is invalid") from exc


def _object(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise QualificationError(f"{label} fields are invalid")
    return value


def _regular_json(path, label):
    target = Path(path).resolve()
    if not target.is_file() or target.is_symlink() or target.stat().st_size > MAX_JSON_BYTES:
        raise QualificationError(f"{label} is missing or unsafe")
    try:
        return target, json.loads(target.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"{label} is not valid UTF-8 JSON") from exc


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path, value):
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_evidence_validator():
    path = Path(__file__).with_name("validate-evidence.py")
    spec = importlib.util.spec_from_file_location("z1rr_evidence_validator", path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise QualificationError("evidence validator cannot be loaded")
    spec.loader.exec_module(module)
    return module


def _validate_identity(path):
    target, value = _regular_json(path, "release identity")
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise QualificationError("release identity schema is invalid")
    components = value.get("components")
    if not isinstance(components, dict) or not components:
        raise QualificationError("release identity has no components")
    return target, _sha256(target)


def initialize_state(state_path, release_identity_path, *, environment):
    if environment != "qualification":
        raise QualificationError("only the qualification environment may be initialized")
    destination = Path(state_path).resolve()
    if destination.exists():
        raise QualificationError("qualification state already exists")
    identity, identity_hash = _validate_identity(release_identity_path)
    now = _utc_now().isoformat().replace("+00:00", "Z")
    state = {
        "schema_version": 1,
        "environment": environment,
        "release_identity_path": str(identity),
        "release_identity_sha256": identity_hash,
        "created_at_utc": now,
        "updated_at_utc": now,
        "attempts": [],
        "chain_sha256": "0" * 64,
    }
    _atomic_json(destination, state)
    return state


def _verify_attempt_chain(attempts, final_hash):
    previous = "0" * 64
    for attempt in attempts:
        _object(attempt, ATTEMPT_FIELDS, "qualification attempt")
        if attempt["previous_hash"] != previous:
            raise QualificationError("qualification attempt chain is broken")
        unsigned = {key: value for key, value in attempt.items() if key != "record_hash"}
        actual = _canonical_hash(unsigned)
        if attempt["record_hash"] != actual:
            raise QualificationError("qualification attempt record was modified")
        previous = actual
    if final_hash != previous:
        raise QualificationError("qualification state chain head is invalid")


def load_state(state_path, *, verify_evidence=False):
    path, state = _regular_json(state_path, "qualification state")
    _object(state, STATE_FIELDS, "qualification state")
    if state["schema_version"] != 1 or state["environment"] != "qualification":
        raise QualificationError("qualification state schema or environment is invalid")
    for field in ("release_identity_sha256", "chain_sha256"):
        if not isinstance(state[field], str) or not SHA256.fullmatch(state[field]):
            raise QualificationError(f"qualification state {field} is invalid")
    identity, current_hash = _validate_identity(state["release_identity_path"])
    if current_hash != state["release_identity_sha256"]:
        raise QualificationError("release identity changed after qualification began")
    if not isinstance(state["attempts"], list):
        raise QualificationError("qualification attempts are invalid")
    _verify_attempt_chain(state["attempts"], state["chain_sha256"])
    if verify_evidence:
        for attempt in state["attempts"]:
            evidence = Path(attempt["evidence_path"]).resolve()
            if (
                not evidence.is_file()
                or evidence.is_symlink()
                or _sha256(evidence) != attempt["evidence_sha256"]
            ):
                raise QualificationError("recorded qualification evidence changed")
    return state


def _passed(state, stage):
    return any(item["stage"] == stage and item["status"] == "pass" for item in state["attempts"])


def _has_blocking_finding(state):
    return any(
        severity in {"P0", "P1"}
        for item in state["attempts"]
        for severity in item["blocker_severities"]
    )


def _evidence_summary(path):
    target, value = _regular_json(path, "qualification evidence")
    validator = _load_evidence_validator()
    try:
        validator._reject_secrets(value)
    except validator.EvidenceError as exc:
        raise QualificationError("qualification evidence contains secret-like material") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise QualificationError("qualification evidence schema is invalid")
    status = value.get("result")
    if status not in {"pass", "fail"}:
        raise QualificationError("qualification evidence result is invalid")
    findings = value.get("findings")
    if not isinstance(findings, list):
        raise QualificationError("qualification evidence findings are invalid")
    blockers = []
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("severity") not in {"P0", "P1", "P2", "P3"}:
            raise QualificationError("qualification evidence finding is invalid")
        if finding["severity"] in {"P0", "P1"}:
            blockers.append(finding["severity"])
    if status == "pass":
        try:
            validator.validate_manifest(target)
        except validator.EvidenceError as exc:
            raise QualificationError("passing qualification evidence failed validation") from exc
    return target, status, sorted(set(blockers))


def record_stage(state_path, stage, evidence_path, *, claims=None):
    if stage not in STAGE_DEPENDENCIES:
        raise QualificationError("qualification stage is unknown")
    state = load_state(state_path, verify_evidence=True)
    if _has_blocking_finding(state) and not any(
        item["stage"] == stage and item["blocker_severities"] for item in state["attempts"]
    ):
        raise QualificationError("a recorded P0/P1 finding blocks later qualification")
    missing = [dependency for dependency in STAGE_DEPENDENCIES[stage] if not _passed(state, dependency)]
    if missing:
        raise QualificationError("qualification stage dependencies have not passed")
    claims = {} if claims is None else claims
    if not isinstance(claims, dict):
        raise QualificationError("qualification claims are invalid")
    if stage == "fresh_production" and claims != FRESH_PRODUCTION_CLAIMS:
        raise QualificationError("fresh-production claims are incomplete or unsafe")
    if stage != "fresh_production" and claims:
        raise QualificationError("claims are only accepted for fresh production")
    evidence, status, blockers = _evidence_summary(evidence_path)
    previous = state["chain_sha256"]
    attempt_number = 1 + sum(item["stage"] == stage for item in state["attempts"])
    attempt = {
        "stage": stage,
        "attempt": attempt_number,
        "status": status,
        "evidence_path": str(evidence),
        "evidence_sha256": _sha256(evidence),
        "claims": claims,
        "blocker_severities": blockers,
        "recorded_at_utc": _utc_now().isoformat().replace("+00:00", "Z"),
        "previous_hash": previous,
    }
    attempt["record_hash"] = _canonical_hash(attempt)
    state["attempts"].append(attempt)
    state["chain_sha256"] = attempt["record_hash"]
    state["updated_at_utc"] = attempt["recorded_at_utc"]
    _atomic_json(Path(state_path), state)
    return state


def is_complete(state):
    return _passed(state, FINAL_STAGE) and not _has_blocking_finding(state)


def _validate_activation(path):
    target, value = _regular_json(path, "G1 activation record")
    _object(value, ACTIVATION_FIELDS, "G1 activation record")
    if value["schema_version"] != 1 or value["gate"] != "G1":
        raise QualificationError("G1 activation record is invalid")
    if not isinstance(value["activation_id"], str) or not ACTIVATION_ID.fullmatch(value["activation_id"]):
        raise QualificationError("G1 activation ID is invalid")
    _timestamp(value["activated_at_utc"], "activated_at_utc")
    if value["canonical_origin"] != "https://raceroom.z1rracing.com":
        raise QualificationError("G1 activation canonical origin is invalid")
    if not isinstance(value["allowlist_record_sha256"], str) or not SHA256.fullmatch(value["allowlist_record_sha256"]):
        raise QualificationError("G1 activation allowlist hash is invalid")
    return value


def _validate_command(command):
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) or not item or len(item) > 2000 for item in command)
        or any(SECRET_TEXT.search(item) for item in command)
    ):
        raise QualificationError("adapter command is invalid or secret-like")
    return command


def _build_evidence(config, stage, adapter, started, completed, return_code, stdout_hash):
    status = "pass" if return_code == 0 else "fail"
    expires = completed + timedelta(days=30)
    return {
        "schema_version": 1,
        "evidence_id": f"QUAL-{stage.replace('_', '-').upper()}-{completed.strftime('%Y%m%dT%H%M%SZ')}",
        "environment": "qualification",
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "completed_at_utc": completed.isoformat().replace("+00:00", "Z"),
        "local_timezone": "America/New_York",
        "operator": {"role": "primary technical operator"},
        "reviewer": {"role": "implementation reviewer"},
        "components": config["components"],
        "requirements": adapter["requirements"],
        "artifacts": adapter["artifacts"],
        "commands": [{
            "id": stage,
            "command": "argv adapter (shell disabled)",
            "expected": adapter["expected"],
            "observed": "adapter exited zero" if status == "pass" else "adapter failed safely",
            "exit_code": return_code,
            "status": status,
            "stdout_sha256": stdout_hash,
        }],
        "attachments": [],
        "findings": [],
        "expires_at_utc": expires.isoformat().replace("+00:00", "Z"),
        "result": status,
    }


def run_stage(config_path, stage, *, activation_record=None):
    config_file, config = _regular_json(config_path, "qualification adapter configuration")
    _object(config, ADAPTER_FIELDS, "qualification adapter configuration")
    if config["schema_version"] != 1 or config["environment"] != "qualification":
        raise QualificationError("qualification adapter environment is invalid")
    stages = config["stages"]
    if not isinstance(stages, dict) or stage not in stages or stage not in STAGE_DEPENDENCIES:
        raise QualificationError("qualification adapter stage is not configured")
    adapter = _object(stages[stage], STAGE_ADAPTER_FIELDS, "qualification stage adapter")
    if not isinstance(adapter["mutates"], bool):
        raise QualificationError("qualification adapter mutation declaration is invalid")
    if adapter["mutates"]:
        if activation_record is None:
            raise QualificationError("mutating qualification adapter requires G1 activation")
        _validate_activation(activation_record)
    command = _validate_command(adapter["command"])
    overrides = adapter["environment_overrides"]
    if not isinstance(overrides, dict) or not set(overrides).issubset(ALLOWED_ENVIRONMENT_OVERRIDES):
        raise QualificationError("qualification adapter environment overrides are unsafe")
    if any(not isinstance(value, str) or not value or SECRET_TEXT.search(value) for value in overrides.values()):
        raise QualificationError("qualification adapter environment override is invalid")
    working_directory = Path(config["working_directory"]).resolve()
    evidence_directory = Path(config["evidence_directory"]).resolve()
    if not working_directory.is_dir() or working_directory.is_symlink():
        raise QualificationError("qualification adapter working directory is unsafe")
    evidence_directory.mkdir(parents=True, exist_ok=True)
    if evidence_directory.is_symlink():
        raise QualificationError("qualification evidence directory is unsafe")
    state = load_state(config["state_path"], verify_evidence=True)
    identity = Path(config["release_identity_path"]).resolve()
    if identity != Path(state["release_identity_path"]).resolve():
        raise QualificationError("adapter release identity does not match qualification state")
    environment = os.environ.copy()
    environment.update(overrides)
    started = _utc_now()
    try:
        completed_process = subprocess.run(
            command,
            cwd=working_directory,
            env=environment,
            capture_output=True,
            shell=False,
            timeout=1800,
        )
        return_code = completed_process.returncode
        stdout = completed_process.stdout + completed_process.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("qualification adapter could not run safely") from exc
    completed = _utc_now()
    evidence = _build_evidence(
        config, stage, adapter, started, completed, return_code, hashlib.sha256(stdout).hexdigest()
    )
    evidence_path = evidence_directory / f"{stage}-{completed.strftime('%Y%m%dT%H%M%SZ')}.json"
    _atomic_json(evidence_path, evidence)
    updated = record_stage(config["state_path"], stage, evidence_path)
    if return_code != 0:
        raise QualificationError("qualification adapter failed; immutable evidence was recorded")
    return updated


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    initialize = subparsers.add_parser("initialize")
    initialize.add_argument("--state", required=True)
    initialize.add_argument("--release-identity", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--state", required=True)
    record.add_argument("--stage", required=True, choices=tuple(STAGE_DEPENDENCIES))
    record.add_argument("--evidence", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--config", required=True)
    run.add_argument("--stage", required=True, choices=tuple(STAGE_DEPENDENCIES))
    run.add_argument("--activation-record")
    status = subparsers.add_parser("status")
    status.add_argument("--state", required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.action == "initialize":
            state = initialize_state(arguments.state, arguments.release_identity, environment="qualification")
        elif arguments.action == "record":
            state = record_stage(arguments.state, arguments.stage, arguments.evidence)
        elif arguments.action == "run":
            state = run_stage(arguments.config, arguments.stage, activation_record=arguments.activation_record)
        else:
            state = load_state(arguments.state, verify_evidence=True)
    except QualificationError as exc:
        sys.stderr.write(f"QUALIFICATION=FAIL code={type(exc).__name__}\n")
        return 1
    print(f"QUALIFICATION={'PASS' if is_complete(state) else 'IN_PROGRESS'} attempts={len(state['attempts'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
