from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "collect-release-identities.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collector = load_module("z1rr_release_identity", SCRIPT)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repos = {}
        for name in ("racetime", "restream", "ttpbot", "livesplit"):
            repo = self.root / name
            repo.mkdir()
            self.git(repo, "init", "-b", "z1rr-production")
            self.git(repo, "config", "user.name", "Test Operator")
            self.git(repo, "config", "user.email", "operator@example.invalid")
            (repo / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            self.repos[name] = repo

        racetime = self.repos["racetime"]
        (racetime / "racetime" / "migrations").mkdir(parents=True)
        (racetime / "racetime" / "migrations" / "0081_prior.py").write_text("# prior\n")
        (racetime / "racetime" / "migrations" / "0082_externalidentity.py").write_text("# leaf\n")
        (racetime / "config.schema.json").write_text('{"schema_version": 1}\n')
        self.commit(racetime, "base")
        racetime_commit = self.git(racetime, "rev-parse", "HEAD").strip()
        self.racetime_identity = self.root / "racetime-release-identities.json"
        self.racetime_identity.write_text(json.dumps({
            "schema_version": 1,
            "source_commit": racetime_commit,
            "images": {
                "web": {"manifest_digest": "sha256:" + "a" * 64},
                "racebot": {"manifest_digest": "sha256:" + "b" * 64},
            },
        }) + "\n")

        restream = self.repos["restream"]
        (restream / "dist").mkdir()
        (restream / "dist" / "restream.js").write_text("restream-build\n")
        self.commit(restream, "build")

        ttpbot = self.repos["ttpbot"]
        (ttpbot / "requirements.lock").write_text("requests==2.34.2\n")
        self.commit(ttpbot, "lock")

        livesplit = self.repos["livesplit"]
        (livesplit / "dist").mkdir()
        for filename, content in (
            ("Z1RR.RaceTime.dll", b"dll"),
            ("Z1RR.RaceTime.zip", b"package"),
            ("update.xml", b"update"),
        ):
            (livesplit / "dist" / filename).write_bytes(content)
        (livesplit / "dist" / "signature.json").write_text(
            json.dumps({"schema_version": 1, "key_id": "ABCD1234EF567890"}) + "\n"
        )
        self.commit(livesplit, "release")

    def git(self, repo, *args):
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        ).stdout

    def commit(self, repo, message, amend=False):
        self.git(repo, "add", ".")
        if amend:
            self.git(repo, "commit", "--amend", "--no-edit")
        else:
            self.git(repo, "commit", "-m", message)

    def config(self):
        return {
            "schema_version": 1,
            "expected_version": "1.2.3",
            "components": {
                "racetime": {
                    "repository": str(self.repos["racetime"]),
                    "expected_branch": "z1rr-production",
                    "version_files": ["VERSION"],
                    "release_identity": str(self.racetime_identity),
                    "migration_directory": "racetime/migrations",
                    "config_schema": "config.schema.json",
                },
                "restream": {
                    "repository": str(self.repos["restream"]),
                    "expected_branch": "z1rr-production",
                    "version_files": ["VERSION"],
                    "build_artifact": "dist/restream.js",
                },
                "ttpbot": {
                    "repository": str(self.repos["ttpbot"]),
                    "expected_branch": "z1rr-production",
                    "version_files": ["VERSION"],
                    "lock_file": "requirements.lock",
                },
                "livesplit": {
                    "repository": str(self.repos["livesplit"]),
                    "expected_branch": "z1rr-production",
                    "version_files": ["VERSION"],
                    "dll": "dist/Z1RR.RaceTime.dll",
                    "package": "dist/Z1RR.RaceTime.zip",
                    "update_manifest": "dist/update.xml",
                    "signature_metadata": "dist/signature.json",
                },
            },
        }

    def write_config(self, config=None):
        path = self.root / "release-paths.json"
        path.write_text(json.dumps(config or self.config(), indent=2) + "\n")
        return path

    def clean_identity_fixture(self):
        repo = self.repos["racetime"]
        identity = json.loads(self.racetime_identity.read_text())
        identity["source_commit"] = self.git(repo, "rev-parse", "HEAD").strip()
        self.racetime_identity.write_text(json.dumps(identity) + "\n")

    def test_collects_exact_clean_component_and_artifact_identities(self):
        # Use the collector's supported post-build metadata relationship.
        self.clean_identity_fixture()
        result = self.collector.collect_release_identities(self.write_config())
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(set(result["components"]), {"racetime", "restream", "ttpbot", "livesplit"})
        race = result["components"]["racetime"]
        self.assertEqual(race["migration_leaf"], "0082_externalidentity")
        self.assertRegex(race["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(race["web_image_digest"], "sha256:" + "a" * 64)
        self.assertEqual(race["racebot_image_digest"], "sha256:" + "b" * 64)
        self.assertEqual(race["config_schema_sha256"], digest(self.repos["racetime"] / "config.schema.json"))
        self.assertEqual(result["components"]["restream"]["build_sha256"], digest(self.repos["restream"] / "dist/restream.js"))
        self.assertEqual(result["components"]["ttpbot"]["lock_sha256"], digest(self.repos["ttpbot"] / "requirements.lock"))
        self.assertEqual(result["components"]["livesplit"]["signature_key_id"], "ABCD1234EF567890")

    def test_dirty_tree_branch_mismatch_missing_artifact_and_version_mismatch_fail(self):
        cases = []
        (self.repos["restream"] / "dirty.txt").write_text("dirty\n")
        cases.append(self.config())
        (self.repos["restream"] / "dirty.txt").unlink()
        config = self.config()
        config["components"]["ttpbot"]["expected_branch"] = "wrong"
        cases.append(config)
        config = self.config()
        config["components"]["livesplit"]["dll"] = "dist/missing.dll"
        cases.append(config)
        config = self.config()
        config["expected_version"] = "9.9.9"
        cases.append(config)
        # Recreate dirty state only for the first isolated subtest.
        for index, config in enumerate(cases):
            if index == 0:
                (self.repos["restream"] / "dirty.txt").write_text("dirty\n")
            with self.subTest(index=index), self.assertRaises(self.collector.ReleaseIdentityError):
                self.collector.collect_release_identities(self.write_config(config))
            if index == 0:
                (self.repos["restream"] / "dirty.txt").unlink()

    def test_mutable_images_wrong_source_commit_and_secret_paths_fail(self):
        self.clean_identity_fixture()
        repo = self.repos["racetime"]
        identity_path = self.racetime_identity
        original = json.loads(identity_path.read_text())
        for mutate in (
            lambda item: item["images"]["web"].update(manifest_digest="ghcr.io/example:web"),
            lambda item: item.update(source_commit="f" * 40),
        ):
            value = json.loads(json.dumps(original))
            mutate(value)
            identity_path.write_text(json.dumps(value) + "\n")
            with self.assertRaises(self.collector.ReleaseIdentityError):
                self.collector.collect_release_identities(self.write_config())
        identity_path.write_text(json.dumps(original) + "\n")
        config = self.config()
        config["components"]["ttpbot"]["lock_file"] = ".env"
        with self.assertRaises(self.collector.ReleaseIdentityError):
            self.collector.collect_release_identities(self.write_config(config))

    def test_cli_output_is_schema_versioned_and_path_free(self):
        self.clean_identity_fixture()
        config = self.write_config()
        output = self.root / "identities.json"
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = self.collector.main(["--config", str(config), "--output", str(output)])
        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue().strip(), "RELEASE_IDENTITIES=PASS components=4")
        rendered = output.read_text()
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn("repository", rendered)
        self.assertNotIn(".env", rendered)


if __name__ == "__main__":
    unittest.main()
