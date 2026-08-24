from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"


class TestSettingsTests(SimpleTestCase):
    def test_test_settings_are_isolated(self):
        self.assertFalse(settings.DEBUG)
        self.assertEqual(
            settings.EMAIL_BACKEND,
            "django.core.mail.backends.locmem.EmailBackend",
        )
        self.assertEqual(
            settings.CHANNEL_LAYERS["default"]["BACKEND"],
            "channels.layers.InMemoryChannelLayer",
        )
        self.assertEqual(
            settings.CACHES["default"]["BACKEND"],
            "django.core.cache.backends.locmem.LocMemCache",
        )
        self.assertEqual(
            settings.DATABASES["default"]["ENGINE"],
            "django.db.backends.sqlite3",
        )
        database_name = str(settings.DATABASES["default"]["NAME"])
        self.assertTrue(
            database_name == ":memory:"
            or database_name.startswith("file:memorydb_default?"),
        )
        self.assertNotIn("debug_toolbar", settings.INSTALLED_APPS)
        self.assertNotIn(
            "debug_toolbar.middleware.DebugToolbarMiddleware", settings.MIDDLEWARE
        )
        self.assertEqual(settings.RT_SITE_URI, "https://testserver")

    def test_test_safe_feature_flags_are_explicit(self):
        self.assertFalse(settings.RT_PUBLIC_PASSWORD_AUTH)
        self.assertFalse(settings.RT_PUBLIC_CATEGORY_REQUESTS)
        self.assertFalse(settings.RT_PATREON_ENABLED)
        self.assertTrue(settings.RT_DISCORD_AUTH_ENABLED)
        self.assertFalse(settings.RT_ENABLE_LEGACY_LIVESPLIT_PKCE_BYPASS)
        self.assertFalse(settings.RT_SERVICE_BACKED_CI)
        self.assertTrue(settings.RT_THROTTLING_ENABLED)
        self.assertFalse(settings.RT_THROTTLING_REQUIRE_REDIS)
        self.assertGreaterEqual(len(settings.RACETIME_THROTTLE_HMAC_KEY), 32)
        self.assertEqual(settings.RACETIME_TRUSTED_PROXY_CIDR, "172.30.0.2/32")


class TestWorkflowContractTests(SimpleTestCase):
    def test_ci_has_distinct_fast_and_service_backed_jobs(self):
        self.assertTrue(WORKFLOW.is_file(), ".github/workflows/test.yml must exist")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        for required in (
            "fast-tests:",
            "service-integration-tests:",
            "mariadb:",
            "redis:",
            "project.settings.test",
            "project.settings.ci",
            "npm audit --omit=dev",
            "makemigrations --check --dry-run",
            "collectstatic --noinput",
            "check --deploy",
            "contents: read",
        ):
            with self.subTest(required=required):
                self.assertIn(required, workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("continue-on-error", workflow)
