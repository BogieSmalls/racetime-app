import json
from pathlib import Path
import subprocess
import sys
import unittest

from tests.platform.test_config_contract import run_production_probe


class ProductionSettingsTests(unittest.TestCase):
    def load_settings(self, **overrides):
        completed = run_production_probe(overrides=overrides)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def assert_invalid(self, variable, value=None, *, remove=False):
        completed = run_production_probe(
            overrides={} if remove else {variable: value},
            remove=(variable,) if remove else (),
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn(variable, output)
        if value:
            self.assertNotIn(value, output)

    def test_restricted_profile_is_fail_closed_and_complete(self):
        settings = self.load_settings()
        self.assertFalse(settings["debug"])
        self.assertNotIn("debug_toolbar", " ".join(settings["apps"]))
        self.assertNotIn("debug_toolbar", " ".join(settings["middleware"]))
        self.assertEqual(settings["hosts"], ["integration.racetime.test"])
        self.assertEqual(settings["csrf_origins"], ["https://integration.racetime.test"])
        self.assertTrue(settings["session_secure"])
        self.assertTrue(settings["session_httponly"])
        self.assertEqual(settings["session_samesite"], "Lax")
        self.assertTrue(settings["csrf_secure"])
        self.assertEqual(settings["csrf_samesite"], "Lax")
        self.assertTrue(settings["ssl_redirect"])
        self.assertEqual(settings["hsts"], 300)
        self.assertFalse(settings["hsts_preload"])
        self.assertEqual(settings["proxy_ssl"], ["HTTP_X_FORWARDED_PROTO", "https"])
        self.assertFalse(settings["cors_all"])
        self.assertEqual(settings["cors_origins"], ["https://integration.racetime.test"])
        self.assertEqual(settings["frame"], "DENY")
        self.assertEqual(settings["referrer"], "same-origin")
        self.assertEqual(settings["db_engine"], "django.db.backends.mysql")
        self.assertEqual(settings["db_host"], "db")
        self.assertEqual(settings["cache"], "django.core.cache.backends.redis.RedisCache")
        self.assertEqual(settings["channels"], "racetime.utils.RedisChannelLayer")
        self.assertEqual(settings["trusted_proxy"], "172.30.0.2/32")
        self.assertEqual(settings["real_ip"], "HTTP_X_FORWARDED_FOR")
        self.assertEqual(settings["static_root"], "/srv/racetime/static")
        self.assertEqual(settings["media_root"], "/srv/racetime/media")
        self.assertLessEqual(settings["file_limit"], settings["body_limit"])
        self.assertLessEqual(settings["body_limit"], 10 * 1024 * 1024)
        self.assertTrue(settings["discord"])
        self.assertFalse(settings["password"])
        self.assertFalse(settings["category_requests"])
        self.assertFalse(settings["patreon"])
        self.assertFalse(settings["legacy_pkce"])
        self.assertTrue(settings["pkce"])
        for gate in (
            "COMPLIANT_BCP_RFC9700_IMPLICIT_GRANT",
            "COMPLIANT_BCP_RFC9700_PASSWORD_GRANT",
            "COMPLIANT_BCP_RFC9700_PKCE_METHOD",
            "COMPLIANT_BCP_RFC9700_ACCESS_TOKEN_TRANSPORT",
            "COMPLIANT_BCP_RFC9700_AUTHZ_RESPONSE_ISS",
            "COMPLIANT_BCP_RFC9700_TOKEN_STORAGE",
            "COMPLIANT_BCP_RFC9700_REFRESH_TOKEN",
            "COMPLIANT_BCP_RFC9700_REDIRECT_URI_MATCHING",
            "COMPLIANT_BCP_RFC9700_PKCE_REQUIRED",
            "REFRESH_TOKEN_REUSE_PROTECTION",
        ):
            self.assertTrue(settings["oauth"][gate], gate)
        self.assertFalse(settings["oauth"]["ALLOW_URI_WILDCARDS"])
        self.assertEqual(
            settings["oauth"]["ALLOWED_REDIRECT_URI_SCHEMES"],
            ["https", "http"],
        )
        self.assertEqual(set(settings["silenced_checks"]), {
            "django_recaptcha.recaptcha_test_key_error",
            "oauth2_provider.W008",
            "security.W005",
            "security.W021",
        })
        self.assertEqual(settings["log_formatter"], "project.logging.JsonFormatter")

    def test_public_phase_raises_hsts_without_preload(self):
        settings = self.load_settings(RACETIME_ACCESS_PHASE="public")
        self.assertGreaterEqual(settings["hsts"], 31536000)
        self.assertFalse(settings["hsts_preload"])

    def test_deployment_check_has_no_unreviewed_warnings(self):
        root = Path(__file__).resolve().parents[2]
        script = (
            "from tests.platform.test_config_contract import parse_env_file,CI_ENV_PATH;"
            "import os,subprocess,sys;"
            "env={**os.environ,**parse_env_file(CI_ENV_PATH)};"
            "raise SystemExit(subprocess.call([sys.executable,'manage.py','check',"
            "'--deploy','--fail-level','WARNING',"
            "'--settings=project.settings.production'],cwd=r'%s',env=env))"
        ) % root
        completed = subprocess.run(
            [sys.executable, "-c", script], cwd=root,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_missing_invalid_and_placeholder_settings_fail_safely(self):
        self.assert_invalid("DJANGO_SECRET_KEY", remove=True)
        self.assert_invalid("DJANGO_SECRET_KEY", "changeme")
        self.assert_invalid("ALLOWED_HOSTS", "*")
        self.assert_invalid("CSRF_TRUSTED_ORIGINS", "https://*.example.com")
        self.assert_invalid("RT_SITE_URI", "http://racetime.z1rracing.com")
        self.assert_invalid(
            "REDIS_URL",
            "redis://user:secret-value@example.invalid/0?token=canary",
        )
        self.assert_invalid("RACETIME_ACCESS_PHASE", "preview")
        self.assert_invalid("RACETIME_TRUSTED_PROXY_CIDRS", "172.30.0.0/29")
        self.assert_invalid("RACETIME_THROTTLE_HMAC_KEY", "not-base64-secret")

    def test_throttle_key_cannot_reuse_django_secret(self):
        script = (
            "import os;os.environ['RACETIME_THROTTLE_HMAC_KEY']="
            "os.environ['DJANGO_SECRET_KEY'];import django;django.setup()"
        )
        completed = run_production_probe(script=script)
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn("RACETIME_THROTTLE_HMAC_KEY", output)
        self.assertNotIn("ci-only-django", output)

    def test_discord_redirect_must_match_site_callback(self):
        self.assert_invalid(
            "DISCORD_REDIRECT_URI",
            "https://integration.racetime.test/account/discord/wrong",
        )

    def test_unknown_security_environment_name_is_rejected(self):
        completed = run_production_probe(
            overrides={"RACETIME_ACCESS_PHSAE": "public"},
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertIn("RACETIME_ACCESS_PHSAE", output)
        self.assertNotIn("public", output)
