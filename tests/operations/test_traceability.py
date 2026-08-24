from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "validate-traceability.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TraceabilityValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_module("z1rr_validate_traceability", SCRIPT)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        evidence = self.root / "evidence"
        evidence.mkdir()
        for name in ("g0.md", "g1.md", "exception.md"):
            (evidence / name).write_text("# safe evidence\n", encoding="utf-8")

    def requirements(self, *, duplicate=False):
        text = """# Requirements

- **FR-TEST-001:** First requirement.
- **FR-TEST-002:** Second requirement.
- **NFR-TEST-001:** Third requirement.
"""
        if duplicate:
            text += "- **FR-TEST-001:** Duplicate.\n"
        return text

    def register(self, *, duplicate=False, orphan=False):
        rows = [
            "| APP-001 | G0 | `a` | A | pass |",
            "| APP-002 | G0 | `b` | B | pass |",
            "| OPS-001 | G1 | `c` | C | pass |",
            "| GOV-001 | G0 | `d` | D | pass |",
        ]
        if duplicate:
            rows.append("| APP-001 | G0 | `x` | duplicate | pass |")
        if orphan:
            rows.append("| OPS-999 | G4 | `x` | orphan | pass |")
        return """# Artifact register

| ID | Gate | Path | Artifact | Acceptance evidence |
| --- | --- | --- | --- | --- |
""" + "\n".join(rows) + "\n"

    def matrix(self, *, first_status="Verified ([evidence](evidence/g0.md))", second_status="Planned", bad_artifacts=None, duplicate_row=False, architecture="GOV-001"):
        artifacts = bad_artifacts or "APP-001–002"
        rows = [
            f"| FR-TEST-001 first | Task 1 | {artifacts} | test | G0 | {first_status} |",
            f"| FR-TEST-002 second | Task 2 | OPS-001 | test | G1 | {second_status} |",
            "| NFR-TEST-001 third | Task 3 | APP-002 | test | G4 | Planned |",
        ]
        if duplicate_row:
            rows.append(f"| FR-TEST-001 duplicate | Task 9 | APP-001 | test | G0 | {first_status} |")
        return """# Traceability

| Requirement | Plan/task | Artifacts | Verification | Gate | Status |
| --- | --- | --- | --- | --- | --- |
""" + "\n".join(rows) + f"""

## Architecture coverage not represented by a single requirement ID

| Architecture topic | Coverage |
| --- | --- |
| Control | {architecture} |
"""

    def write_inputs(self, *, requirements=None, register=None, matrix=None):
        paths = {
            "requirements": self.root / "requirements.md",
            "artifacts": self.root / "artifacts.md",
            "matrix": self.root / "matrix.md",
        }
        paths["requirements"].write_text(requirements or self.requirements(), encoding="utf-8")
        paths["artifacts"].write_text(register or self.register(), encoding="utf-8")
        paths["matrix"].write_text(matrix or self.matrix(), encoding="utf-8")
        return paths

    def validate(self, gate="G0", **kwargs):
        paths = self.write_inputs(**kwargs)
        return self.validator.validate_traceability(
            requirements_path=paths["requirements"],
            artifacts_path=paths["artifacts"],
            matrix_path=paths["matrix"],
            gate=gate,
        )

    def test_valid_gate_expands_same_prefix_ranges_and_reverse_coverage(self):
        summary = self.validate("G0")
        self.assertEqual(summary["requirements"], 3)
        self.assertEqual(summary["artifacts"], 4)
        self.assertEqual(summary["due"], 1)
        for gate in ("G0", "G1", "G2", "G3", "G4"):
            with self.subTest(gate=gate):
                matrix = self.matrix(
                    first_status="Verified ([evidence](evidence/g0.md))",
                    second_status="Verified ([evidence](evidence/g1.md))",
                ).replace(
                    "| NFR-TEST-001 third | Task 3 | APP-002 | test | G4 | Planned |",
                    "| NFR-TEST-001 third | Task 3 | APP-002 | test | G4 | Verified ([evidence](evidence/g1.md)) |",
                )
                self.validate(gate, matrix=matrix)

    def test_unknown_duplicate_requirement_and_artifact_definitions_fail(self):
        cases = (
            {"requirements": self.requirements(duplicate=True)},
            {"register": self.register(duplicate=True)},
            {"matrix": self.matrix(duplicate_row=True)},
            {"matrix": self.matrix().replace("FR-TEST-002", "FR-TEST-999")},
            {"matrix": self.matrix(bad_artifacts="APP-999")},
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(self.validator.TraceabilityError):
                self.validate(**case)

    def test_invalid_or_ambiguous_ranges_fail(self):
        for value in ("APP-002–001", "APP-001–OPS-001", "APP-001–999", "APP-001-002"):
            with self.subTest(value=value), self.assertRaises(self.validator.TraceabilityError):
                self.validate(matrix=self.matrix(bad_artifacts=value))

    def test_due_planned_invalid_status_and_terminal_without_good_link_fail(self):
        with self.assertRaises(self.validator.TraceabilityError):
            self.validate("G1")
        for status in (
            "Done",
            "Verified without link",
            "Verified ([evidence](evidence/missing.md))",
            "Accepted exception (no-id, [evidence](evidence/exception.md))",
        ):
            with self.subTest(status=status), self.assertRaises(self.validator.TraceabilityError):
                self.validate(matrix=self.matrix(first_status=status))

    def test_accepted_exception_requires_council_id_and_existing_evidence(self):
        status = "Accepted exception (COUNCIL-2026-004, [evidence](evidence/exception.md))"
        self.validate(matrix=self.matrix(first_status=status))

    def test_orphan_registered_artifact_fails_unless_architecture_covers_it(self):
        with self.assertRaises(self.validator.TraceabilityError):
            self.validate(register=self.register(orphan=True))
        self.validate(register=self.register(orphan=True), matrix=self.matrix(architecture="GOV-001, OPS-999"))

    def test_duplicate_status_links_and_unsafe_evidence_paths_fail(self):
        statuses = (
            "Verified ([one](evidence/g0.md), [two](evidence/g1.md))",
            "Verified ([evidence](../outside.md))",
            "Verified ([evidence](https://example.test/evidence))",
        )
        for status in statuses:
            with self.subTest(status=status), self.assertRaises(self.validator.TraceabilityError):
                self.validate(matrix=self.matrix(first_status=status))


if __name__ == "__main__":
    unittest.main()
