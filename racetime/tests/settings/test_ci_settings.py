import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.test import SimpleTestCase, TransactionTestCase


ROOT = Path(__file__).resolve().parents[3]
CI_VARIABLES = (
    "RACETIME_CI_DB_NAME",
    "RACETIME_CI_DB_USER",
    "RACETIME_CI_DB_PASSWORD",
    "RACETIME_CI_DB_HOST",
    "RACETIME_CI_DB_PORT",
    "RACETIME_CI_REDIS_URL",
)


class CISettingsEnvironmentTests(SimpleTestCase):
    def test_ci_profile_fails_when_service_variables_are_missing(self):
        environment = os.environ.copy()
        for name in CI_VARIABLES:
            environment.pop(name, None)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "manage.py"),
                "check",
                "--settings=project.settings.ci",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Missing required RaceTime CI environment variables",
            result.stdout + result.stderr,
        )


@unittest.skipUnless(
    getattr(settings, "RT_SERVICE_BACKED_CI", False),
    "requires the project.settings.ci service-backed profile",
)
class CISettingsContractTests(TransactionTestCase):
    def test_ci_settings_select_mysql_redis_cache_and_redis_channels(self):
        self.assertEqual(
            settings.DATABASES["default"]["ENGINE"],
            "django.db.backends.mysql",
        )
        self.assertEqual(
            settings.CACHES["default"]["BACKEND"],
            "django.core.cache.backends.redis.RedisCache",
        )
        self.assertEqual(
            settings.CHANNEL_LAYERS["default"]["BACKEND"],
            "racetime.utils.RedisChannelLayer",
        )

    def test_database_transaction_round_trip(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT 41 + 1")
                self.assertEqual(cursor.fetchone()[0], 42)

    def test_cache_round_trip_and_delete(self):
        key = f"z1rr-ci-cache-{uuid.uuid4().hex}"
        cache.set(key, "round-trip", timeout=30)
        self.assertEqual(cache.get(key), "round-trip")
        cache.delete(key)
        self.assertIsNone(cache.get(key))

    def test_channel_round_trip(self):
        layer = get_channel_layer()
        channel = async_to_sync(layer.new_channel)("z1rr.ci.")
        async_to_sync(layer.send)(channel, {"type": "ci.probe", "value": 42})
        self.assertEqual(
            async_to_sync(layer.receive)(channel),
            {"type": "ci.probe", "value": 42},
        )
