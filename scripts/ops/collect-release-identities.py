#!/usr/bin/env python3
"""Collect immutable, path-free release identities for all Z1RR components."""

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


class ReleaseIdentityError(ValueError):
    """The candidate is not a complete, immutable release set."""


COMPONENTS = {"racetime", "restream", "ttpbot", "livesplit"}
TOP_LEVEL_FIELDS = {"schema_version", "expected_version", "components"}
COMPONENT_FIELDS = {
    "racetime": {
        "repository", "expected_branch", "version_files", "release_identity",
        "migration_directory", "config_schema",
    },
    "restream": {"repository", "expected_branch", "version_files", "build_artifact"},
    "ttpbot": {"repository", "expected_branch", "version_files", "lock_file"},
    "livesplit": {
        "repository", "expected_branch", "version_files", "dll", "package",
        "update_manifest", "signature_metadata",
    },
}
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
MIGRATION = re.compile(r"^(\d{4})_([a-z0-9_]+)\.py$")
SAFE_KEY_ID = re.compile(r"^[A-Za-z0-9._-]{16,64}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
SECRET_PATH = re.compile(
    r"(?:^|[._-])(?:env|credential|password|secret|token|terraform[._-]?state)(?:$|[._-])",
    re.IGNORECASE,
)
MAX_JSON_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024


def _object(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ReleaseIdentityError(f"{label} fields are invalid")
    return value


def _read_json(path: Path, label: str):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_JSON_BYTES:
        raise ReleaseIdentityError(f"{label} is missing or unsafe")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseIdentityError(f"{label} is not valid UTF-8 JSON") from exc


def _safe_path_text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ReleaseIdentityError(f"{label} path is invalid")
    parts = Path(value).parts
    if any(SECRET_PATH.search(part) for part in parts):
        raise ReleaseIdentityError(f"{label} uses a secret-like path")
    return value


def _regular_file(path: Path, label: str):
    if (
        not path.is_file()
        or path.is_symlink()
        or path.stat().st_size > MAX_ARTIFACT_BYTES
    ):
        raise ReleaseIdentityError(f"{label} is missing or unsafe")
    return path


def _repo_file(repository: Path, value, label):
    relative = Path(_safe_path_text(value, label))
    if relative.is_absolute() or ".." in relative.parts:
        raise ReleaseIdentityError(f"{label} must be repository-relative")
    target = (repository / relative).resolve()
    try:
        target.relative_to(repository)
    except ValueError as exc:
        raise ReleaseIdentityError(f"{label} escapes its repository") from exc
    return _regular_file(target, label)


def _external_file(config_directory: Path, value, label):
    declared = Path(_safe_path_text(value, label))
    target = declared if declared.is_absolute() else config_directory / declared
    return _regular_file(target.resolve(), label)


def _sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repository: Path, *arguments):
    try:
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseIdentityError("repository identity cannot be read") from exc


def _repository_identity(component, config):
    repository_text = _safe_path_text(config["repository"], f"{component}.repository")
    repository = Path(repository_text).resolve()
    if not repository.is_dir() or repository.is_symlink():
        raise ReleaseIdentityError(f"{component} repository is missing or unsafe")
    branch = _git(repository, "branch", "--show-current")
    expected_branch = config["expected_branch"]
    if not isinstance(expected_branch, str) or branch != expected_branch:
        raise ReleaseIdentityError(f"{component} branch does not match")
    if _git(repository, "status", "--porcelain", "--untracked-files=all"):
        raise ReleaseIdentityError(f"{component} repository is dirty")
    commit = _git(repository, "rev-parse", "HEAD")
    if not COMMIT.fullmatch(commit):
        raise ReleaseIdentityError(f"{component} commit is invalid")
    return repository, commit


def _verify_versions(component, repository, files, expected):
    if not isinstance(files, list) or not files:
        raise ReleaseIdentityError(f"{component} version_files are invalid")
    versions = []
    for index, value in enumerate(files):
        path = _repo_file(repository, value, f"{component}.version_files[{index}]")
        try:
            versions.append(path.read_text(encoding="utf-8").strip())
        except UnicodeDecodeError as exc:
            raise ReleaseIdentityError(f"{component} version is not UTF-8") from exc
    if any(version != expected for version in versions):
        raise ReleaseIdentityError(f"{component} version does not match")


def _racetime(config, repository, commit, config_directory):
    identity_path = _external_file(
        config_directory, config["release_identity"], "racetime.release_identity"
    )
    identity = _read_json(identity_path, "racetime release identity")
    identity = _object(identity, {"schema_version", "source_commit", "images"}, "release identity")
    if identity["schema_version"] != 1 or identity["source_commit"] != commit:
        raise ReleaseIdentityError("RaceTime release identity names the wrong source commit")
    images = _object(identity["images"], {"web", "racebot"}, "release images")
    values = {}
    for image in ("web", "racebot"):
        record = _object(images[image], {"manifest_digest"}, f"{image} image")
        digest = record["manifest_digest"]
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ReleaseIdentityError(f"{image} image is not an immutable manifest digest")
        values[f"{image}_image_digest"] = digest

    migration_text = _safe_path_text(config["migration_directory"], "migration_directory")
    migration_relative = Path(migration_text)
    if migration_relative.is_absolute() or ".." in migration_relative.parts:
        raise ReleaseIdentityError("migration directory must be repository-relative")
    migration_directory = (repository / migration_relative).resolve()
    try:
        migration_directory.relative_to(repository)
    except ValueError as exc:
        raise ReleaseIdentityError("migration directory escapes its repository") from exc
    if not migration_directory.is_dir() or migration_directory.is_symlink():
        raise ReleaseIdentityError("migration directory is missing or unsafe")
    migrations = []
    for path in migration_directory.iterdir():
        match = MIGRATION.fullmatch(path.name)
        if match and path.is_file() and not path.is_symlink():
            migrations.append((int(match.group(1)), path.stem))
    if not migrations:
        raise ReleaseIdentityError("no migration leaf can be identified")
    maximum = max(item[0] for item in migrations)
    leaves = sorted(name for number, name in migrations if number == maximum)
    if len(leaves) != 1:
        raise ReleaseIdentityError("migration leaf is ambiguous")
    schema = _repo_file(repository, config["config_schema"], "racetime.config_schema")
    return {
        "commit": commit,
        "version": None,
        "migration_leaf": leaves[0],
        **values,
        "config_schema_sha256": _sha256(schema),
    }


def _restream(config, repository, commit):
    artifact = _repo_file(repository, config["build_artifact"], "restream.build_artifact")
    return {"commit": commit, "version": None, "build_sha256": _sha256(artifact)}


def _ttpbot(config, repository, commit):
    lock_file = _repo_file(repository, config["lock_file"], "ttpbot.lock_file")
    return {"commit": commit, "version": None, "lock_sha256": _sha256(lock_file)}


def _livesplit(config, repository, commit):
    dll = _repo_file(repository, config["dll"], "livesplit.dll")
    package = _repo_file(repository, config["package"], "livesplit.package")
    update = _repo_file(repository, config["update_manifest"], "livesplit.update_manifest")
    signature_path = _repo_file(
        repository, config["signature_metadata"], "livesplit.signature_metadata"
    )
    signature = _read_json(signature_path, "LiveSplit signature metadata")
    signature = _object(signature, {"schema_version", "key_id"}, "signature metadata")
    key_id = signature["key_id"]
    if signature["schema_version"] != 1 or not isinstance(key_id, str) or not SAFE_KEY_ID.fullmatch(key_id):
        raise ReleaseIdentityError("LiveSplit signature metadata is invalid")
    return {
        "commit": commit,
        "version": None,
        "dll_sha256": _sha256(dll),
        "package_sha256": _sha256(package),
        "update_manifest_sha256": _sha256(update),
        "signature_metadata_sha256": _sha256(signature_path),
        "signature_key_id": key_id,
    }


def collect_release_identities(config_path):
    path = Path(config_path).resolve()
    config = _read_json(path, "release path configuration")
    config = _object(config, TOP_LEVEL_FIELDS, "release path configuration")
    expected_version = config["expected_version"]
    if config["schema_version"] != 1 or not isinstance(expected_version, str) or not VERSION.fullmatch(expected_version):
        raise ReleaseIdentityError("release path configuration version is invalid")
    components = config["components"]
    if not isinstance(components, dict) or set(components) != COMPONENTS:
        raise ReleaseIdentityError("release path configuration must name exactly four components")
    output = {
        "schema_version": 1,
        "collected_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "expected_version": expected_version,
        "components": {},
    }
    collectors = {
        "racetime": lambda c, r, h: _racetime(c, r, h, path.parent),
        "restream": _restream,
        "ttpbot": _ttpbot,
        "livesplit": _livesplit,
    }
    for component in sorted(COMPONENTS):
        component_config = _object(components[component], COMPONENT_FIELDS[component], component)
        repository, commit = _repository_identity(component, component_config)
        _verify_versions(
            component, repository, component_config["version_files"], expected_version
        )
        identity = collectors[component](component_config, repository, commit)
        identity["version"] = expected_version
        output["components"][component] = identity
    return output


def _atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as destination:
            json.dump(value, destination, indent=2, sort_keys=True)
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    try:
        identities = collect_release_identities(arguments.config)
        _atomic_json(Path(arguments.output).resolve(), identities)
    except ReleaseIdentityError as exc:
        sys.stderr.write(f"RELEASE_IDENTITIES=FAIL code={type(exc).__name__}\n")
        return 1
    print(f"RELEASE_IDENTITIES=PASS components={len(identities['components'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
