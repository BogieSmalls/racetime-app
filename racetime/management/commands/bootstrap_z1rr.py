"""Idempotently bootstrap the Z1RR Raceroom site and sole public category."""

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from ...models import Category, ExternalIdentity, Goal


CANONICAL_DOMAIN = "raceroom.z1rracing.com"
INTEGRATION_DOMAIN = "integration.racetime.test"
ALLOWED_DOMAINS = frozenset((CANONICAL_DOMAIN, INTEGRATION_DOMAIN))
DEFAULT_SITE_NAME = "Z1RR Raceroom"
CATEGORY_SLUG = "z1rr"
CATEGORY_MANAGED_FIELDS = {
    "name": "Zelda 1 Randomizer Racing",
    "short_name": "Z1RR",
    "streaming_required": True,
    "allow_stream_override": False,
    "allow_user_races": True,
    "allow_unlisted": False,
    "unlisted_by_default": False,
    "active": True,
    "max_owners": 20,
    "max_moderators": 50,
    "max_bots": 20,
}
DEFAULT_GOAL = "Beat the game"


def _validation_message(error):
    if hasattr(error, "message_dict"):
        messages = []
        for field, field_messages in sorted(error.message_dict.items()):
            messages.extend(f"{field}: {message}" for message in field_messages)
        return " ".join(messages)
    return " ".join(error.messages)


class Command(BaseCommand):
    help = "Bootstrap the exact Z1RR Site, category, goals, and existing owners."

    def add_arguments(self, parser):
        parser.add_argument("--site-domain", required=True)
        parser.add_argument("--site-name", default=DEFAULT_SITE_NAME)
        parser.add_argument(
            "--exclusive-public-category",
            action="store_true",
            help="Deactivate every active category other than z1rr.",
        )
        parser.add_argument(
            "--owner-discord-id",
            action="append",
            default=[],
            help="Existing Discord subject to add as a category owner.",
        )
        parser.add_argument(
            "--goal",
            action="append",
            help=f"Goal to ensure; defaults to {DEFAULT_GOAL!r}.",
        )
        parser.add_argument(
            "--reconcile-managed-fields",
            action="store_true",
            help="Restore bootstrap-owned category fields to their defaults.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show changes and roll the transaction back.",
        )

    def _validate_options(self, options):
        domain = str(options["site_domain"]).strip().lower()
        if domain not in ALLOWED_DOMAINS:
            raise CommandError(
                "--site-domain must be raceroom.z1rracing.com or "
                "integration.racetime.test."
            )
        if not options["exclusive_public_category"]:
            raise CommandError(
                "--exclusive-public-category is required for Z1RR bootstrap."
            )

        site_name = str(options["site_name"]).strip()
        name_field = Site._meta.get_field("name")
        if not site_name or len(site_name) > name_field.max_length:
            raise CommandError(
                f"--site-name must contain 1-{name_field.max_length} characters."
            )

        goal_values = options.get("goal") or [DEFAULT_GOAL]
        goals = []
        seen_goals = set()
        max_goal_length = Goal._meta.get_field("name").max_length
        for value in goal_values:
            name = str(value).strip()
            if not name or len(name) > max_goal_length:
                raise CommandError(
                    f"Each --goal must contain 1-{max_goal_length} characters."
                )
            if name not in seen_goals:
                seen_goals.add(name)
                goals.append(name)

        subjects = []
        seen_subjects = set()
        for value in options.get("owner_discord_id") or []:
            try:
                _, subject = ExternalIdentity.objects.normalize("discord", value)
            except ValidationError as error:
                raise CommandError(_validation_message(error)) from None
            if subject not in seen_subjects:
                seen_subjects.add(subject)
                subjects.append(subject)
        return domain, site_name, goals, subjects

    def handle(self, *args, **options):
        domain, site_name, goal_names, owner_subjects = self._validate_options(
            options
        )
        changes = []
        try:
            with transaction.atomic():
                owners = []
                for subject in owner_subjects:
                    try:
                        identity = (
                            ExternalIdentity.objects.select_for_update()
                            .select_related("user")
                            .get(provider="discord", subject=subject)
                        )
                    except ExternalIdentity.DoesNotExist:
                        raise CommandError(
                            "Every --owner-discord-id must resolve to an existing identity."
                        ) from None
                    if not identity.user.is_active:
                        raise CommandError(
                            "Every requested category owner must be an active user."
                        )
                    owners.append(identity.user)

                site, site_created = Site.objects.select_for_update().get_or_create(
                    pk=settings.SITE_ID,
                    defaults={"domain": domain, "name": site_name},
                )
                if site_created:
                    changes.append("Created Site identity")
                else:
                    site_fields = []
                    if site.domain != domain:
                        site.domain = domain
                        site_fields.append("domain")
                    if site.name != site_name:
                        site.name = site_name
                        site_fields.append("name")
                    if site_fields:
                        site.full_clean()
                        site.save(update_fields=tuple(site_fields))
                        changes.append("Updated Site identity")

                try:
                    category = Category.objects.select_for_update().get(
                        slug=CATEGORY_SLUG
                    )
                except Category.DoesNotExist:
                    category = Category(
                        slug=CATEGORY_SLUG,
                        **CATEGORY_MANAGED_FIELDS,
                    )
                    category.full_clean()
                    category.save()
                    changes.append("Created category z1rr")
                else:
                    category_fields = []
                    if not category.active:
                        category.active = True
                        category_fields.append("active")
                    if options["reconcile_managed_fields"]:
                        for field, desired in CATEGORY_MANAGED_FIELDS.items():
                            if getattr(category, field) != desired:
                                setattr(category, field, desired)
                                if field not in category_fields:
                                    category_fields.append(field)
                    if category_fields:
                        category.full_clean()
                        category.save(update_fields=tuple(category_fields) + ("updated_at",))
                        changes.append("Reconciled category z1rr")

                other_categories = list(
                    Category.objects.select_for_update()
                    .filter(active=True)
                    .exclude(pk=category.pk)
                    .order_by("pk")
                )
                if other_categories:
                    Category.objects.filter(
                        pk__in=[item.pk for item in other_categories]
                    ).update(active=False)
                    changes.append(
                        f"Deactivated {len(other_categories)} other active category(s)"
                    )

                existing_owner_ids = set(
                    category.owners.values_list("pk", flat=True)
                )
                missing_owners = [
                    owner for owner in owners if owner.pk not in existing_owner_ids
                ]
                if category.owners.count() + len(missing_owners) > category.max_owners:
                    raise CommandError(
                        "Requested owners exceed the category owner ceiling; "
                        "use --reconcile-managed-fields if the ceiling drifted."
                    )
                if missing_owners:
                    category.owners.add(*missing_owners)
                    changes.append(f"Added {len(missing_owners)} category owner(s)")

                for goal_name in goal_names:
                    _, created = Goal.objects.get_or_create(
                        category=category,
                        name=goal_name,
                    )
                    if created:
                        changes.append(f"Created goal {goal_name}")

                if options["dry_run"]:
                    transaction.set_rollback(True)
        except (IntegrityError, ValidationError) as error:
            if isinstance(error, ValidationError):
                detail = _validation_message(error)
            else:
                detail = "a uniqueness constraint was violated"
            raise CommandError(f"Bootstrap validation failed: {detail}.") from None

        if not changes:
            self.stdout.write(self.style.SUCCESS("No changes; Z1RR bootstrap is current."))
            return
        prefix = "DRY RUN: " if options["dry_run"] else ""
        for change in changes:
            self.stdout.write(prefix + change)
