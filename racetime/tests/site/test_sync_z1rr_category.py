from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from racetime.models import Category, ExternalIdentity, User


class SyncZ1RRCategoryCommandTests(TestCase):
    def setUp(self):
        self.owner = self.make_user("owner", "100000000000000001")
        self.moderator = self.make_user("moderator", "100000000000000002")
        self.previous_owner = self.make_user("previous", "100000000000000003")
        self.category = Category.objects.create(
            name="Zelda 1 Randomizer Racing",
            short_name="Z1RR",
            slug="z1rr",
        )
        self.category.owners.add(self.previous_owner)
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)

    def make_user(self, name, discord_id):
        user = User.objects.create_user(f"{name}@discord.invalid", name=name)
        ExternalIdentity.objects.create(
            user=user,
            provider="discord",
            subject=discord_id,
        )
        return user

    def run_command(self, *, apply=False, owners=None, moderators=None):
        stdout = StringIO()
        with override_settings(MEDIA_ROOT=self.media.name):
            call_command(
                "sync_z1rr_category",
                owner_discord_id=owners or ["100000000000000001"],
                moderator_discord_id=moderators or ["100000000000000002"],
                apply=apply,
                stdout=stdout,
            )
        return stdout.getvalue()

    def test_apply_sets_exact_restream_roles_and_dodongo_image(self):
        output = self.run_command(apply=True)

        self.category.refresh_from_db()
        self.assertEqual(list(self.category.owners.all()), [self.owner])
        self.assertEqual(list(self.category.moderators.all()), [self.moderator])
        self.assertEqual(
            self.category.image.name,
            "category/dodongo_5horns_256x256.png",
        )
        self.assertTrue((Path(self.media.name) / self.category.image.name).is_file())
        self.assertIn("APPLIED", output)

    def test_default_is_dry_run(self):
        output = self.run_command()

        self.category.refresh_from_db()
        self.assertEqual(list(self.category.owners.all()), [self.previous_owner])
        self.assertEqual(list(self.category.moderators.all()), [])
        self.assertFalse(self.category.image)
        self.assertIn("DRY RUN", output)

    def test_missing_or_inactive_identity_fails_without_changes(self):
        self.moderator.active = False
        self.moderator.save(update_fields=("active",))

        with self.assertRaises(CommandError):
            self.run_command(apply=True)

        self.category.refresh_from_db()
        self.assertEqual(list(self.category.owners.all()), [self.previous_owner])
        self.assertFalse(self.category.image)
