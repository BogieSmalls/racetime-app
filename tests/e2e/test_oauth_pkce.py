"""G0 contracts tying the integration stack to the exact public PKCE client."""

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class IntegrationOAuthPKCEContractTests(unittest.TestCase):
    def test_fixture_creates_public_livesplit_client_with_exact_loopback(self):
        fixture = (
            REPOSITORY_ROOT / "tests" / "e2e" / "prepare_integration.py"
        ).read_text(encoding="utf-8")
        self.assertIn('PUBLIC_CLIENT_ID = "z1rr-livesplit-integration-public"', fixture)
        self.assertIn('REDIRECT_URI = "http://127.0.0.1:4888/"', fixture)
        self.assertIn("application_model.CLIENT_PUBLIC", fixture)
        self.assertIn("application_model.GRANT_AUTHORIZATION_CODE", fixture)
        self.assertNotIn("client_secret", fixture.lower())

    def test_integration_profile_keeps_s256_enforcement_and_disables_bypass(self):
        settings_text = (
            REPOSITORY_ROOT / "project" / "settings" / "integration.py"
        ).read_text(encoding="utf-8")
        ci_text = (
            REPOSITORY_ROOT / "project" / "settings" / "ci.py"
        ).read_text(encoding="utf-8")
        test_text = (
            REPOSITORY_ROOT / "project" / "settings" / "test.py"
        ).read_text(encoding="utf-8")
        self.assertIn("from .ci import *", settings_text)
        self.assertIn("from .test import *", ci_text)
        self.assertIn('"PKCE_REQUIRED": True', test_text)
        self.assertIn('"COMPLIANT_BCP_RFC9700_PKCE_METHOD": True', test_text)
        self.assertIn("RT_ENABLE_LEGACY_LIVESPLIT_PKCE_BYPASS = False", settings_text)


if __name__ == "__main__":
    unittest.main()
