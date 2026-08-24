from unittest import mock

from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase, override_settings

from racetime.views.health import _cache_ready, _database_ready


HEALTH_TOKEN = "test-only-internal-health-token"


class PublicLivenessTests(SimpleTestCase):
    @mock.patch(
        "racetime.views.health._cache_ready",
        side_effect=AssertionError("liveness ran cache readiness"),
    )
    @mock.patch(
        "racetime.views.health._database_ready",
        side_effect=AssertionError("liveness ran database readiness"),
    )
    def test_healthz_is_minimal_and_dependency_free(
        self,
        _database_cursor,
        _cache_get,
    ):
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.content, b'{"status":"ok"}')


@override_settings(INTERNAL_HEALTH_TOKEN=HEALTH_TOKEN)
class InternalReadinessEndpointTests(SimpleTestCase):
    def authorization(self, token=HEALTH_TOKEN):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    @mock.patch("racetime.views.health._cache_ready", return_value=True)
    @mock.patch("racetime.views.health._database_ready", return_value=True)
    def test_exact_bearer_token_returns_only_component_booleans(
        self,
        database_ready,
        cache_ready,
    ):
        response = self.client.get(
            "/internal/readyz",
            **self.authorization(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.content,
            b'{"database":true,"cache":true}',
        )
        database_ready.assert_called_once_with()
        cache_ready.assert_called_once_with()

    def test_missing_wrong_or_malformed_credentials_conceal_endpoint(self):
        attempts = (
            {},
            self.authorization("wrong-token"),
            {"HTTP_AUTHORIZATION": f"bearer {HEALTH_TOKEN}"},
            {"HTTP_AUTHORIZATION": f"Bearer  {HEALTH_TOKEN}"},
        )

        for headers in attempts:
            with self.subTest(headers=headers):
                response = self.client.get("/internal/readyz", **headers)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b"ready", response.content.lower())

    @override_settings(INTERNAL_HEALTH_TOKEN="")
    def test_unconfigured_token_conceals_endpoint(self):
        response = self.client.get(
            "/internal/readyz",
            **self.authorization(),
        )

        self.assertEqual(response.status_code, 404)

    @mock.patch("racetime.views.health._cache_ready", return_value=True)
    @mock.patch("racetime.views.health._database_ready", return_value=False)
    def test_database_failure_is_generic_503(
        self,
        _database_ready,
        _cache_ready,
    ):
        response = self.client.get(
            "/internal/readyz",
            **self.authorization(),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.content,
            b'{"database":false,"cache":true}',
        )

    @mock.patch("racetime.views.health._cache_ready", return_value=False)
    @mock.patch("racetime.views.health._database_ready", return_value=True)
    def test_cache_failure_is_generic_503(
        self,
        _database_ready,
        _cache_ready,
    ):
        response = self.client.get(
            "/internal/readyz",
            **self.authorization(),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.content,
            b'{"database":true,"cache":false}',
        )


class DependencyProbeTests(TestCase):
    def test_database_probe_executes_select_one(self):
        cursor = mock.MagicMock()
        cursor.fetchone.return_value = (1,)
        context = mock.MagicMock()
        context.__enter__.return_value = cursor

        with mock.patch(
            "racetime.views.health.connection.cursor",
            return_value=context,
        ):
            result = _database_ready()

        self.assertTrue(result)
        cursor.execute.assert_called_once_with("SELECT 1")
        cursor.fetchone.assert_called_once_with()

    @mock.patch(
        "racetime.views.health.connection.cursor",
        side_effect=DatabaseError("sensitive database topology"),
    )
    def test_database_probe_contains_exceptions(self, _cursor):
        self.assertFalse(_database_ready())

    def test_cache_probe_round_trips_and_cleans_up(self):
        fake_cache = mock.MagicMock()
        fake_cache.get.side_effect = lambda key: key.rsplit(":", 1)[-1]

        with mock.patch("racetime.views.health.cache", fake_cache):
            result = _cache_ready()

        self.assertTrue(result)
        set_args, set_kwargs = fake_cache.set.call_args
        cache_key, marker = set_args
        self.assertEqual(cache_key, f"racetime:readyz:{marker}")
        self.assertEqual(set_kwargs, {"timeout": 5})
        fake_cache.get.assert_called_once_with(cache_key)
        fake_cache.delete.assert_called_once_with(cache_key)

    def test_cache_probe_contains_failures_and_still_attempts_cleanup(self):
        fake_cache = mock.MagicMock()
        fake_cache.get.side_effect = RuntimeError("sensitive redis topology")

        with mock.patch("racetime.views.health.cache", fake_cache):
            result = _cache_ready()

        self.assertFalse(result)
        cache_key = fake_cache.set.call_args.args[0]
        fake_cache.delete.assert_called_once_with(cache_key)
