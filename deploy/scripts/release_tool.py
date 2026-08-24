#!/usr/bin/env python3
"""Validate releases and maintain secret-free deployment records."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence


TOP_LEVEL = {
    "schema",
    "release_sha",
    "generated_at",
    "images",
    "migrations",
    "config_schema_version",
    "minimum_rollback_digest",
    "smoke_version",
}
IMAGE_KEYS = {"repository", "digest", "platforms"}
PLATFORMS = {"linux/arm64", "linux/amd64"}
MIGRATION_KEYS = {
    "from",
    "to",
    "strategy",
    "rollback_class",
    "reverse_target",
    "forward_fix_release",
}
RECORD_KEYS = {
    "schema",
    "manifest",
    "manifest_sha256",
    "promoted_at",
    "actor",
    "emergency_change_id",
}
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
REPOSITORY = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+$"
)
MIGRATION = re.compile(r"^[a-z][a-z0-9_]*\.[0-9]{4}_[a-z0-9_]+$")
ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{2,127}$")
EMERGENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$")
FORBIDDEN_KEY_PARTS = (
    "password",
    "secret",
    "private_key",
    "client_secret",
    "token",
    "cookie",
)


class ReleaseError(ValueError):
    """A release or deployment record is incomplete or unsafe."""


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ReleaseError("timestamp missing")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise ReleaseError("timestamp invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReleaseError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _scan_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                raise ReleaseError("credential-bearing field forbidden")
            _scan_keys(child)
    elif isinstance(value, list):
        for child in value:
            _scan_keys(child)


def _exact(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ReleaseError(f"{label} fields invalid")
    return value


def _validate_image(value: Any, label: str) -> None:
    image = _exact(value, IMAGE_KEYS, label)
    repository = image["repository"]
    if (
        not isinstance(repository, str)
        or not REPOSITORY.fullmatch(repository)
        or ".." in repository
        or "@" in repository
    ):
        raise ReleaseError(f"{label} repository invalid")
    if not DIGEST.fullmatch(str(image["digest"])):
        raise ReleaseError(f"{label} digest invalid")
    platforms = _exact(image["platforms"], PLATFORMS, f"{label} platforms")
    for platform_digest in platforms.values():
        if not DIGEST.fullmatch(str(platform_digest)):
            raise ReleaseError(f"{label} platform digest invalid")


def validate_manifest(manifest: Any) -> None:
    manifest = _exact(manifest, TOP_LEVEL, "release")
    _scan_keys(manifest)
    if manifest["schema"] != 1:
        raise ReleaseError("release schema invalid")
    if not SHA.fullmatch(str(manifest["release_sha"])):
        raise ReleaseError("release SHA invalid")
    _utc(manifest["generated_at"])

    images = _exact(
        manifest["images"], {"application", "maintenance"}, "images"
    )
    _validate_image(images["application"], "application image")
    _validate_image(images["maintenance"], "maintenance image")

    migrations = _exact(manifest["migrations"], MIGRATION_KEYS, "migrations")
    for name in ("from", "to"):
        if not MIGRATION.fullmatch(str(migrations[name])):
            raise ReleaseError(f"migration {name} invalid")
    strategy = migrations["strategy"]
    if strategy not in {"none", "expand", "migrate", "contract"}:
        raise ReleaseError("migration strategy invalid")
    if strategy == "none" and migrations["from"] != migrations["to"]:
        raise ReleaseError("no-migration release changes migration ceiling")

    rollback_class = migrations["rollback_class"]
    reverse_target = migrations["reverse_target"]
    forward_fix = migrations["forward_fix_release"]
    if rollback_class == "code-only":
        if reverse_target is not None or forward_fix is not None:
            raise ReleaseError("code-only rollback has incompatible target")
    elif rollback_class == "forward-fix":
        if reverse_target is not None or not SHA.fullmatch(str(forward_fix)):
            raise ReleaseError("forward-fix release target invalid")
    elif rollback_class == "reversible":
        if not MIGRATION.fullmatch(str(reverse_target)) or forward_fix is not None:
            raise ReleaseError("reversible migration target invalid")
    else:
        raise ReleaseError("rollback class invalid")

    if manifest["config_schema_version"] != 1:
        raise ReleaseError("config schema version unsupported")
    if not DIGEST.fullmatch(str(manifest["minimum_rollback_digest"])):
        raise ReleaseError("minimum rollback digest invalid")
    if manifest["smoke_version"] != 1:
        raise ReleaseError("smoke version unsupported")


def canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_record(record: Any) -> None:
    record = _exact(record, RECORD_KEYS, "release record")
    if record["schema"] != 1:
        raise ReleaseError("release record schema invalid")
    validate_manifest(record["manifest"])
    if record["manifest_sha256"] != canonical_hash(record["manifest"]):
        raise ReleaseError("release record manifest hash mismatch")
    _utc(record["promoted_at"])
    if not ACTOR.fullmatch(str(record["actor"])):
        raise ReleaseError("release record actor invalid")
    emergency = record["emergency_change_id"]
    if emergency is not None and not EMERGENCY.fullmatch(str(emergency)):
        raise ReleaseError("release record emergency ID invalid")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ReleaseError("JSON record unreadable") from None
    if not isinstance(value, dict):
        raise ReleaseError("JSON record must be an object")
    return value


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    if path.is_symlink():
        raise ReleaseError("refusing symlink record target")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _field(value: Any, dotted: str) -> Any:
    for segment in dotted.split("."):
        if not segment or not isinstance(value, Mapping) or segment not in value:
            raise ReleaseError("field unavailable")
        value = value[segment]
    return value


def _print_value(value: Any) -> None:
    if isinstance(value, (dict, list)):
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))
    elif value is None:
        print("null")
    else:
        print(value)


def _audit(args: argparse.Namespace) -> None:
    if not ACTOR.fullmatch(args.actor):
        raise ReleaseError("audit actor invalid")
    if not SHA.fullmatch(args.release_sha):
        raise ReleaseError("audit release SHA invalid")
    if args.emergency_change_id and not EMERGENCY.fullmatch(
        args.emergency_change_id
    ):
        raise ReleaseError("audit emergency ID invalid")
    if args.environment not in {"integration", "production"}:
        raise ReleaseError("audit environment invalid")
    if args.status not in {"start", "pass", "fail", "skipped"}:
        raise ReleaseError("audit status invalid")
    if not re.fullmatch(r"^[a-z][a-z0-9_]{1,63}$", args.stage):
        raise ReleaseError("audit stage invalid")

    entry = {
        "schema": 1,
        "action": args.action,
        "release_sha": args.release_sha,
        "timestamp": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "stage": args.stage,
        "status": args.status,
        "actor": args.actor,
        "environment": args.environment,
        "emergency_change_id": args.emergency_change_id,
    }
    path = args.log
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ReleaseError("refusing symlink audit target")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(
            descriptor,
            (
                json.dumps(entry, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("utf-8"),
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _promote(args: argparse.Namespace) -> None:
    manifest = read_json(args.manifest)
    validate_manifest(manifest)
    if not ACTOR.fullmatch(args.actor):
        raise ReleaseError("promotion actor invalid")
    if args.emergency_change_id and not EMERGENCY.fullmatch(
        args.emergency_change_id
    ):
        raise ReleaseError("promotion emergency ID invalid")

    if args.current.exists():
        current = read_json(args.current)
        validate_record(current)
        _atomic_write(args.previous, current)
    record = {
        "schema": 1,
        "manifest": manifest,
        "manifest_sha256": canonical_hash(manifest),
        "promoted_at": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "actor": args.actor,
        "emergency_change_id": args.emergency_change_id,
    }
    validate_record(record)
    _atomic_write(args.current, record)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", required=True, type=Path)

    get = subparsers.add_parser("get")
    get.add_argument("--manifest", required=True, type=Path)
    get.add_argument("--field", required=True)

    record_get = subparsers.add_parser("record-get")
    record_get.add_argument("--record", required=True, type=Path)
    record_get.add_argument("--field", required=True)

    audit = subparsers.add_parser("audit")
    audit.add_argument("--log", required=True, type=Path)
    audit.add_argument("--action", choices=("deploy", "rollback"), required=True)
    audit.add_argument("--release-sha", required=True)
    audit.add_argument("--stage", required=True)
    audit.add_argument("--status", required=True)
    audit.add_argument("--actor", required=True)
    audit.add_argument("--environment", required=True)
    audit.add_argument("--emergency-change-id")

    promote = subparsers.add_parser("promote")
    promote.add_argument("--manifest", required=True, type=Path)
    promote.add_argument("--current", required=True, type=Path)
    promote.add_argument("--previous", required=True, type=Path)
    promote.add_argument("--actor", required=True)
    promote.add_argument("--emergency-change-id")

    pin = subparsers.add_parser("pin-until")
    pin.add_argument("--days", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            validate_manifest(read_json(args.manifest))
        elif args.command == "get":
            manifest = read_json(args.manifest)
            validate_manifest(manifest)
            _print_value(_field(manifest, args.field))
        elif args.command == "record-get":
            record = read_json(args.record)
            validate_record(record)
            _print_value(_field(record, args.field))
        elif args.command == "audit":
            _audit(args)
        elif args.command == "promote":
            _promote(args)
        else:
            if not 1 <= args.days <= 365:
                raise ReleaseError("pin interval invalid")
            print(
                (
                    datetime.now(timezone.utc) + timedelta(days=args.days)
                ).isoformat().replace("+00:00", "Z")
            )
    except (OSError, ReleaseError) as error:
        print(f"RELEASE_TOOL=FAIL {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
