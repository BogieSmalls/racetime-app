from django.test import TestCase
from django.urls import reverse
from oauth2_provider.models import get_application_model

from racetime.models import Bot, Category, ExternalIdentity, User


class IdentityLinksAPITests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(
            name="Zelda 1 Randomizer Racing",
            short_name="Z1RR",
            slug="z1rr",
        )
        application_model = get_application_model()
        self.client_secret = "restream-confidential-secret"
        self.application = application_model.objects.create(
            name="Z1RR Restream",
            client_id="z1rr-restream",
            client_secret=self.client_secret,
            client_type=application_model.CLIENT_CONFIDENTIAL,
            authorization_grant_type=application_model.GRANT_CLIENT_CREDENTIALS,
        )
        Bot.objects.create(
            application=self.application,
            category=self.category,
            name="Z1RR Restream",
        )
        self.url = reverse(
            "oauth_identity_links",
            kwargs={"category": self.category.slug},
        )

    def access_token(self):
        response = self.client.post(
            reverse("oauth2_token"),
            {
                "grant_type": "client_credentials",
                "client_id": self.application.client_id,
                "client_secret": self.client_secret,
                "scope": "read",
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["access_token"]

    def create_linked_user(
        self,
        *,
        email,
        twitch_login,
        discord_id=None,
        racetimegg_id=None,
        active=True,
    ):
        user = User.objects.create_user(
            email=email,
            password=None,
            name=twitch_login,
            discriminator="0000",
            twitch_login=twitch_login,
            active=active,
        )
        if discord_id:
            ExternalIdentity.objects.create(
                user=user,
                provider="discord",
                subject=discord_id,
            )
        if racetimegg_id:
            ExternalIdentity.objects.create(
                user=user,
                provider="racetimegg",
                subject=racetimegg_id,
            )
        return user

    def test_active_category_bot_gets_only_complete_verified_identity_links(self):
        self.create_linked_user(
            email="linked@example.invalid",
            twitch_login="LinkedRacer",
            discord_id="123456789012345678",
            racetimegg_id="rtgg-linked",
        )
        self.create_linked_user(
            email="missing-discord@example.invalid",
            twitch_login="MissingDiscord",
            racetimegg_id="rtgg-missing-discord",
        )
        self.create_linked_user(
            email="inactive@example.invalid",
            twitch_login="InactiveRacer",
            discord_id="223456789012345678",
            racetimegg_id="rtgg-inactive",
            active=False,
        )

        response = self.client.get(
            self.url,
            HTTP_AUTHORIZATION=f"Bearer {self.access_token()}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "identities": [
                    {
                        "racetimegg_id": "rtgg-linked",
                        "discord_id": "123456789012345678",
                        "twitch_login": "linkedracer",
                    }
                ]
            },
        )

    def test_endpoint_rejects_missing_token_and_non_restream_bot(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)

        bot = self.category.bot_set.get()
        bot.name = "Another Category Bot"
        bot.save(update_fields=("name",))
        response = self.client.get(
            self.url,
            HTTP_AUTHORIZATION=f"Bearer {self.access_token()}",
        )
        self.assertEqual(response.status_code, 403)
