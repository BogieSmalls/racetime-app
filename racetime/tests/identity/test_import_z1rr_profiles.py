import json
import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from racetime.models import ExternalIdentity, User


class ImportZ1RRProfilesTests(TestCase):
    profile = {
        "discord_id": "123456789012345678",
        "rtgg_id": "fR42gLweew3pQlm4",
        "name": "Racer One",
        "discriminator": "1234",
        "pronouns": "they/them",
        "twitch_id": 987654321,
        "twitch_login": "racerone",
        "twitch_name": "RacerOne",
        "twitch_aliases": ["racerone", "racer_one_old"],
    }

    def setUp(self):
        self.initial_user_count = User.objects.count()

    def run_import(self, *, apply=False):
        handle, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as output:
                json.dump({"profiles": [self.profile]}, output)
            stdout = StringIO()
            call_command(
                "import_z1rr_profiles",
                input=path,
                apply=apply,
                stdout=stdout,
            )
            return stdout.getvalue()
        finally:
            os.unlink(path)

    def test_dry_run_then_apply_creates_claimable_idempotent_profile(self):
        dry_run = self.run_import()

        self.assertIn("DRY RUN", dry_run)
        self.assertEqual(User.objects.count(), self.initial_user_count)

        applied = self.run_import(apply=True)

        self.assertIn("CREATED=1", applied)
        user = User.objects.get(email="123456789012345678@discord.invalid")
        self.assertEqual(user.email, "123456789012345678@discord.invalid")
        self.assertEqual(user.name, "Racer One")
        self.assertEqual(user.discriminator, "1234")
        self.assertEqual(user.pronouns, "they/them")
        self.assertEqual(user.twitch_id, 987654321)
        self.assertEqual(user.twitch_login, "racerone")
        self.assertEqual(user.twitch_name, "RacerOne")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(
            set(
                ExternalIdentity.objects.filter(user=user).values_list(
                    "provider", "subject"
                )
            ),
            {
                ("discord", "123456789012345678"),
                ("racetimegg", "fR42gLweew3pQlm4"),
            },
        )

        repeated = self.run_import(apply=True)

        self.assertIn("CREATED=0", repeated)
        self.assertIn("EXISTING=1", repeated)
        self.assertEqual(User.objects.count(), self.initial_user_count + 1)
