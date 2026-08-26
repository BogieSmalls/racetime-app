#!/usr/bin/env python3
"""Prepare exact, local-only source and artifact custody for one G0 run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

try:
    from scripts.g0.contracts import (
        ContractError,
        load_json,
        load_run_manifest_with_sha256,
        safe_relative_path,
        safe_sha256,
        validate_run_manifest,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.g0.contracts import (
        ContractError,
        load_json,
        load_run_manifest_with_sha256,
        safe_relative_path,
        safe_sha256,
        validate_run_manifest,
    )


class PreparationError(ValueError):
    """An input cannot safely enter the G0 transfer boundary."""


_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_SECRET_PATH = re.compile(
    r"(?:^|[._-])(?:\.env|credential|password|secret|token|private[._-]?key|"
    r"terraform[._-]?tfstate)(?:$|[._-])",
    re.IGNORECASE,
)
_SECRET_BYTES = re.compile(
    rb"(?:-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|"
    rb"(?:password|secret|token|credential|api[_.-]?key|private[_.-]?key)"
    rb"[ \t]*[:=][ \t]*(?!<redacted>|\$\{|example(?:$|[._-])|placeholder|changeme)"
    rb"[^\r\n]{4,})",
    re.IGNORECASE,
)
_MAX_JSON_BYTES = 1_048_576
_MAX_COMMAND_BYTES = 16 * 1_048_576
_MAX_FILE_BYTES = 64 * 1_048_576
_MAX_TOTAL_BYTES = 1_073_741_824
_MAX_TRACKED_FILES = 100_000
_COMMAND_SECONDS = 60


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _has_symlink_or_reparse(path: Path, stop: Path | None = None) -> bool:
    candidate = path
    while True:
        try:
            metadata = os.lstat(candidate)
        except FileNotFoundError:
            pass
        except OSError:
            return True
        else:
            if stat.S_ISLNK(metadata.st_mode) or (
                getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ):
                return True
        if candidate == stop or candidate.parent == candidate:
            return False
        candidate = candidate.parent


def _require_boundary(path: Path, label: str, *, root: Path | None = None, file: bool = False) -> None:
    if _has_symlink_or_reparse(path, root):
        raise PreparationError(f"{label} crosses a symlink or reparse boundary")
    if file:
        if not path.is_file():
            raise PreparationError(f"{label} is not a regular file")
    elif not path.is_dir():
        raise PreparationError(f"{label} is not a directory")
    if root is not None and not _within(path, root):
        raise PreparationError(f"{label} is outside the workspace")


def _run_git(
    repository: Path,
    arguments: tuple[str, ...],
    *,
    deadline: float,
    output_limit: int = _MAX_COMMAND_BYTES,
) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PreparationError("repository command exceeded its bounded deadline")
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen(
                ("git", "-C", str(repository), *arguments),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                close_fds=True,
                env={key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR"}},
            )
            try:
                return_code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise PreparationError("repository command exceeded its bounded deadline") from None
        except OSError as error:
            raise PreparationError("repository command could not run") from error
        stdout_size = stdout.tell()
        stderr_size = stderr.tell()
        if stdout_size > output_limit or stderr_size > _MAX_COMMAND_BYTES:
            raise PreparationError("repository command output exceeded its byte limit")
        if return_code != 0:
            raise PreparationError("repository command failed")
        stdout.seek(0)
        return stdout.read()


def _git_text(repository: Path, *arguments: str, deadline: float) -> str:
    try:
        return _run_git(repository, tuple(arguments), deadline=deadline).decode("utf-8").rstrip("\r\n")
    except UnicodeError as error:
        raise PreparationError("repository command returned non-UTF-8 metadata") from error


def _load_plain_json(path: Path, label: str) -> dict:
    _require_boundary(path, label, file=True)
    if path.stat().st_size > _MAX_JSON_BYTES:
        raise PreparationError(f"{label} exceeds its byte limit")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        raise PreparationError(f"{label} is not safe JSON") from error
    if type(value) is not dict:
        raise PreparationError(f"{label} must be an object")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _repository_status(repository: Path, deadline: float) -> bytes:
    return _run_git(
        repository,
        ("status", "--porcelain=v1", "--ignored=matching", "--untracked-files=all"),
        deadline=deadline,
    )


def _inspect_repository(repository: Path, source: dict, deadline: float) -> tuple[bytes, list[dict]]:
    _require_boundary(repository, f"{source['name']} repository", root=repository.parent)
    if _git_text(repository, "rev-parse", "--is-inside-work-tree", deadline=deadline) != "true":
        raise PreparationError(f"{source['name']} repository is invalid")
    if _git_text(repository, "rev-parse", "--is-shallow-repository", deadline=deadline) != "false":
        raise PreparationError(f"{source['name']} repository is shallow")
    status = _repository_status(repository, deadline)
    if status:
        raise PreparationError(f"{source['name']} repository is not clean")
    branch = _git_text(repository, "symbolic-ref", "--quiet", "--short", "HEAD", deadline=deadline)
    if branch != source["branch"]:
        raise PreparationError(f"{source['name']} branch does not match")
    commit = _git_text(repository, "rev-parse", "--verify", "HEAD^{commit}", deadline=deadline)
    if commit != source["commit"]:
        raise PreparationError(f"{source['name']} commit does not match")
    return status, _tree_entries(repository, commit, deadline)


def _tree_entries(repository: Path, commit: str, deadline: float) -> list[dict]:
    raw = _run_git(
        repository,
        ("ls-tree", "-r", "-z", "--full-tree", "-l", commit),
        deadline=deadline,
        output_limit=_MAX_COMMAND_BYTES,
    )
    records = raw.split(b"\0")
    if records[-1:] == [b""]:
        records.pop()
    if len(records) > _MAX_TRACKED_FILES:
        raise PreparationError("repository has too many tracked files")
    entries: list[dict] = []
    total_size = 0
    for record in records:
        try:
            header, raw_path = record.split(b"\t", 1)
            mode, kind, oid, raw_size = header.split(b" ", 3)
            path = raw_path.decode("utf-8")
            size = int(raw_size)
        except (ValueError, UnicodeError) as error:
            raise PreparationError("repository tree metadata is unsafe") from error
        if mode not in {b"100644", b"100755"} or kind != b"blob":
            raise PreparationError("repository tree contains a symlink or unsupported entry")
        normalized = PurePosixPath(path)
        if normalized.is_absolute() or str(normalized) != path or any(part in {"", ".", ".."} for part in normalized.parts):
            raise PreparationError("repository tree contains an unsafe path")
        if size < 0 or size > _MAX_FILE_BYTES:
            raise PreparationError("repository file exceeds its byte limit")
        total_size += size
        if total_size > _MAX_TOTAL_BYTES:
            raise PreparationError("repository tree exceeds its byte limit")
        oid_text = oid.decode("ascii")
        if not re.fullmatch(r"[0-9a-f]{40,64}", oid_text):
            raise PreparationError("repository tree object identity is unsafe")
        entries.append({"path": path, "mode": mode.decode("ascii"), "oid": oid_text, "size": size})
    entries.sort(key=lambda item: item["path"].encode("utf-8"))
    return entries


def _create_bundle(repository: Path, target: Path, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PreparationError("bundle creation exceeded its bounded deadline")
    try:
        result = subprocess.run(
            ("git", "-C", str(repository), "bundle", "create", str(target), "--all"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=False,
            timeout=remaining,
            env={key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR"}},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreparationError("bundle creation failed") from error
    if result.returncode != 0 or not target.is_file() or target.is_symlink():
        raise PreparationError("bundle creation failed")


def _repository_refs(repository: Path, deadline: float) -> list[str]:
    lines = _git_text(repository, "show-ref", "--head", deadline=deadline).splitlines()
    refs = []
    for line in lines:
        parts = line.split(" ", 1)
        if len(parts) != 2 or _COMMIT.fullmatch(parts[0]) is None:
            raise PreparationError("repository refs are unsafe")
        refs.append(line)
    return sorted(set(refs))


def _bundle_refs(repository: Path, bundle: Path, deadline: float) -> list[str]:
    lines = _git_text(repository, "bundle", "list-heads", str(bundle), deadline=deadline).splitlines()
    refs = []
    for line in lines:
        parts = line.split(" ", 1)
        if len(parts) != 2 or _COMMIT.fullmatch(parts[0]) is None:
            raise PreparationError("bundle refs are unsafe")
        refs.append(line)
    return sorted(set(refs))


def _verify_bundle(repository: Path, bundle: Path, commit: str, deadline: float) -> list[str]:
    _run_git(repository, ("bundle", "verify", str(bundle)), deadline=deadline)
    expected = _repository_refs(repository, deadline)
    actual = _bundle_refs(repository, bundle, deadline)
    if actual != expected:
        raise PreparationError("bundle refs do not match the repository")
    if not any(line.startswith(commit + " ") for line in actual):
        raise PreparationError("bundle lacks the declared commit ref")
    return actual


def _blob(repository: Path, oid: str, expected_size: int, deadline: float) -> bytes:
    value = _run_git(repository, ("cat-file", "blob", oid), deadline=deadline, output_limit=_MAX_FILE_BYTES)
    if len(value) != expected_size:
        raise PreparationError("repository blob size does not match its tree")
    return value


def _contains_forbidden_secret(value: bytes) -> bool:
    return _SECRET_BYTES.search(value) is not None


def _create_archive(repository: Path, commit: str, entries: list[dict], target: Path, deadline: float) -> None:
    del commit
    with tarfile.open(target, "w", format=tarfile.USTAR_FORMAT) as stream:
        for entry in entries:
            value = _blob(repository, entry["oid"], entry["size"], deadline)
            if _contains_forbidden_secret(value):
                raise PreparationError("candidate archive contains forbidden runtime secret material")
            information = tarfile.TarInfo(entry["path"])
            information.size = len(value)
            information.mode = 0o755 if entry["mode"] == "100755" else 0o644
            information.mtime = 0
            information.uid = 0
            information.gid = 0
            information.uname = ""
            information.gname = ""
            import io
            stream.addfile(information, io.BytesIO(value))


def _tracked_identity(entries: list[dict]) -> str:
    reduced = [{"mode": entry["mode"], "oid": entry["oid"], "path": entry["path"], "size": entry["size"]} for entry in entries]
    return _sha256_bytes(_canonical_json(reduced))


def _verify_archive(repository: Path, archive: Path, entries: list[dict], deadline: float) -> None:
    try:
        with tarfile.open(archive, "r:") as stream:
            members = stream.getmembers()
            if [member.name for member in members] != [entry["path"] for entry in entries]:
                raise PreparationError("archive does not match the declared source tree")
            for member, entry in zip(members, entries):
                if not member.isfile() or member.issym() or member.islnk():
                    raise PreparationError("archive does not match the declared source tree")
                expected_mode = 0o755 if entry["mode"] == "100755" else 0o644
                if member.size != entry["size"] or member.mode != expected_mode or member.mtime != 0:
                    raise PreparationError("archive does not match the declared source tree")
                extracted = stream.extractfile(member)
                if extracted is None or extracted.read(_MAX_FILE_BYTES + 1) != _blob(repository, entry["oid"], entry["size"], deadline):
                    raise PreparationError("archive does not match the declared source tree")
    except (tarfile.TarError, OSError) as error:
        raise PreparationError("archive does not match the declared source tree") from error


def _history_review(manifest_path: Path, source: dict, repository: Path, bundle: Path, deadline: float) -> dict:
    if source["name"] != "restream":
        return {"finding_count": 0, "metadata_sha256": None}
    history_path = manifest_path.with_name("restream-history.json")
    _require_boundary(history_path, "Restream history review", root=manifest_path.parent, file=True)
    try:
        history = load_json(history_path, "restream-history")
    except ContractError as error:
        raise PreparationError("Restream history review is unsafe or incomplete") from error
    if history["candidate_commit"] != source["commit"]:
        raise PreparationError("Restream history candidate commit does not match")
    commits = {history["base_commit"], *(finding["source_commit"] for finding in history["findings"])}
    for commit in commits:
        try:
            _run_git(repository, ("cat-file", "-e", f"{commit}^{{commit}}"), deadline=deadline, output_limit=0)
            containing_refs = _git_text(
                repository,
                "for-each-ref",
                "--format=%(refname)",
                f"--contains={commit}",
                deadline=deadline,
            )
            if not containing_refs:
                raise PreparationError("history commit is not reachable from a repository ref")
        except PreparationError as error:
            raise PreparationError("Restream history review names unavailable history") from error
    return {"finding_count": len(history["findings"]), "metadata_sha256": _sha256_file(history_path)}


def _artifact_declarations(manifest_path: Path) -> list[dict]:
    path = manifest_path.with_name(f"{manifest_path.stem}.artifacts.json")
    if not path.exists():
        return []
    value = _load_plain_json(path, "artifact declaration")
    if set(value) != {"schema_version", "artifacts"} or value["schema_version"] != "1" or type(value["artifacts"]) is not list:
        raise PreparationError("artifact declaration fields are invalid")
    declarations = []
    names: set[str] = set()
    destinations: set[str] = set()
    for item in value["artifacts"]:
        if type(item) is not dict or set(item) != {"name", "source_path", "destination_path", "sha256"}:
            raise PreparationError("artifact declaration fields are invalid")
        name = item["name"]
        if type(name) is not str or _SAFE_NAME.fullmatch(name) is None or name in names:
            raise PreparationError("artifact declaration name is invalid")
        try:
            source_path = str(safe_relative_path(item["source_path"], "artifact source path"))
            destination = str(safe_relative_path(item["destination_path"], "artifact destination path"))
            digest = safe_sha256(item["sha256"], "artifact hash")
        except ContractError as error:
            raise PreparationError("artifact declaration path or hash is invalid") from error
        if not destination.startswith("custody/artifacts/") or PurePosixPath(destination).name != name:
            raise PreparationError("artifact destination is outside the allowlist")
        if any(_SECRET_PATH.search(part) for part in PurePosixPath(source_path).parts + PurePosixPath(destination).parts):
            raise PreparationError("artifact path is secret-like")
        if destination in destinations:
            raise PreparationError("artifact destinations collide")
        names.add(name)
        destinations.add(destination)
        declarations.append({"name": name, "source_path": source_path, "destination_path": destination, "sha256": digest})
    return sorted(declarations, key=lambda item: item["name"])


def _copy_artifacts(workspace: Path, staging: Path, declarations: list[dict], repositories: list[Path]) -> dict:
    result = []
    for item in declarations:
        source = workspace / Path(*PurePosixPath(item["source_path"]).parts)
        _require_boundary(source, f"{item['name']} artifact", root=workspace, file=True)
        if any(_within(source, repository) for repository in repositories):
            raise PreparationError("artifact input must be independent of source repositories")
        size = source.stat().st_size
        if size > _MAX_FILE_BYTES:
            raise PreparationError("artifact input exceeds its byte limit")
        value = source.read_bytes()
        if _contains_forbidden_secret(value):
            raise PreparationError("artifact input contains forbidden secret material")
        if _sha256_bytes(value) != item["sha256"]:
            raise PreparationError("artifact input hash does not match")
        target = staging / Path(*PurePosixPath(item["destination_path"]).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if _has_symlink_or_reparse(target.parent, staging):
            raise PreparationError("artifact destination crosses a symlink boundary")
        target.write_bytes(value)
        result.append({"name": item["name"], "path": item["destination_path"], "sha256": item["sha256"], "size_bytes": size})
    return {"schema_version": "1", "artifacts": result}


def _target(staging: Path, logical: str) -> Path:
    relative = safe_relative_path(logical, "custody destination")
    if not str(relative).startswith("custody/"):
        raise PreparationError("custody destination is outside the allowlist")
    target = staging / Path(*relative.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    if _has_symlink_or_reparse(target.parent, staging):
        raise PreparationError("custody destination crosses a symlink boundary")
    return target


def prepare_inputs(workspace_root: Path, manifest_path: Path, output_root: Path) -> dict:
    """Create exact bundles, archives, and path-free custody manifests locally."""

    workspace = Path(os.path.abspath(workspace_root))
    manifest = Path(os.path.abspath(manifest_path))
    output = Path(os.path.abspath(output_root))
    _require_boundary(workspace, "workspace root")
    _require_boundary(manifest, "run manifest", root=workspace, file=True)
    if output.exists():
        raise PreparationError("output root must not already exist")
    if not _within(output, workspace):
        raise PreparationError("output root is outside the workspace")
    _require_boundary(output.parent, "output parent", root=workspace)
    try:
        run_manifest, _ = load_run_manifest_with_sha256(manifest)
    except ContractError as error:
        raise PreparationError("run manifest is unsafe or invalid") from error

    deadline = time.monotonic() + _COMMAND_SECONDS
    repositories: list[Path] = []
    source_states: list[tuple[Path, bytes]] = []
    for source in run_manifest["sources"]:
        repository = workspace / Path(*PurePosixPath(source["local_path"]).parts)
        if any(_within(output, repository) or _within(repository, output) for repository in [repository]):
            raise PreparationError("output root overlaps a source repository")
        repositories.append(repository)

    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        resolved = json.loads(json.dumps(run_manifest))
        custody_sources = []
        for index, source in enumerate(run_manifest["sources"]):
            repository = repositories[index]
            initial_status, entries = _inspect_repository(repository, source, deadline)
            source_states.append((repository, initial_status))
            bundle = _target(stage, source["bundle_path"])
            archive = _target(stage, source["archive_path"])
            _create_bundle(repository, bundle, deadline)
            refs = _verify_bundle(repository, bundle, source["commit"], deadline)
            _create_archive(repository, source["commit"], entries, archive, deadline)
            _verify_archive(repository, archive, entries, deadline)
            history = _history_review(manifest, source, repository, bundle, deadline)
            bundle_hash = _sha256_file(bundle)
            archive_hash = _sha256_file(archive)
            resolved["sources"][index]["bundle_sha256"] = bundle_hash
            resolved["sources"][index]["archive_sha256"] = archive_hash
            custody_sources.append(
                {
                    "name": source["name"],
                    "branch": source["branch"],
                    "commit": source["commit"],
                    "bundle_path": source["bundle_path"],
                    "bundle_sha256": bundle_hash,
                    "bundle_size_bytes": bundle.stat().st_size,
                    "bundle_refs_sha256": _sha256_bytes(_canonical_json(refs)),
                    "archive_path": source["archive_path"],
                    "archive_sha256": archive_hash,
                    "archive_size_bytes": archive.stat().st_size,
                    "tracked_file_count": len(entries),
                    "tracked_files_sha256": _tracked_identity(entries),
                    "history_review": history,
                }
            )
        validate_run_manifest(resolved)
        declarations = _artifact_declarations(manifest)
        artifact_custody = _copy_artifacts(workspace, stage, declarations, repositories)
        source_custody = {
            "schema_version": "1",
            "allowed_destination": run_manifest["remote_root"],
            "sources": custody_sources,
        }
        (stage / "run-manifest.json").write_bytes(_canonical_json(resolved))
        (stage / "source-custody.json").write_bytes(_canonical_json(source_custody))
        (stage / "artifact-custody.json").write_bytes(_canonical_json(artifact_custody))
        for repository, initial in source_states:
            if _repository_status(repository, deadline) != initial:
                raise PreparationError("source preparation changed repository status")
        os.replace(stage, output)
        return {"run_manifest": resolved, "source_custody": source_custody, "artifact_custody": artifact_custody}
    except (ContractError, OSError) as error:
        raise PreparationError("input preparation failed safely") from error
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        prepare_inputs(arguments.workspace_root, arguments.manifest, arguments.output_root)
    except PreparationError as error:
        print(f"INPUT_PREPARATION=FAIL class={type(error).__name__}", file=sys.stderr)
        return 1
    print("INPUT_PREPARATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
