import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / "docs" / "upstream" / "UPSTREAM_BASELINE.json"
SCHEMA_PATH = ROOT / "docs" / "upstream" / "UPSTREAM_BASELINE.schema.json"
SOURCE_PLAN_PATH = (
    ROOT
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-08-22-z1rr-racetime-source-preservation.md"
)


class BaselineSchemaValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )

    def assertValid(self, instance):
        errors = sorted(
            self.validator.iter_errors(instance),
            key=lambda error: list(error.path),
        )
        self.assertEqual([], errors, "\n".join(error.message for error in errors))

    def assertInvalid(self, instance):
        self.assertTrue(list(self.validator.iter_errors(instance)))

    def test_committed_baseline_matches_draft_2020_12_schema_and_default_head(self):
        self.assertValid(self.baseline)
        self.assertEqual(
            self.baseline["branches"][self.baseline["default_branch"]],
            self.baseline["upstream_head"],
        )

    def test_schema_rejects_malformed_non_default_refs_and_other_contract_drift(self):
        mutations = []

        bad_branch = copy.deepcopy(self.baseline)
        bad_branch["branches"]["malformed-ref"] = "not-an-object-id"
        mutations.append(bad_branch)

        bad_tag = copy.deepcopy(self.baseline)
        bad_tag["tags"]["release"] = "f" * 39
        mutations.append(bad_tag)

        bad_timestamp = copy.deepcopy(self.baseline)
        bad_timestamp["captured_at_utc"] = "not-a-date-time"
        mutations.append(bad_timestamp)

        bad_url = copy.deepcopy(self.baseline)
        bad_url["upstream_url"] = "https://example.invalid/racetime-app.git"
        mutations.append(bad_url)

        bad_wiki = copy.deepcopy(self.baseline)
        bad_wiki["wiki"] = {"status": "archived", "sha256": "0" * 64}
        mutations.append(bad_wiki)

        extra_archive_field = copy.deepcopy(self.baseline)
        extra_archive_field["source_bundle"]["unexpected"] = True
        mutations.append(extra_archive_field)

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertInvalid(mutation)

    def test_final_verification_uses_complete_remote_guard_and_exact_source_bundle(self):
        plan = SOURCE_PLAN_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "pwsh scripts\\source\\check-remotes.ps1 -Repository . "
            "-MetadataPath docs\\upstream\\UPSTREAM_BASELINE.json "
            "-ExpectedForkDefaultBranch master",
            plan,
        )
        self.assertIn("$sourceBaseline.source_bundle.file", plan)
        self.assertNotIn(
            "Get-ChildItem artifacts\\source\\racetime-app-*.bundle",
            plan,
        )


if __name__ == "__main__":
    unittest.main()
