import json
import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from racetime.models import ExternalIdentity, ProfileImportCandidate, User


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

    def test_dry_run_then_apply_creates_private_idempotent_candidate(self):
        dry_run = self.run_import()

        self.assertIn("DRY RUN", dry_run)
        self.assertEqual(User.objects.count(), self.initial_user_count)

        applied = self.run_import(apply=True)

        self.assertIn("CREATED=1", applied)
        candidate = ProfileImportCandidate.objects.get(
            discord_subject="123456789012345678"
        )
        self.assertEqual(candidate.racetimegg_subject, "fR42gLweew3pQlm4")
        self.assertEqual(candidate.twitch_id, 987654321)
        self.assertEqual(User.objects.count(), self.initial_user_count)
        self.assertFalse(ExternalIdentity.objects.exists())

        repeated = self.run_import(apply=True)

        self.assertIn("CREATED=0", repeated)
        self.assertIn("EXISTING=1", repeated)
        self.assertEqual(User.objects.count(), self.initial_user_count)
        self.assertEqual(ProfileImportCandidate.objects.count(), 1)
