"""Fail-closed data contracts for the OCI G0 worker."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence
from urllib.parse import urlsplit


class ContractError(ValueError):
    """Raised when untrusted worker contract data is unsafe or malformed."""


_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_RUN_ID_PATTERN = re.compile(r"[0-9]{8}t[0-9]{6}z-[0-9a-f]{8}\Z")
_SAFE_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_BRANCH_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")
_IMAGE_REFERENCE_PATTERN = re.compile(
    r"[a-z0-9][a-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?"
    r"@sha256:([0-9a-f]{64})\Z"
)
_PHASE_NAMES = (
    "preflight",
    "worker-setup",
    "images",
    "security-and-sbom",
    "services-and-configuration",
    "recovery-and-service-hardening",
    "cross-repository-evidence",
    "identities-and-gates",
    "cleanup",
)
_CUSTODY_CLASSES = frozenset({"retained", "transient"})
_CLEANUP_STATES = frozenset({"not-required", "pending", "verified", "failed"})


def safe_relative_path(value: object, label: str) -> PurePosixPath:
    """Return a workspace-relative POSIX path or fail closed."""

    if not isinstance(value, str) or not value or len(value) > 255:
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
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ContractError(f"{label} contains traversal or an empty segment")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value:
        raise ContractError(f"{label} is not a normalized relative path")
    return path


def safe_sha256(value: object, label: str) -> str:
    """Return an immutable sha256 identity with its algorithm prefix."""

    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ContractError(f"{label} must be sha256 followed by 64 lowercase hex digits")
    return value


def redact_text(value: str, canaries: Sequence[str]) -> str:
    """Remove exact canaries and simple secret assignments from diagnostic text."""

    if not isinstance(value, str):
        raise ContractError("text to redact must be a string")
    checked_canaries: list[str] = []
    for canary in canaries:
        if not isinstance(canary, str):
            raise ContractError("redaction canaries must be strings")
        if canary:
            checked_canaries.append(canary)
    redacted = value
    for canary in sorted(set(checked_canaries), key=len, reverse=True):
        redacted = redacted.replace(canary, "[REDACTED]")
    return re.sub(
        r"(?i)\b(token|secret|password|private[_-]?key)\s*[:=]\s*[^\s,;]+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        redacted,
    )


def _object(value: object, label: str, keys: set[str]) -> dict:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise ContractError(f"{label} has missing keys {missing} and unknown keys {unknown}")
    if any(not isinstance(key, str) for key in value):
        raise ContractError(f"{label} keys must be strings")
    return value


def _array(value: object, label: str, *, minimum: int = 0) -> list:
    if not isinstance(value, list) or len(value) < minimum:
        raise ContractError(f"{label} must be an array with at least {minimum} item(s)")
    return value


def _string(
    value: object,
    label: str,
    *,
    pattern: re.Pattern[str] | None = None,
    maximum: int = 255,
) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContractError(f"{label} must be a non-empty string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ContractError(f"{label} has an unsafe format")
    return value


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise ContractError(f"{label} must be an integer from {minimum} through {maximum}")
    return value


def _number(value: object, label: str, minimum: float, maximum: float) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise ContractError(f"{label} must be a number from {minimum} through {maximum}")
    return float(value)


def _choice(value: object, label: str, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ContractError(f"{label} must be one of {sorted(choices)}")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z",
        value,
    ):
        raise ContractError(f"{label} must be an RFC 3339 UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ContractError(f"{label} is not a real UTC timestamp") from error


def _commit(value: object, label: str) -> str:
    return _string(value, label, pattern=_COMMIT_PATTERN, maximum=40)


def _url(value: object, label: str) -> str:
    result = _string(value, label, maximum=2048)
    parsed = urlsplit(result)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
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
    result = _object(
        value,
        "run manifest",
        {
            "schema_version",
            "run_id",
            "project_prefix",
            "created_at_utc",
            "remote_root",
            "aggregate_timeout_seconds",
            "lock_identities",
            "sources",
            "outputs",
            "phases",
        },
    )
    if result["schema_version"] != 1:
        raise ContractError("run manifest schema_version must be 1")
    run_id = _string(result["run_id"], "run manifest run_id", pattern=_RUN_ID_PATTERN)
    expected_prefix = f"z1rr-racetime-g0-{run_id}"
    if result["project_prefix"] != expected_prefix:
        raise ContractError("run manifest project_prefix does not match run_id")
    _timestamp(result["created_at_utc"], "run manifest created_at_utc")
    if result["remote_root"] != f"/var/lib/z1rr-racetime/g0/{run_id}":
        raise ContractError("run manifest remote_root is outside the allowed G0 root")
    aggregate_timeout = _integer(
        result["aggregate_timeout_seconds"],
        "run manifest aggregate_timeout_seconds",
        1,
        86400,
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
    for index, (phase_value, expected_name) in enumerate(zip(phases, _PHASE_NAMES)):
        phase = _object(
            phase_value,
            f"run manifest phases[{index}]",
            {"name", "timeout_seconds"},
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
    return result


def _validate_bootstrap_lock(value: object) -> dict:
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
    if result["schema_version"] != 1:
        raise ContractError("docker bootstrap lock schema_version must be 1")
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
    result = _object(
        value,
        "tool lock",
        {"schema_version", "generated_at_utc", "bootstrap_lock_sha256", "tools"},
    )
    if result["schema_version"] != 1:
        raise ContractError("tool lock schema_version must be 1")
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
    if result["schema_version"] != 1:
        raise ContractError("worker evidence schema_version must be 1")
    run_id = _string(result["run_id"], "worker evidence run_id", pattern=_RUN_ID_PATTERN)
    if result["project_prefix"] != f"z1rr-racetime-g0-{run_id}":
        raise ContractError("worker evidence project_prefix does not match run_id")
    _commit(result["source_commit"], "worker evidence source_commit")
    started = _timestamp(result["started_at_utc"], "worker evidence started_at_utc")
    completed = _timestamp(result["completed_at_utc"], "worker evidence completed_at_utc")
    if completed < started:
        raise ContractError("worker evidence completes before it starts")
    final_result = _choice(result["result"], "worker evidence result", frozenset({"PASS", "FAIL"}))
    phases = _array(result["phases"], "worker evidence phases", minimum=9)
    if len(phases) != len(_PHASE_NAMES):
        raise ContractError("worker evidence must contain exactly nine phases")
    observed_results = []
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
        _integer(
            phase["exit_status"],
            f"worker evidence phases[{index}].exit_status",
            -255,
            255,
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
        _choice(
            phase["cleanup_state"],
            f"worker evidence phases[{index}].cleanup_state",
            _CLEANUP_STATES,
        )
    if final_result == "PASS" and any(item != "PASS" for item in observed_results):
        raise ContractError("worker evidence cannot pass with a failed phase")
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


def validate_restream_history(value: object) -> dict:
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
    if result["schema_version"] != 1:
        raise ContractError("restream history schema_version must be 1")
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
            raise ContractError(f"contract path traverses a symlink: {path}")


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-standard JSON constant is forbidden: {value}")


def _pairs_to_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path, schema_name: str) -> dict:
    """Load one named G0 contract without following symlinks and validate it."""

    contract_path = Path(path)
    _reject_symlink(contract_path)
    try:
        text = contract_path.read_text(encoding="utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_pairs_to_object,
            parse_constant=_reject_constant,
        )
    except ContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot load {contract_path}: {error}") from error
    normalized_name = schema_name.removesuffix(".schema.json")
    validators: dict[str, Callable[[object], dict]] = {
        "run-manifest": validate_run_manifest,
        "docker-bootstrap-lock": _validate_bootstrap_lock,
        "tool-lock": validate_tool_lock,
        "worker-evidence": validate_worker_evidence,
        "restream-history": validate_restream_history,
    }
    validator = validators.get(normalized_name)
    if validator is None:
        raise ContractError(f"unknown schema name: {schema_name}")
    return validator(value)
