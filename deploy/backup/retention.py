#!/usr/bin/env python3
"""Plan and apply Z1RR RaceTime backup retention without guessing state."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence


SCHEMA = 1
BACKUP_TYPES = ("database", "media", "production-caddy-state")
Runner = Callable[..., subprocess.CompletedProcess]


class RetentionError(RuntimeError):
    """A retention input or external operation was ambiguous or unsafe."""


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp missing")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def _safe_object_name(value: Any, *, suffix: str) -> str:
    if not isinstance(value, str) or not value.startswith("production/"):
        raise ValueError("object is outside production prefix")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not value.endswith(suffix):
        raise ValueError("object name is unsafe")
    return value


def _display_name(item: Mapping[str, Any], index: int) -> str:
    try:
        manifest_name = item["object_storage"]["manifest_object"]
        filename = PurePosixPath(str(manifest_name)).name
        suffix = ".manifest.json"
        return filename[:-len(suffix)] if filename.endswith(suffix) else filename
    except (KeyError, TypeError):
        return f"unknown-{index}"


def _validate_item(
    item: Any,
    *,
    now: datetime,
    index: int,
) -> dict[str, Any]:
    if not isinstance(item, Mapping) or item.get("schema") != SCHEMA:
        raise ValueError("unsupported or missing schema")
    backup_type = item.get("type")
    if backup_type not in BACKUP_TYPES:
        raise ValueError("unknown backup type")
    completed_at = _parse_utc(item.get("completed_at"))
    if completed_at > now + timedelta(minutes=5):
        raise ValueError("completion time is in the future")
    verification = item.get("verification")
    if not isinstance(verification, Mapping):
        raise ValueError("verification missing")
    if verification.get("result") != "verified":
        raise ValueError("backup is not verified")
    verified_at = _parse_utc(verification.get("at"))
    if verified_at < completed_at - timedelta(minutes=5):
        raise ValueError("verification predates completion")

    storage = item.get("object_storage")
    if not isinstance(storage, Mapping):
        raise ValueError("object storage record missing")
    object_name = _safe_object_name(storage.get("object"), suffix=".age")
    manifest_object = _safe_object_name(
        storage.get("manifest_object"), suffix=".manifest.json"
    )

    pinned_until = None
    retention = item.get("retention")
    if retention is not None:
        if not isinstance(retention, Mapping):
            raise ValueError("retention record invalid")
        raw_pin = retention.get("pinned_until")
        if raw_pin is not None:
            pinned_until = _parse_utc(raw_pin)

    return {
        "name": _display_name(item, index),
        "type": backup_type,
        "completed_at": completed_at,
        "object": object_name,
        "manifest_object": manifest_object,
        "pinned_until": pinned_until,
    }


def _action(item: Mapping[str, Any], reason: str) -> dict[str, str]:
    return {
        "name": str(item["name"]),
        "object": str(item["object"]),
        "manifest_object": str(item["manifest_object"]),
        "reason": reason,
    }


def plan_retention(
    manifests: Iterable[Any], *, now: datetime | None = None
) -> dict[str, list[dict[str, str]]]:
    """Return explicit retain/delete/quarantine actions for manifest records."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    valid: list[dict[str, Any]] = []
    quarantine: list[dict[str, str]] = []

    for index, raw in enumerate(manifests):
        try:
            valid.append(_validate_item(raw, now=now, index=index))
        except (KeyError, TypeError, ValueError) as error:
            name = _display_name(raw, index) if isinstance(raw, Mapping) else f"unknown-{index}"
            quarantine.append(
                {
                    "name": name,
                    "object": "",
                    "manifest_object": "",
                    "reason": str(error),
                }
            )

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in valid:
        by_type[item["type"]].append(item)
    for items in by_type.values():
        items.sort(key=lambda entry: entry["completed_at"], reverse=True)

    retained: dict[tuple[str, str], str] = {}
    for backup_type, items in by_type.items():
        if not items:
            continue
        retained[(backup_type, items[0]["manifest_object"])] = "newest-verified"

        if backup_type == "production-caddy-state":
            for item in items[:3]:
                retained[(backup_type, item["manifest_object"])] = "current-plus-two-prior"
            continue

        weekly: dict[int, dict[str, Any]] = {}
        monthly: dict[tuple[int, int], dict[str, Any]] = {}
        for item in items:
            age = now - item["completed_at"]
            age_days = age.total_seconds() / 86400
            key = (backup_type, item["manifest_object"])
            if item["pinned_until"] is not None and item["pinned_until"] >= now:
                retained[key] = "explicit-pin"
            if age_days < 14:
                retained[key] = "daily-window"
            elif age_days < 91:
                bucket = int(age_days // 7)
                weekly.setdefault(bucket, item)
            elif age_days <= 365:
                month = (item["completed_at"].year, item["completed_at"].month)
                monthly.setdefault(month, item)

        for item in weekly.values():
            retained[(backup_type, item["manifest_object"])] = "weekly-window"
        for item in monthly.values():
            retained[(backup_type, item["manifest_object"])] = "monthly-window"

    keep: list[dict[str, str]] = []
    delete: list[dict[str, str]] = []
    for item in sorted(
        valid,
        key=lambda entry: (entry["type"], entry["completed_at"]),
        reverse=True,
    ):
        reason = retained.get((item["type"], item["manifest_object"]))
        if reason:
            keep.append(_action(item, reason))
        else:
            delete.append(_action(item, "expired"))

    return {
        "retain": keep,
        "delete": delete,
        "quarantine": quarantine,
    }


def _delete_command(config: Mapping[str, str], object_name: str) -> list[str]:
    namespace = config.get("namespace")
    bucket = config.get("bucket")
    if not namespace or not bucket:
        raise RetentionError("namespace and bucket are required")
    return [
        "oci",
        "os",
        "object",
        "delete",
        "--namespace",
        namespace,
        "--bucket-name",
        bucket,
        "--auth",
        "instance_principal",
        "--force",
        "--name",
        object_name,
    ]


def apply_retention(
    plan: Mapping[str, Sequence[Mapping[str, str]]],
    *,
    config: Mapping[str, str],
    apply: bool = False,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Apply only explicit delete actions; dry-run is the immutable default."""
    if not apply:
        return {"mode": "dry-run", "deleted": 0}

    deleted = 0
    for entry in plan.get("delete", ()):
        for key in ("manifest_object", "object"):
            command = _delete_command(config, entry[key])
            completed = runner(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RetentionError("Object Storage delete failed")
        deleted += 1
    return {"mode": "apply", "deleted": deleted}


def list_manifest_objects(
    *,
    config: Mapping[str, str],
    prefix: str,
    runner: Runner = subprocess.run,
) -> list[dict[str, Any]]:
    """List manifest metadata; every listing error is fatal, never empty."""
    namespace = config.get("namespace")
    bucket = config.get("bucket")
    if not namespace or not bucket or not prefix:
        raise RetentionError("namespace, bucket, and prefix are required")
    command = [
        "oci",
        "os",
        "object",
        "list",
        "--namespace",
        namespace,
        "--bucket-name",
        bucket,
        "--prefix",
        prefix,
        "--all",
        "--auth",
        "instance_principal",
        "--output",
        "json",
    ]
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RetentionError("Object Storage listing failed")
    try:
        payload = json.loads(completed.stdout)
        objects = payload["data"]
        if not isinstance(objects, list):
            raise TypeError
    except (json.JSONDecodeError, KeyError, TypeError):
        raise RetentionError("Object Storage listing was ambiguous") from None
    return [
        item
        for item in objects
        if isinstance(item, Mapping)
        and str(item.get("name", "")).endswith(".manifest.json")
    ]


def load_remote_manifests(
    *,
    config: Mapping[str, str],
    prefix: str,
    runner: Runner = subprocess.run,
) -> list[dict[str, Any]]:
    objects = list_manifest_objects(config=config, prefix=prefix, runner=runner)
    manifests: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="z1rr-retention-") as temporary:
        directory = Path(temporary)
        for index, item in enumerate(objects):
            object_name = item.get("name")
            if not isinstance(object_name, str):
                raise RetentionError("manifest listing entry was ambiguous")
            path = PurePosixPath(object_name)
            if (
                not object_name.startswith(prefix)
                or path.is_absolute()
                or ".." in path.parts
                or not object_name.endswith(".manifest.json")
            ):
                raise RetentionError("manifest object name was unsafe")
            destination = directory / f"manifest-{index}.json"
            command = [
                "oci", "os", "object", "get",
                "--namespace", str(config["namespace"]),
                "--bucket-name", str(config["bucket"]),
                "--auth", "instance_principal",
                "--name", object_name,
                "--file", str(destination),
            ]
            completed = runner(
                command, capture_output=True, text=True, check=False
            )
            if completed.returncode != 0:
                raise RetentionError("manifest download failed")
            try:
                payload = json.loads(destination.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise RetentionError("downloaded manifest was unreadable") from None
            manifests.append(payload)
    return manifests


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest-index", type=Path)
    source.add_argument("--remote", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--now", help="UTC policy evaluation time")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--namespace")
    parser.add_argument("--bucket")
    parser.add_argument("--prefix", default="production/")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config = {"namespace": args.namespace, "bucket": args.bucket}
        if args.remote:
            raw = load_remote_manifests(config=config, prefix=args.prefix)
        else:
            raw = json.loads(args.manifest_index.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise RetentionError("manifest index must be a JSON array")
        now = _parse_utc(args.now) if args.now else datetime.now(timezone.utc)
        plan = plan_retention(raw, now=now)
        quarantine_count = len(plan["quarantine"])
        if quarantine_count:
            # Ambiguous input is an alerting condition and blocks destructive
            # retention. The written plan is the quarantine record.
            execution = {
                "mode": "blocked-quarantine" if args.apply else "dry-run",
                "deleted": 0,
            }
        else:
            execution = apply_retention(
                plan, config=config, apply=args.apply
            )
        payload = {
            "schema": SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mode": execution["mode"],
            "actions": plan,
        }
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, RetentionError, ValueError) as error:
        print(f"RETENTION=FAIL {type(error).__name__}", file=sys.stderr)
        return 1
    if quarantine_count:
        print(f"RETENTION=FAIL quarantined={quarantine_count}", file=sys.stderr)
        return 2
    print(f"RETENTION=PASS mode={execution['mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
