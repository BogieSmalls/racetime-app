import io
import os
import tempfile
from io import StringIO
from unittest import mock

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from racetime.models import ExternalIdentity, User


def _avatar_bytes():
    output = io.BytesIO()
    Image.new("RGB", (240, 120), "green").save(output, format="PNG")
    return output.getvalue()


class _Response:
    def __init__(self, *, url, text="", content=b"", content_type="text/html"):
        self.url = url
        self.text = text
        self.content = content
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        return None


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if "/media/" in url:
            return _Response(
                url=url,
                content=_avatar_bytes(),
                content_type="image/png",
            )
        return _Response(
            url="https://racetime.gg/user/rtgg-subject/racer-one",
            text="""
                <div class="user-profile">
                    <span class="avatar" style="background-image: url(https://racetime.gg/media/avatar.png)"></span>
                    <span class="pronouns">they / them</span>
                    <p class="bio">Racer bio &amp; schedule</p>
                </div>
            """,
        )


class SyncZ1RRRTGGProfilesTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.settings = override_settings(MEDIA_ROOT=self.media.name)
        self.settings.enable()
        self.user = User.objects.create_user(
            email="123456789012345678@discord.invalid",
            password=None,
            name="Racer One",
            discriminator="1234",
        )
        ExternalIdentity.objects.create(
            user=self.user,
            provider="discord",
            subject="123456789012345678",
        )
        ExternalIdentity.objects.create(
            user=self.user,
            provider="racetimegg",
            subject="rtgg-subject",
        )

    def tearDown(self):
        self.settings.disable()
        self.media.cleanup()

    def run_sync(self, session, *, apply=False):
        stdout = StringIO()
        with mock.patch(
            "racetime.management.commands.sync_z1rr_rtgg_profiles.requests.Session",
            return_value=session,
        ):
            call_command(
                "sync_z1rr_rtgg_profiles",
                apply=apply,
                stdout=stdout,
            )
        return stdout.getvalue()

    def test_dry_run_then_apply_fills_blanks_and_is_idempotent(self):
        dry_output = self.run_sync(_Session())

        self.user.refresh_from_db()
        self.assertIn("DRY RUN", dry_output)
        self.assertFalse(self.user.avatar)
        self.assertIsNone(self.user.pronouns)
        self.assertIsNone(self.user.profile_bio)

        apply_output = self.run_sync(_Session(), apply=True)

        self.user.refresh_from_db()
        self.assertIn("AVATARS=1", apply_output)
        self.assertIn("PRONOUNS=1", apply_output)
        self.assertIn("BIOS=1", apply_output)
        self.assertEqual(self.user.pronouns, "they/them")
        self.assertEqual(self.user.profile_bio, "Racer bio & schedule")
        self.assertTrue(self.user.avatar.name.startswith("rtgg-rtgg-subject"))
        self.assertLessEqual(self.user.avatar.size, 100 * 1024)
        with Image.open(self.user.avatar.path) as avatar:
            self.assertLessEqual(avatar.width, 100)
            self.assertLessEqual(avatar.height, 100)

        repeated_session = _Session()
        repeated_output = self.run_sync(repeated_session, apply=True)

        self.assertIn("UNCHANGED=1", repeated_output)
        self.assertEqual(repeated_session.calls, [])

    def test_existing_profile_fields_are_never_overwritten(self):
        self.user.pronouns = "he/him"
        self.user.profile_bio = "Locally edited bio"
        self.user.avatar.save("existing.png", ContentFile(_avatar_bytes()))
        session = _Session()

        output = self.run_sync(session, apply=True)

        self.user.refresh_from_db()
        self.assertIn("UNCHANGED=1", output)
        self.assertEqual(session.calls, [])
        self.assertEqual(self.user.pronouns, "he/him")
        self.assertEqual(self.user.profile_bio, "Locally edited bio")
        self.assertTrue(self.user.avatar.name.startswith("existing"))

    def test_rtgg_identity_without_discord_identity_is_out_of_scope(self):
        unclaimed = User.objects.create_user(
            email="other@example.invalid",
            password=None,
            name="Other Racer",
            discriminator="5678",
        )
        ExternalIdentity.objects.create(
            user=unclaimed,
            provider="racetimegg",
            subject="other-subject",
        )
        session = _Session()

        output = self.run_sync(session, apply=True)

        self.assertIn("USERS=1", output)
        self.assertEqual(len([url for url in session.calls if "/user/" in url]), 1)
        unclaimed.refresh_from_db()
        self.assertFalse(unclaimed.avatar)
        self.assertIsNone(unclaimed.pronouns)
        self.assertIsNone(unclaimed.profile_bio)
