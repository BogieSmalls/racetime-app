"""Fail-closed data contracts for the OCI G0 worker."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import unicodedata
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence
from urllib.parse import urlsplit


class ContractError(ValueError):
    """Raised when untrusted worker contract data is unsafe or malformed."""


_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_RUN_ID_PATTERN = re.compile(r"[0-9]{8}t[0-9]{6}z-[0-9a-f]{8}\Z")
_RELATIVE_PATH_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_SAFE_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_BRANCH_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")
_IMAGE_REFERENCE_PATTERN = re.compile(
    r"[a-z0-9][a-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?"
    r"@sha256:([0-9a-f]{64})\Z"
)
_HTTPS_URL_PATTERN = re.compile(
    r"https://(?:\[[0-9A-Fa-f:.]+\]|"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)"
    r"(?::(?:[1-9][0-9]{0,3}|[1-5][0-9]{4}|6[0-4][0-9]{3}|"
    r"65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5]))?"
    r"(?:/[^\s\x00-\x1f\x7f\x80-\x9f]*)?\Z"
)
_ASSIGNMENT_PATTERN = re.compile(
    r"""
    (?P<head>
        (?<![A-Za-z0-9_.-])
        (?:export[ \t]+)?
        (?P<key_quote>["']?)
        (?P<key>
            (?=[A-Za-z0-9_.-]*(?:
                password|secret|token|credential|api[_.-]?key|private[_.-]?key
            ))
            [A-Za-z_][A-Za-z0-9_.-]*
        )
        (?P=key_quote)
        [ \t]*[:=][ \t]*
    )
    (?P<value>
        "(?:\\.|[^"\\])*"
        | '(?:\\.|[^'\\])*'
        | [^\r\n]*
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_ASSIGNMENT_START_PATTERN = re.compile(
    r"""
    (?<![A-Za-z0-9_.-])
    (?:export[ \t]+)?
    (?P<key_quote>["']?)
    (?P<key>[A-Za-z_][A-Za-z0-9_.-]*)
    (?P=key_quote)
    [ \t]*[:=][ \t]*
    """,
    re.IGNORECASE | re.VERBOSE,
)
_AUTHORIZATION_PATTERN = re.compile(
    r"""
    (?P<head>
        (?<![A-Za-z0-9_.-])
        (?P<auth_quote>["']?)authorization(?P=auth_quote)
        [ \t]*[:=][ \t]*
    )
    (?P<value>
        "(?:bearer|basic)[ \t]+(?:\\.|[^"\\])*"
        | '(?:bearer|basic)[ \t]+(?:\\.|[^'\\])*'
        | (?:bearer|basic)[^\r\n]*
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_AUTHORIZATION_START_PATTERN = re.compile(
    r"""
    (?<![A-Za-z0-9_.-])
    (?P<auth_quote>["']?)authorization(?P=auth_quote)
    [ \t]*[:=][ \t]*
    """,
    re.IGNORECASE | re.VERBOSE,
)
_REDACTED_VALUE_PATTERN = re.compile(
    r"""(?:["']<redacted>["']|<redacted>)(?=$|[\s,;}\]])""",
    re.IGNORECASE,
)
_REDACTED_AUTHORIZATION_PATTERN = re.compile(
    r"""(?:["'](?:(?:bearer|basic)[ \t]+)?<redacted>["']|"""
    r"(?:(?:bearer|basic)[ \t]+)?<redacted>)(?=$|[\s,;}\]])",
    re.IGNORECASE,
)
_PHASE_NAMES = (
    "preflight",
    "setup",
    "images",
    "security",
    "services",
    "recovery",
    "cross_repo",
    "identities",
    "cleanup",
)
_CUSTODY_CLASSES = frozenset({"retained", "transient"})
_CLEANUP_STATES = frozenset({"not-required", "pending", "verified", "failed"})
_INSTANCE_FINGERPRINT_DOMAIN = "z1rr-racetime-g0-instance-ocid-v1"
_FAILED_PROOF_CLASSES = frozenset(
    {
        "process-ownership",
        "boundary-emptiness",
        "supervisor-termination",
        "stream-eof",
        "log-finalization",
        "heartbeat-authentication",
        "terminal-response-authentication",
    }
)
_LEASE_STATUSES = frozenset(
    {
        "authenticated-remote-signal",
        "heartbeat-lost",
        "terminal-response-lost",
    }
)
_DISPOSAL_LIFECYCLE = (
    "disposal-recorded",
    "external-cleanup-complete",
    "stop-requested",
    "stopped",
    "restart-requested",
    "running",
    "verify-clean-requested",
    "recovery-verified",
)
_COMPLETE_HASH_KINDS = frozenset(
    {
        "run-manifest",
        "docker-bootstrap-lock",
        "tool-lock",
        "source-bundle",
        "source-archive",
        "retained-artifact",
        "control-record",
    }
)
_FIXED_COMPLETE_HASH_NAMES = {
    "run-manifest": "run-manifest.json",
    "docker-bootstrap-lock": "docker-bootstrap-lock.json",
    "tool-lock": "tool-lock.json",
    "control-record": "control-record.json",
}
_MAX_CONTRACT_BYTES = 1_048_576
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 100_000
_MAX_MONOTONIC_NS = (1 << 63) - 1
_NANOSECONDS_PER_SECOND = 1_000_000_000


def safe_relative_path(value: object, label: str) -> PurePosixPath:
    """Return a workspace-relative POSIX path or fail closed."""

    if type(value) is not str or not value or len(value) > 255:
        raise ContractError(f"{label} must be a non-empty relative path")
    if (
        "\x00" in value
        or "\\" in value
        or ":" in value
        or value.startswith("~")
        or value.startswith("/")
        or "//" in value
    ):
        raise ContractError(f"{label} must be a workspace-relative POSIX path")
    if _RELATIVE_PATH_PATTERN.fullmatch(value) is None:
        raise ContractError(
            f"{label} may contain only ASCII letters, digits, slash, dot, underscore, and hyphen"
        )
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ContractError(f"{label} contains traversal or an empty segment")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value:
        raise ContractError(f"{label} is not a normalized relative path")
    return path


def safe_sha256(value: object, label: str) -> str:
    """Return an immutable sha256 identity with its algorithm prefix."""

    if type(value) is not str or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ContractError(f"{label} must be sha256 followed by 64 lowercase hex digits")
    return value


def _is_secret_key(value: str) -> bool:
    lowered = value.lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    compact = normalized.replace("_", "")
    return (
        any(marker in lowered for marker in ("password", "secret", "token", "credential"))
        or "api_key" in normalized
        or "private_key" in normalized
        or "apikey" in compact
        or "privatekey" in compact
    )


def _is_redacted_value(value: str, *, authorization: bool = False) -> bool:
    pattern = _REDACTED_AUTHORIZATION_PATTERN if authorization else _REDACTED_VALUE_PATTERN
    return pattern.match(value) is not None


def _redact_assignment(match: re.Match[str]) -> str:
    if not _is_secret_key(match.group("key")):
        return match.group(0)
    original_value = match.group("value")
    if _is_redacted_value(original_value):
        return match.group(0)
    if original_value.lstrip().startswith(("{", "[")):
        raise ContractError("structured secret assignments cannot be safely redacted")
    quote = original_value[0] if original_value[:1] in {'"', "'"} else ""
    replacement = f"{quote}<redacted>{quote}" if quote else "<redacted>"
    return match.group("head") + replacement


def _redact_authorization(match: re.Match[str]) -> str:
    original_value = match.group("value")
    if _is_redacted_value(original_value, authorization=True):
        return match.group(0)
    quote = original_value[0] if original_value[0] in {'"', "'"} else ""
    replacement = f"{quote}<redacted>{quote}" if quote else "<redacted>"
    return match.group("head") + replacement


def _assert_redaction_complete(value: str) -> None:
    for match in _ASSIGNMENT_START_PATTERN.finditer(value):
        if _is_secret_key(match.group("key")) and not _is_redacted_value(value[match.end() :]):
            raise ContractError("unredacted secret assignment remains after redaction")
    for match in _AUTHORIZATION_START_PATTERN.finditer(value):
        if not _is_redacted_value(value[match.end() :], authorization=True):
            raise ContractError("unredacted authorization value remains after redaction")


def redact_text(value: str, canaries: Sequence[str]) -> str:
    """Redact supported secrets and fail when a canary or unsafe form remains."""

    if not isinstance(value, str):
        raise ContractError("text to redact must be a string")
    for canary in canaries:
        if not isinstance(canary, str):
            raise ContractError("redaction canaries must be strings")
        if canary and canary in value:
            raise ContractError("redaction canary detected")
    redacted = _AUTHORIZATION_PATTERN.sub(_redact_authorization, value)
    redacted = _ASSIGNMENT_PATTERN.sub(_redact_assignment, redacted)
    _assert_redaction_complete(redacted)
    return redacted


def _require_plain_json(value: object, label: str) -> None:
    stack = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > _MAX_JSON_DEPTH or nodes > _MAX_JSON_NODES:
            raise ContractError(f"{label} exceeds safe structural limits")
        current_type = type(current)
        if current_type is dict:
            for key, child in current.items():
                if type(key) is not str:
                    raise ContractError(f"{label} contains a non-JSON object key")
                stack.append((child, depth + 1))
        elif current_type is list:
            for child in current:
                stack.append((child, depth + 1))
        elif current_type is float:
            if not math.isfinite(current):
                raise ContractError(f"{label} contains a non-finite number")
        elif current_type not in (str, int, bool, type(None)):
            raise ContractError(f"{label} contains a non-builtin JSON value")


def _object(value: object, label: str, keys: set[str]) -> dict:
    if type(value) is not dict:
        raise ContractError(f"{label} must be an object")
    if any(type(key) is not str for key in value):
        raise ContractError(f"{label} keys must be strings")
    actual = set(value)
    if actual != keys:
        raise ContractError(f"{label} keys do not match the closed contract")
    return value


def _array(value: object, label: str, *, minimum: int = 0) -> list:
    if type(value) is not list or len(value) < minimum:
        raise ContractError(f"{label} must be an array with at least {minimum} item(s)")
    return value


def _string(
    value: object,
    label: str,
    *,
    pattern: re.Pattern[str] | None = None,
    maximum: int = 255,
) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise ContractError(f"{label} must be a non-empty string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ContractError(f"{label} has an unsafe format")
    return value


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if (
        type(value) is not int
        or value < minimum
        or value > maximum
    ):
        raise ContractError(f"{label} must be an integer from {minimum} through {maximum}")
    return value


def _require_schema_version_one(value: object, label: str) -> None:
    if type(value) is not str or value != "1":
        raise ContractError(f"{label} schema_version must be the string 1")


def _number(value: object, label: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ContractError(f"{label} must be a number from {minimum} through {maximum}")
    try:
        numeric = float(value)
    except (OverflowError, ValueError) as error:
        raise ContractError(
            f"{label} must be a number from {minimum} through {maximum}"
        ) from error
    if not math.isfinite(numeric) or numeric < minimum or numeric > maximum:
        raise ContractError(f"{label} must be a number from {minimum} through {maximum}")
    return numeric


def _choice(value: object, label: str, choices: frozenset[str]) -> str:
    if type(value) is not str or value not in choices:
        raise ContractError(f"{label} must be one of {sorted(choices)}")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if type(value) is not str or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z",
        value,
    ):
        raise ContractError(f"{label} must be an RFC 3339 UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ContractError(f"{label} is not a real UTC timestamp") from error


def _disposal_timestamp(value: object, label: str) -> datetime:
    if type(value) is not str or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z",
        value,
    ):
        raise ContractError(f"{label} must be canonical UTC with six fractional digits")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ContractError(f"{label} is not a real canonical UTC timestamp") from error


def _commit(value: object, label: str) -> str:
    return _string(value, label, pattern=_COMMIT_PATTERN, maximum=40)


def _url(value: object, label: str) -> str:
    result = _string(value, label, maximum=2048)
    if any(character.isspace() or unicodedata.category(character) == "Cc" for character in result):
        raise ContractError(f"{label} must not contain whitespace or control characters")
    if _HTTPS_URL_PATTERN.fullmatch(result) is None:
        raise ContractError(f"{label} must be an allowed HTTPS URL")
    try:
        parsed = urlsplit(result)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as error:
        raise ContractError(f"{label} is not a valid HTTPS URL") from error
    if (
        parsed.scheme != "https"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ContractError(f"{label} must be an HTTPS URL without embedded credentials")
    return result


def _safe_output_name(value: object, label: str) -> str:
    return _string(value, label, pattern=_SAFE_NAME_PATTERN, maximum=128)


def _unique(values: Sequence[str], label: str) -> None:
    if len(set(values)) != len(values):
        raise ContractError(f"{label} values must be unique")


def _validate_binary_lock(value: object, label: str) -> dict:
    result = _object(
        value,
        label,
        {"name", "kind", "version", "url", "sha256", "executable_path"},
    )
    _string(result["name"], f"{label}.name", pattern=_IDENTIFIER_PATTERN, maximum=128)
    if result["kind"] != "binary":
        raise ContractError(f"{label}.kind must be binary")
    _string(result["version"], f"{label}.version", pattern=_IDENTIFIER_PATTERN)
    _url(result["url"], f"{label}.url")
    safe_sha256(result["sha256"], f"{label}.sha256")
    safe_relative_path(result["executable_path"], f"{label}.executable_path")
    return result


def _validate_image_lock(value: object, label: str) -> dict:
    result = _object(
        value,
        label,
        {"name", "kind", "version", "reference", "index_digest", "platforms"},
    )
    _string(result["name"], f"{label}.name", pattern=_IDENTIFIER_PATTERN, maximum=128)
    if result["kind"] != "image":
        raise ContractError(f"{label}.kind must be image")
    _string(result["version"], f"{label}.version", pattern=_IDENTIFIER_PATTERN)
    reference = _string(result["reference"], f"{label}.reference", maximum=512)
    match = _IMAGE_REFERENCE_PATTERN.fullmatch(reference)
    if match is None:
        raise ContractError(f"{label}.reference must end in an immutable sha256 digest")
    index_digest = safe_sha256(result["index_digest"], f"{label}.index_digest")
    if match.group(1) != index_digest.removeprefix("sha256:"):
        raise ContractError(f"{label}.reference and index_digest must match")
    platforms = _array(result["platforms"], f"{label}.platforms", minimum=1)
    platform_names = []
    for index, platform_value in enumerate(platforms):
        platform = _object(
            platform_value,
            f"{label}.platforms[{index}]",
            {"platform", "digest"},
        )
        platform_names.append(
            _choice(
                platform["platform"],
                f"{label}.platforms[{index}].platform",
                frozenset({"linux/amd64", "linux/arm64"}),
            )
        )
        safe_sha256(platform["digest"], f"{label}.platforms[{index}].digest")
    _unique(platform_names, f"{label}.platforms")
    return result


def validate_run_manifest(value: object) -> dict:
    _require_plain_json(value, "run manifest")
    result = _object(
        value,
        "run manifest",
        {
            "schema_version",
            "run_id",
            "project_prefix",
            "created_at_utc",
            "remote_root",
            "aggregate_wall_seconds",
            "final_cleanup_timeout_seconds",
            "heartbeat_interval_seconds",
            "lease_timeout_seconds",
            "absolute_terminal_seconds",
            "lock_identities",
            "sources",
            "outputs",
            "phases",
        },
    )
    _require_schema_version_one(result["schema_version"], "run manifest")
    run_id = _string(result["run_id"], "run manifest run_id", pattern=_RUN_ID_PATTERN)
    expected_prefix = f"z1rr-racetime-g0-{run_id}"
    if result["project_prefix"] != expected_prefix:
        raise ContractError("run manifest project_prefix does not match run_id")
    _timestamp(result["created_at_utc"], "run manifest created_at_utc")
    if result["remote_root"] != f"/var/lib/z1rr-racetime/g0/{run_id}":
        raise ContractError("run manifest remote_root is outside the allowed G0 root")
    aggregate_timeout = _integer(
        result["aggregate_wall_seconds"],
        "run manifest aggregate_wall_seconds",
        86400,
        86400,
    )
    final_cleanup_timeout = _integer(
        result["final_cleanup_timeout_seconds"],
        "run manifest final_cleanup_timeout_seconds",
        60,
        1800,
    )
    heartbeat_interval = _integer(
        result["heartbeat_interval_seconds"],
        "run manifest heartbeat_interval_seconds",
        15,
        15,
    )
    lease_timeout = _integer(
        result["lease_timeout_seconds"],
        "run manifest lease_timeout_seconds",
        90,
        90,
    )
    absolute_terminal_timeout = _integer(
        result["absolute_terminal_seconds"],
        "run manifest absolute_terminal_seconds",
        86490,
        86490,
    )
    if heartbeat_interval >= lease_timeout:
        raise ContractError("run manifest heartbeat interval must be shorter than its lease")
    if absolute_terminal_timeout != aggregate_timeout + lease_timeout:
        raise ContractError(
            "run manifest absolute terminal timeout must equal aggregate plus lease"
        )

    identities = _object(
        result["lock_identities"],
        "run manifest lock_identities",
        {"docker_bootstrap_sha256", "tool_lock_sha256"},
    )
    bootstrap_identity = safe_sha256(
        identities["docker_bootstrap_sha256"], "docker bootstrap lock identity"
    )
    tool_identity = safe_sha256(identities["tool_lock_sha256"], "tool lock identity")
    if bootstrap_identity == tool_identity:
        raise ContractError("docker bootstrap and tool locks require separate identities")

    sources = _array(result["sources"], "run manifest sources", minimum=1)
    source_names = []
    for index, source_value in enumerate(sources):
        source = _object(
            source_value,
            f"run manifest sources[{index}]",
            {
                "name",
                "branch",
                "commit",
                "local_path",
                "bundle_path",
                "bundle_sha256",
                "archive_path",
                "archive_sha256",
                "custody_class",
            },
        )
        source_names.append(
            _choice(
                source["name"],
                f"run manifest sources[{index}].name",
                frozenset({"racetime", "restream", "ttpbot", "livesplit"}),
            )
        )
        branch = _string(
            source["branch"],
            f"run manifest sources[{index}].branch",
            pattern=_BRANCH_PATTERN,
            maximum=128,
        )
        if ".." in branch or "//" in branch or branch.endswith("/"):
            raise ContractError(f"run manifest sources[{index}].branch is unsafe")
        _commit(source["commit"], f"run manifest sources[{index}].commit")
        for path_key in ("local_path", "bundle_path", "archive_path"):
            safe_relative_path(
                source[path_key], f"run manifest sources[{index}].{path_key}"
            )
        safe_sha256(
            source["bundle_sha256"], f"run manifest sources[{index}].bundle_sha256"
        )
        safe_sha256(
            source["archive_sha256"], f"run manifest sources[{index}].archive_sha256"
        )
        _choice(
            source["custody_class"],
            f"run manifest sources[{index}].custody_class",
            _CUSTODY_CLASSES,
        )
    _unique(source_names, "run manifest source names")

    outputs = _array(result["outputs"], "run manifest outputs", minimum=1)
    output_names = []
    output_paths = []
    for index, output_value in enumerate(outputs):
        output = _object(
            output_value,
            f"run manifest outputs[{index}]",
            {"name", "path", "custody_class"},
        )
        name = _safe_output_name(output["name"], f"run manifest outputs[{index}].name")
        path = safe_relative_path(output["path"], f"run manifest outputs[{index}].path")
        if path.name != name:
            raise ContractError(f"run manifest outputs[{index}] name and path must match")
        _choice(
            output["custody_class"],
            f"run manifest outputs[{index}].custody_class",
            _CUSTODY_CLASSES,
        )
        output_names.append(name)
        output_paths.append(str(path))
    _unique(output_names, "run manifest output names")
    _unique(output_paths, "run manifest output paths")

    phases = _array(result["phases"], "run manifest phases", minimum=9)
    if len(phases) != len(_PHASE_NAMES):
        raise ContractError("run manifest must contain exactly nine phases")
    phase_allocations = []
    for index, (phase_value, expected_name) in enumerate(zip(phases, _PHASE_NAMES)):
        phase = _object(
            phase_value,
            f"run manifest phases[{index}]",
            {
                "name",
                "timeout_seconds",
                "execution_timeout_seconds",
                "cleanup_timeout_seconds",
            },
        )
        if phase["name"] != expected_name:
            raise ContractError("run manifest phase names or order are incorrect")
        timeout = _integer(
            phase["timeout_seconds"],
            f"run manifest phases[{index}].timeout_seconds",
            1,
            86400,
        )
        if timeout > aggregate_timeout:
            raise ContractError("a phase timeout exceeds the aggregate timeout")
        execution_timeout = _integer(
            phase["execution_timeout_seconds"],
            f"run manifest phases[{index}].execution_timeout_seconds",
            1,
            18000,
        )
        cleanup_timeout = _integer(
            phase["cleanup_timeout_seconds"],
            f"run manifest phases[{index}].cleanup_timeout_seconds",
            5,
            600,
        )
        if execution_timeout + cleanup_timeout > timeout:
            raise ContractError("command execution plus cleanup exceeds its phase allocation")
        phase_allocations.append(timeout)
    if sum(phase_allocations) + final_cleanup_timeout > aggregate_timeout:
        raise ContractError("phase allocations plus final cleanup exceed the aggregate timeout")
    return result


def _validate_bootstrap_lock(value: object) -> dict:
    _require_plain_json(value, "docker bootstrap lock")
    result = _object(
        value,
        "docker bootstrap lock",
        {
            "schema_version",
            "generated_at_utc",
            "host",
            "signing_key",
            "repository",
            "packages",
            "allowed_package_delta",
            "bootstrap_tools",
        },
    )
    _require_schema_version_one(result["schema_version"], "docker bootstrap lock")
    _timestamp(result["generated_at_utc"], "docker bootstrap lock generated_at_utc")
    host = _object(
        result["host"], "docker bootstrap lock host", {"distribution", "release", "architecture"}
    )
    if host != {"distribution": "ubuntu", "release": "24.04", "architecture": "arm64"}:
        raise ContractError("docker bootstrap lock host must be Ubuntu 24.04 arm64")
    signing_key = _object(
        result["signing_key"],
        "docker bootstrap lock signing_key",
        {"url", "sha256", "fingerprint"},
    )
    _url(signing_key["url"], "docker bootstrap lock signing_key.url")
    safe_sha256(signing_key["sha256"], "docker bootstrap lock signing_key.sha256")
    _string(
        signing_key["fingerprint"],
        "docker bootstrap lock signing_key.fingerprint",
        pattern=re.compile(r"[0-9A-F]{40}\Z"),
        maximum=40,
    )
    repository = _object(
        result["repository"],
        "docker bootstrap lock repository",
        {"definition", "inrelease_url", "inrelease_sha256"},
    )
    definition = _string(repository["definition"], "docker bootstrap lock repository.definition", maximum=1024)
    if "\n" in definition or "\r" in definition:
        raise ContractError("docker bootstrap repository definition must be one line")
    _url(repository["inrelease_url"], "docker bootstrap lock repository.inrelease_url")
    safe_sha256(
        repository["inrelease_sha256"], "docker bootstrap lock repository.inrelease_sha256"
    )
    packages = _array(result["packages"], "docker bootstrap lock packages", minimum=1)
    package_names = []
    for index, package_value in enumerate(packages):
        package = _object(
            package_value,
            f"docker bootstrap lock packages[{index}]",
            {"name", "version", "architecture", "origin", "url", "sha256"},
        )
        package_names.append(
            _string(package["name"], f"docker bootstrap lock packages[{index}].name", pattern=_IDENTIFIER_PATTERN)
        )
        _string(package["version"], f"docker bootstrap lock packages[{index}].version")
        if package["architecture"] != "arm64":
            raise ContractError("docker bootstrap packages must be arm64")
        _string(package["origin"], f"docker bootstrap lock packages[{index}].origin")
        _url(package["url"], f"docker bootstrap lock packages[{index}].url")
        safe_sha256(package["sha256"], f"docker bootstrap lock packages[{index}].sha256")
    _unique(package_names, "docker bootstrap package names")
    allowed_delta = _array(
        result["allowed_package_delta"], "docker bootstrap lock allowed_package_delta", minimum=1
    )
    for index, package_name in enumerate(allowed_delta):
        _string(
            package_name,
            f"docker bootstrap lock allowed_package_delta[{index}]",
            pattern=_IDENTIFIER_PATTERN,
        )
    _unique(allowed_delta, "docker bootstrap allowed package delta")
    if set(allowed_delta) != set(package_names):
        raise ContractError("allowed_package_delta must name the exact locked package set")
    bootstrap_tools = _object(
        result["bootstrap_tools"],
        "docker bootstrap lock bootstrap_tools",
        {"buildx", "buildkit", "runtime_probe"},
    )
    _validate_binary_lock(bootstrap_tools["buildx"], "docker bootstrap lock bootstrap_tools.buildx")
    _validate_image_lock(bootstrap_tools["buildkit"], "docker bootstrap lock bootstrap_tools.buildkit")
    _validate_image_lock(
        bootstrap_tools["runtime_probe"], "docker bootstrap lock bootstrap_tools.runtime_probe"
    )
    return result


def validate_tool_lock(value: object) -> dict:
    _require_plain_json(value, "tool lock")
    result = _object(
        value,
        "tool lock",
        {"schema_version", "generated_at_utc", "bootstrap_lock_sha256", "tools"},
    )
    _require_schema_version_one(result["schema_version"], "tool lock")
    _timestamp(result["generated_at_utc"], "tool lock generated_at_utc")
    safe_sha256(result["bootstrap_lock_sha256"], "tool lock bootstrap_lock_sha256")
    tools = _array(result["tools"], "tool lock tools", minimum=1)
    names = []
    for index, tool_value in enumerate(tools):
        if not isinstance(tool_value, dict):
            raise ContractError(f"tool lock tools[{index}] must be an object")
        kind = tool_value.get("kind")
        if kind == "binary":
            tool = _validate_binary_lock(tool_value, f"tool lock tools[{index}]")
        elif kind == "image":
            tool = _validate_image_lock(tool_value, f"tool lock tools[{index}]")
        else:
            raise ContractError(f"tool lock tools[{index}].kind is unsupported")
        names.append(tool["name"])
    _unique(names, "tool lock tool names")
    return result


def validate_worker_evidence(value: object) -> dict:
    _require_plain_json(value, "worker evidence")
    result = _object(
        value,
        "worker evidence",
        {
            "schema_version",
            "run_id",
            "project_prefix",
            "source_commit",
            "started_at_utc",
            "completed_at_utc",
            "result",
            "phases",
            "retained_artifacts",
            "cleanup_state",
        },
    )
    _require_schema_version_one(result["schema_version"], "worker evidence")
    run_id = _string(result["run_id"], "worker evidence run_id", pattern=_RUN_ID_PATTERN)
    if result["project_prefix"] != f"z1rr-racetime-g0-{run_id}":
        raise ContractError("worker evidence project_prefix does not match run_id")
    _commit(result["source_commit"], "worker evidence source_commit")
    started = _timestamp(result["started_at_utc"], "worker evidence started_at_utc")
    completed = _timestamp(result["completed_at_utc"], "worker evidence completed_at_utc")
    if completed < started:
        raise ContractError("worker evidence completes before it starts")
    if (completed - started).total_seconds() > 86400:
        raise ContractError("worker evidence wall duration exceeds 86400 seconds")
    final_result = _choice(result["result"], "worker evidence result", frozenset({"PASS", "FAIL"}))
    phases = _array(result["phases"], "worker evidence phases", minimum=9)
    if len(phases) != len(_PHASE_NAMES):
        raise ContractError("worker evidence must contain exactly nine phases")
    observed_results = []
    exit_statuses = []
    phase_cleanup_states = []
    for index, (phase_value, expected_name) in enumerate(zip(phases, _PHASE_NAMES)):
        phase = _object(
            phase_value,
            f"worker evidence phases[{index}]",
            {
                "name",
                "expected_result",
                "observed_result",
                "command_id",
                "exit_status",
                "duration_seconds",
                "stdout_sha256",
                "stderr_sha256",
                "retained_artifact_hashes",
                "cleanup_state",
            },
        )
        if phase["name"] != expected_name:
            raise ContractError("worker evidence phase names or order are incorrect")
        if phase["expected_result"] != "PASS":
            raise ContractError("worker evidence phase expected_result must be PASS")
        observed_results.append(
            _choice(
                phase["observed_result"],
                f"worker evidence phases[{index}].observed_result",
                frozenset({"PASS", "FAIL"}),
            )
        )
        _string(
            phase["command_id"],
            f"worker evidence phases[{index}].command_id",
            pattern=_IDENTIFIER_PATTERN,
            maximum=128,
        )
        exit_statuses.append(
            _integer(
                phase["exit_status"],
                f"worker evidence phases[{index}].exit_status",
                -255,
                255,
            )
        )
        _number(
            phase["duration_seconds"],
            f"worker evidence phases[{index}].duration_seconds",
            0,
            86400,
        )
        safe_sha256(
            phase["stdout_sha256"], f"worker evidence phases[{index}].stdout_sha256"
        )
        safe_sha256(
            phase["stderr_sha256"], f"worker evidence phases[{index}].stderr_sha256"
        )
        artifact_hashes = _array(
            phase["retained_artifact_hashes"],
            f"worker evidence phases[{index}].retained_artifact_hashes",
        )
        for hash_index, artifact_hash in enumerate(artifact_hashes):
            safe_sha256(
                artifact_hash,
                f"worker evidence phases[{index}].retained_artifact_hashes[{hash_index}]",
            )
        _unique(artifact_hashes, f"worker evidence phases[{index}] artifact hashes")
        phase_cleanup_states.append(
            _choice(
                phase["cleanup_state"],
                f"worker evidence phases[{index}].cleanup_state",
                _CLEANUP_STATES,
            )
        )
    if final_result == "PASS":
        if any(item != "PASS" for item in observed_results):
            raise ContractError("worker evidence cannot pass with a failed phase")
        if any(status != 0 for status in exit_statuses):
            raise ContractError("worker evidence cannot pass with a nonzero phase exit")
        if any(state in {"pending", "failed"} for state in phase_cleanup_states):
            raise ContractError("worker evidence cannot pass with incomplete phase cleanup")
        if phase_cleanup_states[-1] != "verified":
            raise ContractError("worker evidence cleanup phase must verify cleanup")
    artifacts = _array(result["retained_artifacts"], "worker evidence retained_artifacts")
    artifact_names = []
    artifact_paths = []
    for index, artifact_value in enumerate(artifacts):
        artifact = _object(
            artifact_value,
            f"worker evidence retained_artifacts[{index}]",
            {"name", "path", "sha256", "custody_class"},
        )
        name = _safe_output_name(
            artifact["name"], f"worker evidence retained_artifacts[{index}].name"
        )
        path = safe_relative_path(
            artifact["path"], f"worker evidence retained_artifacts[{index}].path"
        )
        if path.name != name:
            raise ContractError("worker evidence artifact name and path must match")
        safe_sha256(
            artifact["sha256"], f"worker evidence retained_artifacts[{index}].sha256"
        )
        if artifact["custody_class"] != "retained":
            raise ContractError("worker evidence artifacts must have retained custody")
        artifact_names.append(name)
        artifact_paths.append(str(path))
    _unique(artifact_names, "worker evidence artifact names")
    _unique(artifact_paths, "worker evidence artifact paths")
    cleanup_state = _choice(
        result["cleanup_state"], "worker evidence cleanup_state", frozenset({"verified", "failed"})
    )
    if final_result == "PASS" and cleanup_state != "verified":
        raise ContractError("worker evidence cannot pass without verified cleanup")
    return result


def validate_worker_disposal(value: object) -> dict:
    """Validate the redacted, append-only worker-disposal control record."""

    _require_plain_json(value, "worker disposal")
    result = _object(
        value,
        "worker disposal",
        {
            "schema_version",
            "disposition",
            "run_id",
            "project_prefix",
            "instance_fingerprint",
            "last_authenticated_heartbeat_at_utc",
            "failed_proof_classes",
            "lease_status",
            "lifecycle_events",
            "complete_pre_failure_hashes",
        },
    )
    _require_schema_version_one(result["schema_version"], "worker disposal")
    if result["disposition"] != "WORKER_DISPOSAL_REQUIRED":
        raise ContractError("worker disposal cannot claim PASS or ordinary failure evidence")

    run_id = _string(result["run_id"], "worker disposal run_id", pattern=_RUN_ID_PATTERN)
    if result["project_prefix"] != f"z1rr-racetime-g0-{run_id}":
        raise ContractError("worker disposal project_prefix does not match run_id")

    fingerprint = _object(
        result["instance_fingerprint"],
        "worker disposal instance_fingerprint",
        {"domain", "sha256"},
    )
    if fingerprint["domain"] != _INSTANCE_FINGERPRINT_DOMAIN:
        raise ContractError("worker disposal instance fingerprint domain is incorrect")
    safe_sha256(fingerprint["sha256"], "worker disposal instance fingerprint")

    heartbeat_at = _disposal_timestamp(
        result["last_authenticated_heartbeat_at_utc"],
        "worker disposal last_authenticated_heartbeat_at_utc",
    )
    proof_values = _array(
        result["failed_proof_classes"],
        "worker disposal failed_proof_classes",
        minimum=1,
    )
    proof_classes = []
    for index, proof_value in enumerate(proof_values):
        proof_classes.append(
            _choice(
                proof_value,
                f"worker disposal failed_proof_classes[{index}]",
                _FAILED_PROOF_CLASSES,
            )
        )
    _unique(proof_classes, "worker disposal failed proof classes")

    lease_status = _choice(
        result["lease_status"], "worker disposal lease_status", _LEASE_STATUSES
    )
    required_external_proof = {
        "heartbeat-lost": "heartbeat-authentication",
        "terminal-response-lost": "terminal-response-authentication",
    }.get(lease_status)
    if required_external_proof is not None and required_external_proof not in proof_classes:
        raise ContractError("worker disposal lease status lacks its failed proof class")

    lifecycle_values = _array(
        result["lifecycle_events"], "worker disposal lifecycle_events", minimum=1
    )
    if len(lifecycle_values) > len(_DISPOSAL_LIFECYCLE):
        raise ContractError("worker disposal lifecycle has too many states")
    lifecycle_times = []
    for index, lifecycle_value in enumerate(lifecycle_values):
        lifecycle = _object(
            lifecycle_value,
            f"worker disposal lifecycle_events[{index}]",
            {"state", "recorded_at_utc"},
        )
        if lifecycle["state"] != _DISPOSAL_LIFECYCLE[index]:
            raise ContractError("worker disposal lifecycle must be an exact monotonic prefix")
        lifecycle_times.append(
            _disposal_timestamp(
                lifecycle["recorded_at_utc"],
                f"worker disposal lifecycle_events[{index}].recorded_at_utc",
            )
        )
    if any(later < earlier for earlier, later in zip(lifecycle_times, lifecycle_times[1:])):
        raise ContractError("worker disposal lifecycle timestamps move backwards")
    disposal_recorded_at = lifecycle_times[0]
    if heartbeat_at > disposal_recorded_at:
        raise ContractError("worker disposal heartbeat occurs after disposal was recorded")

    complete_hash_values = _array(
        result["complete_pre_failure_hashes"],
        "worker disposal complete_pre_failure_hashes",
    )
    if len(complete_hash_values) > 256:
        raise ContractError("worker disposal permits at most 256 complete hashes")
    complete_hash_names = []
    for index, complete_hash_value in enumerate(complete_hash_values):
        complete_hash = _object(
            complete_hash_value,
            f"worker disposal complete_pre_failure_hashes[{index}]",
            {"name", "kind", "sha256", "completed_at_utc"},
        )
        name = _safe_output_name(
            complete_hash["name"],
            f"worker disposal complete_pre_failure_hashes[{index}].name",
        )
        if _is_secret_key(name) or "ocid1." in name:
            raise ContractError("worker disposal complete hash name is unsafe")
        kind = _choice(
            complete_hash["kind"],
            f"worker disposal complete_pre_failure_hashes[{index}].kind",
            _COMPLETE_HASH_KINDS,
        )
        expected_fixed_name = _FIXED_COMPLETE_HASH_NAMES.get(kind)
        if expected_fixed_name is not None and name != expected_fixed_name:
            raise ContractError("worker disposal hash name and kind do not match protocol")
        safe_sha256(
            complete_hash["sha256"],
            f"worker disposal complete_pre_failure_hashes[{index}].sha256",
        )
        completed_at = _disposal_timestamp(
            complete_hash["completed_at_utc"],
            f"worker disposal complete_pre_failure_hashes[{index}].completed_at_utc",
        )
        if completed_at >= disposal_recorded_at:
            raise ContractError("worker disposal hash is not strictly before the failure boundary")
        complete_hash_names.append(name)
    _unique(complete_hash_names, "worker disposal complete hash names")
    return result


def _canonical_sha256(value: dict) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ContractError("contract cannot be encoded canonically") from error
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_disposal_control(value: object, run_manifest: dict) -> dict:
    _require_plain_json(value, "trusted disposal control")
    control = _object(
        value,
        "trusted disposal control",
        {
            "schema_version",
            "armed",
            "run_id",
            "project_prefix",
            "instance_fingerprint_sha256",
            "run_manifest_sha256",
            "lease_status",
            "run_started_monotonic_ns",
            "last_authenticated_heartbeat_monotonic_ns",
            "authenticated_remote_disposal_monotonic_ns",
            "disposal_observed_monotonic_ns",
            "absolute_terminal_deadline_monotonic_ns",
        },
    )
    _require_schema_version_one(control["schema_version"], "trusted disposal control")
    if type(control["armed"]) is not bool:
        raise ContractError("trusted disposal control armed must be a boolean")
    run_id = _string(
        control["run_id"], "trusted disposal control run_id", pattern=_RUN_ID_PATTERN
    )
    if control["project_prefix"] != f"z1rr-racetime-g0-{run_id}":
        raise ContractError("trusted disposal control run identity is inconsistent")
    safe_sha256(
        control["instance_fingerprint_sha256"],
        "trusted disposal control instance fingerprint",
    )
    manifest_sha256 = safe_sha256(
        control["run_manifest_sha256"], "trusted disposal control run manifest hash"
    )
    if manifest_sha256 != _canonical_sha256(run_manifest):
        raise ContractError("trusted disposal control run manifest hash is incorrect")
    lease_status = _choice(
        control["lease_status"],
        "trusted disposal control lease_status",
        _LEASE_STATUSES,
    )

    run_started = _integer(
        control["run_started_monotonic_ns"],
        "trusted disposal control run start",
        0,
        _MAX_MONOTONIC_NS,
    )
    last_heartbeat = _integer(
        control["last_authenticated_heartbeat_monotonic_ns"],
        "trusted disposal control last heartbeat",
        0,
        _MAX_MONOTONIC_NS,
    )
    remote_disposal_value = control[
        "authenticated_remote_disposal_monotonic_ns"
    ]
    remote_disposal = None
    if remote_disposal_value is not None:
        remote_disposal = _integer(
            remote_disposal_value,
            "trusted disposal control authenticated remote disposal",
            0,
            _MAX_MONOTONIC_NS,
        )
    disposal_observed = _integer(
        control["disposal_observed_monotonic_ns"],
        "trusted disposal control disposal observation",
        0,
        _MAX_MONOTONIC_NS,
    )
    absolute_deadline = _integer(
        control["absolute_terminal_deadline_monotonic_ns"],
        "trusted disposal control absolute deadline",
        0,
        _MAX_MONOTONIC_NS,
    )
    expected_deadline = (
        run_started
        + run_manifest["absolute_terminal_seconds"] * _NANOSECONDS_PER_SECOND
    )
    if absolute_deadline != expected_deadline:
        raise ContractError("trusted disposal control absolute deadline is incorrect")
    if last_heartbeat < run_started or disposal_observed < last_heartbeat:
        raise ContractError("trusted disposal control monotonic clocks move backwards")
    if remote_disposal is not None and (
        remote_disposal < run_started or remote_disposal > disposal_observed
    ):
        raise ContractError("trusted disposal control remote signal clock is invalid")

    lease_ns = run_manifest["lease_timeout_seconds"] * _NANOSECONDS_PER_SECOND
    triggers = [
        (last_heartbeat + lease_ns, 1, "heartbeat-lost"),
        (absolute_deadline, 2, "terminal-response-lost"),
    ]
    if remote_disposal is not None:
        triggers.append((remote_disposal, 0, "authenticated-remote-signal"))
    trigger_at, _, trigger_status = min(triggers)
    if disposal_observed < trigger_at:
        raise ContractError("trusted disposal control has no mature disposal trigger")
    if lease_status != trigger_status:
        raise ContractError("trusted disposal control did not retain the earliest trigger")
    return control


def _disposal_hash_allowlist(run_manifest: dict) -> dict[str, tuple[str, str | None]]:
    allowed: dict[str, tuple[str, str | None]] = {}

    def register(name: str, kind: str, sha256: str | None) -> None:
        entry = (kind, sha256)
        previous = allowed.get(name)
        if previous is not None and previous != entry:
            raise ContractError("run manifest disposal hash protocol is ambiguous")
        allowed[name] = entry

    register("run-manifest.json", "run-manifest", _canonical_sha256(run_manifest))
    register(
        "docker-bootstrap-lock.json",
        "docker-bootstrap-lock",
        run_manifest["lock_identities"]["docker_bootstrap_sha256"],
    )
    register(
        "tool-lock.json",
        "tool-lock",
        run_manifest["lock_identities"]["tool_lock_sha256"],
    )
    register("control-record.json", "control-record", None)
    for source in run_manifest["sources"]:
        register(
            PurePosixPath(source["bundle_path"]).name,
            "source-bundle",
            source["bundle_sha256"],
        )
        register(
            PurePosixPath(source["archive_path"]).name,
            "source-archive",
            source["archive_sha256"],
        )
    for output in run_manifest["outputs"]:
        if output["custody_class"] == "retained" and output["name"] != "worker-evidence.json":
            register(output["name"], "retained-artifact", None)
    return allowed


def _require_append_only_prefix(previous: list, candidate: list, label: str) -> None:
    if len(candidate) < len(previous) or candidate[: len(previous)] != previous:
        raise ContractError(f"worker disposal {label} is not append-only")


def validate_worker_disposal_transition(
    previous: object | None,
    candidate: object,
    *,
    run_manifest: object,
    trusted_control: object,
) -> dict:
    """Validate one monotonic disposal-record transition against trusted control state."""

    manifest = validate_run_manifest(run_manifest)
    current = validate_worker_disposal(candidate)
    prior = None if previous is None else validate_worker_disposal(previous)
    control = _validate_disposal_control(trusted_control, manifest)
    if not control["armed"]:
        raise ContractError("worker disposal requires an armed trusted control")

    if current["run_id"] != manifest["run_id"] or current["project_prefix"] != manifest[
        "project_prefix"
    ]:
        raise ContractError("worker disposal run identity does not match its manifest")
    if control["run_id"] != current["run_id"] or control["project_prefix"] != current[
        "project_prefix"
    ]:
        raise ContractError("worker disposal run identity does not match trusted control")
    if (
        current["instance_fingerprint"]["sha256"]
        != control["instance_fingerprint_sha256"]
    ):
        raise ContractError("worker disposal instance identity does not match trusted control")
    if current["lease_status"] != control["lease_status"]:
        raise ContractError("worker disposal lease status does not match trusted control")

    allowlist = _disposal_hash_allowlist(manifest)
    manifest_hash = None
    for complete_hash in current["complete_pre_failure_hashes"]:
        allowed = allowlist.get(complete_hash["name"])
        if allowed is None or allowed[0] != complete_hash["kind"]:
            raise ContractError("worker disposal hash is outside the protocol allowlist")
        if allowed[1] is not None and complete_hash["sha256"] != allowed[1]:
            raise ContractError("worker disposal hash does not match its protocol identity")
        if complete_hash["name"] == "run-manifest.json":
            manifest_hash = complete_hash["sha256"]
    if manifest_hash != control["run_manifest_sha256"]:
        raise ContractError("worker disposal lacks the exact run manifest hash")

    if prior is None:
        if len(current["lifecycle_events"]) != 1:
            raise ContractError(
                "initial worker disposal lifecycle must be disposal-recorded only"
            )
        return current

    immutable_keys = (
        "schema_version",
        "disposition",
        "run_id",
        "project_prefix",
        "instance_fingerprint",
        "last_authenticated_heartbeat_at_utc",
        "lease_status",
    )
    if any(prior[key] != current[key] for key in immutable_keys):
        raise ContractError("worker disposal immutable identity changed")
    if prior["lifecycle_events"][-1]["state"] == "recovery-verified":
        if current != prior:
            raise ContractError("worker disposal recovery-verified record is terminal")
        return current
    _require_append_only_prefix(
        prior["lifecycle_events"], current["lifecycle_events"], "lifecycle"
    )
    _require_append_only_prefix(
        prior["failed_proof_classes"], current["failed_proof_classes"], "proof classes"
    )
    _require_append_only_prefix(
        prior["complete_pre_failure_hashes"],
        current["complete_pre_failure_hashes"],
        "complete hashes",
    )
    return current


def validate_restream_history(value: object) -> dict:
    _require_plain_json(value, "restream history")
    result = _object(
        value,
        "restream history",
        {
            "schema_version",
            "repository",
            "base_commit",
            "candidate_commit",
            "captured_at_utc",
            "findings",
        },
    )
    _require_schema_version_one(result["schema_version"], "restream history")
    if result["repository"] != "restream":
        raise ContractError("restream history repository must be restream")
    _commit(result["base_commit"], "restream history base_commit")
    _commit(result["candidate_commit"], "restream history candidate_commit")
    _timestamp(result["captured_at_utc"], "restream history captured_at_utc")
    findings = _array(result["findings"], "restream history findings")
    fingerprints = []
    for index, finding_value in enumerate(findings):
        finding = _object(
            finding_value,
            f"restream history findings[{index}]",
            {
                "rule_id",
                "path",
                "source_commit",
                "line",
                "fingerprint_sha256",
                "classification",
                "outside_candidate",
                "live_credential_disposition",
                "evidence_id",
            },
        )
        _string(
            finding["rule_id"],
            f"restream history findings[{index}].rule_id",
            pattern=_IDENTIFIER_PATTERN,
        )
        safe_relative_path(finding["path"], f"restream history findings[{index}].path")
        _commit(
            finding["source_commit"], f"restream history findings[{index}].source_commit"
        )
        _integer(finding["line"], f"restream history findings[{index}].line", 1, 2**31 - 1)
        fingerprints.append(
            safe_sha256(
                finding["fingerprint_sha256"],
                f"restream history findings[{index}].fingerprint_sha256",
            )
        )
        _choice(
            finding["classification"],
            f"restream history findings[{index}].classification",
            frozenset({"inactive-history", "test-fixture"}),
        )
        if finding["outside_candidate"] is not True:
            raise ContractError("restream history findings must be outside the candidate range")
        _choice(
            finding["live_credential_disposition"],
            f"restream history findings[{index}].live_credential_disposition",
            frozenset({"not-a-credential", "revoked", "rotated"}),
        )
        _string(
            finding["evidence_id"],
            f"restream history findings[{index}].evidence_id",
            pattern=_IDENTIFIER_PATTERN,
        )
    _unique(fingerprints, "restream history finding fingerprints")
    return result


def _reject_symlink(path: Path) -> None:
    absolute = path.absolute()
    for candidate in (absolute, *absolute.parents):
        if candidate.is_symlink():
            raise ContractError("contract path traverses a symlink")


def _reject_constant(value: str) -> None:
    raise ContractError("non-standard JSON constant is forbidden")


def _pairs_to_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate JSON key")
        result[key] = value
    return result


def _read_contract_bytes_posix(contract_path: Path) -> bytes:
    if any(
        not hasattr(os, option)
        for option in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")
    ) or os.open not in os.supports_dir_fd:
        raise ContractError("atomic no-follow contract loading is unavailable")
    absolute_path = Path(os.path.abspath(contract_path))
    components = absolute_path.parts[1:]
    if not components:
        raise ContractError("contract path is not a regular file")

    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | close_on_exec
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | close_on_exec
    directory_descriptor = None
    descriptor = None
    try:
        directory_descriptor = os.open(absolute_path.anchor, directory_flags)
        for component in components[:-1]:
            next_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        descriptor = os.open(
            components[-1],
            file_flags,
            dir_fd=directory_descriptor,
        )
        os.close(directory_descriptor)
        directory_descriptor = None
        file_status = os.fstat(descriptor)
        if not stat.S_ISREG(file_status.st_mode):
            raise ContractError("contract path is not a regular file")
        stream = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = None
        with stream:
            return stream.read(_MAX_CONTRACT_BYTES + 1)
    except ContractError:
        raise
    except OSError as error:
        raise ContractError("cannot load contract file") from error
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        if descriptor is not None:
            os.close(descriptor)


def _normalize_windows_handle_path(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return os.path.normcase(os.path.normpath(value))


def _read_contract_bytes_windows(contract_path: Path) -> bytes:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    generic_read = 0x80000000
    share_all = 0x00000001 | 0x00000002 | 0x00000004
    open_existing = 3
    file_flag_open_reparse_point = 0x00200000
    file_flag_sequential_scan = 0x08000000
    file_attribute_directory = 0x00000010
    file_attribute_reparse_point = 0x00000400
    file_attribute_tag_info_class = 9

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [
            ("file_attributes", wintypes.DWORD),
            ("reparse_tag", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    get_information = kernel32.GetFileInformationByHandleEx
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_information.restype = wintypes.BOOL
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    requested_path = str(contract_path.absolute())
    handle = create_file(
        requested_path,
        generic_read,
        share_all,
        None,
        open_existing,
        file_flag_open_reparse_point | file_flag_sequential_scan,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise ContractError("cannot load contract file")

    descriptor = None
    try:
        attributes = FileAttributeTagInfo()
        if not get_information(
            handle,
            file_attribute_tag_info_class,
            ctypes.byref(attributes),
            ctypes.sizeof(attributes),
        ):
            raise ContractError("cannot inspect contract file handle")
        if attributes.file_attributes & (
            file_attribute_directory | file_attribute_reparse_point
        ):
            raise ContractError("contract path is not a retained regular file")

        required = get_final_path(handle, None, 0, 0)
        if required == 0:
            raise ContractError("cannot inspect contract file handle")
        final_path_buffer = ctypes.create_unicode_buffer(required)
        written = get_final_path(handle, final_path_buffer, required, 0)
        if written == 0 or written >= required:
            raise ContractError("cannot inspect contract file handle")
        if _normalize_windows_handle_path(final_path_buffer.value) != (
            _normalize_windows_handle_path(requested_path)
        ):
            raise ContractError("contract handle does not match its retained path")

        descriptor = msvcrt.open_osfhandle(
            int(handle), os.O_RDONLY | getattr(os, "O_BINARY", 0)
        )
        handle = None
        stream = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = None
        with stream:
            return stream.read(_MAX_CONTRACT_BYTES + 1)
    except ContractError:
        raise
    except (OSError, ValueError) as error:
        raise ContractError("cannot load contract file") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if handle is not None:
            close_handle(handle)


def _read_contract_bytes(contract_path: Path) -> bytes:
    _reject_symlink(contract_path)
    if os.name == "nt":
        return _read_contract_bytes_windows(contract_path)
    return _read_contract_bytes_posix(contract_path)


def load_json(path: Path, schema_name: str) -> dict:
    """Load one named G0 contract without following symlinks and validate it."""

    contract_path = Path(path)
    try:
        raw = _read_contract_bytes(contract_path)
    except RecursionError as error:
        raise ContractError("cannot load contract file") from error
    if len(raw) > _MAX_CONTRACT_BYTES:
        raise ContractError("contract JSON exceeds the byte limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as error:
        raise ContractError("contract JSON is not valid UTF-8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs_to_object,
            parse_constant=_reject_constant,
        )
    except ContractError:
        raise
    except (ValueError, RecursionError) as error:
        raise ContractError("cannot decode contract JSON") from error
    normalized_name = schema_name.removesuffix(".schema.json")
    validators: dict[str, Callable[[object], dict]] = {
        "run-manifest": validate_run_manifest,
        "docker-bootstrap-lock": _validate_bootstrap_lock,
        "tool-lock": validate_tool_lock,
        "worker-evidence": validate_worker_evidence,
        "worker-disposal": validate_worker_disposal,
        "restream-history": validate_restream_history,
    }
    validator = validators.get(normalized_name)
    if validator is None:
        raise ContractError("unknown schema name")
    return validator(value)
