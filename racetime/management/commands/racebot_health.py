from collections.abc import Mapping

from django.core.cache import cache
from django.core.management import BaseCommand, CommandError
from django.utils import timezone

from ... import models
from ...racebot import (
    ACTIVE_RACE_STATES,
    RACEBOT_ADOPTION_HEARTBEAT_KEY,
)


class Command(BaseCommand):
    help = "Check racebot adoption heartbeat and database reachability."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age-seconds",
            type=int,
            default=30,
            help="Maximum accepted age of the last completed adoption scan.",
        )

    def handle(self, *args, **options):
        maximum_age = options["max_age_seconds"]
        if not 5 <= maximum_age <= 300:
            raise CommandError("RACEBOT_HEALTH=FAIL invalid maximum age")

        try:
            heartbeat = cache.get(RACEBOT_ADOPTION_HEARTBEAT_KEY)
        except Exception as error:
            raise CommandError("RACEBOT_HEALTH=FAIL heartbeat unavailable") from error

        if not isinstance(heartbeat, Mapping):
            raise CommandError("RACEBOT_HEALTH=FAIL heartbeat missing")
        pid = heartbeat.get("pid")
        observed_at = heartbeat.get("observed_at")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise CommandError("RACEBOT_HEALTH=FAIL heartbeat invalid")
        try:
            age = timezone.now().timestamp() - float(observed_at)
        except (TypeError, ValueError):
            raise CommandError("RACEBOT_HEALTH=FAIL heartbeat invalid") from None
        if age < -5 or age > maximum_age:
            raise CommandError("RACEBOT_HEALTH=FAIL heartbeat stale")

        try:
            # This indexed existence query proves the authoritative database is
            # reachable without changing race state or requiring an active room.
            models.Race.objects.filter(state__in=ACTIVE_RACE_STATES).exists()
        except Exception as error:
            raise CommandError("RACEBOT_HEALTH=FAIL database unavailable") from error

        self.stdout.write(
            self.style.SUCCESS(
                f"RACEBOT_HEALTH=PASS pid={pid} adoption_age_seconds={age:.3f}"
            )
        )
