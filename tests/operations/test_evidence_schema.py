from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "validate-evidence.py"
SCHEMA = ROOT / "docs" / "evidence" / "evidence.schema.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EvidenceValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_module("z1rr_validate_evidence", SCRIPT)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.attachment = self.root / "safe-output.txt"
        self.attachment.write_text("TEST=PASS id=unit-1\n", encoding="utf-8")

    def manifest(self):
        started = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=2)
        completed = started + timedelta(minutes=1)
        return {
            "schema_version": 1,
            "evidence_id": "G0-CORE-20260824-001",
            "environment": "local",
            "started_at_utc": started.isoformat().replace("+00:00", "Z"),
            "completed_at_utc": completed.isoformat().replace("+00:00", "Z"),
            "local_timezone": "America/New_York",
            "operator": {"role": "primary technical operator"},
            "reviewer": {"role": "implementation reviewer"},
            "components": [
                {
                    "name": "racetime",
                    "commit": "a" * 40,
                    "image_digest": "sha256:" + "b" * 64,
                    "dll_sha256": None,
                    "config_sha256": "c" * 64,
                }
            ],
            "requirements": ["FR-CORE-005", "NFR-TEST-001"],
            "artifacts": ["APP-007", "APP-011"],
            "commands": [
                {
                    "id": "unit-1",
                    "command": "python -m unittest tests.example -v",
                    "expected": "tests pass",
                    "observed": "tests passed",
                    "exit_code": 0,
                    "status": "pass",
                    "stdout_sha256": "d" * 64,
                }
            ],
            "attachments": [
                {"path": self.attachment.name, "sha256": sha256(self.attachment), "redacted": True}
            ],
            "findings": [],
            "expires_at_utc": (completed + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
            "result": "pass",
        }

    def write(self, value, name="evidence.json"):
        path = self.root / name
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        return path

    def test_schema_is_closed_and_valid_manifest_and_hashes_pass(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        required = set(schema["required"])
        self.assertTrue(
            {"components", "requirements", "artifacts", "commands", "attachments", "findings", "result"}.issubset(required)
        )
        summary = self.validator.validate_manifest(self.write(self.manifest()))
        self.assertEqual(summary["evidence_id"], "G0-CORE-20260824-001")
        self.assertEqual(summary["requirements"], ["FR-CORE-005", "NFR-TEST-001"])

    def test_cli_prints_only_safe_ids(self):
        path = self.write(self.manifest())
        output = io.StringIO()
        with redirect_stdout(output):
            result = self.validator.main([str(path)])
        self.assertEqual(result, 0)
        rendered = output.getvalue()
        self.assertIn("EVIDENCE=PASS", rendered)
        self.assertIn("G0-CORE-20260824-001", rendered)
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn("python -m unittest", rendered)

    def test_unknown_secret_like_fields_and_values_fail(self):
        for mutate in (
            lambda item: item.update(discord_webhook="https://discord.com/api/webhooks/id/canary"),
            lambda item: item["commands"][0].update(observed="password=canary"),
            lambda item: item["operator"].update(discord_id="123456789"),
        ):
            with self.subTest(mutate=mutate):
                manifest = self.manifest()
                mutate(manifest)
                with self.assertRaises(self.validator.EvidenceError):
                    self.validator.validate_manifest(self.write(manifest))

    def test_attachment_tamper_traversal_and_unredacted_attachment_fail(self):
        for path, digest, redacted in (
            (self.attachment.name, "0" * 64, True),
            ("../outside.txt", sha256(self.attachment), True),
            (self.attachment.name, sha256(self.attachment), False),
        ):
            with self.subTest(path=path, redacted=redacted):
                manifest = self.manifest()
                manifest["attachments"] = [{"path": path, "sha256": digest, "redacted": redacted}]
                with self.assertRaises(self.validator.EvidenceError):
                    self.validator.validate_manifest(self.write(manifest))

    def test_failed_commands_results_p0_p1_and_expiry_fail(self):
        cases = []
        failed_command = self.manifest()
        failed_command["commands"][0].update(status="fail", exit_code=1)
        cases.append(failed_command)
        failed_result = self.manifest()
        failed_result["result"] = "fail"
        cases.append(failed_result)
        for severity in ("P0", "P1"):
            finding = self.manifest()
            finding["findings"] = [{
                "id": f"F-{severity}", "severity": severity, "status": "open",
                "owner": "operator", "due_date": "2026-08-25", "risk_acceptance_id": None,
            }]
            cases.append(finding)
        expired = self.manifest()
        expired["expires_at_utc"] = "2000-01-01T00:00:00Z"
        cases.append(expired)
        for index, manifest in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(self.validator.EvidenceError):
                    self.validator.validate_manifest(self.write(manifest))

    def test_p2_requires_council_acceptance_and_p3_requires_owner_date(self):
        p2 = self.manifest()
        p2["findings"] = [{
            "id": "F-P2", "severity": "P2", "status": "accepted",
            "owner": "operator", "due_date": "2026-09-01", "risk_acceptance_id": None,
        }]
        with self.assertRaises(self.validator.EvidenceError):
            self.validator.validate_manifest(self.write(p2))
        p2["findings"][0]["risk_acceptance_id"] = "COUNCIL-2026-004"
        self.validator.validate_manifest(self.write(p2))

        for missing in ("owner", "due_date"):
            p3 = self.manifest()
            p3["findings"] = [{
                "id": "F-P3", "severity": "P3", "status": "open",
                "owner": "operator", "due_date": "2026-09-01", "risk_acceptance_id": None,
            }]
            p3["findings"][0][missing] = ""
            with self.assertRaises(self.validator.EvidenceError):
                self.validator.validate_manifest(self.write(p3))

    def test_duplicate_ids_bad_hashes_and_bad_timestamps_fail(self):
        mutations = (
            lambda item: item["requirements"].append(item["requirements"][0]),
            lambda item: item["artifacts"].append(item["artifacts"][0]),
            lambda item: item["components"][0].update(commit="mutable-main"),
            lambda item: item.update(completed_at_utc="2026-08-20T00:00:00Z"),
        )
        for mutate in mutations:
            manifest = self.manifest()
            mutate(manifest)
            with self.subTest(mutate=mutate), self.assertRaises(self.validator.EvidenceError):
                self.validator.validate_manifest(self.write(manifest))


if __name__ == "__main__":
    unittest.main()
