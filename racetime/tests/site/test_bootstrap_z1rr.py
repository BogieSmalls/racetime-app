from io import StringIO

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management import CommandError, call_command
from django.test import TestCase

from racetime.models import Bot, Category, ExternalIdentity, Goal, User


CANONICAL_DOMAIN = "racetime.z1rracing.com"
INTEGRATION_DOMAIN = "integration.racetime.test"
OWNER_SUBJECT = "123456789012345678"


class BootstrapZ1RRCommandTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            "owner@discord.invalid",
            name="Council Owner",
        )
        ExternalIdentity.objects.create(
            user=self.owner,
            provider="discord",
            subject=OWNER_SUBJECT,
        )

    def run_command(self, **overrides):
        options = {
            "site_domain": CANONICAL_DOMAIN,
            "exclusive_public_category": True,
            "owner_discord_id": [OWNER_SUBJECT],
        }
        options.update(overrides)
        stdout = StringIO()
        stderr = StringIO()
        call_command(
            "bootstrap_z1rr",
            stdout=stdout,
            stderr=stderr,
            **options,
        )
        return stdout.getvalue(), stderr.getvalue()

    def snapshot(self):
        site = Site.objects.get(pk=settings.SITE_ID)
        return {
            "site": (site.domain, site.name),
            "categories": list(
                Category.objects.order_by("slug").values_list(
                    "slug",
                    "name",
                    "short_name",
                    "active",
                    "streaming_required",
                    "allow_user_races",
                    "max_owners",
                    "max_moderators",
                    "max_bots",
                )
            ),
            "goals": list(
                Goal.objects.order_by("category__slug", "name").values_list(
                    "category__slug", "name", "active"
                )
            ),
            "owners": list(
                Category.objects.filter(slug="z1rr")
                .values_list("owners__id", flat=True)
                .order_by("owners__id")
            ),
            "users": User.objects.count(),
            "identities": ExternalIdentity.objects.count(),
            "bots": Bot.objects.count(),
        }

    def test_first_run_sets_exact_site_category_goal_owner_and_exclusivity(self):
        other = Category.objects.create(
            name="Other Public Category",
            short_name="OTHER",
            slug="other",
            active=True,
        )

        stdout, _ = self.run_command()

        site = Site.objects.get(pk=settings.SITE_ID)
        self.assertEqual(site.domain, CANONICAL_DOMAIN)
        self.assertEqual(site.name, "Z1RR RaceTime")
        category = Category.objects.get(slug="z1rr")
        self.assertEqual(category.name, "Zelda 1 Randomizer Racing")
        self.assertEqual(category.short_name, "Z1RR")
        self.assertTrue(category.active)
        self.assertTrue(category.streaming_required)
        self.assertTrue(category.allow_user_races)
        self.assertEqual(category.max_owners, 20)
        self.assertEqual(category.max_moderators, 50)
        self.assertEqual(category.max_bots, 20)
        self.assertEqual(
            list(category.owners.values_list("pk", flat=True)),
            [self.owner.pk],
        )
        goal = Goal.objects.get(category=category, name="Beat the game")
        self.assertTrue(goal.active)
        other.refresh_from_db()
        self.assertFalse(other.active)
        self.assertIn("Created category z1rr", stdout)
        self.assertNotIn(OWNER_SUBJECT, stdout)

    def test_second_identical_run_reports_no_changes_and_is_identical(self):
        self.run_command()
        first = self.snapshot()

        stdout, _ = self.run_command()

        self.assertEqual(self.snapshot(), first)
        self.assertIn("No changes", stdout)

    def test_normal_rerun_preserves_council_changes_and_reconcile_is_explicit(self):
        self.run_command()
        category = Category.objects.get(slug="z1rr")
        category.name = "Council Display Name"
        category.short_name = "CUSTOM"
        category.info = "Council-maintained category text"
        category.max_bots = 99
        category.allow_user_races = False
        category.save()
        custom_goal = Goal.objects.create(category=category, name="Council Goal")
        second_owner = User.objects.create_user(
            "second-owner@discord.invalid",
            name="Second Council Owner",
        )
        category.owners.add(second_owner)

        self.run_command()
        category.refresh_from_db()
        self.assertEqual(category.name, "Council Display Name")
        self.assertEqual(category.short_name, "CUSTOM")
        self.assertEqual(category.info, "Council-maintained category text")
        self.assertEqual(category.max_bots, 99)
        self.assertFalse(category.allow_user_races)
        self.assertTrue(Goal.objects.filter(pk=custom_goal.pk).exists())
        self.assertTrue(category.owners.filter(pk=second_owner.pk).exists())

        self.run_command(reconcile_managed_fields=True)
        category.refresh_from_db()
        self.assertEqual(category.name, "Zelda 1 Randomizer Racing")
        self.assertEqual(category.short_name, "Z1RR")
        self.assertEqual(category.info, "Council-maintained category text")
        self.assertEqual(category.max_bots, 20)
        self.assertTrue(category.allow_user_races)
        self.assertTrue(Goal.objects.filter(pk=custom_goal.pk).exists())
        self.assertTrue(category.owners.filter(pk=second_owner.pk).exists())

    def test_canonical_bootstrap_requires_exclusive_flag_before_mutation(self):
        conflict = Category.objects.create(
            name="Existing Public Category",
            short_name="EXISTING",
            slug="existing",
            active=True,
        )
        before = self.snapshot()

        with self.assertRaisesMessage(CommandError, "exclusive-public-category"):
            self.run_command(exclusive_public_category=False)

        self.assertEqual(self.snapshot(), before)
        conflict.refresh_from_db()
        self.assertTrue(conflict.active)
        self.assertFalse(Category.objects.filter(slug="z1rr").exists())

    def test_dry_run_reports_exact_plan_and_rolls_everything_back(self):
        Category.objects.create(
            name="Disposable Public Category",
            short_name="TEMP",
            slug="temporary",
            active=True,
        )
        before = self.snapshot()

        stdout, _ = self.run_command(
            site_domain=INTEGRATION_DOMAIN,
            site_name="Z1RR RaceTime Integration",
            dry_run=True,
        )

        self.assertEqual(self.snapshot(), before)
        self.assertIn("DRY RUN", stdout)
        self.assertIn("Created category z1rr", stdout)
        self.assertNotIn(OWNER_SUBJECT, stdout)

    def test_missing_or_invalid_owner_identity_fails_without_creating_accounts(self):
        before = self.snapshot()
        for owner_ids in (["999999999999999999"], ["not-a-discord-id"]):
            with self.subTest(owner_ids=owner_ids), self.assertRaises(CommandError):
                self.run_command(owner_discord_id=owner_ids)
            self.assertEqual(self.snapshot(), before)

    def test_only_canonical_and_isolated_integration_domains_are_accepted(self):
        before = self.snapshot()
        for domain in (
            "staging.racetime.z1rracing.com",
            "racetime.example.com",
            "localhost",
        ):
            with self.subTest(domain=domain), self.assertRaisesMessage(
                CommandError, "site-domain"
            ):
                self.run_command(site_domain=domain)
            self.assertEqual(self.snapshot(), before)

    def test_goals_are_additive_validated_and_never_remove_existing_goals(self):
        self.run_command(goal=["Beat the game", "Exploratory Flags"])
        category = Category.objects.get(slug="z1rr")
        Goal.objects.create(category=category, name="Council Added Goal")

        self.run_command(goal=["Beat the game"])

        self.assertEqual(
            set(category.goal_set.values_list("name", flat=True)),
            {"Beat the game", "Exploratory Flags", "Council Added Goal"},
        )
        before = self.snapshot()
        for goals in ([""], ["x" * 101]):
            with self.subTest(goals=goals), self.assertRaises(CommandError):
                self.run_command(goal=goals)
            self.assertEqual(self.snapshot(), before)
