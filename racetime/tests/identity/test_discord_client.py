import base64
from unittest import mock
from urllib.parse import parse_qs, urlparse

import requests
from django.test import RequestFactory, SimpleTestCase, override_settings

from project.settings import base as base_settings
from racetime.discord import (
    DISCORD_OAUTH_SESSION_KEY,
    DiscordIdentity,
    DiscordOAuthClient,
    DiscordOAuthDenied,
    DiscordOAuthError,
    DiscordOAuthStateError,
    consume_discord_callback,
    consume_discord_oauth_state,
    issue_discord_oauth_state,
)


DISCORD_SETTINGS = {
    "DISCORD_AUTHORIZE_URL": "https://discord.com/oauth2/authorize",
    "DISCORD_TOKEN_URL": "https://discord.com/api/oauth2/token",
    "DISCORD_USER_URL": "https://discord.com/api/users/@me",
    "DISCORD_CLIENT_ID": "client-123",
    "DISCORD_CLIENT_SECRET": "client-secret-value",
    "DISCORD_REDIRECT_URI": "https://testserver/account/discord/callback",
    "DISCORD_HTTP_TIMEOUT": (2.0, 7.0),
}


@override_settings(**DISCORD_SETTINGS)
class DiscordAuthorizationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, path="/", data=None):
        request = self.factory.get(
            path,
            data=data or {},
            secure=True,
            HTTP_HOST="testserver",
        )
        request.session = {}
        return request

    def test_base_settings_are_disabled_and_have_no_credentials(self):
        self.assertFalse(base_settings.RT_DISCORD_AUTH_ENABLED)
        self.assertIsNone(base_settings.DISCORD_CLIENT_ID)
        self.assertIsNone(base_settings.DISCORD_CLIENT_SECRET)

    def test_authorization_url_has_exact_endpoint_and_minimal_scope(self):
        parsed = urlparse(DiscordOAuthClient(session=mock.Mock()).authorization_url("state"))
        self.assertEqual(
            (parsed.scheme, parsed.netloc, parsed.path),
            ("https", "discord.com", "/oauth2/authorize"),
        )
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "client_id": ["client-123"],
                "redirect_uri": [
                    "https://testserver/account/discord/callback"
                ],
                "response_type": ["code"],
                "scope": ["identify"],
                "state": ["state"],
            },
        )

    def test_issued_state_is_256_bits_url_safe_and_has_safe_next_and_time(self):
        request = self.request()
        state = issue_discord_oauth_state(
            request,
            "https://testserver/category/z1rr",
            now=1_000,
        )
        decoded = base64.urlsafe_b64decode(state + "=" * (-len(state) % 4))
        self.assertEqual(len(decoded), 32)
        self.assertRegex(state, r"^[A-Za-z0-9_-]+$")
        self.assertEqual(
            request.session[DISCORD_OAUTH_SESSION_KEY],
            {
                "state": state,
                "issued_at": 1_000,
                "next": "https://testserver/category/z1rr",
            },
        )

    def test_unsafe_next_is_replaced_with_root(self):
        for next_url in (
            "http://testserver/insecure",
            "https://evil.invalid/steal",
            "//evil.invalid/steal",
        ):
            with self.subTest(next_url=next_url):
                request = self.request()
                issue_discord_oauth_state(request, next_url, now=1_000)
                self.assertEqual(
                    request.session[DISCORD_OAUTH_SESSION_KEY]["next"], "/"
                )

    def test_only_one_pending_state_exists_per_session(self):
        request = self.request()
        first = issue_discord_oauth_state(request, "/first", now=1_000)
        second = issue_discord_oauth_state(request, "/second", now=1_001)
        self.assertNotEqual(first, second)
        self.assertEqual(
            request.session[DISCORD_OAUTH_SESSION_KEY]["state"], second
        )
        with self.assertRaises(DiscordOAuthStateError):
            consume_discord_oauth_state(request, first, now=1_001)
        self.assertNotIn(DISCORD_OAUTH_SESSION_KEY, request.session)

    def test_state_is_consumed_once_and_returns_safe_next(self):
        request = self.request()
        state = issue_discord_oauth_state(request, "/races", now=1_000)
        self.assertEqual(
            consume_discord_oauth_state(request, state, now=1_599),
            "/races",
        )
        with self.assertRaises(DiscordOAuthStateError):
            consume_discord_oauth_state(request, state, now=1_599)

    def test_mismatch_and_expiration_consume_pending_state(self):
        for supplied, now in (("mismatch", 1_001), (None, 1_601)):
            with self.subTest(supplied=supplied, now=now):
                request = self.request()
                state = issue_discord_oauth_state(request, "/", now=1_000)
                with self.assertRaises(DiscordOAuthStateError):
                    consume_discord_oauth_state(
                        request, supplied or state, now=now
                    )
                self.assertNotIn(DISCORD_OAUTH_SESSION_KEY, request.session)

    def test_provider_denial_consumes_state_without_exposing_reason(self):
        request = self.request()
        state = issue_discord_oauth_state(request, "/", now=1_000)
        request.GET = self.factory.get(
            "/callback",
            {"state": state, "error": "access_denied", "error_description": "secret body"},
        ).GET
        with self.assertRaisesRegex(DiscordOAuthDenied, "authorization was denied") as caught:
            consume_discord_callback(request, now=1_001)
        self.assertNotIn("secret body", str(caught.exception))
        self.assertNotIn(DISCORD_OAUTH_SESSION_KEY, request.session)


@override_settings(**DISCORD_SETTINGS)
class DiscordClientTests(SimpleTestCase):
    def response(self, payload=None, status_error=None):
        response = mock.Mock()
        response.text = "full-sensitive-response-body"
        response.raise_for_status.side_effect = status_error
        if isinstance(payload, Exception):
            response.json.side_effect = payload
        else:
            response.json.return_value = payload
        return response

    def test_exchange_uses_exact_endpoint_redirect_timeout_and_credentials(self):
        session = mock.Mock()
        session.post.return_value = self.response({"access_token": "token-value"})
        client = DiscordOAuthClient(session=session)
        self.assertEqual(client.exchange_code("authorization-code"), "token-value")
        session.post.assert_called_once_with(
            "https://discord.com/api/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": "authorization-code",
                "redirect_uri": "https://testserver/account/discord/callback",
                "client_id": "client-123",
                "client_secret": "client-secret-value",
            },
            headers={"Accept": "application/json"},
            timeout=(2.0, 7.0),
        )
        session.post.return_value.raise_for_status.assert_called_once_with()

    def test_fetch_identity_returns_only_immutable_numeric_subject(self):
        session = mock.Mock()
        session.get.return_value = self.response(
            {
                "id": "1234567890",
                "username": "do-not-return",
                "email": "do-not-return@example.invalid",
                "avatar": "do-not-return",
            }
        )
        identity = DiscordOAuthClient(session=session).fetch_identity("token-value")
        self.assertEqual(identity, DiscordIdentity(subject="1234567890"))
        with self.assertRaises((AttributeError, TypeError)):
            identity.subject = "different"
        self.assertEqual(tuple(identity.__dict__), ("subject",))
        session.get.assert_called_once_with(
            "https://discord.com/api/users/@me",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer token-value",
            },
            timeout=(2.0, 7.0),
        )
        session.get.return_value.raise_for_status.assert_called_once_with()

    def test_exchange_failures_are_sanitized(self):
        sensitive = (
            "authorization-code",
            "client-secret-value",
            "token-value",
            "full-sensitive-response-body",
        )
        cases = (
            requests.Timeout("authorization-code timed out"),
            self.response(
                {"access_token": "token-value"},
                requests.HTTPError("full-sensitive-response-body"),
            ),
            self.response(ValueError("full-sensitive-response-body")),
            self.response({}),
        )
        for case in cases:
            with self.subTest(case=type(case).__name__):
                session = mock.Mock()
                if isinstance(case, Exception):
                    session.post.side_effect = case
                else:
                    session.post.return_value = case
                with self.assertRaises(DiscordOAuthError) as caught:
                    DiscordOAuthClient(session=session).exchange_code(
                        "authorization-code"
                    )
                message = str(caught.exception)
                for value in sensitive:
                    self.assertNotIn(value, message)

    def test_identity_failures_are_sanitized(self):
        cases = (
            requests.Timeout("token-value timed out"),
            self.response(
                {"id": "123"},
                requests.HTTPError("full-sensitive-response-body"),
            ),
            self.response(ValueError("full-sensitive-response-body")),
            self.response({}),
            self.response({"id": ""}),
            self.response({"id": "abc"}),
            self.response({"id": 123}),
        )
        for case in cases:
            with self.subTest(case=type(case).__name__):
                session = mock.Mock()
                if isinstance(case, Exception):
                    session.get.side_effect = case
                else:
                    session.get.return_value = case
                with self.assertRaises(DiscordOAuthError) as caught:
                    DiscordOAuthClient(session=session).fetch_identity("token-value")
                message = str(caught.exception)
                for value in (
                    "token-value",
                    "full-sensitive-response-body",
                    "abc",
                ):
                    self.assertNotIn(value, message)

    def test_callback_requires_code_after_consuming_valid_state(self):
        factory = RequestFactory()
        request = factory.get("/callback", secure=True, HTTP_HOST="testserver")
        request.session = {}
        state = issue_discord_oauth_state(request, "/", now=1_000)
        request.GET = factory.get("/callback", {"state": state}).GET
        with self.assertRaises(DiscordOAuthError):
            consume_discord_callback(request, now=1_001)
        self.assertNotIn(DISCORD_OAUTH_SESSION_KEY, request.session)
