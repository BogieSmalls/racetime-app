from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from racetime.models import (
    ExternalIdentity,
    ProfileImportCandidate,
    User,
    UserAction,
)


class ConvertUnclaimedZ1RRProfilesTests(TestCase):
    def create_placeholder(self, *, authenticated=False):
        user = User(
            email="123456789012345678@discord.invalid",
            name="Racer One",
            discriminator="1234",
            pronouns="they/them",
            twitch_id=987654321,
            twitch_login="racerone",
            twitch_name="RacerOne",
        )
        user.set_unusable_password()
        user.save()
        ExternalIdentity.objects.create(
            user=user,
            provider="discord",
            subject="123456789012345678",
            last_authenticated_at=timezone.now() if authenticated else None,
        )
        ExternalIdentity.objects.create(
            user=user,
            provider="racetimegg",
            subject="rtgg-subject",
        )
        return user

    def run_conversion(self, *, apply=False):
        stdout = StringIO()
        call_command(
            "convert_unclaimed_z1rr_profiles",
            apply=apply,
            stdout=stdout,
        )
        return stdout.getvalue()

    def test_dry_run_then_apply_replaces_only_unclaimed_placeholder(self):
        user = self.create_placeholder()

        dry_run = self.run_conversion()

        self.assertIn("DRY RUN", dry_run)
        self.assertIn("CONVERT=1", dry_run)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(ProfileImportCandidate.objects.exists())

        applied = self.run_conversion(apply=True)

        self.assertIn("APPLIED", applied)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        candidate = ProfileImportCandidate.objects.get()
        self.assertEqual(candidate.discord_subject, "123456789012345678")
        self.assertEqual(candidate.racetimegg_subject, "rtgg-subject")
        self.assertEqual(candidate.twitch_id, 987654321)

    def test_authenticated_account_is_left_unchanged(self):
        user = self.create_placeholder(authenticated=True)

        result = self.run_conversion(apply=True)

        self.assertIn("CLAIMED=1", result)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(ProfileImportCandidate.objects.exists())

    def test_unclaimed_account_with_activity_fails_closed(self):
        user = self.create_placeholder()
        UserAction.objects.create(user=user, action="unexpected_activity")

        with self.assertRaises(CommandError):
            self.run_conversion(apply=True)

        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(ProfileImportCandidate.objects.exists())
