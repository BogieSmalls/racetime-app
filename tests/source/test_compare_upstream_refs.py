import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPARATOR_PATH = ROOT / "scripts" / "source" / "compare-upstream-refs.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "upstream-drift.yml"

A = "a" * 40
B = "b" * 40
C = "c" * 40
D = "d" * 40


def load_comparator():
    if not COMPARATOR_PATH.is_file():
        raise FileNotFoundError(COMPARATOR_PATH)
    spec = importlib.util.spec_from_file_location("compare_upstream_refs", COMPARATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RefComparatorTests(unittest.TestCase):
    def setUp(self):
        self.baseline = {
            "default_branch": "master",
            "upstream_head": A,
            "branches": {"legacy": B, "master": A, "same": C},
            "tags": {"old": A, "same": B, "version": C},
        }
        self.current = {
            "default_branch": "main",
            "upstream_head": D,
            "branches": {"added": A, "main": D, "master": B, "same": C},
            "tags": {"new": D, "same": B, "version": A},
        }

    def test_reports_deterministic_added_removed_changed_and_default_head(self):
        module = load_comparator()
        result = module.compare_refs(self.baseline, self.current)
        self.assertEqual(
            result,
            {
                "default": {
                    "changed": True,
                    "before_branch": "master",
                    "after_branch": "main",
                    "before_head": A,
                    "after_head": D,
                },
                "branches": {
                    "added": {"added": A, "main": D},
                    "removed": {"legacy": B},
                    "changed": {"master": {"before": A, "after": B}},
                },
                "tags": {
                    "added": {"new": D},
                    "removed": {"old": A},
                    "changed": {"version": {"before": C, "after": A}},
                },
                "has_drift": True,
            },
        )
        report = module.render_markdown(result)
        self.assertLess(
            report.index("| Added | `added`"),
            report.index("| Added | `main`"),
        )
        self.assertIn("Default HEAD | `master`", report)
        self.assertIn("Result: **DRIFT DETECTED**", report)

    def test_identical_refs_report_no_drift(self):
        module = load_comparator()
        result = module.compare_refs(self.baseline, json.loads(json.dumps(self.baseline)))
        self.assertFalse(result["has_drift"])
        self.assertIn("Result: **NO DRIFT**", module.render_markdown(result))

    def test_cli_writes_report_and_uses_exit_status_for_drift(self):
        with tempfile.TemporaryDirectory(prefix="z1rr-ref-compare-") as temp:
            root = Path(temp)
            baseline = root / "baseline.json"
            current = root / "current.json"
            report = root / "report.md"
            baseline.write_text(json.dumps(self.baseline), encoding="utf-8")
            current.write_text(json.dumps(self.current), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(COMPARATOR_PATH),
                    "--baseline",
                    str(baseline),
                    "--captured",
                    str(current),
                    "--output",
                    str(report),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(result.stdout, report.read_text(encoding="utf-8"))
            self.assertIn("DRIFT DETECTED", result.stdout)

            current.write_text(json.dumps(self.baseline), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(COMPARATOR_PATH),
                    "--baseline",
                    str(baseline),
                    "--captured",
                    str(current),
                    "--output",
                    str(report),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("NO DRIFT", result.stdout)

    def test_rejects_malformed_ref_capture(self):
        module = load_comparator()
        malformed = json.loads(json.dumps(self.current))
        malformed["branches"]["master"] = "not-an-object-id"
        with self.assertRaises(ValueError):
            module.compare_refs(self.baseline, malformed)


class DriftWorkflowContractTests(unittest.TestCase):
    def test_workflow_is_read_only_locally_testable_and_g1_activatable(self):
        self.assertTrue(WORKFLOW_PATH.is_file(), "upstream-drift.yml must exist")
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        for required in (
            "workflow_dispatch:",
            "schedule:",
            "contents: read",
            "test_compare_upstream_refs",
            "compare-upstream-refs.py",
            "actions/upload-artifact@",
            "upstream-drift-report",
            "git ls-remote --symref",
        ):
            with self.subTest(required=required):
                self.assertIn(required, workflow)
        for forbidden in (
            "contents: write",
            "pull-requests: write",
            "deployments: write",
            "git push",
            "gh pr create",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, workflow)

    def test_workflow_documents_default_branch_activation_boundary(self):
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("G0", workflow)
        self.assertIn("z1rr-production", workflow)
        self.assertIn("default branch", workflow.lower())


if __name__ == "__main__":
    unittest.main()
