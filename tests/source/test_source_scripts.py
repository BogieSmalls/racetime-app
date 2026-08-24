import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / "docs" / "upstream" / "UPSTREAM_BASELINE.json"
SCHEMA_PATH = ROOT / "docs" / "upstream" / "UPSTREAM_BASELINE.schema.json"


class SourceMetadataTests(unittest.TestCase):
    def test_schema_locks_urls_fields_and_archive_shape(self):
        self.assertTrue(
            SCHEMA_PATH.is_file(),
            "UPSTREAM_BASELINE.schema.json must define the committed contract",
        )
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        required = {
            "captured_at_utc",
            "upstream_url",
            "fork_url",
            "default_branch",
            "upstream_head",
            "branches",
            "tags",
            "source_bundle",
            "wiki",
        }
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), required)
        self.assertEqual(
            schema["properties"]["upstream_url"]["const"],
            "https://github.com/racetimeGG/racetime-app.git",
        )
        self.assertEqual(
            schema["properties"]["fork_url"]["const"],
            "https://github.com/BogieSmalls/racetime-app.git",
        )
        self.assertEqual(
            set(schema["$defs"]["archive"]["required"]),
            {"file", "sha256", "bytes"},
        )

    def test_baseline_schema_requires_restore_fields(self):
        self.assertTrue(
            BASELINE_PATH.is_file(),
            "UPSTREAM_BASELINE.json must exist before its restore contract can pass",
        )
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        required = {
            "captured_at_utc",
            "upstream_url",
            "fork_url",
            "default_branch",
            "upstream_head",
            "branches",
            "tags",
            "source_bundle",
            "wiki",
        }
        self.assertEqual(set(baseline).intersection(required), required)
        self.assertRegex(baseline["upstream_head"], r"^[0-9a-f]{40}$")
        self.assertRegex(baseline["default_branch"], r"^[A-Za-z0-9._/-]+$")
        self.assertEqual(
            baseline["branches"][baseline["default_branch"]],
            baseline["upstream_head"],
        )
        self.assertRegex(
            baseline["source_bundle"]["sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertGreater(baseline["source_bundle"]["bytes"], 0)


if __name__ == "__main__":
    unittest.main()
