from datetime import timedelta
from io import StringIO
from unittest import mock

import requests
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from racetime import models
from racetime.racebot import RaceBot


LOCMEM_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "racebot-health-tests",
    },
}


@override_settings(CACHES=LOCMEM_CACHE)
class RacebotHealthTests(TestCase):
    def setUp(self):
        cache.clear()
        RaceBot.races.clear()

    def create_ready_race(self, *, bot_pid=None):
        category = models.Category.objects.create(
            name="Racebot Test",
            short_name="RBT",
            slug="racebot-test",
        )
        race = models.Race.objects.create(
            category=category,
            slug="twitch-outage",
            bot_pid=bot_pid,
        )
        for number in (1, 2):
            user = models.User.objects.create_user(
                f"racer{number}@example.invalid",
                name=f"Racer{number}",
                discriminator=f"{number:04d}",
                twitch_id=number,
                twitch_login=f"racer{number}",
                twitch_name=f"Racer{number}",
            )
            models.Entrant.objects.create(
                race=race,
                user=user,
                ready=True,
                stream_override=True,
            )
        return race

    def test_twitch_outage_does_not_block_new_race_auto_start(self):
        race = self.create_ready_race()
        bot = RaceBot(4242)

        with mock.patch(
            "racetime.racebot.requests.post",
            side_effect=requests.Timeout("Twitch unavailable"),
        ) as token_request, mock.patch(
            "racetime.racebot.requests.get"
        ) as stream_request, mock.patch(
            "racetime.racebot.notice_exception"
        ), mock.patch(
            "racetime.racebot.sleep"
        ):
            bot.handle()
            bot.races[0]["last_refresh"] = timezone.now() - timedelta(seconds=1)
            bot.handle()

        race.refresh_from_db()
        self.assertEqual(race.state, models.RaceStates.pending.value)
        self.assertIsNotNone(race.started_at)
        self.assertEqual(token_request.call_count, 1)
        self.assertEqual(token_request.call_args.kwargs["timeout"], (3.05, 5))
        stream_request.assert_not_called()

    def test_startup_releases_active_races_owned_by_reused_container_pid(self):
        race = self.create_ready_race(bot_pid=1)

        RaceBot(1)

        race.refresh_from_db()
        self.assertIsNone(race.bot_pid)

    def test_adoption_cycle_records_pid_and_time(self):
        observed_at = timezone.now()
        bot = RaceBot(4242)
        with mock.patch("racetime.racebot.timezone.now", return_value=observed_at):
            bot.record_adoption_heartbeat()

        heartbeat = cache.get("z1rr:racebot:adoption-heartbeat")
        self.assertEqual(heartbeat, {
            "pid": 4242,
            "observed_at": observed_at.timestamp(),
        })

    def test_heartbeat_cache_failure_does_not_stop_race_management(self):
        bot = RaceBot(4242)
        with mock.patch(
            "racetime.racebot.cache.set",
            side_effect=RuntimeError("cache unavailable"),
        ):
            self.assertFalse(bot.record_adoption_heartbeat())

    def test_health_command_accepts_recent_adoption_probe(self):
        bot = RaceBot(4242)
        bot.record_adoption_heartbeat()
        stdout = StringIO()
        call_command("racebot_health", max_age_seconds=30, stdout=stdout)
        self.assertIn("RACEBOT_HEALTH=PASS", stdout.getvalue())

    def test_health_command_rejects_stale_or_malformed_heartbeat(self):
        stale = timezone.now() - timedelta(seconds=31)
        invalid = (
            None,
            "not-a-mapping",
            {"pid": 0, "observed_at": timezone.now().timestamp()},
            {"pid": 12, "observed_at": "not-a-number"},
            {"pid": 12, "observed_at": stale.timestamp()},
        )
        for heartbeat in invalid:
            with self.subTest(heartbeat=heartbeat):
                cache.clear()
                if heartbeat is not None:
                    cache.set("z1rr:racebot:adoption-heartbeat", heartbeat, 60)
                with self.assertRaises(CommandError):
                    call_command("racebot_health", max_age_seconds=30)

    def test_health_command_rejects_database_failure(self):
        RaceBot(4242).record_adoption_heartbeat()
        with mock.patch(
            "racetime.management.commands.racebot_health.models.Race.objects.filter",
            side_effect=RuntimeError("database unavailable"),
        ), self.assertRaises(CommandError):
            call_command("racebot_health", max_age_seconds=30)

    def test_container_healthcheck_uses_management_probe(self):
        healthcheck = (
            __import__("pathlib").Path(__file__).resolve().parents[2]
            / ".docker" / "healthcheck"
        ).read_text(encoding="utf-8")
        self.assertIn("kill -0 1", healthcheck)
        self.assertIn(
            "python manage.py racebot_health --max-age-seconds 30",
            healthcheck,
        )
