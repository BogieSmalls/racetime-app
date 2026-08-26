"""Tests for local, fail-closed G0 input preparation."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

from scripts.g0.prepare_inputs import PreparationError, prepare_inputs


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    ).stdout.strip()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(source: dict) -> dict:
    phases = []
    for name in (
        "preflight", "setup", "images", "security", "services",
        "recovery", "cross_repo", "identities", "cleanup",
    ):
        phases.append(
            {
                "name": name,
                "timeout_seconds": 100,
                "execution_timeout_seconds": 50,
                "cleanup_timeout_seconds": 10,
            }
        )
    return {
        "schema_version": "1",
        "run_id": "20260826t120000z-1234abcd",
        "project_prefix": "z1rr-racetime-g0-20260826t120000z-1234abcd",
        "created_at_utc": "2026-08-26T12:00:00Z",
        "remote_root": "/var/lib/z1rr-racetime/g0/20260826t120000z-1234abcd",
        "aggregate_wall_seconds": 86400,
        "final_cleanup_timeout_seconds": 900,
        "heartbeat_interval_seconds": 15,
        "lease_timeout_seconds": 90,
        "absolute_terminal_seconds": 86490,
        "lock_identities": {
            "docker_bootstrap_sha256": SHA_A,
            "tool_lock_sha256": SHA_B,
        },
        "sources": [source],
        "outputs": [
            {
                "name": "worker-evidence.json",
                "path": "evidence/worker-evidence.json",
                "custody_class": "retained",
            }
        ],
        "phases": phases,
    }


class PrepareInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name).resolve()
        self.repository = self.workspace / "repositories" / "racetime"
        self.repository.mkdir(parents=True)
        subprocess.run(
            ["git", "init", "-b", "main", str(self.repository)],
            check=True,
            capture_output=True,
            timeout=20,
        )
        _git(self.repository, "config", "user.email", "test@example.invalid")
        _git(self.repository, "config", "user.name", "G0 Test")
        (self.repository / "app.txt").write_text("candidate\n", encoding="utf-8")
        (self.repository / "bin.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        _git(self.repository, "add", "app.txt", "bin.sh")
        _git(self.repository, "update-index", "--chmod=+x", "bin.sh")
        _git(self.repository, "commit", "-m", "candidate")
        _git(self.repository, "tag", "v1")
        self.commit = _git(self.repository, "rev-parse", "HEAD")
        self.source = {
            "name": "racetime",
            "branch": "main",
            "commit": self.commit,
            "local_path": "repositories/racetime",
            "bundle_path": "custody/racetime.bundle",
            "bundle_sha256": SHA_A,
            "archive_path": "custody/racetime.tar",
            "archive_sha256": SHA_B,
            "custody_class": "transient",
        }
        self.manifest_path = self.workspace / "run-manifest.json"
        _write_json(self.manifest_path, _manifest(self.source))

    def prepare(self, name: str = "prepared") -> dict:
        return prepare_inputs(self.workspace, self.manifest_path, self.workspace / name)

    def test_prepares_complete_bundle_deterministic_archive_and_path_free_manifests(self):
        first = self.prepare("first")
        second = self.prepare("second")

        for leaf in ("run-manifest.json", "source-custody.json", "artifact-custody.json"):
            self.assertEqual(
                (self.workspace / "first" / leaf).read_bytes(),
                (self.workspace / "second" / leaf).read_bytes(),
            )
        for relative in ("custody/racetime.bundle", "custody/racetime.tar"):
            self.assertEqual(
                (self.workspace / "first" / relative).read_bytes(),
                (self.workspace / "second" / relative).read_bytes(),
            )

        bundle = self.workspace / "first" / "custody" / "racetime.bundle"
        archive = self.workspace / "first" / "custody" / "racetime.tar"
        verify = subprocess.run(
            ["git", "bundle", "verify", str(bundle)],
            cwd=self.repository,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(0, verify.returncode, verify.stderr)
        with tarfile.open(archive, "r:") as stream:
            self.assertEqual(["app.txt", "bin.sh"], stream.getnames())
            self.assertEqual(b"candidate\n", stream.extractfile("app.txt").read())
            members = {member.name: member for member in stream.getmembers()}
            self.assertEqual(0, members["app.txt"].mtime)
            self.assertEqual(0o755, members["bin.sh"].mode)

        custody = json.loads((self.workspace / "first" / "source-custody.json").read_text())
        self.assertEqual(2, custody["sources"][0]["tracked_file_count"])
        self.assertEqual(self.source["bundle_path"], custody["sources"][0]["bundle_path"])
        self.assertEqual(self.source["archive_path"], custody["sources"][0]["archive_path"])
        self.assertEqual(_digest(bundle), custody["sources"][0]["bundle_sha256"])
        self.assertEqual(_digest(archive), custody["sources"][0]["archive_sha256"])
        self.assertEqual(
            "/var/lib/z1rr-racetime/g0/20260826t120000z-1234abcd",
            custody["allowed_destination"],
        )
        serialized = json.dumps(custody)
        self.assertNotIn(str(self.workspace), serialized)
        self.assertEqual(custody, first["source_custody"])

        resolved = json.loads((self.workspace / "first" / "run-manifest.json").read_text())
        self.assertEqual(_digest(bundle), resolved["sources"][0]["bundle_sha256"])
        self.assertEqual(_digest(archive), resolved["sources"][0]["archive_sha256"])

    def test_does_not_mutate_repository_status(self):
        before = _git(self.repository, "status", "--porcelain=v1", "--ignored=matching", "--untracked-files=all")
        self.prepare()
        after = _git(self.repository, "status", "--porcelain=v1", "--ignored=matching", "--untracked-files=all")
        self.assertEqual(before, after)

    def test_rejects_dirty_untracked_and_ignored_repository_inputs(self):
        cases = {
            "modified": lambda: (self.repository / "app.txt").write_text("dirty\n", encoding="utf-8"),
            "untracked": lambda: (self.repository / "loose.txt").write_text("loose\n", encoding="utf-8"),
            "ignored": self._add_ignored_file,
        }
        for index, (label, mutate) in enumerate(cases.items()):
            with self.subTest(label=label):
                if index:
                    _git(self.repository, "reset", "--hard", "HEAD")
                    for leaf in ("loose.txt", ".gitignore", "ignored.bin"):
                        path = self.repository / leaf
                        if path.exists():
                            path.unlink()
                mutate()
                with self.assertRaisesRegex(PreparationError, "repository is not clean"):
                    self.prepare(f"out-{label}")

    def _add_ignored_file(self) -> None:
        (self.repository / ".gitignore").write_text("ignored.bin\n", encoding="utf-8")
        _git(self.repository, "add", ".gitignore")
        _git(self.repository, "commit", "-m", "ignore")
        self.source["commit"] = _git(self.repository, "rev-parse", "HEAD")
        _write_json(self.manifest_path, _manifest(self.source))
        (self.repository / "ignored.bin").write_bytes(b"ignored")

    def test_rejects_shallow_repository(self):
        bare = self.workspace / "origin.git"
        subprocess.run(["git", "clone", "--bare", str(self.repository), str(bare)], check=True, capture_output=True, timeout=20)
        shallow = self.workspace / "repositories" / "shallow"
        subprocess.run(
            ["git", "clone", "--depth", "1", f"file:///{bare.as_posix()}", str(shallow)],
            check=True,
            capture_output=True,
            timeout=20,
        )
        self.source["local_path"] = "repositories/shallow"
        _write_json(self.manifest_path, _manifest(self.source))
        with self.assertRaisesRegex(PreparationError, "shallow"):
            self.prepare()

    def test_rejects_branch_and_commit_mismatch(self):
        for key, value in (("branch", "wrong"), ("commit", "0" * 40)):
            with self.subTest(key=key):
                source = copy.deepcopy(self.source)
                source[key] = value
                _write_json(self.manifest_path, _manifest(source))
                with self.assertRaisesRegex(PreparationError, key):
                    self.prepare(f"out-{key}")

    def test_rejects_bundle_missing_repository_refs(self):
        def incomplete(repository, target, _deadline):
            subprocess.run(
                ["git", "-C", str(repository), "bundle", "create", str(target), "HEAD"],
                check=True,
                capture_output=True,
                timeout=20,
            )

        with mock.patch("scripts.g0.prepare_inputs._create_bundle", side_effect=incomplete):
            with self.assertRaisesRegex(PreparationError, "bundle refs do not match"):
                self.prepare()

    def test_rejects_archive_from_another_tree(self):
        def wrong_archive(_repository, _commit, entries, target, _deadline):
            with tarfile.open(target, "w", format=tarfile.USTAR_FORMAT) as stream:
                for entry in entries:
                    info = tarfile.TarInfo(entry["path"])
                    payload = b"wrong\n"
                    info.size = len(payload)
                    info.mtime = 0
                    info.mode = 0o644
                    stream.addfile(info, io.BytesIO(payload))

        with mock.patch("scripts.g0.prepare_inputs._create_archive", side_effect=wrong_archive):
            with self.assertRaisesRegex(PreparationError, "archive does not match"):
                self.prepare()

    def test_rejects_symlink_at_manifest_repository_artifact_or_output_boundary(self):
        link = self.workspace / "manifest-link.json"
        try:
            link.symlink_to(self.manifest_path)
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        with self.assertRaisesRegex(PreparationError, "symlink"):
            prepare_inputs(self.workspace, link, self.workspace / "out-link")

        repo_link = self.workspace / "repositories" / "repo-link"
        repo_link.symlink_to(self.repository, target_is_directory=True)
        source = copy.deepcopy(self.source)
        source["local_path"] = "repositories/repo-link"
        _write_json(self.manifest_path, _manifest(source))
        with self.assertRaisesRegex(PreparationError, "symlink"):
            self.prepare("out-repo-link")

    def test_rejects_paths_outside_the_closed_logical_destination(self):
        for key, value in (
            ("local_path", "../private/repo"),
            ("bundle_path", "D:/private/repo.bundle"),
            ("archive_path", "outside.tar"),
        ):
            with self.subTest(key=key):
                source = copy.deepcopy(self.source)
                source[key] = value
                _write_json(self.manifest_path, _manifest(source))
                with self.assertRaises(PreparationError):
                    self.prepare(f"out-{key}")

    def test_copies_hash_listed_regular_artifacts_and_records_no_private_source_path(self):
        artifact = self.workspace / "artifacts" / "release.bin"
        artifact.parent.mkdir()
        artifact.write_bytes(b"release bytes\n")
        _write_json(
            self.workspace / "run-manifest.artifacts.json",
            {
                "schema_version": "1",
                "artifacts": [
                    {
                        "name": "release.bin",
                        "source_path": "artifacts/release.bin",
                        "destination_path": "custody/artifacts/release.bin",
                        "sha256": _digest(artifact),
                    }
                ],
            },
        )
        result = self.prepare()
        copied = self.workspace / "prepared" / "custody" / "artifacts" / "release.bin"
        self.assertEqual(artifact.read_bytes(), copied.read_bytes())
        custody = json.loads((self.workspace / "prepared" / "artifact-custody.json").read_text())
        self.assertEqual(1, len(custody["artifacts"]))
        self.assertNotIn("source_path", custody["artifacts"][0])
        self.assertNotIn(str(self.workspace), json.dumps(custody))
        self.assertEqual(custody, result["artifact_custody"])

    def test_rejects_artifact_hash_secret_path_secret_content_and_symlink(self):
        artifact = self.workspace / "artifacts" / "release.bin"
        artifact.parent.mkdir()
        artifact.write_bytes(b"release bytes\n")
        base = {
            "name": "release.bin",
            "source_path": "artifacts/release.bin",
            "destination_path": "custody/artifacts/release.bin",
            "sha256": _digest(artifact),
        }
        cases = {
            "hash": {**base, "sha256": SHA_A},
            "secret-path": {**base, "source_path": "artifacts/.env"},
        }
        for label, declaration in cases.items():
            with self.subTest(label=label):
                _write_json(self.workspace / "run-manifest.artifacts.json", {"schema_version": "1", "artifacts": [declaration]})
                with self.assertRaises(PreparationError):
                    self.prepare(f"out-{label}")

        secret = "G0_CANARY_VALUE_93c91"
        artifact.write_text(f"api_token={secret}\n", encoding="utf-8")
        base["sha256"] = _digest(artifact)
        _write_json(self.workspace / "run-manifest.artifacts.json", {"schema_version": "1", "artifacts": [base]})
        with self.assertRaises(PreparationError) as caught:
            self.prepare("out-secret-content")
        self.assertNotIn(secret, str(caught.exception))

        target = self.workspace / "artifacts" / "target.bin"
        target.write_bytes(b"target")
        artifact.unlink()
        try:
            artifact.symlink_to(target)
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        base["sha256"] = _digest(target)
        _write_json(self.workspace / "run-manifest.artifacts.json", {"schema_version": "1", "artifacts": [base]})
        with self.assertRaisesRegex(PreparationError, "symlink"):
            self.prepare("out-artifact-link")

    def test_accepts_metadata_only_reviewed_inactive_bundle_history(self):
        _git(self.repository, "checkout", "--orphan", "history")
        _git(self.repository, "rm", "-rf", ".")
        (self.repository / "old.txt").write_text("api_token=old-revoked-value\n", encoding="utf-8")
        _git(self.repository, "add", "old.txt")
        _git(self.repository, "commit", "-m", "inactive history")
        historical_commit = _git(self.repository, "rev-parse", "HEAD")
        _git(self.repository, "checkout", "main")
        _write_json(
            self.workspace / "restream-history.json",
            {
                "schema_version": "1",
                "repository": "restream",
                "base_commit": historical_commit,
                "candidate_commit": self.commit,
                "captured_at_utc": "2026-08-26T12:00:00Z",
                "findings": [
                    {
                        "rule_id": "generic-api-key",
                        "path": "old.txt",
                        "source_commit": historical_commit,
                        "line": 1,
                        "fingerprint_sha256": SHA_A,
                        "classification": "inactive-history",
                        "outside_candidate": True,
                        "live_credential_disposition": "revoked",
                        "evidence_id": "rotation-ticket-123",
                    }
                ],
            },
        )
        self.source["name"] = "restream"
        _write_json(self.manifest_path, _manifest(self.source))
        result = self.prepare()
        history = result["source_custody"]["sources"][0]["history_review"]
        self.assertEqual(1, history["finding_count"])
        self.assertEqual(_digest(self.workspace / "restream-history.json"), history["metadata_sha256"])
        self.assertNotIn("old-revoked-value", json.dumps(result))

    def test_rejects_possible_live_or_raw_historical_finding_metadata(self):
        self.source["name"] = "restream"
        _write_json(self.manifest_path, _manifest(self.source))
        valid = {
            "schema_version": "1",
            "repository": "restream",
            "base_commit": self.commit,
            "candidate_commit": self.commit,
            "captured_at_utc": "2026-08-26T12:00:00Z",
            "findings": [],
        }
        for label, change in (
            ("possible-live", {"findings": [{
                "rule_id": "api-key", "path": "app.txt", "source_commit": self.commit,
                "line": 1, "fingerprint_sha256": SHA_A, "classification": "inactive-history",
                "outside_candidate": True, "live_credential_disposition": "possibly-live",
                "evidence_id": "pending-rotation",
            }]}),
            ("raw-match", {"raw_match": "do-not-transfer-this-value"}),
        ):
            with self.subTest(label=label):
                value = copy.deepcopy(valid)
                value.update(change)
                _write_json(self.workspace / "restream-history.json", value)
                with self.assertRaises(PreparationError) as caught:
                    self.prepare(f"out-{label}")
                self.assertNotIn("do-not-transfer-this-value", str(caught.exception))

    def test_rejects_current_archive_secret_even_with_historical_review(self):
        (self.repository / "app.txt").write_text("password=current-unsafe-value\n", encoding="utf-8")
        _git(self.repository, "add", "app.txt")
        _git(self.repository, "commit", "-m", "unsafe candidate")
        self.source["name"] = "restream"
        self.source["commit"] = _git(self.repository, "rev-parse", "HEAD")
        _write_json(self.manifest_path, _manifest(self.source))
        _write_json(
            self.workspace / "restream-history.json",
            {
                "schema_version": "1", "repository": "restream",
                "base_commit": self.commit, "candidate_commit": self.source["commit"],
                "captured_at_utc": "2026-08-26T12:00:00Z", "findings": [],
            },
        )
        with self.assertRaisesRegex(PreparationError, "candidate archive contains forbidden"):
            self.prepare()

    def test_rejects_historical_disposition_for_commit_not_reachable_from_bundle_refs(self):
        (self.repository / "orphaned.txt").write_text("old\n", encoding="utf-8")
        _git(self.repository, "add", "orphaned.txt")
        _git(self.repository, "commit", "-m", "unreferenced finding")
        unreferenced = _git(self.repository, "rev-parse", "HEAD")
        _git(self.repository, "reset", "--hard", self.commit)
        self.source["name"] = "restream"
        _write_json(self.manifest_path, _manifest(self.source))
        _write_json(
            self.workspace / "restream-history.json",
            {
                "schema_version": "1", "repository": "restream",
                "base_commit": unreferenced, "candidate_commit": self.commit,
                "captured_at_utc": "2026-08-26T12:00:00Z", "findings": [],
            },
        )
        with self.assertRaisesRegex(PreparationError, "unavailable history"):
            self.prepare()


if __name__ == "__main__":
    unittest.main()
