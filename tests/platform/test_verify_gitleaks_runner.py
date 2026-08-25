"""Tests for the pinned, fail-closed Gitleaks verification runner."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts" / "security" / "verify_gitleaks.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("verify_gitleaks", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load verify_gitleaks.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VerifyGitleaksRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(
            RUNNER_PATH.is_file(),
            "scripts/security/verify_gitleaks.py must be implemented",
        )
        self.runner = load_runner()

    def test_selects_only_checksum_pinned_windows_and_linux_x64_assets(self) -> None:
        windows = self.runner.select_asset("Windows", "AMD64")
        self.assertEqual(windows.filename, "gitleaks_8.30.1_windows_x64.zip")
        self.assertEqual(
            windows.sha256,
            "d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e",
        )
        self.assertEqual(windows.archive_kind, "zip")
        self.assertEqual(windows.executable_name, "gitleaks.exe")
        self.assertEqual(
            windows.url,
            "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/"
            "gitleaks_8.30.1_windows_x64.zip",
        )

        linux = self.runner.select_asset("Linux", "x86_64")
        self.assertEqual(linux.filename, "gitleaks_8.30.1_linux_x64.tar.gz")
        self.assertEqual(
            linux.sha256,
            "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
        )
        self.assertEqual(linux.archive_kind, "tar.gz")
        self.assertEqual(linux.executable_name, "gitleaks")

    def test_rejects_every_unsupported_platform_or_architecture(self) -> None:
        for system, machine in (
            ("Darwin", "x86_64"),
            ("Linux", "aarch64"),
            ("Windows", "ARM64"),
            ("FreeBSD", "amd64"),
        ):
            with self.subTest(system=system, machine=machine):
                with self.assertRaises(self.runner.VerificationError):
                    self.runner.select_asset(system, machine)

    def test_checksum_mismatch_fails_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory(prefix="racetime-gitleaks-checksum-") as temp:
            archive = Path(temp) / "asset.zip"
            archive.write_bytes(b"not the pinned archive")
            with self.assertRaisesRegex(
                self.runner.VerificationError, "checksum mismatch"
            ):
                self.runner.verify_sha256(archive, "0" * 64)

    def test_zip_traversal_is_rejected_without_writing_outside_destination(self) -> None:
        asset = self.runner.select_asset("Windows", "AMD64")
        with tempfile.TemporaryDirectory(prefix="racetime-gitleaks-zip-") as temp:
            root = Path(temp)
            archive = root / asset.filename
            destination = root / "extract"
            outside = root / "escape.txt"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(asset.executable_name, b"binary")
                bundle.writestr("../escape.txt", b"escape")

            with self.assertRaisesRegex(
                self.runner.VerificationError, "unsafe archive member"
            ):
                self.runner.extract_archive(archive, destination, asset)
            self.assertFalse(outside.exists())

    def test_tar_links_are_rejected_without_writing_outside_destination(self) -> None:
        asset = self.runner.select_asset("Linux", "x86_64")
        with tempfile.TemporaryDirectory(prefix="racetime-gitleaks-tar-") as temp:
            root = Path(temp)
            archive = root / asset.filename
            destination = root / "extract"
            outside = root / "escape.txt"
            with tarfile.open(archive, "w:gz") as bundle:
                binary = tarfile.TarInfo(asset.executable_name)
                binary.size = len(b"binary")
                binary.mode = 0o755
                bundle.addfile(binary, io.BytesIO(b"binary"))
                link = tarfile.TarInfo("link")
                link.type = tarfile.SYMTYPE
                link.linkname = str(outside)
                bundle.addfile(link)

            with self.assertRaisesRegex(
                self.runner.VerificationError, "unsafe archive member"
            ):
                self.runner.extract_archive(archive, destination, asset)
            self.assertFalse(outside.exists())

    def test_valid_archive_extracts_only_the_expected_binary(self) -> None:
        asset = self.runner.select_asset("Windows", "AMD64")
        with tempfile.TemporaryDirectory(prefix="racetime-gitleaks-valid-") as temp:
            root = Path(temp)
            archive = root / asset.filename
            destination = root / "extract"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(asset.executable_name, b"binary")
                bundle.writestr("LICENSE", b"license")

            executable = self.runner.extract_archive(archive, destination, asset)
            self.assertEqual(executable, destination / asset.executable_name)
            self.assertEqual(executable.read_bytes(), b"binary")
            self.assertEqual((destination / "LICENSE").read_bytes(), b"license")

    def test_commands_require_policy_test_explicit_config_and_redaction(self) -> None:
        executable = ROOT / "tools" / "gitleaks.exe"
        commands = self.runner.build_commands(ROOT, "origin/master", executable)
        self.assertEqual(
            commands[0],
            [
                sys.executable,
                "-m",
                "unittest",
                "tests.platform.test_gitleaks_policy",
                "-v",
            ],
        )
        for command in commands[1:]:
            self.assertEqual(command[:3], [str(executable), "git", str(ROOT)])
            self.assertIn("--config", command)
            self.assertIn(str(ROOT / ".gitleaks.toml"), command)
            self.assertIn("--redact=100", command)
            self.assertIn("--no-banner", command)
            self.assertNotIn("--verbose", command)
        self.assertIn("--log-opts=--all", commands[1])
        self.assertIn("--log-opts=origin/master..HEAD", commands[2])

    def test_missing_base_ref_fails_closed(self) -> None:
        with self.assertRaisesRegex(self.runner.VerificationError, "base ref"):
            self.runner.validate_repository(ROOT, "origin/definitely-missing")


if __name__ == "__main__":
    unittest.main()
