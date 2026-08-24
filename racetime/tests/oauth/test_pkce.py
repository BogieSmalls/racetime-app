import base64
import hashlib
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from oauth2_provider.models import (
    get_application_model,
    get_grant_model,
)

from racetime.models import User


PUBLIC_CLIENT_ID = "z1rr-livesplit-public"
REDIRECT_URI = "http://127.0.0.1:4888/"
SCOPES = "read chat_message race_action"
VERIFIER = "z1rr-livesplit-verifier-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ"
WRONG_VERIFIER = "wrong-verifier-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def s256_challenge(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class PublicClientPKCETests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "pkce-user@discord.invalid",
            name="PKCE Racer",
        )
        self.client.force_login(self.user)
        application_model = get_application_model()
        self.public_application = application_model.objects.create(
            user=self.user,
            name="LiveSplit.Racetime.Z1RR",
            client_id=PUBLIC_CLIENT_ID,
            client_type=application_model.CLIENT_PUBLIC,
            authorization_grant_type=application_model.GRANT_AUTHORIZATION_CODE,
            redirect_uris=REDIRECT_URI,
        )

    def authorization_parameters(self, **overrides):
        parameters = {
            "client_id": PUBLIC_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "state": "exact-state-value",
            "code_challenge": s256_challenge(VERIFIER),
            "code_challenge_method": "S256",
        }
        parameters.update(overrides)
        parameters = {
            key: value for key, value in parameters.items()
            if value is not None
        }
        return parameters

    def authorize(self, **overrides):
        parameters = self.authorization_parameters(**overrides)
        consent = self.client.get(reverse("oauth2_authorize"), parameters)
        if consent.status_code != 200:
            return consent
        return self.client.post(
            reverse("oauth2_authorize"),
            {**parameters, "allow": "on"},
        )

    def authorization_code(self, **overrides):
        response = self.authorize(**overrides)
        self.assertEqual(response.status_code, 302)
        location = urlparse(response["Location"])
        self.assertEqual(
            f"{location.scheme}://{location.netloc}{location.path}",
            REDIRECT_URI,
        )
        query = parse_qs(location.query)
        self.assertNotIn("error", query)
        expected_state = overrides.get("state", "exact-state-value")
        self.assertEqual(query["state"], [expected_state])
        return query["code"][0]

    def exchange_code(self, code, **overrides):
        payload = {
            "grant_type": "authorization_code",
            "client_id": PUBLIC_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code": code,
            "code_verifier": VERIFIER,
        }
        payload.update(overrides)
        return self.client.post(reverse("oauth2_token"), payload)

    def assert_oauth_error(self, response, expected_error):
        if response.status_code == 302:
            payload = parse_qs(urlparse(response["Location"]).query)
            error = payload.get("error", [None])[0]
        else:
            payload = response.json()
            error = payload.get("error")
        self.assertEqual(error, expected_error)
        self.assertNotIn("access_token", payload)

    def test_exact_routes_and_test_profile_require_pkce(self):
        self.assertEqual(reverse("oauth2_authorize"), "/o/authorize")
        self.assertEqual(reverse("oauth2_token"), "/o/token")
        self.assertEqual(reverse("oauth2_revoke"), "/o/revoke_token")
        self.assertEqual(reverse("oauth2_userinfo"), "/o/userinfo")
        self.assertTrue(settings.OAUTH2_PROVIDER["PKCE_REQUIRED"])
        self.assertTrue(
            settings.OAUTH2_PROVIDER["COMPLIANT_BCP_RFC9700_PKCE_METHOD"]
        )
        self.assertFalse(settings.RT_ENABLE_LEGACY_LIVESPLIT_PKCE_BYPASS)
        self.assertEqual(
            settings.RT_Z1RR_LIVESPLIT_REDIRECT_URI,
            REDIRECT_URI,
        )

    def test_public_s256_authorization_code_success_and_exact_scopes(self):
        code = self.authorization_code()
        grant = get_grant_model().objects.get(code=code)
        self.assertEqual(grant.code_challenge, s256_challenge(VERIFIER))
        self.assertEqual(grant.code_challenge_method, "S256")
        self.assertEqual(grant.scope, SCOPES)

        response = self.exchange_code(code)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["access_token"])
        self.assertTrue(payload["refresh_token"])
        self.assertEqual(set(payload["scope"].split()), set(SCOPES.split()))
        self.assertNotIn("client_secret", payload)

    def test_missing_challenge_and_plain_method_are_rejected(self):
        missing = self.authorize(code_challenge=None, code_challenge_method=None)
        self.assert_oauth_error(missing, "invalid_request")

        plain = self.authorize(
            code_challenge=VERIFIER,
            code_challenge_method="plain",
        )
        self.assert_oauth_error(plain, "invalid_request")
        self.assertFalse(get_grant_model().objects.exists())

    def test_wrong_verifier_wrong_redirect_and_replay_are_rejected(self):
        wrong_redirect = self.authorize(
            redirect_uri="http://127.0.0.1:4889/"
        )
        self.assertNotEqual(wrong_redirect.status_code, 200)
        if "Location" in wrong_redirect:
            self.assertFalse(
                wrong_redirect["Location"].startswith("http://127.0.0.1:4889/")
            )

        wrong_redirect_post = self.client.post(
            reverse("oauth2_authorize"),
            {
                **self.authorization_parameters(
                    redirect_uri="http://127.0.0.1:4889/"
                ),
                "allow": "on",
            },
        )
        self.assertEqual(wrong_redirect_post.status_code, 400)
        self.assertNotIn("Location", wrong_redirect_post)

        wrong_code = self.authorization_code(state="wrong-verifier-state")
        wrong = self.exchange_code(
            wrong_code,
            code_verifier=WRONG_VERIFIER,
        )
        self.assert_oauth_error(wrong, "invalid_grant")

        replay_code = self.authorization_code(state="replay-state")
        first = self.exchange_code(replay_code)
        self.assertEqual(first.status_code, 200)
        replay = self.exchange_code(replay_code)
        self.assert_oauth_error(replay, "invalid_grant")

    def test_refresh_and_revocation_work_for_public_client_without_secret(self):
        issued = self.exchange_code(self.authorization_code())
        self.assertEqual(issued.status_code, 200)
        first_tokens = issued.json()
        initial_userinfo = self.client.get(
            reverse("oauth2_userinfo"),
            HTTP_AUTHORIZATION=f"Bearer {first_tokens['access_token']}",
        )
        self.assertEqual(initial_userinfo.status_code, 200)

        refreshed = self.client.post(
            reverse("oauth2_token"),
            {
                "grant_type": "refresh_token",
                "client_id": PUBLIC_CLIENT_ID,
                "refresh_token": first_tokens["refresh_token"],
                "scope": SCOPES,
            },
        )
        self.assertEqual(refreshed.status_code, 200)
        refreshed_tokens = refreshed.json()
        self.assertTrue(refreshed_tokens["access_token"])
        self.assertNotIn("client_secret", refreshed_tokens)

        revoked = self.client.post(
            reverse("oauth2_revoke"),
            {
                "client_id": PUBLIC_CLIENT_ID,
                "token": refreshed_tokens["access_token"],
                "token_type_hint": "access_token",
            },
        )
        self.assertEqual(revoked.status_code, 200)
        rejected_userinfo = self.client.get(
            reverse("oauth2_userinfo"),
            HTTP_AUTHORIZATION=f"Bearer {refreshed_tokens['access_token']}",
        )
        self.assertNotEqual(rejected_userinfo.status_code, 200)

    def test_z1rr_client_never_matches_legacy_stock_name_bypass(self):
        with override_settings(RT_ENABLE_LEGACY_LIVESPLIT_PKCE_BYPASS=True):
            response = self.client.get(
                reverse("oauth2_authorize"),
                self.authorization_parameters(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, s256_challenge(VERIFIER))

    def test_stock_bypass_is_controlled_by_explicit_flag(self):
        application_model = get_application_model()
        stock = application_model.objects.create(
            user=self.user,
            name="LiveSplit",
            client_id="stock-livesplit-client",
            client_type=application_model.CLIENT_PUBLIC,
            authorization_grant_type=application_model.GRANT_AUTHORIZATION_CODE,
            redirect_uris=REDIRECT_URI,
        )
        parameters = self.authorization_parameters(client_id=stock.client_id)

        disabled = self.client.get(reverse("oauth2_authorize"), parameters)
        self.assertEqual(disabled.status_code, 200)

        with override_settings(RT_ENABLE_LEGACY_LIVESPLIT_PKCE_BYPASS=True):
            enabled = self.client.get(reverse("oauth2_authorize"), parameters)
        self.assertEqual(enabled.status_code, 302)
        redirected = parse_qs(urlparse(enabled["Location"]).query)
        self.assertNotIn("code_challenge", redirected)
        self.assertNotIn("code_challenge_method", redirected)


class ConfidentialClientCredentialsTests(TestCase):
    def test_pkce_requirement_does_not_change_confidential_client_credentials(self):
        raw_secret = "ttp-bot-confidential-secret"
        application_model = get_application_model()
        application = application_model.objects.create(
            name="TTPBot",
            client_id="ttp-bot-confidential",
            client_secret=raw_secret,
            client_type=application_model.CLIENT_CONFIDENTIAL,
            authorization_grant_type=application_model.GRANT_CLIENT_CREDENTIALS,
        )

        response = self.client.post(
            reverse("oauth2_token"),
            {
                "grant_type": "client_credentials",
                "client_id": application.client_id,
                "client_secret": raw_secret,
                "scope": "create_race race_action chat_message read",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["access_token"])
        self.assertNotIn("refresh_token", payload)
