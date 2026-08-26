import copy
import json
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts.g0.contracts import (
    ContractError,
    load_json,
    redact_text,
    safe_relative_path,
    safe_sha256,
    validate_restream_history,
    validate_run_manifest,
    validate_tool_lock,
    validate_worker_evidence,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "deploy" / "g0"
SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
RUN_ID = "20260826t120000z-1234abcd"
PROJECT_PREFIX = f"z1rr-racetime-g0-{RUN_ID}"
PHASE_NAMES = (
    "preflight",
    "worker-setup",
    "images",
    "security-and-sbom",
    "services-and-configuration",
    "recovery-and-service-hardening",
    "cross-repository-evidence",
    "identities-and-gates",
    "cleanup",
)


def schema_errors(schema, value, root=None, location="$"):
    if isinstance(schema, bool):
        return [] if schema else [f"{location}: value is forbidden"]
    root = schema if root is None else root
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        return schema_errors(target, value, root, location)
    if "oneOf" in schema:
        matches = [
            not schema_errors(option, value, root, location)
            for option in schema["oneOf"]
        ]
        return [] if matches.count(True) == 1 else [f"{location}: oneOf mismatch"]

    errors = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{location}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{location}: value is outside enum")

    expected_type = schema.get("type")
    type_matches = {
        "object": lambda candidate: isinstance(candidate, dict),
        "array": lambda candidate: isinstance(candidate, list),
        "string": lambda candidate: isinstance(candidate, str),
        "integer": lambda candidate: isinstance(candidate, int)
        and not isinstance(candidate, bool),
        "number": lambda candidate: isinstance(candidate, (int, float))
        and not isinstance(candidate, bool),
        "boolean": lambda candidate: isinstance(candidate, bool),
        "null": lambda candidate: candidate is None,
    }
    if expected_type and not type_matches[expected_type](value):
        return errors + [f"{location}: expected {expected_type}"]

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        errors.extend(f"{location}: missing {key}" for key in sorted(missing))
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            errors.extend(f"{location}: unknown {key}" for key in sorted(unknown))
        for key in set(value) & set(properties):
            errors.extend(
                schema_errors(properties[key], value[key], root, f"{location}.{key}")
            )
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{location}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{location}: too many items")
        if schema.get("uniqueItems"):
            serialized = [json.dumps(item, sort_keys=True) for item in value]
            if len(set(serialized)) != len(value):
                errors.append(f"{location}: duplicate items")
        prefix_items = schema.get("prefixItems", [])
        for index, item_schema in enumerate(prefix_items[: len(value)]):
            errors.extend(
                schema_errors(item_schema, value[index], root, f"{location}[{index}]")
            )
        if not prefix_items and "items" in schema:
            for index, item in enumerate(value):
                errors.extend(
                    schema_errors(schema["items"], item, root, f"{location}[{index}]")
                )
        elif len(value) > len(prefix_items) and "items" in schema:
            for index in range(len(prefix_items), len(value)):
                errors.extend(
                    schema_errors(schema["items"], value[index], root, f"{location}[{index}]")
                )
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{location}: string too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{location}: string too long")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            errors.append(f"{location}: pattern mismatch")
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{location}: invalid date-time")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{location}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{location}: above maximum")
    return errors


def image_lock(name="buildkit"):
    return {
        "name": name,
        "kind": "image",
        "version": "v1.2.3",
        "reference": f"docker.io/example/{name}:v1.2.3@{SHA_A}",
        "index_digest": SHA_A,
        "platforms": [
            {"platform": "linux/arm64", "digest": SHA_B},
            {"platform": "linux/amd64", "digest": SHA_C},
        ],
    }


def binary_lock(name="buildx"):
    return {
        "name": name,
        "kind": "binary",
        "version": "v1.2.3",
        "url": f"https://artifacts.example.invalid/{name}-v1.2.3",
        "sha256": SHA_A,
        "executable_path": f"tools/{name}",
    }


def valid_run_manifest():
    phase_timeouts = (1800, 3600, 50400, 7200, 7200, 7200, 3600, 1800, 3600)
    return {
        "schema_version": 1,
        "run_id": RUN_ID,
        "project_prefix": PROJECT_PREFIX,
        "created_at_utc": "2026-08-26T12:00:00Z",
        "remote_root": f"/var/lib/z1rr-racetime/g0/{RUN_ID}",
        "aggregate_timeout_seconds": 86400,
        "lock_identities": {
            "docker_bootstrap_sha256": SHA_A,
            "tool_lock_sha256": SHA_B,
        },
        "sources": [
            {
                "name": "racetime",
                "branch": "feature/racetime-readiness",
                "commit": COMMIT_A,
                "local_path": "repositories/racetime",
                "bundle_path": "custody/racetime.bundle",
                "bundle_sha256": SHA_A,
                "archive_path": "custody/racetime.tar",
                "archive_sha256": SHA_B,
                "custody_class": "transient",
            },
            {
                "name": "restream",
                "branch": "master",
                "commit": COMMIT_B,
                "local_path": "repositories/restream",
                "bundle_path": "custody/restream.bundle",
                "bundle_sha256": SHA_B,
                "archive_path": "custody/restream.tar",
                "archive_sha256": SHA_C,
                "custody_class": "transient",
            },
        ],
        "outputs": [
            {
                "name": "worker-evidence.json",
                "path": "evidence/worker-evidence.json",
                "custody_class": "retained",
            },
            {
                "name": "raw-worker.log",
                "path": "transient/raw-worker.log",
                "custody_class": "transient",
            },
        ],
        "phases": [
            {"name": name, "timeout_seconds": timeout}
            for name, timeout in zip(PHASE_NAMES, phase_timeouts)
        ],
    }


def valid_bootstrap_lock():
    return {
        "schema_version": 1,
        "generated_at_utc": "2026-08-26T11:00:00Z",
        "host": {
            "distribution": "ubuntu",
            "release": "24.04",
            "architecture": "arm64",
        },
        "signing_key": {
            "url": "https://download.example.invalid/docker.asc",
            "sha256": SHA_A,
            "fingerprint": "A" * 40,
        },
        "repository": {
            "definition": "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] https://download.example.invalid noble stable",
            "inrelease_url": "https://download.example.invalid/dists/noble/InRelease",
            "inrelease_sha256": SHA_B,
        },
        "packages": [
            {
                "name": "docker-ce",
                "version": "5:28.3.3-1~ubuntu.24.04~noble",
                "architecture": "arm64",
                "origin": "Docker",
                "url": "https://download.example.invalid/docker-ce.deb",
                "sha256": SHA_C,
            }
        ],
        "allowed_package_delta": ["docker-ce"],
        "bootstrap_tools": {
            "buildx": binary_lock(),
            "buildkit": image_lock(),
            "runtime_probe": image_lock("runtime-probe"),
        },
    }


def valid_tool_lock():
    return {
        "schema_version": 1,
        "generated_at_utc": "2026-08-26T11:30:00Z",
        "bootstrap_lock_sha256": SHA_A,
        "tools": [binary_lock(), image_lock()],
    }


def phase_evidence(name, command_id):
    return {
        "name": name,
        "expected_result": "PASS",
        "observed_result": "PASS",
        "command_id": command_id,
        "exit_status": 0,
        "duration_seconds": 1.25,
        "stdout_sha256": SHA_A,
        "stderr_sha256": SHA_B,
        "retained_artifact_hashes": [SHA_C],
        "cleanup_state": "not-required",
    }


def valid_worker_evidence():
    return {
        "schema_version": 1,
        "run_id": RUN_ID,
        "project_prefix": PROJECT_PREFIX,
        "source_commit": COMMIT_A,
        "started_at_utc": "2026-08-26T12:00:00Z",
        "completed_at_utc": "2026-08-26T12:30:00Z",
        "result": "PASS",
        "phases": [
            phase_evidence(name, f"phase-{index:02d}")
            for index, name in enumerate(PHASE_NAMES, start=1)
        ],
        "retained_artifacts": [
            {
                "name": "worker-summary.md",
                "path": "evidence/worker-summary.md",
                "sha256": SHA_C,
                "custody_class": "retained",
            }
        ],
        "cleanup_state": "verified",
    }


def valid_restream_history():
    return {
        "schema_version": 1,
        "repository": "restream",
        "base_commit": COMMIT_A,
        "candidate_commit": COMMIT_B,
        "captured_at_utc": "2026-08-26T10:00:00Z",
        "findings": [
            {
                "rule_id": "generic-api-key",
                "path": "tests/fixtures/inactive-token.txt",
                "source_commit": COMMIT_A,
                "line": 7,
                "fingerprint_sha256": SHA_A,
                "classification": "test-fixture",
                "outside_candidate": True,
                "live_credential_disposition": "not-a-credential",
                "evidence_id": "RESTREAM-HISTORY-001",
            }
        ],
    }


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = {}
        for name in (
            "run-manifest",
            "docker-bootstrap-lock",
            "tool-lock",
            "worker-evidence",
            "restream-history",
        ):
            schema = json.loads(
                (SCHEMA_ROOT / f"{name}.schema.json").read_text(encoding="utf-8")
            )
            cls.schemas[name] = schema

    def assertSchemaValid(self, schema_name, value):
        errors = schema_errors(self.schemas[schema_name], value)
        self.assertEqual([], errors, "\n".join(errors))

    def assertSchemaInvalid(self, schema_name, value):
        self.assertTrue(schema_errors(self.schemas[schema_name], value))

    def assertClosed(self, value, location="$"):
        if isinstance(value, dict):
            if value.get("type") == "object":
                self.assertIs(
                    False,
                    value.get("additionalProperties"),
                    f"open object schema at {location}",
                )
            for key, child in value.items():
                self.assertClosed(child, f"{location}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self.assertClosed(child, f"{location}[{index}]")

    def test_schemas_are_draft_2020_12_closed_and_have_exact_top_level_keys(self):
        expected = {
            "run-manifest": {
                "schema_version",
                "run_id",
                "project_prefix",
                "created_at_utc",
                "remote_root",
                "aggregate_timeout_seconds",
                "lock_identities",
                "sources",
                "outputs",
                "phases",
            },
            "docker-bootstrap-lock": {
                "schema_version",
                "generated_at_utc",
                "host",
                "signing_key",
                "repository",
                "packages",
                "allowed_package_delta",
                "bootstrap_tools",
            },
            "tool-lock": {
                "schema_version",
                "generated_at_utc",
                "bootstrap_lock_sha256",
                "tools",
            },
            "worker-evidence": {
                "schema_version",
                "run_id",
                "project_prefix",
                "source_commit",
                "started_at_utc",
                "completed_at_utc",
                "result",
                "phases",
                "retained_artifacts",
                "cleanup_state",
            },
            "restream-history": {
                "schema_version",
                "repository",
                "base_commit",
                "candidate_commit",
                "captured_at_utc",
                "findings",
            },
        }
        for name, keys in expected.items():
            with self.subTest(schema=name):
                schema = self.schemas[name]
                self.assertEqual(
                    "https://json-schema.org/draft/2020-12/schema", schema["$schema"]
                )
                self.assertEqual(keys, set(schema["required"]))
                self.assertEqual(keys, set(schema["properties"]))
                self.assertClosed(schema)

    def test_valid_contracts_match_schemas_and_runtime_validators(self):
        values = {
            "run-manifest": valid_run_manifest(),
            "docker-bootstrap-lock": valid_bootstrap_lock(),
            "tool-lock": valid_tool_lock(),
            "worker-evidence": valid_worker_evidence(),
            "restream-history": valid_restream_history(),
        }
        direct_validators = {
            "run-manifest": validate_run_manifest,
            "tool-lock": validate_tool_lock,
            "worker-evidence": validate_worker_evidence,
            "restream-history": validate_restream_history,
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for schema_name, value in values.items():
                with self.subTest(contract=schema_name):
                    self.assertSchemaValid(schema_name, value)
                    if schema_name in direct_validators:
                        self.assertEqual(value, direct_validators[schema_name](value))
                    path = root / f"{schema_name}.json"
                    path.write_text(json.dumps(value), encoding="utf-8")
                    self.assertEqual(value, load_json(path, schema_name))

    def test_committed_example_is_valid_and_uses_separate_lock_identities(self):
        example = json.loads(
            (SCHEMA_ROOT / "run-manifest.example.json").read_text(encoding="utf-8")
        )
        self.assertEqual(valid_run_manifest(), example)
        validated = validate_run_manifest(example)
        self.assertEqual(
            {"docker_bootstrap_sha256", "tool_lock_sha256"},
            set(validated["lock_identities"]),
        )
        self.assertNotEqual(
            validated["lock_identities"]["docker_bootstrap_sha256"],
            validated["lock_identities"]["tool_lock_sha256"],
        )

    def test_schema_version_commit_digest_and_utc_timestamp_are_exact(self):
        mutations = []
        bad_schema = valid_run_manifest()
        bad_schema["schema_version"] = 2
        mutations.append(("run-manifest", bad_schema, validate_run_manifest))
        bad_commit = valid_run_manifest()
        bad_commit["sources"][0]["commit"] = "a" * 39
        mutations.append(("run-manifest", bad_commit, validate_run_manifest))
        bad_digest = valid_tool_lock()
        bad_digest["tools"][0]["sha256"] = "a" * 64
        mutations.append(("tool-lock", bad_digest, validate_tool_lock))
        bad_timestamp = valid_worker_evidence()
        bad_timestamp["completed_at_utc"] = "2026-08-26T13:30:00+01:00"
        mutations.append(("worker-evidence", bad_timestamp, validate_worker_evidence))
        for schema_name, mutation, validator in mutations:
            with self.subTest(schema=schema_name, mutation=mutation):
                self.assertSchemaInvalid(schema_name, mutation)
                with self.assertRaises(ContractError):
                    validator(mutation)

    def test_run_identity_root_phase_order_and_timeouts_fail_closed(self):
        mutations = []
        bad_prefix = valid_run_manifest()
        bad_prefix["project_prefix"] = "z1rr-racetime-g0-other"
        mutations.append(bad_prefix)
        bad_root = valid_run_manifest()
        bad_root["remote_root"] = f"/tmp/{RUN_ID}"
        mutations.append(bad_root)
        relative_root = valid_run_manifest()
        relative_root["remote_root"] = f"var/lib/z1rr-racetime/g0/{RUN_ID}"
        mutations.append(relative_root)
        wrong_order = valid_run_manifest()
        wrong_order["phases"][0], wrong_order["phases"][1] = (
            wrong_order["phases"][1],
            wrong_order["phases"][0],
        )
        mutations.append(wrong_order)
        missing_timeout = valid_run_manifest()
        del missing_timeout["phases"][2]["timeout_seconds"]
        mutations.append(missing_timeout)
        excessive_phase_timeout = valid_run_manifest()
        excessive_phase_timeout["phases"][2]["timeout_seconds"] = 86401
        mutations.append(excessive_phase_timeout)
        excessive_aggregate = valid_run_manifest()
        excessive_aggregate["aggregate_timeout_seconds"] = 86401
        mutations.append(excessive_aggregate)
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertSchemaInvalid("run-manifest", mutation)
                with self.assertRaises(ContractError):
                    validate_run_manifest(mutation)

    def test_paths_are_workspace_relative_and_outputs_have_safe_names(self):
        for unsafe in (
            "../secrets.env",
            "/home/operator/.ssh/id_ed25519",
            "C:/Users/operator/.ssh/id_ed25519",
            "\\\\server\\share\\private.json",
            "~/.ssh/id_ed25519",
            "evidence\\report.json",
        ):
            with self.subTest(path=unsafe):
                with self.assertRaises(ContractError):
                    safe_relative_path(unsafe, "test path")

        traversal = valid_run_manifest()
        traversal["sources"][0]["local_path"] = "repositories/../private"
        self.assertSchemaInvalid("run-manifest", traversal)
        with self.assertRaises(ContractError):
            validate_run_manifest(traversal)

        for unsafe_name in ("../report.json", ".private", "report name.json"):
            manifest = valid_run_manifest()
            manifest["outputs"][0]["name"] = unsafe_name
            with self.subTest(output=unsafe_name):
                self.assertSchemaInvalid("run-manifest", manifest)
                with self.assertRaises(ContractError):
                    validate_run_manifest(manifest)

    def test_custody_classes_are_only_retained_or_transient(self):
        manifest = valid_run_manifest()
        manifest["outputs"][0]["custody_class"] = "private"
        self.assertSchemaInvalid("run-manifest", manifest)
        with self.assertRaises(ContractError):
            validate_run_manifest(manifest)

    def test_unknown_symlink_and_secret_like_runtime_fields_are_rejected(self):
        mutations = []
        unknown = valid_run_manifest()
        unknown["unexpected"] = True
        mutations.append(unknown)
        symlink = valid_run_manifest()
        symlink["sources"][0]["symlink"] = True
        mutations.append(symlink)
        runtime_secret = valid_run_manifest()
        runtime_secret["discord_token"] = "must-not-be-committed"
        mutations.append(runtime_secret)
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertSchemaInvalid("run-manifest", mutation)
                with self.assertRaises(ContractError):
                    validate_run_manifest(mutation)

    def test_load_json_rejects_symlinks_non_objects_unknown_schemas_and_bad_json(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "manifest.json"
            target.write_text(json.dumps(valid_run_manifest()), encoding="utf-8")
            link = root / "manifest-link.json"
            try:
                link.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlink creation is unavailable: {error}")
            with self.assertRaises(ContractError):
                load_json(link, "run-manifest")

            non_object = root / "array.json"
            non_object.write_text("[]", encoding="utf-8")
            with self.assertRaises(ContractError):
                load_json(non_object, "run-manifest")

            bad_json = root / "bad.json"
            bad_json.write_text("{", encoding="utf-8")
            with self.assertRaises(ContractError):
                load_json(bad_json, "run-manifest")

            with self.assertRaises(ContractError):
                load_json(target, "not-a-contract")

    def test_tool_images_require_immutable_digest_references(self):
        for reference in (
            "docker.io/example/buildkit:latest",
            "docker.io/example/buildkit:v1.2.3",
            "docker.io/example/buildkit@sha256:short",
        ):
            lock = valid_tool_lock()
            lock["tools"][1]["reference"] = reference
            with self.subTest(reference=reference):
                self.assertSchemaInvalid("tool-lock", lock)
                with self.assertRaises(ContractError):
                    validate_tool_lock(lock)

    def test_worker_evidence_has_safe_results_and_hashes_but_no_raw_logs_or_matches(self):
        evidence = valid_worker_evidence()
        required_phase_keys = {
            "name",
            "expected_result",
            "observed_result",
            "command_id",
            "exit_status",
            "duration_seconds",
            "stdout_sha256",
            "stderr_sha256",
            "retained_artifact_hashes",
            "cleanup_state",
        }
        self.assertEqual(required_phase_keys, set(evidence["phases"][0]))
        for forbidden_key in ("stdout", "stderr", "raw_log", "raw_match"):
            mutation = copy.deepcopy(evidence)
            mutation["phases"][0][forbidden_key] = "credential material"
            with self.subTest(forbidden=forbidden_key):
                self.assertSchemaInvalid("worker-evidence", mutation)
                with self.assertRaises(ContractError):
                    validate_worker_evidence(mutation)

    def test_restream_history_is_metadata_only_and_requires_safe_disposition(self):
        for key, value in (
            ("raw_match", "secret"),
            ("possible_live", True),
            ("local_path", "C:/Users/operator/restream"),
        ):
            history = valid_restream_history()
            history["findings"][0][key] = value
            with self.subTest(key=key):
                self.assertSchemaInvalid("restream-history", history)
                with self.assertRaises(ContractError):
                    validate_restream_history(history)

        possible_live = valid_restream_history()
        possible_live["findings"][0]["live_credential_disposition"] = "possible-live"
        self.assertSchemaInvalid("restream-history", possible_live)
        with self.assertRaises(ContractError):
            validate_restream_history(possible_live)

    def test_safe_sha256_and_redaction_are_fail_closed(self):
        self.assertEqual(SHA_A, safe_sha256(SHA_A, "artifact"))
        for invalid in ("a" * 64, "sha256:" + "A" * 64, SHA_A + "0", None):
            with self.subTest(value=invalid):
                with self.assertRaises(ContractError):
                    safe_sha256(invalid, "artifact")

        redacted = redact_text(
            "canary-alpha token=runtime-secret private_key=key-material",
            ["canary-alpha", "runtime-secret", "key-material"],
        )
        self.assertNotIn("canary-alpha", redacted)
        self.assertNotIn("runtime-secret", redacted)
        self.assertNotIn("key-material", redacted)
        self.assertIn("[REDACTED]", redacted)


if __name__ == "__main__":
    unittest.main()
