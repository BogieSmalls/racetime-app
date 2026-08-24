import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from django.core.exceptions import ImproperlyConfigured

from project.settings import env


ROOT = Path(__file__).resolve().parents[2]
CI_ENV_PATH = ROOT / "deploy" / "env" / "ci.env"
EXAMPLE_ENV_PATH = ROOT / ".env.production.example"
EXPECTED_VARIABLES = {
    "DJANGO_SECRET_KEY", "RT_SITE_URI", "ALLOWED_HOSTS",
    "CSRF_TRUSTED_ORIGINS", "DB_NAME", "DB_USER", "DB_PASSWORD",
    "DB_HOST", "DB_PORT", "REDIS_URL", "INTERNAL_HEALTH_TOKEN",
    "RACETIME_THROTTLE_HMAC_KEY", "RACETIME_TRUSTED_PROXY_CIDRS",
    "DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "DISCORD_REDIRECT_URI",
    "TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "STATIC_ROOT",
    "MEDIA_ROOT", "LOG_LEVEL", "RACETIME_ACCESS_PHASE",
}


def parse_env_file(path):
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            name, value = line.split("=", 1)
            values[name] = value
    return values


def run_production_probe(*, overrides=None, remove=(), script=None):
    prefixes = (
        "DJANGO_", "RT_", "DB_", "REDIS_", "INTERNAL_",
        "RACETIME_", "DISCORD_", "TWITCH_",
    )
    process_env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(prefixes)
    }
    process_env.update(parse_env_file(CI_ENV_PATH))
    process_env["DJANGO_SETTINGS_MODULE"] = "project.settings.production"
    for name in remove:
        process_env.pop(name, None)
    process_env.update(overrides or {})
    probe = script or (
        "import json,django;django.setup();from django.conf import settings;s=settings;"
        "print(json.dumps({"
        "'debug':s.DEBUG,'apps':s.INSTALLED_APPS,'middleware':s.MIDDLEWARE,"
        "'hosts':s.ALLOWED_HOSTS,'csrf_origins':s.CSRF_TRUSTED_ORIGINS,"
        "'session_secure':s.SESSION_COOKIE_SECURE,"
        "'session_httponly':s.SESSION_COOKIE_HTTPONLY,"
        "'session_samesite':s.SESSION_COOKIE_SAMESITE,"
        "'csrf_secure':s.CSRF_COOKIE_SECURE,'csrf_samesite':s.CSRF_COOKIE_SAMESITE,"
        "'ssl_redirect':s.SECURE_SSL_REDIRECT,'hsts':s.SECURE_HSTS_SECONDS,"
        "'hsts_preload':s.SECURE_HSTS_PRELOAD,'proxy_ssl':s.SECURE_PROXY_SSL_HEADER,"
        "'cors_all':s.CORS_ALLOW_ALL_ORIGINS,'cors_origins':s.CORS_ALLOWED_ORIGINS,"
        "'frame':s.X_FRAME_OPTIONS,'referrer':s.SECURE_REFERRER_POLICY,"
        "'db_engine':s.DATABASES['default']['ENGINE'],"
        "'db_host':s.DATABASES['default']['HOST'],"
        "'cache':s.CACHES['default']['BACKEND'],"
        "'channels':s.CHANNEL_LAYERS['default']['BACKEND'],"
        "'trusted_proxy':s.RACETIME_TRUSTED_PROXY_CIDR,'real_ip':s.REAL_IP_HEADER,"
        "'static_root':s.STATIC_ROOT,'media_root':s.MEDIA_ROOT,"
        "'body_limit':s.DATA_UPLOAD_MAX_MEMORY_SIZE,"
        "'file_limit':s.FILE_UPLOAD_MAX_MEMORY_SIZE,"
        "'discord':s.RT_DISCORD_AUTH_ENABLED,'password':s.RT_PUBLIC_PASSWORD_AUTH,"
        "'category_requests':s.RT_PUBLIC_CATEGORY_REQUESTS,"
        "'patreon':s.RT_PATREON_ENABLED,"
        "'legacy_pkce':s.RT_ENABLE_LEGACY_LIVESPLIT_PKCE_BYPASS,"
        "'pkce':s.OAUTH2_PROVIDER['PKCE_REQUIRED'],"
        "'oauth':s.OAUTH2_PROVIDER,"
        "'silenced_checks':s.SILENCED_SYSTEM_CHECKS,"
        "'log_formatter':s.LOGGING['formatters']['json']['()']}))"
    )
    return subprocess.run(
        [sys.executable, "-c", probe], cwd=ROOT, env=process_env,
        capture_output=True, text=True, timeout=20, check=False,
    )


class EnvironmentParserTests(unittest.TestCase):
    def assert_safe_error(self, name, sensitive, call):
        with self.assertRaises(ImproperlyConfigured) as caught:
            call()
        message = str(caught.exception)
        self.assertIn(name, message)
        if sensitive:
            self.assertNotIn(sensitive, message)

    def test_required_and_secret_fail_closed(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assert_safe_error("REQUIRED_VALUE", "", lambda: env.required("REQUIRED_VALUE"))
        for value in ("", "  ", "changeme", "example", "sensitive-short"):
            with self.subTest(value=value), mock.patch.dict(
                os.environ, {"SECRET_VALUE": value}, clear=True,
            ):
                self.assert_safe_error(
                    "SECRET_VALUE", value,
                    lambda: env.secret("SECRET_VALUE", minimum=32),
                )

    def test_boolean_integer_and_csv_are_strict(self):
        with mock.patch.dict(os.environ, {
            "YES": "true", "NO": "0", "COUNT": "42", "LIST": "a, b",
        }, clear=True):
            self.assertTrue(env.boolean("YES"))
            self.assertFalse(env.boolean("NO"))
            self.assertEqual(env.integer("COUNT", minimum=1, maximum=50), 42)
            self.assertEqual(env.csv("LIST", required=True), ["a", "b"])
        invalid = (
            ("BOOL", "sometimes", lambda: env.boolean("BOOL")),
            ("COUNT", "51", lambda: env.integer("COUNT", minimum=1, maximum=50)),
            ("LIST", "a,,b", lambda: env.csv("LIST", required=True)),
        )
        for name, value, call in invalid:
            with self.subTest(name=name), mock.patch.dict(
                os.environ, {name: value}, clear=True,
            ):
                self.assert_safe_error(name, value, call)

    def test_https_origin_rejects_insecure_non_origin_and_credentials(self):
        with mock.patch.dict(os.environ, {
            "ORIGIN": "https://racetime.z1rracing.com",
        }, clear=True):
            self.assertEqual(env.https_origin("ORIGIN"), "https://racetime.z1rracing.com")
        for value in (
            "http://racetime.z1rracing.com",
            "https://user:pass@racetime.z1rracing.com",
            "https://racetime.z1rracing.com/path",
            "https://*.z1rracing.com",
        ):
            with self.subTest(value=value), mock.patch.dict(
                os.environ, {"ORIGIN": value}, clear=True,
            ):
                self.assert_safe_error("ORIGIN", value, lambda: env.https_origin("ORIGIN"))

    def test_public_export_surface_is_deliberately_small(self):
        self.assertEqual(set(env.__all__), {
            "required", "secret", "boolean", "integer", "csv", "https_origin",
        })


class EnvironmentFileContractTests(unittest.TestCase):
    def test_example_and_fixture_have_exact_schema(self):
        example = parse_env_file(EXAMPLE_ENV_PATH)
        fixture = parse_env_file(CI_ENV_PATH)
        self.assertEqual(set(example), EXPECTED_VARIABLES)
        self.assertEqual(set(fixture), EXPECTED_VARIABLES)
        self.assertTrue(any(value in {"", "changeme", "example"} for value in example.values()))
        self.assertEqual(fixture["RACETIME_ACCESS_PHASE"], "restricted")
        self.assertEqual(fixture["RACETIME_TRUSTED_PROXY_CIDRS"], "172.30.0.2/32")
        self.assertNotEqual(fixture["DJANGO_SECRET_KEY"], fixture["RACETIME_THROTTLE_HMAC_KEY"])

    def test_validator_passes_fixture_and_fails_without_secret(self):
        fixture = parse_env_file(CI_ENV_PATH)
        process_env = {**os.environ, **fixture}
        valid = subprocess.run(
            [sys.executable, "deploy/validate-config.py"], cwd=ROOT,
            env=process_env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        self.assertIn("CONFIG=PASS", valid.stdout)
        sensitive = process_env.pop("DJANGO_SECRET_KEY")
        missing = subprocess.run(
            [sys.executable, "deploy/validate-config.py"], cwd=ROOT,
            env=process_env, capture_output=True, text=True, timeout=20,
        )
        output = missing.stdout + missing.stderr
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", output)
        self.assertNotIn(sensitive, output)


class LoggingContractTests(unittest.TestCase):
    def test_nested_values_urls_and_exception_messages_are_redacted(self):
        from project.logging import JsonFormatter, RedactionFilter

        record = logging.LogRecord(
            "racetime.security", logging.ERROR, __file__, 1,
            {"authorization": "Bearer auth-canary", "nested": {
                "safe": "kept", "client_secret": "secret-canary",
            }, "url": "https://testserver/o/authorize?code=code-canary&state=x",
             "email": "123456789@discord.invalid"},
            (), RuntimeError("refresh_token=refresh-canary"),
        )
        record.request_id = "request-123"
        self.assertTrue(RedactionFilter().filter(record))
        payload = json.loads(JsonFormatter().format(record))
        serialized = json.dumps(payload)
        for canary in (
            "auth-canary", "secret-canary", "code-canary",
            "123456789@discord.invalid", "refresh-canary",
        ):
            self.assertNotIn(canary, serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertEqual(payload["exception_class"], "RuntimeError")
        self.assertEqual(payload["request_id"], "request-123")
        self.assertEqual(payload["level"], "ERROR")
