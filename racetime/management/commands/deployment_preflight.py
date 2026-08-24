"""Authoritative, secret-safe deployment readiness checks."""

import json
import secrets

from django.core.cache import cache
from django.core.management import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import F

from ... import models
from ...racebot import ACTIVE_RACE_STATES


class Command(BaseCommand):
    help = "Refuse deployment unless authoritative application checks pass."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit a bounded JSON result for deployment automation.",
        )
        parser.add_argument(
            "--allow-active-races",
            action="store_true",
            help=(
                "Permit only the active-race check to be overridden by the "
                "outer emergency deployment workflow."
            ),
        )

    def _migrations_current(self):
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        return not executor.migration_plan(targets)

    def _database_write_probe(self, category_id):
        """Prove write access without committing an application mutation."""
        with transaction.atomic():
            updated = models.Category.objects.filter(pk=category_id).update(
                active=F("active")
            )
            transaction.set_rollback(True)
        return updated == 1

    def _cache_round_trip(self):
        nonce = secrets.token_urlsafe(24)
        key = f"z1rr:deployment-preflight:{nonce}"
        try:
            cache.set(key, nonce, timeout=10)
            return secrets.compare_digest(str(cache.get(key)), nonce)
        except Exception:
            return False
        finally:
            try:
                cache.delete(key)
            except Exception:
                pass

    def handle(self, *args, **options):
        result = {
            "schema": 1,
            "status": "fail",
            "active_race_count": None,
            "active_races_overridden": False,
            "migrations_current": False,
            "category_present": False,
            "category_active": False,
            "database_read_write": False,
            "cache_round_trip": False,
            "failures": [],
        }

        try:
            result["active_race_count"] = models.Race.objects.filter(
                state__in=ACTIVE_RACE_STATES
            ).count()
        except Exception:
            result["failures"].append("race_query_unavailable")

        active_count = result["active_race_count"]
        if active_count:
            if options["allow_active_races"]:
                result["active_races_overridden"] = True
            else:
                result["failures"].append("active_races")

        category = None
        try:
            category = (
                models.Category.objects.filter(slug="z1rr")
                .only("id", "active")
                .first()
            )
            result["category_present"] = category is not None
            result["category_active"] = bool(category and category.active)
        except Exception:
            result["failures"].append("category_query_unavailable")

        if category is None:
            if "category_query_unavailable" not in result["failures"]:
                result["failures"].append("category_missing")
        elif not category.active:
            result["failures"].append("category_inactive")

        try:
            result["migrations_current"] = self._migrations_current()
        except Exception:
            result["migrations_current"] = False
        if not result["migrations_current"]:
            result["failures"].append("unapplied_migrations")

        if category is not None:
            try:
                result["database_read_write"] = bool(
                    self._database_write_probe(category.pk)
                )
            except Exception:
                result["database_read_write"] = False
        if not result["database_read_write"]:
            result["failures"].append("database_unavailable_or_read_only")

        result["cache_round_trip"] = self._cache_round_trip()
        if not result["cache_round_trip"]:
            result["failures"].append("cache_unavailable")

        result["status"] = "pass" if not result["failures"] else "fail"
        if options["json"]:
            self.stdout.write(json.dumps(result, sort_keys=True))
        else:
            suffix = ""
            if result["failures"]:
                suffix = " failures=" + ",".join(result["failures"])
            self.stdout.write(
                f"DEPLOYMENT_PREFLIGHT={result['status'].upper()}{suffix}"
            )

        if result["status"] != "pass":
            raise CommandError("DEPLOYMENT_PREFLIGHT=FAIL")
