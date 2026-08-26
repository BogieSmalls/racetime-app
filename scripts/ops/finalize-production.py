#!/usr/bin/env python3
"""Execute the resumable fresh-production transition behind the G2 allowlist."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


class FinalizationError(ValueError):
    """The fresh-production transition is incomplete or unsafe."""


TRANSITION_STEPS = (
    "barrier_entered",
    "qualification_writes_stopped",
    "qualification_sealed",
    "fresh_volumes_created",
    "compose_stopped",
    "application_repointed",
    "qualification_credentials_revoked",
    "qualification_sessions_invalidated",
    "production_bootstrapped",
    "production_tls_issued",
    "g2_allowlist_restored",
    "post_issuance_ready",
)
CONFIG_FIELDS = {"schema_version", "environment", "public_mode", "state_path", "steps"}
STEP_FIELDS = {"command", "probe"}
STATE_FIELDS = {
    "schema_version", "environment", "change_id", "config_sha256", "started_at_utc",
    "updated_at_utc", "completed_steps", "audit", "chain_sha256",
}
AUDIT_FIELDS = {
    "step", "recorded_at_utc", "command_sha256", "probe_sha256", "previous_hash", "record_hash",
}
ACTIVATION_FIELDS = {
    "schema_version", "gate", "activation_id", "activated_at_utc", "canonical_origin",
    "allowlist_record_sha256",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHANGE_ID = re.compile(r"^[A-Z0-9][A-Z0-9._-]{5,79}$")
SECRET_TEXT = re.compile(
    r"(?:BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|Bearer\s+\S+|"
    r"(?:password|secret|token|authorization|cookie)\s*[=:]\s*\S+|"
    r"discord(?:app)?\.com/api/webhooks/)",
    re.IGNORECASE,
)
MAX_JSON_BYTES = 1024 * 1024


def _utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _object(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise FinalizationError(f"{label} fields are invalid")
    return value


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


def _read_json(path, label):
    target = Path(path).resolve()
    if not target.is_file() or target.is_symlink() or target.stat().st_size > MAX_JSON_BYTES:
        raise FinalizationError(f"{label} is missing or unsafe")
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalizationError(f"{label} is not valid UTF-8 JSON") from exc


def _timestamp(value, label):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise FinalizationError(f"{label} must be UTC")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise FinalizationError(f"{label} is invalid") from exc


def _validate_activation(path):
    value = _read_json(path, "G1 activation record")
    _object(value, ACTIVATION_FIELDS, "G1 activation record")
    if value["schema_version"] != 1 or value["gate"] != "G1":
        raise FinalizationError("G1 activation record is invalid")
    if not isinstance(value["activation_id"], str) or not CHANGE_ID.fullmatch(value["activation_id"]):
        raise FinalizationError("G1 activation ID is invalid")
    _timestamp(value["activated_at_utc"], "activated_at_utc")
    if value["canonical_origin"] != "https://raceroom.z1rracing.com":
        raise FinalizationError("G1 canonical origin is invalid")
    if not isinstance(value["allowlist_record_sha256"], str) or not SHA256.fullmatch(value["allowlist_record_sha256"]):
        raise FinalizationError("G1 allowlist record hash is invalid")


def _validate_argv(value, label):
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item or len(item) > 2000 for item in value)
        or any(SECRET_TEXT.search(item) for item in value)
    ):
        raise FinalizationError(f"{label} is invalid or secret-like")
    return value


def _validate_config(config):
    _object(config, CONFIG_FIELDS, "finalization configuration")
    if config["schema_version"] != 1 or config["environment"] != "qualification":
        raise FinalizationError("finalization configuration environment is invalid")
    if not isinstance(config["public_mode"], bool):
        raise FinalizationError("finalization public_mode declaration is invalid")
    if not isinstance(config["state_path"], str) or not config["state_path"]:
        raise FinalizationError("finalization state path is invalid")
    steps = config["steps"]
    if not isinstance(steps, dict) or tuple(steps) != TRANSITION_STEPS or set(steps) != set(TRANSITION_STEPS):
        raise FinalizationError("finalization steps are missing or out of order")
    for step in TRANSITION_STEPS:
        record = _object(steps[step], STEP_FIELDS, f"finalization step {step}")
        _validate_argv(record["command"], f"{step} command")
        _validate_argv(record["probe"], f"{step} probe")
    return config


def _config_hash(config):
    stable = {key: value for key, value in config.items() if key != "state_path"}
    return _canonical_hash(stable)


def _new_state(config, change_id):
    now = _utc()
    return {
        "schema_version": 1,
        "environment": "qualification-to-fresh-production",
        "change_id": change_id,
        "config_sha256": _config_hash(config),
        "started_at_utc": now,
        "updated_at_utc": now,
        "completed_steps": [],
        "audit": [],
        "chain_sha256": "0" * 64,
    }


def _load_state(path, config, change_id):
    value = _read_json(path, "finalization state")
    _object(value, STATE_FIELDS, "finalization state")
    if (
        value["schema_version"] != 1
        or value["environment"] != "qualification-to-fresh-production"
        or value["change_id"] != change_id
        or value["config_sha256"] != _config_hash(config)
    ):
        raise FinalizationError("finalization state does not match this transition")
    completed = value["completed_steps"]
    audit = value["audit"]
    if not isinstance(completed, list) or completed != list(TRANSITION_STEPS[:len(completed)]):
        raise FinalizationError("completed finalization steps are not an ordered prefix")
    if not isinstance(audit, list) or len(audit) != len(completed):
        raise FinalizationError("finalization audit does not match completed steps")
    previous = "0" * 64
    for index, record in enumerate(audit):
        _object(record, AUDIT_FIELDS, "finalization audit record")
        if record["step"] != completed[index] or record["previous_hash"] != previous:
            raise FinalizationError("finalization audit chain is out of order")
        unsigned = {key: item for key, item in record.items() if key != "record_hash"}
        actual = _canonical_hash(unsigned)
        if record["record_hash"] != actual:
            raise FinalizationError("finalization audit record was modified")
        previous = actual
    if value["chain_sha256"] != previous:
        raise FinalizationError("finalization audit chain head is invalid")
    return value


def _default_runner(command):
    try:
        return subprocess.run(command, shell=False, check=False).returncode
    except OSError as exc:
        raise FinalizationError("finalization command could not be started") from exc


def _run_checked(runner, command, label):
    try:
        result = runner(command)
    except FinalizationError:
        raise
    except Exception as exc:
        raise FinalizationError(f"{label} runner failed") from exc
    if type(result) is not int or result != 0:
        raise FinalizationError(f"{label} failed; transition did not advance")


def run_transition(
    config, *, apply=False, activation_record=None, change_id=None, runner=None
):
    config = _validate_config(config)
    if not apply:
        return {"planned_steps": list(TRANSITION_STEPS)}
    if config["public_mode"]:
        raise FinalizationError("fresh-production transition refuses public mode")
    if activation_record is None:
        raise FinalizationError("fresh-production transition requires G1 activation")
    _validate_activation(activation_record)
    if not isinstance(change_id, str) or not CHANGE_ID.fullmatch(change_id):
        raise FinalizationError("fresh-production transition change ID is invalid")
    execute = runner or _default_runner
    state_path = Path(config["state_path"]).resolve()
    if state_path.exists():
        state = _load_state(state_path, config, change_id)
    else:
        state = _new_state(config, change_id)
        _atomic_json(state_path, state)

    for completed_step in state["completed_steps"]:
        _run_checked(execute, config["steps"][completed_step]["probe"], f"{completed_step} resume probe")

    for step in TRANSITION_STEPS[len(state["completed_steps"]):]:
        command = config["steps"][step]["command"]
        probe = config["steps"][step]["probe"]
        _run_checked(execute, command, f"{step} command")
        _run_checked(execute, probe, f"{step} probe")
        record = {
            "step": step,
            "recorded_at_utc": _utc(),
            "command_sha256": _canonical_hash(command),
            "probe_sha256": _canonical_hash(probe),
            "previous_hash": state["chain_sha256"],
        }
        record["record_hash"] = _canonical_hash(record)
        state["completed_steps"].append(step)
        state["audit"].append(record)
        state["chain_sha256"] = record["record_hash"]
        state["updated_at_utc"] = record["recorded_at_utc"]
        _atomic_json(state_path, state)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--activation-record")
    parser.add_argument("--change-id")
    arguments = parser.parse_args(argv)
    try:
        config = _read_json(arguments.config, "finalization configuration")
        result = run_transition(
            config,
            apply=arguments.apply,
            activation_record=arguments.activation_record,
            change_id=arguments.change_id,
        )
    except FinalizationError as exc:
        sys.stderr.write(f"FINALIZATION=FAIL code={type(exc).__name__}\n")
        return 1
    if arguments.apply:
        print(f"FINALIZATION=PASS completed={len(result['completed_steps'])}")
    else:
        print(f"FINALIZATION=DRY_RUN steps={len(result['planned_steps'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
