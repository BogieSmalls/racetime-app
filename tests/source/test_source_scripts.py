import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / "docs" / "upstream" / "UPSTREAM_BASELINE.json"
SCHEMA_PATH = ROOT / "docs" / "upstream" / "UPSTREAM_BASELINE.schema.json"
REMOTE_GUARD_PATH = ROOT / "scripts" / "source" / "check-remotes.ps1"


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


class RemoteGuardTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="z1rr-source-remotes-")
        self.root = Path(self._temp.name)
        self.seed = self.root / "seed"
        self.upstream = self.root / "upstream.git"
        self.origin = self.root / "origin.git"
        self.checkout = self.root / "checkout"
        self.metadata_path = self.root / "baseline.json"

        self._git("init", "--initial-branch=master", str(self.seed))
        self._git("-C", str(self.seed), "config", "user.name", "Z1RR Test")
        self._git("-C", str(self.seed), "config", "user.email", "z1rr@example.invalid")
        (self.seed / "README.md").write_text("baseline\n", encoding="utf-8")
        self._git("-C", str(self.seed), "add", "README.md")
        self._git("-C", str(self.seed), "commit", "-m", "baseline")
        self.baseline_head = self._git(
            "-C", str(self.seed), "rev-parse", "HEAD", capture=True
        ).strip()

        for remote in (self.upstream, self.origin):
            self._git("init", "--bare", str(remote))
            self._git(
                "-C",
                str(self.seed),
                "push",
                remote.as_uri(),
                "HEAD:refs/heads/master",
            )
            self._git(
                "--git-dir",
                str(remote),
                "symbolic-ref",
                "HEAD",
                "refs/heads/master",
            )

        self._git("init", str(self.checkout))
        self._git(
            "-C", str(self.checkout), "remote", "add", "origin", self.origin.as_uri()
        )
        self._git(
            "-C",
            str(self.checkout),
            "remote",
            "add",
            "upstream",
            self.upstream.as_uri(),
        )
        self._git(
            "-C", str(self.checkout), "remote", "set-url", "--push", "upstream", "DISABLED"
        )
        self._write_metadata()

    def tearDown(self):
        self._temp.cleanup()

    def _git(self, *args, capture=False):
        result = subprocess.run(
            ["git", *args],
            check=True,
            cwd=self.root,
            text=True,
            capture_output=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        return result.stdout if capture else ""

    def _write_metadata(self):
        metadata = {
            "upstream_url": self.upstream.as_uri(),
            "fork_url": self.origin.as_uri(),
            "default_branch": "master",
            "upstream_head": self.baseline_head,
        }
        self.metadata_path.write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )

    def _run_guard(self, expected_default="master"):
        self.assertTrue(
            REMOTE_GUARD_PATH.is_file(),
            "check-remotes.ps1 must exist before remote-boundary tests can pass",
        )
        return subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-File",
                str(REMOTE_GUARD_PATH),
                "-Repository",
                str(self.checkout),
                "-MetadataPath",
                str(self.metadata_path),
                "-ExpectedForkDefaultBranch",
                expected_default,
                "-AllowNonGitHubFixture",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )

    def _assert_guard_rejects_without_urls(self):
        result = self._run_guard()
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertNotIn(self.upstream.as_uri(), combined)
        self.assertNotIn(self.origin.as_uri(), combined)

    def test_accepts_exact_fetch_urls_disabled_push_and_default_heads(self):
        result = self._run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "PASS: origin/upstream source boundary is configured.",
        )

    def test_rejects_swapped_origin_and_upstream(self):
        self._git(
            "-C", str(self.checkout), "remote", "set-url", "origin", self.upstream.as_uri()
        )
        self._git(
            "-C", str(self.checkout), "remote", "set-url", "upstream", self.origin.as_uri()
        )
        self._assert_guard_rejects_without_urls()

    def test_rejects_enabled_upstream_push(self):
        self._git(
            "-C", str(self.checkout), "remote", "set-url", "--push", "upstream",
            "https://example.invalid/upstream.git",
        )
        self._assert_guard_rejects_without_urls()

    def test_rejects_missing_upstream(self):
        self._git("-C", str(self.checkout), "remote", "remove", "upstream")
        self._assert_guard_rejects_without_urls()

    def test_rejects_upstream_head_different_from_baseline(self):
        (self.seed / "README.md").write_text("changed\n", encoding="utf-8")
        self._git("-C", str(self.seed), "commit", "-am", "change upstream")
        self._git(
            "-C", str(self.seed), "push", "--force", self.upstream.as_uri(),
            "HEAD:refs/heads/master",
        )
        self._assert_guard_rejects_without_urls()

    def test_rejects_unexpected_origin_default_branch(self):
        self._git(
            "-C", str(self.seed), "push", self.origin.as_uri(),
            "HEAD:refs/heads/other",
        )
        self._git(
            "--git-dir", str(self.origin), "symbolic-ref", "HEAD", "refs/heads/other"
        )
        self._assert_guard_rejects_without_urls()



if __name__ == "__main__":
    unittest.main()
