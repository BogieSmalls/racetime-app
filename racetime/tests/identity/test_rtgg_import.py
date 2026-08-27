import io
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from PIL import Image

from racetime.models import ExternalIdentity, User
from racetime.rtgg import discover_profile


class _Response:
    def __init__(self, *, url, text):
        self.url = url
        self.text = text

    def raise_for_status(self):
        return None


class _DiscoverySession:
    def __init__(self):
        self.search_terms = []

    def get(self, url, **kwargs):
        if url == "https://racetime.gg/search":
            self.search_terms.append(kwargs["params"]["q"])
            return _Response(
                url="https://racetime.gg/search?q=BogieSmalls",
                text="""
                    <a class="user-pop inline" href="/user/wrong/other"></a>
                    <a class="user-pop inline" href="/user/rtgg-subject/bogie"></a>
                """,
            )
        if url.endswith("/user/wrong/other"):
            return _Response(
                url=url,
                text="""
                    <div class="user-profile">
                        <span class="name">Other</span>
                        <span class="scrim">#1111</span>
                        <a class="twitch-channel" href="https://www.twitch.tv/somebody_else">Other</a>
                    </div>
                """,
            )
        if url.endswith("/user/rtgg-subject/bogie"):
            return _Response(
                url=url,
                text="""
                    <div class="user-profile">
                        <span class="avatar" style="background-image: url(https://racetime.gg/media/bogie.png)"></span>
                        <span class="name">Bogie</span>
                        <span class="scrim">#4670</span>
                        <span class="pronouns">he / him</span>
                        <a class="twitch-channel" href="https://www.twitch.tv/bogiesmalls">BogieSmalls</a>
                        <p class="bio">Z1R racer</p>
                    </div>
                """,
            )
        raise AssertionError(f"Unexpected URL: {url}")


class RacetimeGGDiscoveryTests(SimpleTestCase):
    def test_verified_twitch_login_selects_the_exact_public_profile(self):
        session = _DiscoverySession()

        profile = discover_profile(
            twitch_login="bogiesmalls",
            twitch_name="BogieSmalls",
            session=session,
        )

        self.assertEqual(session.search_terms, ["bogiesmalls"])
        self.assertEqual(profile["subject"], "rtgg-subject")
        self.assertEqual(profile["name"], "Bogie")
        self.assertEqual(profile["discriminator"], "4670")
        self.assertEqual(profile["twitch_login"], "bogiesmalls")
        self.assertEqual(profile["pronouns"], "he/him")
        self.assertEqual(profile["bio"], "Z1R racer")
        self.assertEqual(
            profile["avatar_url"],
            "https://racetime.gg/media/bogie.png",
        )


class RacetimeGGImportViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="123456789012345678@discord.invalid",
            password=None,
            name="Discord Name",
            discriminator="0000",
            twitch_id=12345,
            twitch_login="bogiesmalls",
            twitch_name="BogieSmalls",
        )
        ExternalIdentity.objects.create(
            user=self.user,
            provider="discord",
            subject="123456789012345678",
        )
        self.client.force_login(self.user)

    @mock.patch("racetime.views.user.discover_profile")
    def test_connected_twitch_account_shows_the_exact_profile_for_confirmation(
        self, discover,
    ):
        discover.return_value = {
            "subject": "rtgg-subject",
            "url": "https://racetime.gg/user/rtgg-subject/bogie",
            "name": "Bogie",
            "discriminator": "4670",
            "twitch_login": "bogiesmalls",
            "avatar_url": "https://racetime.gg/media/bogie.png",
            "pronouns": "he/him",
            "bio": "Z1R racer",
        }

        response = self.client.get(reverse("racetimegg_import"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "We found Bogie#4670")
        self.assertContains(response, "Import this profile")
        discover.assert_called_once_with(
            twitch_login="bogiesmalls",
            twitch_name="BogieSmalls",
        )

    @staticmethod
    def avatar_bytes():
        output = io.BytesIO()
        Image.new("RGB", (2, 2), "#e05000").save(output, format="PNG")
        return output.getvalue()

    @mock.patch("racetime.views.user.download_avatar")
    @mock.patch("racetime.views.user.load_profile")
    def test_import_links_identity_and_preserves_existing_local_fields(
        self, load_profile, download_avatar,
    ):
        self.user.profile_bio = "Keep my local bio"
        self.user.save(update_fields=["profile_bio"])
        load_profile.return_value = {
            "subject": "rtgg-subject",
            "url": "https://racetime.gg/user/rtgg-subject/bogie",
            "name": "Bogie",
            "discriminator": "4670",
            "twitch_login": "bogiesmalls",
            "avatar_url": "https://racetime.gg/media/bogie.png",
            "pronouns": "he/him",
            "bio": "RTGG bio",
        }
        download_avatar.return_value = self.avatar_bytes()

        response = self.client.post(
            reverse("racetimegg_import"),
            {"profile_url": load_profile.return_value["url"]},
        )

        self.assertRedirects(response, reverse("edit_account"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Bogie")
        self.assertEqual(self.user.discriminator, "4670")
        self.assertEqual(self.user.pronouns, "he/him")
        self.assertEqual(self.user.profile_bio, "Keep my local bio")
        self.assertTrue(self.user.avatar)
        self.addCleanup(
            self.user.avatar.storage.delete,
            self.user.avatar.name,
        )
        self.assertTrue(
            ExternalIdentity.objects.filter(
                user=self.user,
                provider="racetimegg",
                subject="rtgg-subject",
            ).exists()
        )
        load_profile.assert_called_once_with(
            "https://racetime.gg/user/rtgg-subject/bogie",
        )
        download_avatar.assert_called_once_with(
            "https://racetime.gg/media/bogie.png",
        )

    @mock.patch("racetime.views.user.load_profile")
    def test_import_refuses_a_profile_with_a_different_twitch_login(
        self, load_profile,
    ):
        load_profile.return_value = {
            "subject": "rtgg-subject",
            "url": "https://racetime.gg/user/rtgg-subject/other",
            "name": "Other",
            "discriminator": "1234",
            "twitch_login": "somebody_else",
            "avatar_url": None,
            "pronouns": None,
            "bio": None,
        }

        response = self.client.post(
            reverse("racetimegg_import"),
            {"profile_url": load_profile.return_value["url"]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "does not match your connected Twitch account",
            status_code=400,
        )
        self.assertFalse(
            ExternalIdentity.objects.filter(provider="racetimegg").exists()
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Discord Name")
        self.assertEqual(self.user.discriminator, "0000")

    @mock.patch("racetime.views.user.load_profile")
    def test_existing_link_is_not_reimported_over_later_profile_edits(
        self, load_profile,
    ):
        ExternalIdentity.objects.create(
            user=self.user,
            provider="racetimegg",
            subject="rtgg-subject",
        )
        self.user.name = "Later Edit"
        self.user.discriminator = "9999"
        self.user.save(update_fields=["name", "discriminator"])

        response = self.client.post(
            reverse("racetimegg_import"),
            {"profile_url": "https://racetime.gg/user/rtgg-subject/bogie"},
        )

        self.assertRedirects(response, reverse("edit_account"))
        load_profile.assert_not_called()
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Later Edit")
        self.assertEqual(self.user.discriminator, "9999")

    @mock.patch("racetime.views.user.load_profile")
    def test_import_refuses_a_profile_linked_to_another_account(
        self, load_profile,
    ):
        other = User.objects.create_user(
            email="other@example.com",
            password=None,
            name="Other",
            discriminator="1111",
        )
        ExternalIdentity.objects.create(
            user=other,
            provider="racetimegg",
            subject="rtgg-subject",
        )
        load_profile.return_value = {
            "subject": "rtgg-subject",
            "url": "https://racetime.gg/user/rtgg-subject/bogie",
            "name": "Bogie",
            "discriminator": "4670",
            "twitch_login": "bogiesmalls",
            "avatar_url": None,
            "pronouns": "he/him",
            "bio": "Z1R racer",
        }

        response = self.client.post(
            reverse("racetimegg_import"),
            {"profile_url": load_profile.return_value["url"]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "already linked to another Raceroom account",
            status_code=400,
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Discord Name")
        self.assertFalse(
            ExternalIdentity.objects.filter(
                user=self.user,
                provider="racetimegg",
            ).exists()
        )

    def test_twitch_connection_is_requested_before_import(self):
        self.user.twitch_id = None
        self.user.twitch_login = None
        self.user.twitch_name = None
        self.user.save(
            update_fields=["twitch_id", "twitch_login", "twitch_name"],
        )

        response = self.client.get(reverse("racetimegg_import"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Connect Twitch")
        self.assertEqual(
            self.client.session["twitch_auth_next"],
            reverse("racetimegg_import"),
        )

    @mock.patch("racetime.views.user.requests.get")
    @mock.patch.object(User, "twitch_access_token", return_value="token")
    def test_twitch_callback_returns_to_the_import_page(
        self, twitch_access_token, twitch_get,
    ):
        self.user.twitch_id = None
        self.user.twitch_login = None
        self.user.twitch_name = None
        self.user.save(
            update_fields=["twitch_id", "twitch_login", "twitch_name"],
        )
        self.client.get(reverse("racetimegg_import"))
        state = self.client.cookies["csrftoken"].value
        twitch_get.return_value.status_code = 200
        twitch_get.return_value.json.return_value = {
            "data": [{
                "id": "12345",
                "login": "bogiesmalls",
                "display_name": "BogieSmalls",
            }],
        }

        response = self.client.get(
            reverse("twitch_auth"),
            {"code": "oauth-code", "state": state},
        )

        self.assertRedirects(response, reverse("racetimegg_import"))
        self.assertNotIn("twitch_auth_next", self.client.session)
        self.user.refresh_from_db()
        self.assertEqual(self.user.twitch_login, "bogiesmalls")
