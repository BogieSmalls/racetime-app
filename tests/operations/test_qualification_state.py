from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
QUALIFY = ROOT / "scripts" / "ops" / "qualify-candidate.py"
FINALIZE = ROOT / "scripts" / "ops" / "finalize-production.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class QualificationStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qualify = load_module("z1rr_qualify", QUALIFY)
        cls.finalize = load_module("z1rr_finalize", FINALIZE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = self.root / "release-identities.json"
        self.identity.write_text(json.dumps({"schema_version": 1, "components": {"racetime": {"commit": "a" * 40}}}) + "\n")
        self.state = self.root / "qualification-state.json"
        self.qualify.initialize_state(self.state, self.identity, environment="qualification")

    def evidence(self, stage, *, result="pass", severity=None):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        finding = []
        if severity:
            finding = [{
                "id": f"F-{stage}", "severity": severity, "status": "open",
                "owner": "operator", "due_date": (now.date() + timedelta(days=1)).isoformat(),
                "risk_acceptance_id": None,
            }]
        value = {
            "schema_version": 1,
            "evidence_id": f"EVIDENCE-{stage.upper().replace('_', '-')}",
            "environment": "qualification",
            "started_at_utc": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "completed_at_utc": now.isoformat().replace("+00:00", "Z"),
            "local_timezone": "America/New_York",
            "operator": {"role": "primary technical operator"},
            "reviewer": {"role": "implementation reviewer"},
            "components": [{
                "name": "racetime", "commit": "a" * 40,
                "image_digest": "sha256:" + "b" * 64,
                "dll_sha256": None, "config_sha256": "c" * 64,
            }],
            "requirements": ["NFR-TEST-001"],
            "artifacts": ["APP-001"],
            "commands": [{
                "id": stage, "command": "python safe-adapter.py", "expected": "pass",
                "observed": "pass" if result == "pass" else "failed safely",
                "exit_code": 0 if result == "pass" else 1,
                "status": result, "stdout_sha256": "d" * 64,
            }],
            "attachments": [], "findings": finding,
            "expires_at_utc": (now + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
            "result": result,
        }
        path = self.root / f"{stage}-{len(list(self.root.glob(stage + '-*.json')))}.json"
        path.write_text(json.dumps(value, indent=2) + "\n")
        return path

    def record(self, stage, *, result="pass", severity=None, claims=None):
        return self.qualify.record_stage(
            self.state, stage, self.evidence(stage, result=result, severity=severity), claims=claims or {}
        )

    def record_through_fresh_production(self):
        self.record("release_identity")
        self.record("qualification_core")
        self.record("governance")
        for stage in ("failure", "security", "load", "backup_restore"):
            self.record(stage)
        self.record("fresh_production", claims={
            "certificate_environment": "production",
            "ordinary_trust": True,
            "state_generation": "fresh-production",
            "public_mode": False,
        })

    def test_dependencies_prevent_skips_and_every_stage_can_complete(self):
        with self.assertRaises(self.qualify.QualificationError):
            self.record("qualification_core")
        self.record_through_fresh_production()
        for stage in (
            "post_issuance_ttpbot", "post_issuance_restream", "post_issuance_livesplit"
        ):
            self.record(stage)
        self.record("dress_rehearsal")
        state = self.record("cutover_rehearsal")
        self.assertTrue(self.qualify.is_complete(state))
        self.assertEqual(len(state["attempts"]), 13)

    def test_programmatic_client_stages_require_production_certificate_claims(self):
        self.record("release_identity")
        self.record("qualification_core")
        self.record("governance")
        for stage in ("failure", "security", "load", "backup_restore"):
            self.record(stage)
        with self.assertRaises(self.qualify.QualificationError):
            self.record("fresh_production", claims={"certificate_environment": "staging"})

    def test_evidence_hashes_are_immutable_and_reruns_append_attempts(self):
        evidence = self.evidence("release_identity", result="fail")
        first = self.qualify.record_stage(self.state, "release_identity", evidence)
        self.assertEqual(first["attempts"][0]["attempt"], 1)
        second = self.record("release_identity")
        self.assertEqual(second["attempts"][1]["attempt"], 2)
        evidence.write_text("tampered\n")
        with self.assertRaises(self.qualify.QualificationError):
            self.qualify.load_state(self.state, verify_evidence=True)

    def test_p0_p1_findings_block_all_later_stages(self):
        self.record("release_identity", result="fail", severity="P1")
        self.record("release_identity")
        with self.assertRaises(self.qualify.QualificationError):
            self.record("qualification_core")

    def activation(self):
        path = self.root / "activation.json"
        path.write_text(json.dumps({
            "schema_version": 1, "gate": "G1", "activation_id": "PLAN-B-20260824",
            "activated_at_utc": "2026-08-24T12:00:00Z",
            "canonical_origin": "https://raceroom.z1rracing.com",
            "allowlist_record_sha256": "e" * 64,
        }) + "\n")
        return path

    def adapter_config(self, *, mutates=True):
        evidence_dir = self.root / "generated-evidence"
        evidence_dir.mkdir(exist_ok=True)
        return {
            "schema_version": 1,
            "environment": "qualification",
            "state_path": str(self.state),
            "release_identity_path": str(self.identity),
            "evidence_directory": str(evidence_dir),
            "working_directory": str(self.root),
            "components": [{
                "name": "racetime", "commit": "a" * 40,
                "image_digest": "sha256:" + "b" * 64,
                "dll_sha256": None, "config_sha256": "c" * 64,
            }],
            "stages": {
                "release_identity": {
                    "command": ["python", "-c", "print('SAFE=PASS')"],
                    "mutates": mutates,
                    "environment_overrides": {"REQUESTS_CA_BUNDLE": str(self.root / "staging-ca.pem")},
                    "requirements": ["NFR-TEST-001"],
                    "artifacts": ["APP-001"],
                    "expected": "adapter exits zero",
                }
            },
        }

    def test_mutating_adapter_requires_activation_and_process_scoped_ca_only(self):
        config = self.adapter_config()
        config_path = self.root / "adapters.json"
        config_path.write_text(json.dumps(config) + "\n")
        with self.assertRaises(self.qualify.QualificationError):
            self.qualify.run_stage(config_path, "release_identity")
        state = self.qualify.run_stage(config_path, "release_identity", activation_record=self.activation())
        self.assertEqual(state["attempts"][-1]["status"], "pass")
        config["stages"]["release_identity"]["environment_overrides"] = {"PYTHONHTTPSVERIFY": "0"}
        config_path.write_text(json.dumps(config) + "\n")
        with self.assertRaises(self.qualify.QualificationError):
            self.qualify.run_stage(config_path, "release_identity", activation_record=self.activation())

    def finalizer_config(self, *, public_mode=False):
        return {
            "schema_version": 1,
            "environment": "qualification",
            "public_mode": public_mode,
            "state_path": str(self.root / "finalize-state.json"),
            "steps": {
                step: {"command": ["safe", step], "probe": ["probe", step]}
                for step in self.finalize.TRANSITION_STEPS
            },
        }

    def test_finalizer_is_dry_run_by_default_refuses_public_and_records_order(self):
        calls = []
        runner = lambda command: calls.append(command) or 0
        plan = self.finalize.run_transition(self.finalizer_config(), apply=False, runner=runner)
        self.assertEqual(plan["planned_steps"], list(self.finalize.TRANSITION_STEPS))
        self.assertEqual(calls, [])
        with self.assertRaises(self.finalize.FinalizationError):
            self.finalize.run_transition(
                self.finalizer_config(public_mode=True), apply=True,
                activation_record=self.activation(), change_id="Z1RR-G2-001", runner=runner,
            )
        state = self.finalize.run_transition(
            self.finalizer_config(), apply=True, activation_record=self.activation(),
            change_id="Z1RR-G2-001", runner=runner,
        )
        self.assertEqual(state["completed_steps"], list(self.finalize.TRANSITION_STEPS))
        self.assertEqual(len(calls), len(self.finalize.TRANSITION_STEPS) * 2)

    def test_finalizer_failure_does_not_advance_and_resume_reprobes_reality(self):
        config = self.finalizer_config()
        failure_step = self.finalize.TRANSITION_STEPS[2]
        calls = []
        def failing(command):
            calls.append(command)
            return 1 if command == ["safe", failure_step] else 0
        with self.assertRaises(self.finalize.FinalizationError):
            self.finalize.run_transition(
                config, apply=True, activation_record=self.activation(),
                change_id="Z1RR-G2-002", runner=failing,
            )
        state = json.loads(Path(config["state_path"]).read_text())
        self.assertEqual(state["completed_steps"], list(self.finalize.TRANSITION_STEPS[:2]))
        resumed_calls = []
        resumed = self.finalize.run_transition(
            config, apply=True, activation_record=self.activation(),
            change_id="Z1RR-G2-002", runner=lambda command: resumed_calls.append(command) or 0,
        )
        self.assertEqual(resumed["completed_steps"], list(self.finalize.TRANSITION_STEPS))
        self.assertEqual(resumed_calls[:2], [["probe", self.finalize.TRANSITION_STEPS[0]], ["probe", self.finalize.TRANSITION_STEPS[1]]])


if __name__ == "__main__":
    unittest.main()
