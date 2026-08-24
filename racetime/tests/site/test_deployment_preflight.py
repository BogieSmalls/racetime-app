import json
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from racetime import racebot
from racetime.models import Category, RaceStates


LOCMEM_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "deployment-preflight-tests",
    },
}
ACTIVE_STATES = [
    RaceStates.open.value,
    RaceStates.invitational.value,
    RaceStates.pending.value,
    RaceStates.in_progress.value,
]


@override_settings(CACHES=LOCMEM_CACHE)
class DeploymentPreflightCommandTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category = Category.objects.create(
            name="Zelda 1 Randomizer Racing",
            short_name="Z1RR",
            slug="z1rr",
            active=True,
        )

    def run_command(self, **options):
        stdout = StringIO()
        call_command("deployment_preflight", stdout=stdout, **options)
        return stdout.getvalue()

    def run_failing_command(self, **options):
        stdout = StringIO()
        with self.assertRaises(CommandError):
            call_command("deployment_preflight", stdout=stdout, **options)
        return stdout.getvalue()

    def test_healthy_authoritative_checks_pass_with_safe_json(self):
        payload = json.loads(self.run_command(json=True))

        self.assertEqual(payload["schema"], 1)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["active_race_count"], 0)
        self.assertTrue(payload["migrations_current"])
        self.assertTrue(payload["category_present"])
        self.assertTrue(payload["category_active"])
        self.assertTrue(payload["database_read_write"])
        self.assertTrue(payload["cache_round_trip"])
        self.assertFalse(payload["active_races_overridden"])
        self.assertEqual(payload["failures"], [])
        self.assertNotIn("Zelda 1 Randomizer Racing", json.dumps(payload))

    def test_queries_exact_racebot_active_states_and_refuses_any_count(self):
        self.assertEqual(racebot.ACTIVE_RACE_STATES, ACTIVE_STATES)
        queryset = mock.Mock()
        queryset.count.return_value = 2
        with mock.patch(
            "racetime.management.commands.deployment_preflight.models.Race.objects.filter",
            return_value=queryset,
        ) as race_filter:
            payload = json.loads(self.run_failing_command(json=True))

        race_filter.assert_called_once_with(state__in=ACTIVE_STATES)
        self.assertEqual(payload["active_race_count"], 2)
        self.assertIn("active_races", payload["failures"])
        serialized = json.dumps(payload)
        self.assertNotIn("race name", serialized.lower())
        self.assertNotIn("user", serialized.lower())

    def test_explicit_active_race_override_is_narrow_and_visible(self):
        queryset = mock.Mock()
        queryset.count.return_value = 1
        with mock.patch(
            "racetime.management.commands.deployment_preflight.models.Race.objects.filter",
            return_value=queryset,
        ):
            payload = json.loads(
                self.run_command(json=True, allow_active_races=True)
            )

        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["active_race_count"], 1)
        self.assertTrue(payload["active_races_overridden"])
        self.assertEqual(payload["failures"], [])

    def test_unapplied_migration_fails(self):
        executor = mock.Mock()
        executor.loader.graph.leaf_nodes.return_value = [("racetime", "9999")]
        executor.migration_plan.return_value = [object()]
        with mock.patch(
            "racetime.management.commands.deployment_preflight.MigrationExecutor",
            return_value=executor,
        ):
            payload = json.loads(self.run_failing_command(json=True))

        self.assertFalse(payload["migrations_current"])
        self.assertIn("unapplied_migrations", payload["failures"])

    def test_missing_or_inactive_z1rr_category_fails(self):
        self.category.delete()
        missing = json.loads(self.run_failing_command(json=True))
        self.assertFalse(missing["category_present"])
        self.assertFalse(missing["category_active"])
        self.assertIn("category_missing", missing["failures"])

        self.category = Category.objects.create(
            name="Inactive Z1RR",
            short_name="Z1RR",
            slug="z1rr",
            active=False,
        )
        inactive = json.loads(self.run_failing_command(json=True))
        self.assertTrue(inactive["category_present"])
        self.assertFalse(inactive["category_active"])
        self.assertIn("category_inactive", inactive["failures"])

    def test_database_unhealthy_or_read_only_fails_without_detail_leak(self):
        for result, error in (
            (False, None),
            (None, RuntimeError("password=do-not-print")),
        ):
            with self.subTest(result=result, error=type(error).__name__ if error else None):
                target = (
                    mock.patch(
                        "racetime.management.commands.deployment_preflight.Command._database_write_probe",
                        return_value=result,
                    )
                    if error is None
                    else mock.patch(
                        "racetime.management.commands.deployment_preflight.Command._database_write_probe",
                        side_effect=error,
                    )
                )
                with target:
                    output = self.run_failing_command(json=True)
                payload = json.loads(output)
                self.assertFalse(payload["database_read_write"])
                self.assertIn("database_unavailable_or_read_only", payload["failures"])
                self.assertNotIn("do-not-print", output)

    def test_cache_set_or_get_failure_fails_and_cleans_up(self):
        for operation in ("set", "get"):
            with self.subTest(operation=operation), mock.patch(
                f"racetime.management.commands.deployment_preflight.cache.{operation}",
                side_effect=RuntimeError("redis://secret@host/0"),
            ), mock.patch(
                "racetime.management.commands.deployment_preflight.cache.delete"
            ) as delete:
                output = self.run_failing_command(json=True)

            payload = json.loads(output)
            self.assertFalse(payload["cache_round_trip"])
            self.assertIn("cache_unavailable", payload["failures"])
            self.assertNotIn("secret", output)
            delete.assert_called_once()

    def test_human_output_is_bounded_and_nonzero_on_failure(self):
        self.category.active = False
        self.category.save(update_fields=["active"])

        output = self.run_failing_command()

        self.assertIn("DEPLOYMENT_PREFLIGHT=FAIL", output)
        self.assertIn("category_inactive", output)
        self.assertNotIn(self.category.name, output)
