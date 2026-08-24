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
PRESERVE_PATH = ROOT / "scripts" / "source" / "preserve-upstream.ps1"
VERIFY_PATH = ROOT / "scripts" / "source" / "verify-upstream-archive.ps1"
RESTORE_RUNBOOK_PATH = ROOT / "docs" / "upstream" / "RESTORE.md"




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



class ArchiveCreationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="z1rr-source-archive-")
        self.root = Path(self._temp.name)
        self.seed = self.root / "seed"
        self.upstream = self.root / "upstream.git"
        self.wiki_seed = self.root / "wiki-seed"
        self.wiki = self.root / "upstream.wiki.git"
        self.empty_wiki = self.root / "empty.wiki.git"
        self.output = self.root / "artifacts" / "source"
        self.metadata = self.root / "metadata"

        self._git("init", "--initial-branch=master", str(self.seed))
        self._configure_identity(self.seed)
        (self.seed / "README.md").write_text("master\n", encoding="utf-8")
        self._git("-C", str(self.seed), "add", "README.md")
        self._git("-C", str(self.seed), "commit", "-m", "master")
        self.master_head = self._git(
            "-C", str(self.seed), "rev-parse", "HEAD", capture=True
        ).strip()
        self._git("-C", str(self.seed), "tag", "v1")
        self._git("-C", str(self.seed), "checkout", "-b", "async")
        (self.seed / "ASYNC.md").write_text("async\n", encoding="utf-8")
        self._git("-C", str(self.seed), "add", "ASYNC.md")
        self._git("-C", str(self.seed), "commit", "-m", "async")
        self._git("-C", str(self.seed), "tag", "v2")
        self._git("-C", str(self.seed), "checkout", "master")

        self._git("init", "--bare", str(self.upstream))
        self._git(
            "-C", str(self.seed), "push", self.upstream.as_uri(),
            "master", "async", "--tags",
        )
        self._git(
            "--git-dir", str(self.upstream), "symbolic-ref", "HEAD", "refs/heads/master"
        )

        self._git("init", "--initial-branch=master", str(self.wiki_seed))
        self._configure_identity(self.wiki_seed)
        (self.wiki_seed / "Home.md").write_text("wiki\n", encoding="utf-8")
        self._git("-C", str(self.wiki_seed), "add", "Home.md")
        self._git("-C", str(self.wiki_seed), "commit", "-m", "wiki")
        self._git("init", "--bare", str(self.wiki))
        self._git(
            "-C", str(self.wiki_seed), "push", self.wiki.as_uri(),
            "HEAD:refs/heads/master",
        )
        self._git(
            "--git-dir", str(self.wiki), "symbolic-ref", "HEAD", "refs/heads/master"
        )
        self._git("init", "--bare", str(self.empty_wiki))

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

    def _configure_identity(self, repository):
        self._git("-C", str(repository), "config", "user.name", "Z1RR Test")
        self._git(
            "-C", str(repository), "config", "user.email", "z1rr@example.invalid"
        )

    def _run_preserve(self, *, wiki_url=None, upstream_url=None, output=None):
        self.assertTrue(
            PRESERVE_PATH.is_file(),
            "preserve-upstream.ps1 must exist before archive tests can pass",
        )
        command = [
            "pwsh",
            "-NoProfile",
            "-File",
            str(PRESERVE_PATH),
            "-UpstreamUrl",
            upstream_url or self.upstream.as_uri(),
            "-ForkUrl",
            (self.root / "fork.git").as_uri(),
            "-OutputDirectory",
            str(output or self.output),
            "-MetadataDirectory",
            str(self.metadata),
            "-AllowNonGitHubFixture",
        ]
        if wiki_url is not None:
            command.extend(["-WikiUrl", wiki_url])
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )

    def _load_baseline(self):
        return json.loads(
            (self.metadata / "UPSTREAM_BASELINE.json").read_text(encoding="utf-8")
        )

    def test_creates_verified_source_and_wiki_bundles_with_complete_refs(self):
        result = self._run_preserve(wiki_url=self.wiki.as_uri())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        baseline = self._load_baseline()

        self.assertEqual(baseline["default_branch"], "master")
        self.assertEqual(baseline["upstream_head"], self.master_head)
        self.assertEqual(set(baseline["branches"]), {"async", "master"})
        self.assertEqual(set(baseline["tags"]), {"v1", "v2"})
        self.assertEqual(
            baseline["branches"][baseline["default_branch"]],
            baseline["upstream_head"],
        )
        self.assertEqual(baseline["wiki"]["status"], "archived")

        archived = [baseline["source_bundle"], baseline["wiki"]]
        for item in archived:
            bundle = self.output / item["file"]
            self.assertTrue(bundle.is_file())
            self.assertEqual(bundle.stat().st_size, item["bytes"])
            self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")

        sums = (self.metadata / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sums, sorted(sums, key=lambda line: line.split()[-1]))
        self.assertEqual(len(sums), 2)
        self.assertNotIn(str(self.root), json.dumps(baseline))
        self.assertFalse(list(self.root.rglob("*.partial")))
        self.assertFalse(list((self.output.parent).glob(".source-preservation-scratch-*")))

    def test_records_absent_wiki_when_probe_succeeds_without_refs(self):
        result = self._run_preserve(wiki_url=self.empty_wiki.as_uri())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        baseline = self._load_baseline()
        self.assertEqual(baseline["wiki"], {"status": "absent"})
        self.assertEqual(len(list(self.output.glob("racetime-app-*.bundle"))), 1)

    def test_git_failure_leaves_no_partial_or_final_archive(self):
        empty_upstream = self.root / "empty-upstream.git"
        self._git("init", "--bare", str(empty_upstream))
        result = self._run_preserve(upstream_url=empty_upstream.as_uri())
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list(self.output.glob("*.bundle")))
        self.assertFalse(list(self.root.rglob("*.partial")))
        self.assertFalse(list((self.output.parent).glob(".source-preservation-scratch-*")))

    def test_rejects_repository_root_and_git_directory_as_output(self):
        for unsafe in (ROOT, ROOT / ".git"):
            with self.subTest(unsafe=unsafe.name):
                result = self._run_preserve(output=unsafe)
                self.assertNotEqual(result.returncode, 0)

class RestoreVerificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ArchiveCreationTests(methodName="runTest")
        self.fixture.setUp()
        result = self.fixture._run_preserve(wiki_url=self.fixture.wiki.as_uri())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.root = self.fixture.root
        self.output = self.fixture.output
        self.metadata = self.fixture.metadata
        self.restore = self.root / "restore"

    def tearDown(self):
        self.fixture.tearDown()

    def _run_verify(self, restore=None):
        self.assertTrue(
            VERIFY_PATH.is_file(),
            "verify-upstream-archive.ps1 must exist before restore tests can pass",
        )
        return subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-File",
                str(VERIFY_PATH),
                "-ArchiveDirectory",
                str(self.output),
                "-MetadataDirectory",
                str(self.metadata),
                "-RestoreDirectory",
                str(restore or self.restore),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )

    def _baseline(self):
        return json.loads(
            (self.metadata / "UPSTREAM_BASELINE.json").read_text(encoding="utf-8")
        )

    def _write_baseline(self, baseline):
        (self.metadata / "UPSTREAM_BASELINE.json").write_text(
            json.dumps(baseline, indent=2) + "\n", encoding="utf-8"
        )

    def _assert_rejected(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("PASS:", result.stdout + result.stderr)

    def test_restores_exact_default_branch_all_refs_and_wiki(self):
        result = self._run_verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        baseline = self._baseline()
        branch = subprocess.run(
            ["git", "-C", str(self.restore), "symbolic-ref", "--short", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "-C", str(self.restore), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        self.assertEqual(branch, baseline["default_branch"])
        self.assertEqual(head, baseline["upstream_head"])
        for name, object_id in baseline["branches"].items():
            actual = self.fixture._git(
                "-C", str(self.restore), "rev-parse", f"refs/heads/{name}",
                capture=True,
            ).strip()
            self.assertEqual(actual, object_id)
        for name, object_id in baseline["tags"].items():
            actual = self.fixture._git(
                "-C", str(self.restore), "rev-parse", f"refs/tags/{name}",
                capture=True,
            ).strip()
            self.assertEqual(actual, object_id)
        self.assertTrue((self.restore / "wiki" / ".git").is_dir())

    def test_rejects_one_byte_bundle_tamper(self):
        baseline = self._baseline()
        bundle = self.output / baseline["source_bundle"]["file"]
        with bundle.open("ab") as archive:
            archive.write(b"x")
        self._assert_rejected(self._run_verify())

    def test_rejects_wrong_manifest_hash(self):
        baseline = self._baseline()
        baseline["source_bundle"]["sha256"] = "0" * 64
        self._write_baseline(baseline)
        self._assert_rejected(self._run_verify())

    def test_rejects_non_empty_restore_target(self):
        self.restore.mkdir()
        (self.restore / "keep.txt").write_text("keep\n", encoding="utf-8")
        self._assert_rejected(self._run_verify())
        self.assertEqual((self.restore / "keep.txt").read_text(), "keep\n")

    def test_rejects_missing_recorded_branch(self):
        baseline = self._baseline()
        baseline["branches"]["missing"] = baseline["upstream_head"]
        self._write_baseline(baseline)
        self._assert_rejected(self._run_verify())

    def test_rejects_missing_or_wrong_default_branch(self):
        original = self._baseline()
        for mutation in ("missing-property", "unknown-branch"):
            with self.subTest(mutation=mutation):
                baseline = json.loads(json.dumps(original))
                if mutation == "missing-property":
                    del baseline["default_branch"]
                else:
                    baseline["default_branch"] = "not-recorded"
                self._write_baseline(baseline)
                self._assert_rejected(self._run_verify())
                self._write_baseline(original)

    def test_rejects_reachable_non_default_upstream_head(self):
        baseline = self._baseline()
        baseline["upstream_head"] = baseline["branches"]["async"]
        self._write_baseline(baseline)
        self._assert_rejected(self._run_verify())

    def test_rejects_default_branch_tip_different_from_manifest(self):
        baseline = self._baseline()
        baseline["upstream_head"] = baseline["branches"]["async"]
        baseline["branches"]["master"] = baseline["branches"]["async"]
        self._write_baseline(baseline)
        self._assert_rejected(self._run_verify())

    def test_rejects_wiki_bundle_tamper(self):
        baseline = self._baseline()
        wiki_bundle = self.output / baseline["wiki"]["file"]
        with wiki_bundle.open("ab") as archive:
            archive.write(b"x")
        self._assert_rejected(self._run_verify())



class RestoreRunbookTests(unittest.TestCase):
    REQUIRED_SECTIONS = (
        "## Prerequisites",
        "## Create an archive",
        "## Verify an archive",
        "## Create the second copy",
        "## Restore into an empty directory",
        "## Recreate the GitHub fork",
        "## Reapply the upstream remote guard",
        "## Quarterly rehearsal",
        "## Custody and access",
        "## Incident handling",
    )

    def test_runbook_covers_creation_restoration_and_custody_contract(self):
        self.assertTrue(RESTORE_RUNBOOK_PATH.is_file(), "RESTORE.md must exist")
        content = RESTORE_RUNBOOK_PATH.read_text(encoding="utf-8")
        for section in self.REQUIRED_SECTIONS:
            with self.subTest(section=section):
                self.assertIn(section, content)
        for required in (
            "scripts\\source\\preserve-upstream.ps1",
            "scripts\\source\\verify-upstream-archive.ps1",
            "scripts\\source\\check-remotes.ps1",
            "https://github.com/racetimeGG/racetime-app.git",
            "https://github.com/BogieSmalls/racetime-app.git",
            "upstream_head",
            "default_branch",
            "z1rr-production",
            "git push --mirror",
        ):
            with self.subTest(required=required):
                self.assertIn(required, content)

    def test_runbook_forbids_single_copy_and_unverified_rotation(self):
        content = RESTORE_RUNBOOK_PATH.read_text(encoding="utf-8").lower()
        for required in (
            "not committed",
            "two independently controlled copies",
            "operator-held encrypted storage",
            "council-approved off-workstation storage",
            "do not delete the only verified prior archive",
            "non-empty destination",
            "destructive authorization",
        ):
            with self.subTest(required=required):
                self.assertIn(required, content)


if __name__ == "__main__":
    unittest.main()
