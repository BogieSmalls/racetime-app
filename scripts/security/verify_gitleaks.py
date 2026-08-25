#!/usr/bin/env python3
"""Download pinned Gitleaks and run the repository's fail-closed scan gates."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile


VERSION = "8.30.1"
RELEASE_ROOT = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}"
SAFE_REF = re.compile(r"^(?!-)[A-Za-z0-9][A-Za-z0-9._/-]*$")


class VerificationError(RuntimeError):
    """Raised when a required verification boundary is absent or unsafe."""


@dataclass(frozen=True)
class Asset:
    filename: str
    sha256: str
    archive_kind: str
    executable_name: str

    @property
    def url(self) -> str:
        return f"{RELEASE_ROOT}/{self.filename}"


ASSETS = {
    ("windows", "x64"): Asset(
        filename="gitleaks_8.30.1_windows_x64.zip",
        sha256="d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e",
        archive_kind="zip",
        executable_name="gitleaks.exe",
    ),
    ("linux", "x64"): Asset(
        filename="gitleaks_8.30.1_linux_x64.tar.gz",
        sha256="551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
        archive_kind="tar.gz",
        executable_name="gitleaks",
    ),
}


def select_asset(system: str | None = None, machine: str | None = None) -> Asset:
    system_name = (system or platform.system()).lower()
    machine_name = (machine or platform.machine()).lower()
    if machine_name in {"amd64", "x86_64"}:
        machine_name = "x64"
    asset = ASSETS.get((system_name, machine_name))
    if asset is None:
        raise VerificationError(
            f"unsupported platform: {system or platform.system()} "
            f"{machine or platform.machine()}"
        )
    return asset


def verify_sha256(path: Path, expected: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise VerificationError("invalid pinned SHA-256")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise VerificationError(
            f"checksum mismatch for {path.name}: expected {expected}, got {actual}"
        )


def _member_target(destination: Path, name: str) -> Path:
    normalized = name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or member.is_absolute()
        or any(part in {"", ".", ".."} for part in member.parts)
        or (member.parts and ":" in member.parts[0])
    ):
        raise VerificationError(f"unsafe archive member: {name!r}")
    target = destination.joinpath(*member.parts)
    try:
        target.resolve(strict=False).relative_to(destination.resolve(strict=True))
    except ValueError as exc:
        raise VerificationError(f"unsafe archive member: {name!r}") from exc
    return target


def _extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = _member_target(destination, member.filename)
            file_type = (member.external_attr >> 16) & 0o170000
            if member.flag_bits & 0x1 or stat.S_ISLNK(file_type):
                raise VerificationError(f"unsafe archive member: {member.filename!r}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with bundle.open(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
            except FileExistsError as exc:
                raise VerificationError(
                    f"duplicate archive member: {member.filename!r}"
                ) from exc


def _extract_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            target = _member_target(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise VerificationError(f"unsafe archive member: {member.name!r}")
            source = bundle.extractfile(member)
            if source is None:
                raise VerificationError(f"unreadable archive member: {member.name!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
            except FileExistsError as exc:
                raise VerificationError(
                    f"duplicate archive member: {member.name!r}"
                ) from exc
            target.chmod(member.mode & 0o755)


def extract_archive(archive: Path, destination: Path, asset: Asset) -> Path:
    if destination.exists() or destination.is_symlink():
        raise VerificationError(f"extraction destination already exists: {destination}")
    destination.mkdir(parents=True)
    if asset.archive_kind == "zip":
        _extract_zip(archive, destination)
    elif asset.archive_kind == "tar.gz":
        _extract_tar(archive, destination)
    else:
        raise VerificationError(f"unsupported archive kind: {asset.archive_kind}")

    executable = destination / asset.executable_name
    if not executable.is_file() or executable.is_symlink():
        raise VerificationError(
            f"archive did not contain expected executable: {asset.executable_name}"
        )
    if os.name != "nt":
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _prepare_tools_root(path: Path) -> Path:
    if path.is_symlink():
        raise VerificationError(f"tools root must not be a symlink: {path}")
    path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise VerificationError(f"tools root is not a directory: {resolved}")
    return resolved


def download_asset(asset: Asset, tools_root: Path) -> Path:
    root = _prepare_tools_root(tools_root)
    archive = root / asset.filename
    if archive.exists():
        if not archive.is_file() or archive.is_symlink():
            raise VerificationError(f"asset path is not a regular file: {archive}")
        verify_sha256(archive, asset.sha256)
        return archive

    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{asset.filename}.", suffix=".download", dir=root
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        request = urllib.request.Request(
            asset.url,
            headers={"User-Agent": f"z1rr-racetime-gitleaks-verifier/{VERSION}"},
        )
        with urllib.request.urlopen(request, timeout=120) as source, temporary.open(
            "wb"
        ) as output:
            shutil.copyfileobj(source, output)
        verify_sha256(temporary, asset.sha256)
        temporary.replace(archive)
    except (OSError, urllib.error.URLError) as exc:
        raise VerificationError(f"failed to download pinned Gitleaks asset: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    return archive


def prepare_binary(asset: Asset, tools_root: Path) -> Path:
    root = _prepare_tools_root(tools_root)
    archive = download_asset(asset, root)
    extraction = Path(
        tempfile.mkdtemp(prefix=f"gitleaks-{VERSION}-", dir=root)
    )
    extraction.rmdir()
    executable = extract_archive(archive, extraction, asset)
    result = subprocess.run(
        [str(executable), "version"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    if result.returncode != 0 or result.stdout.strip() not in {VERSION, f"v{VERSION}"}:
        raise VerificationError("pinned Gitleaks executable reported an unexpected version")
    return executable


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def validate_repository(repository: Path, base_ref: str) -> tuple[Path, str]:
    try:
        resolved = repository.expanduser().resolve(strict=True)
    except OSError as exc:
        raise VerificationError(f"repository does not exist: {repository}") from exc
    if not resolved.is_dir():
        raise VerificationError(f"repository is not a directory: {resolved}")
    if (
        not SAFE_REF.fullmatch(base_ref)
        or ".." in base_ref
        or "//" in base_ref
        or "@{" in base_ref
    ):
        raise VerificationError(f"invalid base ref: {base_ref!r}")

    top_level = _git(resolved, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        raise VerificationError(f"not a Git repository: {resolved}")
    try:
        actual_root = Path(top_level.stdout.strip()).resolve(strict=True)
    except OSError as exc:
        raise VerificationError("Git returned an invalid repository root") from exc
    if actual_root != resolved:
        raise VerificationError(
            f"repository must be its Git top level: {resolved} != {actual_root}"
        )

    config = resolved / ".gitleaks.toml"
    policy_test = resolved / "tests" / "platform" / "test_gitleaks_policy.py"
    if not config.is_file():
        raise VerificationError(f"missing Gitleaks config: {config}")
    if not policy_test.is_file():
        raise VerificationError(f"missing Gitleaks policy test: {policy_test}")

    base = _git(
        resolved,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{base_ref}^{{commit}}",
    )
    if base.returncode != 0:
        raise VerificationError(f"missing base ref: {base_ref}")
    head = _git(resolved, "rev-parse", "--verify", "HEAD^{commit}")
    if head.returncode != 0:
        raise VerificationError("missing HEAD commit")
    ancestor = _git(resolved, "merge-base", "--is-ancestor", base_ref, "HEAD")
    if ancestor.returncode != 0:
        raise VerificationError(f"base ref is not an ancestor of HEAD: {base_ref}")
    status = _git(resolved, "status", "--porcelain", "--untracked-files=all")
    if status.returncode != 0 or status.stdout:
        raise VerificationError("repository worktree is not clean")
    return resolved, head.stdout.strip()


def build_commands(
    repository: Path, base_ref: str, executable: Path
) -> list[list[str]]:
    config = repository / ".gitleaks.toml"
    common = [
        str(executable),
        "git",
        str(repository),
        "--config",
        str(config),
        "--redact=100",
        "--no-banner",
        "--exit-code",
        "1",
    ]
    return [
        [
            sys.executable,
            "-m",
            "unittest",
            "tests.platform.test_gitleaks_policy",
            "-v",
        ],
        [*common, "--log-opts=--all"],
        [*common, f"--log-opts={base_ref}..HEAD"],
    ]


def _run_gate(
    label: str,
    command: list[str],
    repository: Path,
    environment: dict[str, str] | None = None,
) -> None:
    print(f"GITLEAKS_VERIFY gate={label}", flush=True)
    result = subprocess.run(
        command,
        cwd=repository,
        env=environment,
        check=False,
    )
    if result.returncode != 0:
        raise VerificationError(f"{label} failed with exit code {result.returncode}")


def run_verification(repository: Path, base_ref: str, tools_root: Path) -> str:
    repository, head = validate_repository(repository, base_ref)
    asset = select_asset()
    executable = prepare_binary(asset, tools_root)
    commands = build_commands(repository, base_ref, executable)

    policy_environment = os.environ.copy()
    policy_environment["GITLEAKS_BIN"] = str(executable)
    policy_environment["REQUIRE_GITLEAKS_TESTS"] = "1"
    _run_gate("policy-test", commands[0], repository, policy_environment)
    _run_gate("full-history", commands[1], repository)
    _run_gate("candidate-range", commands[2], repository)
    return head


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run checksum-pinned Gitleaks policy and history gates"
    )
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--tools-root", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.tools_root is not None:
            head = run_verification(args.repository, args.base_ref, args.tools_root)
        else:
            with tempfile.TemporaryDirectory(
                prefix="racetime-gitleaks-tools-"
            ) as temporary:
                head = run_verification(
                    args.repository, args.base_ref, Path(temporary)
                )
    except VerificationError as exc:
        print(f"GITLEAKS_VERIFY=FAIL reason={exc}", file=sys.stderr)
        return 1
    print(
        f"GITLEAKS_VERIFY=PASS version={VERSION} base={args.base_ref} head={head}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
