from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SHA_ACTION = re.compile(r"^\s*-?\s*uses:\s*([^\s@]+)@([0-9a-f]{40})\s*(?:#.*)?$")
ANY_ACTION = re.compile(r"^\s*-?\s*uses:\s*([^\s]+)", re.MULTILINE)


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container_path = WORKFLOWS / "container.yml"
        cls.release_path = WORKFLOWS / "release.yml"
        cls.container = cls.container_path.read_text(encoding="utf-8")
        cls.release = cls.release_path.read_text(encoding="utf-8")

    def test_every_external_action_in_every_workflow_is_immutable(self):
        failures = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "uses:" not in line or line.lstrip().startswith("#"):
                    continue
                match = SHA_ACTION.match(line)
                if not match:
                    failures.append(f"{path.name}:{number}:{line.strip()}")
        self.assertEqual(failures, [], "mutable action references: " + "; ".join(failures))

    def test_pull_request_workflow_is_read_only_and_never_pushes(self):
        text = self.container
        self.assertRegex(text, r"(?m)^on:\s*$")
        self.assertRegex(text, r"(?m)^\s{2}pull_request:\s*$")
        self.assertNotRegex(text, r"(?m)^\s{2}push:\s*$")
        self.assertRegex(text, r"(?ms)^permissions:\s*\n\s{2}contents:\s*read\s*$")
        self.assertNotIn("packages: write", text)
        self.assertNotIn("id-token: write", text)
        self.assertNotIn("secrets.", text)
        self.assertRegex(text, r"(?m)^\s+push:\s+false\s*$")
        self.assertNotIn("docker/login-action", text)

    def test_pr_builds_and_smokes_every_target_on_both_platforms(self):
        text = self.container
        for token in (
            "linux/arm64", "linux/amd64", "target: [web, racebot]",
            "python -m unittest discover -s tests -v",
            "python manage.py test --settings=project.settings.test -v 2",
            "npm audit --omit=dev",
            "tests/platform/smoke_images.ps1",
            "docker/setup-qemu-action", "docker/setup-buildx-action",
            "docker/build-push-action", "aquasecurity/trivy-action",
            "anchore/sbom-action", "spdx-json",
        ):
            with self.subTest(token=token):
                self.assertIn(token, text)
        self.assertRegex(text, r"(?s)severity:\s*CRITICAL,HIGH.*exit-code:\s*[\"']?1")
        self.assertIn("VCS_REF=${{ steps.identity.outputs.commit_sha }}", text)

    def test_release_requires_tag_or_protected_manual_dispatch(self):
        text = self.release
        self.assertRegex(text, r"(?m)^\s{2}workflow_dispatch:\s*$")
        self.assertRegex(text, r"(?ms)^\s{2}push:\s*\n\s{4}tags:\s*\n\s{6}-\s*[\"']v\*")
        self.assertIn("commit_sha:", text)
        self.assertIn("release_tag:", text)
        self.assertRegex(text, r"(?m)^\s+environment:\s+production\s*$")
        self.assertIn("git verify-tag", text)
        self.assertIn("RELEASE_SIGNING_PUBLIC_KEY_B64", text)
        self.assertIn("EXPECTED_SHA", text)
        self.assertIn("github.event.inputs.commit_sha", text)

    def test_release_permissions_are_explicit_and_minimal(self):
        text = self.release
        self.assertRegex(text, r"(?ms)^permissions:\s*\n\s{2}contents:\s*read\s*$")
        for permission in ("contents: read", "packages: write", "id-token: write", "attestations: write"):
            self.assertIn(permission, text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("actions: write", text)

    def test_release_builds_scans_attests_and_publishes_same_commit_variants(self):
        text = self.release
        for token in (
            "platform: [linux/amd64, linux/arm64]", "target: [web, racebot]",
            "VCS_REF=${{ needs.identity.outputs.commit_sha }}",
            "docker/build-push-action", "push: true", "aquasecurity/trivy-action",
            "anchore/sbom-action", "spdx-json", "actions/attest-build-provenance",
            "subject-digest:", "actions/upload-artifact", "actions/download-artifact",
            "docker buildx imagetools create", "docker buildx imagetools inspect",
            "sha-${COMMIT_SHA}", "org.opencontainers.image.revision",
            "org.opencontainers.image.source", "org.opencontainers.image.licenses",
        ):
            with self.subTest(token=token):
                self.assertIn(token, text)
        self.assertRegex(text, r"(?s)severity:\s*CRITICAL,HIGH.*exit-code:\s*[\"']?1")
        self.assertNotRegex(text.lower(), r"(?:^|[^a-z])latest(?:[^a-z]|$)")

    def test_manifest_and_release_identity_are_digest_addressed(self):
        text = self.release
        self.assertIn("for target in web racebot", text)
        self.assertIn('manifest="${image}:sha-${COMMIT_SHA}"', text)
        for token in (
            "linux-amd64.digest", "linux-arm64.digest", "@${AMD64_DIGEST}",
            "@${ARM64_DIGEST}", "release-identities.json", "manifest_digest",
            "source_commit", "source_url", "license", "GPL-3.0-only",
        ):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_release_has_no_deployment_or_mutable_image_tag(self):
        lowered = self.release.lower()
        self.assertNotIn("terraform apply", lowered)
        self.assertNotIn("docker compose", lowered)
        self.assertNotIn(":latest", lowered)
        self.assertNotIn("kubectl", lowered)
        self.assertIn("Deployment remains a separate explicit operator action", self.release)

    def test_action_pin_comments_name_a_version(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for line in path.read_text(encoding="utf-8").splitlines():
                match = SHA_ACTION.match(line)
                if match:
                    self.assertRegex(line, r"#\s+v[0-9]", f"missing version comment: {path}:{line}")


if __name__ == "__main__":
    unittest.main()
