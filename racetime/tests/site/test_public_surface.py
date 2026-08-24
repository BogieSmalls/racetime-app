from django.contrib.auth import SESSION_KEY
from django.test import TestCase
from django.urls import resolve, reverse

from racetime.models import Category, CategoryRequest, Entrant, Race, User


class PublicSurfaceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "123@discord.invalid",
            name="Discord Racer",
            patreon_id=1234,
            patreon_name="Legacy Supporter",
            is_supporter=True,
        )

    def test_disabled_legacy_routes_are_exact_generic_404s(self):
        routes = (
            reverse("login"),
            reverse("create_account"),
            reverse("edit_account_security"),
            reverse("password_reset"),
            reverse("password_reset_done"),
            reverse(
                "password_reset_confirm",
                kwargs={"uidb64": "legacy", "token": "legacy-token"},
            ),
            reverse("password_reset_complete"),
            reverse("patreon_auth"),
            reverse("patreon_refresh"),
            reverse("patreon_disconnect"),
            reverse("request_category"),
        )
        for url in routes:
            for method in ("get", "post"):
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method)(url)
                    self.assertEqual(response.status_code, 404)
                    self.assertNotIn("Location", response)
                    self.assertNotContains(
                        response,
                        "<form",
                        status_code=404,
                        html=False,
                    )

    def test_disabled_posts_cannot_mutate_email_password_or_patreon(self):
        self.client.force_login(self.user)
        original_password = self.user.password
        original_email = self.user.email

        response = self.client.post(
            reverse("edit_account"),
            {
                "email": "attacker@example.com",
                "name": "Renamed Racer",
            },
        )
        self.assertRedirects(
            response,
            reverse("edit_account"),
            fetch_redirect_response=False,
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Renamed Racer")
        self.assertEqual(self.user.email, original_email)

        password_response = self.client.post(
            reverse("edit_account_security"),
            {
                "old_password": "ignored",
                "new_password1": "Changed-password-123",
                "new_password2": "Changed-password-123",
            },
        )
        self.assertEqual(password_response.status_code, 404)

        for route in ("patreon_refresh", "patreon_disconnect"):
            with self.subTest(route=route):
                self.assertEqual(self.client.post(reverse(route)).status_code, 404)
        self.assertEqual(
            self.client.get(
                reverse("patreon_auth"),
                {"code": "must-not-reach-provider"},
            ).status_code,
            404,
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.password, original_password)
        self.assertEqual(self.user.patreon_id, 1234)
        self.assertEqual(self.user.patreon_name, "Legacy Supporter")
        self.assertTrue(self.user.is_supporter)
        self.assertEqual(CategoryRequest.objects.count(), 0)

    def test_auth_landing_exposes_only_discord(self):
        response = self.client.get(
            reverse("login_or_register"),
            {"next": "/z1rr"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Continue with Discord", count=1)
        self.assertContains(response, reverse("discord_initiate"))
        for forbidden in ("email", "password", "Patreon", "<form"):
            self.assertNotContains(response, forbidden, html=False)

    def test_navigation_hides_disabled_surfaces_and_synthetic_email(self):
        self.client.force_login(self.user)
        for route in (
            "home",
            "edit_account",
            "edit_account_connections",
            "edit_account_teams",
            "account_standing",
        ):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, reverse("request_category"))
                self.assertNotContains(response, reverse("edit_account_security"))
                self.assertNotContains(response, "Patreon")
                self.assertNotContains(response, self.user.email)

        connections = self.client.get(reverse("edit_account_connections"))
        self.assertContains(connections, "separate from Discord sign-in")
        account = self.client.get(reverse("edit_account"))
        self.assertNotContains(account, 'name="email"')
        self.assertContains(account, "Z1RR RaceTime account")

    def test_required_public_capabilities_remain(self):
        exact_routes = {
            reverse("login_or_register"): "login_or_register",
            reverse("discord_initiate"): "discord_initiate",
            reverse("discord_callback"): "discord_callback",
            reverse("discord_create_account"): "discord_create_account",
            reverse("logout"): "logout",
            reverse("edit_account"): "edit_account",
            reverse("delete_account"): "delete_account",
            reverse("twitch_auth"): "twitch_auth",
            reverse("twitch_disconnect"): "twitch_disconnect",
            reverse("oauth2_authorize"): "oauth2_authorize",
            reverse("category", kwargs={"category": "z1rr"}): "category",
            reverse(
                "race",
                kwargs={"category": "z1rr", "race": "sample-race"},
            ): "race",
        }
        for url, route_name in exact_routes.items():
            with self.subTest(url=url):
                self.assertEqual(resolve(url).url_name, route_name)

        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("edit_account")).status_code, 200)
        self.assertEqual(self.client.get(reverse("delete_account")).status_code, 200)
        connections = self.client.get(reverse("edit_account_connections"))
        self.assertEqual(connections.status_code, 200)
        self.assertContains(connections, "Connect your Twitch.tv account")
        self.assertIn(SESSION_KEY, self.client.session)

    def test_active_race_still_blocks_public_name_changes(self):
        category = Category.objects.create(
            name="Zelda 1 Randomizer",
            short_name="Z1R",
            slug="z1rr",
            streaming_required=False,
        )
        race = Race.objects.create(
            category=category,
            custom_goal="Beat the game",
            slug="active-race",
            opened_by=self.user,
            streaming_required=False,
        )
        Entrant.objects.create(user=self.user, race=race)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("edit_account"),
            {"name": "Forbidden Mid-Race Rename"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "may not change your name")
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Discord Racer")

    def test_stream_required_join_still_depends_on_twitch_connection(self):
        category = Category.objects.create(
            name="Zelda 1 Randomizer",
            short_name="Z1R",
            slug="z1rr",
            streaming_required=True,
        )
        race = Race.objects.create(
            category=category,
            custom_goal="Beat the game",
            slug="stream-required",
            opened_by=self.user,
            streaming_required=True,
        )

        self.assertFalse(race.can_join(self.user))
        self.user.twitch_id = 4321
        self.user.twitch_login = "discordracer"
        self.user.twitch_name = "DiscordRacer"
        self.user.save(
            update_fields=("twitch_id", "twitch_login", "twitch_name")
        )
        connected_user = User.objects.get(pk=self.user.pk)
        self.assertTrue(race.can_join(connected_user))
