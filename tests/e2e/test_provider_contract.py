"""Provider-qualified URL contracts for the isolated integration origin."""

from pathlib import Path
import unittest

from tests.e2e.fixtures import IntegrationEndpoints


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ProviderContractTests(unittest.TestCase):
    def test_all_http_and_websocket_urls_derive_from_one_fixture_origin(self):
        endpoints = IntegrationEndpoints.from_env()
        self.assertEqual(
            endpoints.category_url,
            "https://integration.racetime.test:8443/z1rr",
        )
        self.assertEqual(
            endpoints.websocket_origin,
            "wss://integration.racetime.test:8443",
        )
        self.assertNotIn("racetime.z1rracing.com", endpoints.origin)
        self.assertNotIn("racetime.gg", endpoints.origin)

    def test_fixture_provider_is_internal_and_canonical_browser_route_is_local(self):
        settings_text = (
            REPOSITORY_ROOT / "project" / "settings" / "integration.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'DISCORD_AUTHORIZE_URL = _EXPECTED_ORIGIN + "/fixture-discord/authorize"',
            settings_text,
        )
        self.assertIn(
            'DISCORD_TOKEN_URL = "http://fixture-provider:8090/fixture-discord/token"',
            settings_text,
        )
        self.assertNotIn("discord.com", settings_text)


if __name__ == "__main__":
    unittest.main()
