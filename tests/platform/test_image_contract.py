from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
START = ROOT / ".docker" / "start-production"
HEALTHCHECK = ROOT / ".docker" / "healthcheck"
DOCKERIGNORE = ROOT / ".dockerignore"
LOCK = ROOT / "requirements-production.txt"
SMOKE = ROOT / "tests" / "platform" / "smoke_images.ps1"


class ImageContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    def test_base_images_are_digest_pinned_multiarch_inputs(self):
        from_lines = [
            line.strip() for line in self.dockerfile.splitlines()
            if line.strip().upper().startswith("FROM ")
        ]
        pinned = [line for line in from_lines if "@sha256:" in line]
        self.assertEqual(len(pinned), 2, from_lines)
        for line in pinned:
            self.assertRegex(line, r"@sha256:[0-9a-f]{64}(?:\s+AS\s+\S+)?$")
        self.assertTrue(any("node:24.11.1-bookworm-slim@" in line for line in pinned))
        self.assertTrue(any("python:3.12.11-slim-bookworm@" in line for line in pinned))
        self.assertNotRegex(self.dockerfile, r"(?im)^FROM\s+[^\s]+:latest")
        self.assertNotRegex(self.dockerfile, r"(?i)linux/(?:amd64|arm64)")

    def test_assets_and_python_dependencies_are_locked(self):
        self.assertIn("npm ci --omit=dev --ignore-scripts", self.dockerfile)
        self.assertIn("COPY package.json package-lock.json", self.dockerfile)
        self.assertIn("requirements-production.txt", self.dockerfile)
        self.assertTrue(LOCK.is_file())
        lock_lines = [
            line.strip() for line in LOCK.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertGreaterEqual(len(lock_lines), 35)
        for line in lock_lines:
            self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[^\s;]+$")
        self.assertIn("Django==5.2.17", lock_lines)
        self.assertIn("js-cookie\": \"3.0.8\"", (ROOT / "package.json").read_text())

    def test_runtime_copies_source_and_runs_as_uid_10001(self):
        self.assertIn("FROM python-base AS runtime-base", self.dockerfile)
        self.assertRegex(self.dockerfile, r"(?m)^COPY --chown=10001:10001 project ./project$")
        self.assertRegex(self.dockerfile, r"(?m)^COPY --chown=10001:10001 racetime ./racetime$")
        self.assertIn("COPY --from=python-build /opt/venv /opt/venv", self.dockerfile)
        self.assertIn("COPY --from=assets --chown=10001:10001 /build/node_modules ./node_modules", self.dockerfile)
        self.assertRegex(self.dockerfile, r"(?m)^USER 10001:10001$")
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", self.dockerfile)
        self.assertNotRegex(self.dockerfile, r"(?im)\b(?:ADD|COPY)\s+\.\s+")
        self.assertNotIn("RUNMIGRATIONS", self.dockerfile)
        self.assertNotIn("runserver", self.dockerfile)

    def test_targets_have_explicit_process_contracts(self):
        for target in ("web", "racebot", "maintenance"):
            self.assertRegex(
                self.dockerfile,
                rf"(?m)^FROM runtime-base AS {target}$",
            )
        exposed = re.findall(r"(?im)^EXPOSE\s+(.+)$", self.dockerfile)
        self.assertEqual(exposed, ["8000"])
        self.assertTrue(START.is_file())
        start = START.read_text(encoding="utf-8")
        self.assertIn("exec daphne -b 0.0.0.0 -p 8000 project.asgi:application", start)
        self.assertIn("exec python manage.py racebot --noreload", start)
        self.assertIn("exec python manage.py migrate --noinput", start)
        self.assertIn("exec python manage.py collectstatic --noinput", start)
        self.assertNotIn("runserver", start)
        self.assertNotIn("RUNMIGRATIONS", start)
        self.assertTrue(HEALTHCHECK.is_file())
        health = HEALTHCHECK.read_text(encoding="utf-8")
        self.assertIn("http://127.0.0.1:8000/healthz", health)
        self.assertIn("kill -0 1", health)

    def test_maintenance_tools_are_absent_from_application_targets(self):
        marker = "FROM runtime-base AS maintenance"
        before, separator, maintenance = self.dockerfile.partition(marker)
        self.assertEqual(separator, marker)
        tool_patterns = (
            r"oci-cli==3\.90\.3",
            r"\bage\b",
            r"\bzstd\b",
            r"\bmariadb-client\b",
        )
        for pattern in tool_patterns:
            self.assertNotRegex(before, pattern)
            self.assertRegex(maintenance, pattern)

    def test_build_contains_no_credentials_or_development_mounts(self):
        forbidden = (
            "DJANGO_SECRET_KEY=", "DB_PASSWORD=", "DISCORD_CLIENT_SECRET=",
            "TWITCH_CLIENT_SECRET=", "RACETIME_THROTTLE_HMAC_KEY=",
            "--mount=type=bind", "development secret",
        )
        for value in forbidden:
            self.assertNotIn(value, self.dockerfile)
        self.assertRegex(
            self.dockerfile,
            r'LABEL org\.opencontainers\.image\.revision="\$\{VCS_REF\}"',
        )
        self.assertIn("RACETIME_BUILD_COMMIT=${VCS_REF}", self.dockerfile)

    def test_build_context_excludes_local_and_mutable_state(self):
        self.assertTrue(DOCKERIGNORE.is_file())
        ignored = {
            line.strip() for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        for value in (
            ".git", ".worktrees", "venv", "node_modules", "static", "media",
            "db.sqlite3", "artifacts", ".env*", "deploy/env/*.env",
        ):
            self.assertIn(value, ignored)

    def test_smoke_script_covers_both_platforms_and_runtime_constraints(self):
        self.assertTrue(SMOKE.is_file())
        smoke = SMOKE.read_text(encoding="utf-8")
        for platform in ("linux/arm64", "linux/amd64"):
            self.assertIn(platform, smoke)
        for target in ("web", "racebot"):
            self.assertIn(target, smoke)
        self.assertIn("--read-only", smoke)
        self.assertIn("--tmpfs", smoke)
        self.assertIn("id -u", smoke)
        self.assertIn("10001", smoke)
        self.assertIn("org.opencontainers.image.revision", smoke)
        self.assertIn("docker image history --no-trunc", smoke)


if __name__ == "__main__":
    unittest.main()
