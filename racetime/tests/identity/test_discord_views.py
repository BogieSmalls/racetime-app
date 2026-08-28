from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from racetime.discord import DISCORD_OAUTH_SESSION_KEY, DiscordIdentity, DiscordOAuthError
from racetime.models import ExternalIdentity, ProfileImportCandidate, User, UserAction
from racetime.rtgg import RTGGImportError


PENDING_IDENTITY_SESSION_KEY = "discord_pending_identity"


class DiscordViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

    def set_oauth_state(self, *, state="state-value", next_url="/", issued_at=None):
        session = self.client.session
        session[DISCORD_OAUTH_SESSION_KEY] = {
            "state": state,
            "issued_at": int((issued_at or timezone.now()).timestamp()),
            "next": next_url,
        }
        session.save()
        return state

    def set_pending_identity(self, *, subject="123", next_url="/", issued_at=None):
        session = self.client.session
        session[PENDING_IDENTITY_SESSION_KEY] = {
            "subject": subject,
            "issued_at": int((issued_at or timezone.now()).timestamp()),
            "next": next_url,
        }
        session.save()

    def configure_client(self, client_class, *, subject="123"):
        oauth = client_class.return_value
        oauth.exchange_code.return_value = "provider-access-token"
        oauth.fetch_identity.return_value = DiscordIdentity(subject=subject)
        return oauth

    def racer_user_count(self):
        return User.objects.exclude(email=User.SYSTEM_USER).count()

    @mock.patch("racetime.views.discord_auth.DiscordOAuthClient")
    def test_initiation_redirect_has_new_state_and_safe_next(self, client_class):
        client_class.return_value.authorization_url.side_effect = (
            lambda state: f"https://discord.com/oauth2/authorize?state={state}"
        )
        response = self.client.get(
            reverse("discord_initiate"),
            {"next": "https://testserver/category/z1rr"},
            secure=True,
            HTTP_HOST="testserver",
        )
        self.assertEqual(response.status_code, 302)
        state = parse_qs(urlparse(response["Location"]).query)["state"][0]
        pending = self.client.session[DISCORD_OAUTH_SESSION_KEY]
        self.assertEqual(pending["state"], state)
        self.assertEqual(pending["next"], "https://testserver/category/z1rr")
        self.assertIn("no-store", response["Cache-Control"])

    def test_route_contract_uses_exact_paths(self):
        expected = {
            "/account/auth": "login_or_register",
            "/account/discord": "discord_initiate",
            "/account/discord/callback": "discord_callback",
            "/account/discord/create": "discord_create_account",
            "/account/logout": "logout",
        }
        for path, name in expected.items():
            with self.subTest(path=path):
                self.assertEqual(resolve(path).url_name, name)

    @mock.patch("racetime.views.discord_auth.DiscordOAuthClient")
    def test_existing_identity_logs_in_and_updates_only_authentication_time(
        self, client_class
    ):
        user = User.objects.create_user(
            "123@discord.invalid", name="Stable Racer"
        )
        original_time = timezone.now() - timedelta(days=2)
        identity = ExternalIdentity.objects.create(
            user=user,
            provider="discord",
            subject="123",
            last_authenticated_at=original_time,
        )
        original = {
            "user_id": identity.user_id,
            "provider": identity.provider,
            "subject": identity.subject,
            "created_at": identity.created_at,
        }
        oauth = self.configure_client(client_class)
        state = self.set_oauth_state(next_url="/category/z1rr")
        response = self.client.get(
            reverse("discord_callback"),
            {"state": state, "code": "authorization-code"},
            secure=True,
            HTTP_HOST="testserver",
        )
        self.assertRedirects(response, "/category/z1rr", fetch_redirect_response=False)
        identity.refresh_from_db()
        user.refresh_from_db()
        self.assertGreater(identity.last_authenticated_at, original_time)
        for field, value in original.items():
            self.assertEqual(getattr(identity, field), value)
        self.assertEqual(user.name, "Stable Racer")
        self.assertEqual(int(self.client.session[SESSION_KEY]), user.id)
        self.assertEqual(
            self.client.session[BACKEND_SESSION_KEY],
            "django.contrib.auth.backends.ModelBackend",
        )
        self.assertTrue(
            UserAction.objects.filter(user=user, action="discord_login").exists()
        )
        self.assertNotIn(DISCORD_OAUTH_SESSION_KEY, self.client.session)
        oauth.exchange_code.assert_called_once_with("authorization-code")
        oauth.fetch_identity.assert_called_once_with("provider-access-token")
        self.assertNotIn("provider-access-token", str(dict(self.client.session)))

    @mock.patch("racetime.views.discord_auth.DiscordOAuthClient")
    def test_inactive_linked_user_is_not_logged_in(self, client_class):
        user = User.objects.create_user(
            "123@discord.invalid", name="Inactive Racer", active=False
        )
        ExternalIdentity.objects.create(
            user=user, provider="discord", subject="123"
        )
        self.configure_client(client_class)
        state = self.set_oauth_state()
        response = self.client.get(
            reverse("discord_callback"),
            {"state": state, "code": "authorization-code"},
            secure=True,
            HTTP_HOST="testserver",
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertContains(response, "could not complete", status_code=400)

    @mock.patch("racetime.views.discord_auth.DiscordOAuthClient")
    def test_unknown_identity_stops_at_name_selection_without_user(self, client_class):
        self.configure_client(client_class)
        state = self.set_oauth_state(next_url="/races")
        response = self.client.get(
            reverse("discord_callback"),
            {"state": state, "code": "authorization-code"},
            secure=True,
            HTTP_HOST="testserver",
        )
        self.assertRedirects(
            response, reverse("discord_create_account"), fetch_redirect_response=False
        )
        self.assertEqual(self.racer_user_count(), 0)
        self.assertEqual(
            self.client.session[PENDING_IDENTITY_SESSION_KEY]["subject"], "123"
        )
        self.assertEqual(
            self.client.session[PENDING_IDENTITY_SESSION_KEY]["next"], "/races"
        )
        self.assertNotIn("provider-access-token", str(dict(self.client.session)))

    def test_name_form_is_the_only_public_account_input(self):
        self.set_pending_identity()
        response = self.client.get(reverse("discord_create_account"), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(tuple(response.context["form"].fields), ("name",))
        self.assertContains(response, 'name="name"')
        for forbidden in ("email", "password", "provider", "subject", "is_staff"):
            self.assertNotContains(response, f'name="{forbidden}"')

    def test_valid_name_atomically_creates_unusable_account_identity_and_login(self):
        self.set_pending_identity(next_url="/category/z1rr")
        response = self.client.post(
            reverse("discord_create_account"),
            {"name": "New Racer"},
            secure=True,
            HTTP_HOST="testserver",
        )
        self.assertRedirects(response, "/category/z1rr", fetch_redirect_response=False)
        user = User.objects.get(email="123@discord.invalid")
        self.assertEqual(user.name, "New Racer")
        self.assertFalse(user.has_usable_password())
        self.assertTrue(
            ExternalIdentity.objects.filter(
                user=user, provider="discord", subject="123"
            ).exists()
        )
        self.assertEqual(int(self.client.session[SESSION_KEY]), user.id)
        self.assertNotIn(PENDING_IDENTITY_SESSION_KEY, self.client.session)
        self.assertEqual(
            set(UserAction.objects.filter(user=user).values_list("action", flat=True)),
            {"create_account", "discord_login"},
        )
    @staticmethod
    def import_profile():
        return {
            "subject": "rtgg-subject",
            "url": "https://racetime.gg/user/rtgg-subject/racer",
            "name": "RTGG Racer",
            "discriminator": "4670",
            "twitch_login": "racer_live",
            "twitch_name": "RacerLive",
            "avatar_url": None,
            "pronouns": "she/her",
            "bio": "Imported bio",
        }

    @mock.patch("racetime.views.discord_auth.load_profile")
    def test_private_candidate_is_shown_only_after_discord_authentication(
        self, load_profile
    ):
        ProfileImportCandidate.objects.create(
            discord_subject="123",
            racetimegg_subject="rtgg-subject",
            twitch_id=987654321,
        )
        load_profile.return_value = self.import_profile()
        self.set_pending_identity()

        response = self.client.get(reverse("discord_create_account"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RTGG Racer#4670")
        self.assertContains(response, "Import profile and create account")
        self.assertContains(response, "Create without importing")
        self.assertEqual(self.racer_user_count(), 0)
        load_profile.assert_called_once_with(
            "https://racetime.gg/user/rtgg-subject"
        )

    @mock.patch("racetime.views.discord_auth.load_profile")
    def test_import_choice_creates_account_with_profile_and_consumes_candidate(
        self, load_profile
    ):
        ProfileImportCandidate.objects.create(
            discord_subject="123",
            racetimegg_subject="rtgg-subject",
            twitch_id=987654321,
        )
        load_profile.return_value = self.import_profile()
        self.set_pending_identity(next_url="/category/z1rr")

        response = self.client.post(
            reverse("discord_create_account"),
            {"profile_choice": "import"},
            secure=True,
            HTTP_HOST="testserver",
        )

        self.assertRedirects(response, "/category/z1rr", fetch_redirect_response=False)
        user = User.objects.get(email="123@discord.invalid")
        self.assertEqual(user.name, "RTGG Racer")
        self.assertEqual(user.discriminator, "4670")
        self.assertEqual(user.pronouns, "she/her")
        self.assertEqual(user.profile_bio, "Imported bio")
        self.assertEqual(user.twitch_id, 987654321)
        self.assertEqual(user.twitch_login, "racer_live")
        self.assertEqual(user.twitch_name, "RacerLive")
        self.assertEqual(
            set(user.external_identities.values_list("provider", "subject")),
            {("discord", "123"), ("racetimegg", "rtgg-subject")},
        )
        self.assertFalse(
            ProfileImportCandidate.objects.filter(discord_subject="123").exists()
        )

    def test_fresh_choice_copies_nothing_and_keeps_candidate_for_later(self):
        ProfileImportCandidate.objects.create(
            discord_subject="123",
            racetimegg_subject="rtgg-subject",
            twitch_id=987654321,
        )
        self.set_pending_identity()

        response = self.client.post(
            reverse("discord_create_account"),
            {"profile_choice": "fresh", "name": "Fresh Racer"},
            secure=True,
            HTTP_HOST="testserver",
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        user = User.objects.get(email="123@discord.invalid")
        self.assertEqual(user.name, "Fresh Racer")
        self.assertIsNone(user.twitch_id)
        self.assertFalse(
            user.external_identities.filter(provider="racetimegg").exists()
        )
        self.assertTrue(
            ProfileImportCandidate.objects.filter(discord_subject="123").exists()
        )

    @mock.patch("racetime.views.discord_auth.load_profile")
    def test_candidate_provider_failure_still_allows_fresh_account(self, load_profile):
        ProfileImportCandidate.objects.create(
            discord_subject="123",
            racetimegg_subject="rtgg-subject",
            twitch_id=987654321,
        )
        load_profile.side_effect = RTGGImportError("provider unavailable")
        self.set_pending_identity()

        page = self.client.get(reverse("discord_create_account"), secure=True)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "could not be loaded right now")

        response = self.client.post(
            reverse("discord_create_account"),
            {"profile_choice": "fresh", "name": "Fresh Racer"},
            secure=True,
            HTTP_HOST="testserver",
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(name="Fresh Racer").exists())


    def test_invalid_name_does_not_create_or_consume_pending_identity(self):
        self.set_pending_identity()
        response = self.client.post(
            reverse("discord_create_account"), {"name": "x"}, secure=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at least 3")
        self.assertEqual(self.racer_user_count(), 0)
        self.assertIn(PENDING_IDENTITY_SESSION_KEY, self.client.session)

    def test_expired_and_replayed_pending_identity_fail_closed(self):
        self.set_pending_identity(issued_at=timezone.now() - timedelta(minutes=11))
        expired = self.client.post(
            reverse("discord_create_account"), {"name": "New Racer"}, secure=True
        )
        self.assertEqual(expired.status_code, 400)
        self.assertEqual(self.racer_user_count(), 0)
        self.assertNotIn(PENDING_IDENTITY_SESSION_KEY, self.client.session)

        replay = self.client.post(
            reverse("discord_create_account"), {"name": "New Racer"}, secure=True
        )
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(self.racer_user_count(), 0)

    def test_synthetic_email_collision_never_attaches_identity(self):
        existing = User.objects.create_user(
            "123@discord.invalid", name="Unrelated Account"
        )
        self.set_pending_identity()
        response = self.client.post(
            reverse("discord_create_account"), {"name": "New Racer"}, secure=True
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ExternalIdentity.objects.filter(user=existing).exists())
        self.assertEqual(self.racer_user_count(), 1)

    def test_completed_concurrent_identity_wins_without_renaming_user(self):
        existing = User.objects.create_user(
            "different@discord.invalid", name="Concurrent Racer"
        )
        ExternalIdentity.objects.create(
            user=existing, provider="discord", subject="123"
        )
        self.set_pending_identity()
        response = self.client.post(
            reverse("discord_create_account"), {"name": "Ignored Name"}, secure=True
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        existing.refresh_from_db()
        self.assertEqual(existing.name, "Concurrent Racer")
        self.assertEqual(self.racer_user_count(), 1)
        self.assertEqual(int(self.client.session[SESSION_KEY]), existing.id)

    @mock.patch("racetime.views.discord_auth.DiscordOAuthClient")
    def test_provider_failure_is_generic_and_does_not_echo_error(self, client_class):
        client_class.return_value.exchange_code.side_effect = DiscordOAuthError(
            "authorization-code client-secret provider-body"
        )
        state = self.set_oauth_state()
        response = self.client.get(
            reverse("discord_callback"),
            {"state": state, "code": "authorization-code"},
            secure=True,
            HTTP_HOST="testserver",
        )
        self.assertEqual(response.status_code, 400)
        for secret in ("authorization-code", "client-secret", "provider-body"):
            self.assertNotContains(response, secret, status_code=400)

    @mock.patch("racetime.views.discord_auth.DiscordOAuthClient")
    def test_initial_rate_limit_blocks_provider_after_ten_requests(self, client_class):
        client_class.return_value.authorization_url.side_effect = (
            lambda state: f"https://discord.com/oauth2/authorize?state={state}"
        )
        for request_number in range(1, 12):
            response = self.client.get(
                reverse("discord_initiate"),
                secure=True,
                REMOTE_ADDR="192.0.2.20",
                HTTP_HOST="testserver",
            )
            if request_number <= 10:
                self.assertEqual(response.status_code, 302)
            else:
                self.assertEqual(response.status_code, 429)
                self.assertIn("Retry-After", response)
        self.assertEqual(client_class.return_value.authorization_url.call_count, 10)

    def test_create_post_is_csrf_protected(self):
        protected_client = Client(enforce_csrf_checks=True)
        session = protected_client.session
        session[PENDING_IDENTITY_SESSION_KEY] = {
            "subject": "123",
            "issued_at": int(timezone.now().timestamp()),
            "next": "/",
        }
        session.save()
        response = protected_client.post(
            reverse("discord_create_account"), {"name": "New Racer"}, secure=True
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.racer_user_count(), 0)
    @mock.patch("racetime.views.discord_auth.load_profile")
    def test_import_refuses_candidate_twitch_linked_to_another_user(
        self, load_profile
    ):
        User.objects.create_user(
            "other@example.com",
            name="Other Racer",
            twitch_id=987654321,
            twitch_login="racer_live",
            twitch_name="RacerLive",
        )
        ProfileImportCandidate.objects.create(
            discord_subject="123",
            racetimegg_subject="rtgg-subject",
            twitch_id=987654321,
        )
        load_profile.return_value = self.import_profile()
        self.set_pending_identity()

        response = self.client.post(
            reverse("discord_create_account"),
            {"profile_choice": "import"},
            secure=True,
            HTTP_HOST="testserver",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "could not be imported")
        self.assertFalse(User.objects.filter(email="123@discord.invalid").exists())
        self.assertTrue(ProfileImportCandidate.objects.exists())
