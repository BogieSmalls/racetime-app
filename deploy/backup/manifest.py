#!/usr/bin/env python3
"""Create and validate secret-free Z1RR backup manifests."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Mapping, Sequence


TOP_LEVEL = {
    "schema",
    "type",
    "started_at",
    "completed_at",
    "release_sha",
    "database",
    "source",
    "plaintext",
    "encrypted",
    "encryption",
    "verification",
    "object_storage",
    "tools",
    "retention",
}
TYPES = {"database", "media", "production-caddy-state"}
HASH = re.compile(r"^[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,254}$")
FORBIDDEN_KEY_PARTS = ("password", "secret", "private_key", "client_secret", "token")


class ManifestError(ValueError):
    """The manifest is incomplete, ambiguous, or unsafe."""


def _utc(value: Any, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value:
        raise ManifestError("timestamp missing")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise ManifestError("timestamp invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ManifestError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _exact_mapping(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ManifestError(f"{label} fields invalid")
    return value


def _positive_integer(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{label} must be positive")


def _safe_text(value: Any, label: str, *, maximum: int = 255) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ManifestError(f"{label} invalid")
    if any(ord(character) < 32 for character in value):
        raise ManifestError(f"{label} contains control characters")
    return value


def _safe_object(value: Any, suffix: str) -> str:
    value = _safe_text(value, "object")
    path = PurePosixPath(value)
    if (
        not value.startswith("production/")
        or path.is_absolute()
        or ".." in path.parts
        or not value.endswith(suffix)
    ):
        raise ManifestError("object outside production prefix")
    return value


def _scan_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                raise ManifestError("credential-bearing field forbidden")
            _scan_keys(child)
    elif isinstance(value, list):
        for child in value:
            _scan_keys(child)


def validate_manifest(manifest: Any, *, require_verified: bool = False) -> None:
    if not isinstance(manifest, Mapping) or set(manifest) != TOP_LEVEL:
        raise ManifestError("top-level fields invalid")
    _scan_keys(manifest)
    if manifest["schema"] != 1 or manifest["type"] not in TYPES:
        raise ManifestError("schema or type invalid")
    if not SHA.fullmatch(str(manifest["release_sha"])):
        raise ManifestError("release SHA invalid")
    started = _utc(manifest["started_at"])
    completed = _utc(manifest["completed_at"])
    if completed < started:
        raise ManifestError("completion predates start")

    database = manifest["database"]
    if manifest["type"] == "database":
        database = _exact_mapping(database, {"schema", "migrations"}, "database")
        _safe_text(database["schema"], "database schema", maximum=128)
        migrations = database["migrations"]
        if not isinstance(migrations, list) or not migrations or len(set(migrations)) != len(migrations):
            raise ManifestError("database migrations invalid")
        for migration in migrations:
            _safe_text(migration, "migration")
    elif database is not None:
        raise ManifestError("database metadata forbidden for non-database backup")

    source = _exact_mapping(
        manifest["source"], {"volume", "generation", "bytes", "entries"}, "source"
    )
    volume = _safe_text(source["volume"], "source volume")
    if "qualification" in volume.lower() or not SAFE_NAME.fullmatch(volume):
        raise ManifestError("source volume is ineligible")
    _safe_text(source["generation"], "source generation")
    _positive_integer(source["bytes"], "source bytes")
    _positive_integer(source["entries"], "source entries")

    for label in ("plaintext", "encrypted"):
        record = _exact_mapping(manifest[label], {"sha256", "bytes"}, label)
        if not HASH.fullmatch(str(record["sha256"])):
            raise ManifestError(f"{label} hash invalid")
        _positive_integer(record["bytes"], f"{label} bytes")

    encryption = _exact_mapping(
        manifest["encryption"], {"algorithm", "recipient", "key_id"}, "encryption"
    )
    if encryption["algorithm"] != "age":
        raise ManifestError("encryption algorithm invalid")
    _safe_text(encryption["recipient"], "recipient")
    _safe_text(encryption["key_id"], "key id", maximum=128)

    verification = _exact_mapping(
        manifest["verification"], {"result", "at"}, "verification"
    )
    if verification["result"] not in {"pending", "verified", "failed"}:
        raise ManifestError("verification result invalid")
    verified_at = _utc(verification["at"], nullable=True)
    if verification["result"] == "verified" and verified_at is None:
        raise ManifestError("verified time missing")
    if verified_at is not None and verified_at < completed:
        raise ManifestError("verification predates completion")
    if verification["result"] != "verified" and verified_at is not None:
        raise ManifestError("non-verified manifest has verified time")
    if require_verified and verification["result"] != "verified":
        raise ManifestError("manifest is not verified")

    storage = _exact_mapping(
        manifest["object_storage"],
        {"namespace", "bucket", "object", "manifest_object"},
        "object storage",
    )
    _safe_text(storage["namespace"], "namespace")
    _safe_text(storage["bucket"], "bucket")
    _safe_object(storage["object"], ".age")
    _safe_object(storage["manifest_object"], ".manifest.json")

    tools = manifest["tools"]
    if not isinstance(tools, Mapping) or not {"age", "zstd", "oci", "docker"} <= set(tools):
        raise ManifestError("tool versions incomplete")
    for key, version in tools.items():
        _safe_text(key, "tool name", maximum=64)
        _safe_text(version, "tool version")

    retention = _exact_mapping(
        manifest["retention"], {"reason", "pinned_until"}, "retention"
    )
    _safe_text(retention["reason"], "retention reason", maximum=128)
    _utc(retention["pinned_until"], nullable=True)


def example_manifest() -> dict[str, Any]:
    return {
        "schema": 1,
        "type": "database",
        "started_at": "2026-08-24T00:00:00Z",
        "completed_at": "2026-08-24T00:01:00Z",
        "release_sha": "2" * 40,
        "database": {"schema": "racetime", "migrations": ["racetime.0082_externalidentity"]},
        "source": {"volume": "z1rr-racetime-production-db", "generation": "run-1", "bytes": 10, "entries": 1},
        "plaintext": {"sha256": "a" * 64, "bytes": 10},
        "encrypted": {"sha256": "b" * 64, "bytes": 12},
        "encryption": {"algorithm": "age", "recipient": "age1example", "key_id": "key-v1"},
        "verification": {"result": "verified", "at": "2026-08-24T00:02:00Z"},
        "object_storage": {
            "namespace": "example",
            "bucket": "backups",
            "object": "production/database/run-1.age",
            "manifest_object": "production/database/run-1.manifest.json",
        },
        "tools": {"age": "1", "zstd": "1", "oci": "1", "docker": "1"},
        "retention": {"reason": "scheduled", "pinned_until": None},
    }


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ManifestError("manifest unreadable") from None
    return value


def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _migrations(path: Path | None) -> list[str]:
    if path is None:
        return []
    values = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if value.startswith("[X]"):
            value = value[3:].strip()
        if value:
            values.append(value)
    return sorted(set(values))


def _create(args: argparse.Namespace) -> None:
    tools = {}
    for value in args.tool:
        if "=" not in value:
            raise ManifestError("tool must be name=version")
        key, version = value.split("=", 1)
        tools[key] = version
    database = None
    if args.type == "database":
        database = {"schema": args.db_schema, "migrations": _migrations(args.migrations_file)}
    manifest = {
        "schema": 1,
        "type": args.type,
        "started_at": args.started_at,
        "completed_at": args.completed_at,
        "release_sha": args.release_sha,
        "database": database,
        "source": {"volume": args.source_volume, "generation": args.generation, "bytes": args.source_bytes, "entries": args.source_entries},
        "plaintext": {"sha256": args.plaintext_sha, "bytes": args.plaintext_bytes},
        "encrypted": {"sha256": args.encrypted_sha, "bytes": args.encrypted_bytes},
        "encryption": {"algorithm": "age", "recipient": args.recipient, "key_id": args.key_id},
        "verification": {"result": "pending", "at": None},
        "object_storage": {"namespace": args.namespace, "bucket": args.bucket, "object": args.object, "manifest_object": args.manifest_object},
        "tools": tools,
        "retention": {"reason": args.reason, "pinned_until": args.pinned_until},
    }
    validate_manifest(manifest)
    _write_atomic(args.output, manifest)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    for name in ("type", "started-at", "completed-at", "release-sha", "source-volume", "generation", "plaintext-sha", "encrypted-sha", "recipient", "key-id", "namespace", "bucket", "object", "manifest-object", "reason"):
        create.add_argument(f"--{name}", required=True)
    for name in ("source-bytes", "source-entries", "plaintext-bytes", "encrypted-bytes"):
        create.add_argument(f"--{name}", required=True, type=int)
    create.add_argument("--db-schema")
    create.add_argument("--migrations-file", type=Path)
    create.add_argument("--pinned-until")
    create.add_argument("--tool", action="append", default=[])
    create.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--require-verified", action="store_true")
    mark = subparsers.add_parser("mark-verified")
    mark.add_argument("--manifest", type=Path, required=True)
    mark.add_argument("--verified-at", required=True)
    get = subparsers.add_parser("get")
    get.add_argument("--manifest", type=Path, required=True)
    get.add_argument("--field", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            _create(args)
        elif args.command == "validate":
            validate_manifest(_read(args.manifest), require_verified=args.require_verified)
        elif args.command == "mark-verified":
            manifest = _read(args.manifest)
            validate_manifest(manifest)
            if manifest["verification"]["result"] != "pending":
                raise ManifestError("manifest is not pending")
            _utc(args.verified_at)
            manifest["verification"] = {"result": "verified", "at": args.verified_at}
            validate_manifest(manifest, require_verified=True)
            _write_atomic(args.manifest, manifest)
        else:
            manifest = _read(args.manifest)
            validate_manifest(manifest)
            value: Any = manifest
            for segment in args.field.split("."):
                value = value[segment]
            if isinstance(value, (dict, list)):
                print(json.dumps(value, separators=(",", ":")))
            elif value is None:
                print("null")
            else:
                print(value)
    except (KeyError, OSError, ManifestError) as error:
        print(f"MANIFEST=FAIL {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
