import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = ROOT / "deploy" / "Caddyfile"
ENV_DIRECTORY = ROOT / "deploy" / "caddy"
ENV_FILES = {
    "qualification": ENV_DIRECTORY / "qualification.env.example",
    "production-restricted": ENV_DIRECTORY / "production-restricted.env.example",
    "production-public": ENV_DIRECTORY / "production-public.env.example",
}
EXPECTED_ENVIRONMENT = {
    "CADDY_SITE_HOST", "CADDY_ACME_EMAIL", "CADDY_ACME_CA",
    "CADDY_ACME_TEST_CA", "CADDY_ACCESS_PHASE", "CADDY_ALLOWED_CIDRS",
    "CADDY_HSTS_VALUE",
}
STAGING_CA = "https://acme-staging-v02.api.letsencrypt.org/directory"
PRODUCTION_CA = "https://acme-v02.api.letsencrypt.org/directory"


def parse_env(path):
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            name, value = line.split("=", 1)
            values[name] = value
    return values


def caddy_binary():
    return os.environ.get("CADDY_BIN") or shutil.which("caddy")


def nested_values(value, key):
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            if item_key == key:
                yield item_value
            yield from nested_values(item_value, key)
    elif isinstance(value, list):
        for item in value:
            yield from nested_values(item, key)


class CaddyEnvironmentContractTests(unittest.TestCase):
    def test_phase_examples_have_exact_safe_schema(self):
        environments = {name: parse_env(path) for name, path in ENV_FILES.items()}
        for name, values in environments.items():
            self.assertEqual(set(values), EXPECTED_ENVIRONMENT, name)
            self.assertEqual(values["CADDY_SITE_HOST"], "racetime.z1rracing.com")
            self.assertEqual(values["CADDY_ACME_CA"], values["CADDY_ACME_TEST_CA"])
            self.assertNotIn("zerossl", json.dumps(values).lower())
            self.assertTrue(values["CADDY_ACME_EMAIL"].endswith(".invalid"))
        self.assertEqual(environments["qualification"]["CADDY_ACME_CA"], STAGING_CA)
        self.assertEqual(environments["qualification"]["CADDY_ACCESS_PHASE"], "restricted")
        self.assertEqual(environments["qualification"]["CADDY_HSTS_VALUE"], "max-age=300")
        self.assertEqual(
            environments["production-restricted"]["CADDY_ACME_CA"], PRODUCTION_CA,
        )
        self.assertEqual(
            environments["production-restricted"]["CADDY_ACCESS_PHASE"], "restricted",
        )
        self.assertEqual(
            environments["production-restricted"]["CADDY_HSTS_VALUE"], "max-age=300",
        )
        self.assertEqual(environments["production-public"]["CADDY_ACCESS_PHASE"], "public")
        self.assertEqual(
            environments["production-public"]["CADDY_ALLOWED_CIDRS"],
            "0.0.0.0/0 ::/0",
        )
        self.assertEqual(
            environments["production-public"]["CADDY_HSTS_VALUE"],
            "max-age=31536000",
        )

    def test_restricted_examples_use_documentation_only_cidrs(self):
        for name in ("qualification", "production-restricted"):
            cidrs = parse_env(ENV_FILES[name])["CADDY_ALLOWED_CIDRS"].split()
            self.assertGreaterEqual(len(cidrs), 2)
            self.assertNotIn("0.0.0.0/0", cidrs)
            self.assertNotIn("::/0", cidrs)
            for cidr in cidrs:
                self.assertTrue(cidr.startswith(("192.0.2.", "198.51.100.", "2001:db8:")))


class CaddySourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CADDYFILE.read_text(encoding="utf-8")

    def test_tls_issuer_and_challenge_contract_is_explicit(self):
        self.assertIn("issuer acme", self.source)
        self.assertIn("dir {$CADDY_ACME_CA}", self.source)
        self.assertIn("test_dir {$CADDY_ACME_TEST_CA}", self.source)
        self.assertIn("disable_http_challenge", self.source)
        self.assertNotIn("disable_tlsalpn_challenge", self.source)
        self.assertNotIn("zerossl", self.source.lower())
        self.assertNotIn("acme_server", self.source)

    def test_default_deny_precedes_every_public_route_class(self):
        denial = self.source.index("respond @sourceDenied 404")
        for later in (
            "respond @publicAdmin 404", "handle_path /static/*",
            "handle_path /media/*", "reverse_proxy web:8000",
        ):
            self.assertGreater(self.source.index(later), denial, later)
        self.assertNotIn("basic_auth", self.source)
        self.assertNotIn("basicauth", self.source)
        self.assertIn("remote_ip {$CADDY_ALLOWED_CIDRS}", self.source)

    def test_proxy_media_and_admin_controls_are_explicit(self):
        self.assertIn("request_body", self.source)
        self.assertIn("max_size 5MB", self.source)
        self.assertNotIn("header_up -X-Forwarded-", self.source)
        self.assertIn("header_up X-Forwarded-For {remote_host}", self.source)
        self.assertIn("header_up X-Forwarded-Host {host}", self.source)
        self.assertIn("header_up X-Forwarded-Proto https", self.source)
        self.assertIn("Content-Disposition", self.source)
        self.assertIn("X-Content-Type-Options nosniff", self.source)
        self.assertIn(":8081", self.source)
        self.assertIn("@operatorOnly path /admin* /internal/*", self.source)

    def test_access_logs_redact_oauth_and_secret_query_values(self):
        self.assertEqual(self.source.count("format filter"), 2)
        self.assertEqual(self.source.count("request>uri query"), 2)
        for name in (
            "code", "state", "token", "access_token", "refresh_token",
            "client_secret", "password", "webhook", "error_description",
        ):
            self.assertEqual(
                self.source.count(f"replace {name} REDACTED"), 2, name,
            )
        self.assertEqual(self.source.count("wrap json"), 2)


class AdaptedCaddyContractTests(unittest.TestCase):
    def adapt(self, name):
        binary = caddy_binary()
        if not binary:
            if os.environ.get("REQUIRE_CADDY_TESTS") == "1":
                self.fail("Caddy is required but CADDY_BIN/caddy is unavailable")
            self.skipTest("Caddy binary is unavailable for adapted-config verification")
        completed = subprocess.run(
            [binary, "adapt", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
            cwd=ROOT, env={**os.environ, **parse_env(ENV_FILES[name])},
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def test_all_phases_adapt_to_one_pinned_acme_issuer(self):
        for name in ENV_FILES:
            with self.subTest(name=name):
                config = self.adapt(name)
                expected = parse_env(ENV_FILES[name])
                issuers = [
                    issuer for value in nested_values(config, "issuers")
                    if isinstance(value, list) for issuer in value
                    if isinstance(issuer, dict) and issuer.get("module") == "acme"
                ]
                self.assertEqual(len(issuers), 1, issuers)
                self.assertEqual(issuers[0].get("ca"), expected["CADDY_ACME_CA"])
                self.assertEqual(issuers[0].get("test_ca"), expected["CADDY_ACME_TEST_CA"])
                serialized = json.dumps(config, sort_keys=True).lower()
                self.assertNotIn("zerossl", serialized)
                self.assertIn("http", issuers[0].get("challenges", {}))
                self.assertTrue(issuers[0]["challenges"]["http"]["disabled"])
                self.assertFalse(
                    issuers[0].get("challenges", {}).get("tls-alpn", {}).get("disabled", False)
                )

    def test_adapted_routes_preserve_host_hsts_upstream_and_admin_listener(self):
        for name in ENV_FILES:
            with self.subTest(name=name):
                config = self.adapt(name)
                values = parse_env(ENV_FILES[name])
                serialized = json.dumps(config, sort_keys=True)
                self.assertIn(values["CADDY_SITE_HOST"], serialized)
                self.assertIn(values["CADDY_HSTS_VALUE"], serialized)
                self.assertIn("web:8000", serialized)
                self.assertIn(":8081", serialized)
                for cidr in values["CADDY_ALLOWED_CIDRS"].split():
                    self.assertIn(cidr, serialized)
                self.assertEqual(serialized.count('"filter": "query"'), 2)
                for parameter in (
                    "code", "state", "access_token", "refresh_token", "client_secret",
                ):
                    self.assertIn(f'"parameter": "{parameter}"', serialized)
                servers = config["apps"]["http"]["servers"]
                admin_servers = [
                    server for server in servers.values()
                    if ":8081" in server.get("listen", [])
                ]
                self.assertEqual(len(admin_servers), 1)
                wrappers = admin_servers[0].get("listener_wrappers", [])
                self.assertIn(
                    "tls",
                    [wrapper.get("wrapper") for wrapper in wrappers],
                    "loopback admin needs an explicit TLS listener wrapper",
                )
                self.assertIn(
                    '"X-Forwarded-Proto": ["{http.request.scheme}"]', serialized,
                )


if __name__ == "__main__":
    unittest.main()
