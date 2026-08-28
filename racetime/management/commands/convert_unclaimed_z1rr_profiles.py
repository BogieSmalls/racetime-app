"""Convert never-authenticated imported users into private import candidates."""

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.management import BaseCommand, CommandError
from django.db import transaction

from ...models import Category, ExternalIdentity, ProfileImportCandidate, User


def _related_activity(user):
    for relation in user._meta.related_objects:
        if relation.related_model in {Category, ExternalIdentity}:
            continue
        accessor = relation.get_accessor_name()
        if not accessor or accessor.endswith("+") or not hasattr(user, accessor):
            continue
        try:
            related = getattr(user, accessor)
        except ObjectDoesNotExist:
            continue
        if hasattr(related, "exists"):
            exists = related.exists()
        elif hasattr(related, "all"):
            exists = related.all().exists()
        else:
            exists = related is not None
        if exists:
            return relation.related_model._meta.label

    for field in user._meta.many_to_many:
        if getattr(user, field.name).exists():
            return field.related_model._meta.label
    return None


def _normalize_exclusions(values):
    exclusions = set()
    for value in values:
        try:
            _, subject = ExternalIdentity.objects.normalize("discord", value)
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from None
        exclusions.add(subject)
    return exclusions


def _classify(exclusions):
    convert = []
    claimed = []
    excluded = []
    identities = (
        ExternalIdentity.objects.select_related("user")
        .filter(provider="discord", user__email__endswith="@discord.invalid")
        .order_by("subject")
    )
    for discord_identity in identities:
        user = discord_identity.user
        subject = discord_identity.subject
        if user.email != f"{subject}@discord.invalid":
            continue
        if subject in exclusions:
            excluded.append(subject)
            continue
        if discord_identity.last_authenticated_at is not None:
            claimed.append(subject)
            continue
        if (
            user.has_usable_password()
            or user.is_system
            or user.is_staff
            or user.is_superuser
        ):
            raise CommandError(
                f"Unclaimed Discord identity {subject} is not a safe placeholder."
            )

        linked = list(
            user.external_identities.order_by("provider").values_list(
                "provider", "subject"
            )
        )
        rtgg = [identity for identity in linked if identity[0] == "racetimegg"]
        if (
            len(linked) != 2
            or len(rtgg) != 1
            or user.twitch_id is None
        ):
            raise CommandError(
                f"Unclaimed Discord identity {subject} has unexpected links."
            )
        activity = _related_activity(user)
        if activity:
            raise CommandError(
                f"Unclaimed Discord identity {subject} has related {activity} data."
            )

        candidate = ProfileImportCandidate.objects.filter(
            discord_subject=subject
        ).first()
        if candidate is not None:
            raise CommandError(
                f"Discord identity {subject} has both a User and a candidate."
            )
        if ProfileImportCandidate.objects.filter(
            racetimegg_subject=rtgg[0][1]
        ).exists() or ProfileImportCandidate.objects.filter(
            twitch_id=user.twitch_id
        ).exists():
            raise CommandError(
                f"Discord identity {subject} conflicts with another candidate."
            )
        convert.append(
            {
                "user_id": user.pk,
                "discord_subject": subject,
                "racetimegg_subject": rtgg[0][1],
                "twitch_id": user.twitch_id,
            }
        )
    return convert, claimed, excluded


class Command(BaseCommand):
    help = (
        "Replace safely identifiable, never-authenticated imported users with "
        "private profile import candidates."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--exclude-discord-id",
            action="append",
            default=[],
        )

    def handle(self, *args, **options):
        exclusions = _normalize_exclusions(options["exclude_discord_id"])
        convert, claimed, excluded = _classify(exclusions)
        existing = ProfileImportCandidate.objects.count()
        summary = (
            f"CONVERT={len(convert)} CLAIMED={len(claimed)} "
            f"EXCLUDED={len(excluded)} EXISTING={existing}"
        )
        if not options["apply"]:
            self.stdout.write(f"DRY RUN: {summary}")
            return

        avatar_files = []
        with transaction.atomic():
            convert, claimed, excluded = _classify(exclusions)
            for item in convert:
                user = User.objects.select_for_update().get(pk=item["user_id"])
                candidate = ProfileImportCandidate.objects.create(
                    discord_subject=item["discord_subject"],
                    racetimegg_subject=item["racetimegg_subject"],
                    twitch_id=item["twitch_id"],
                )
                candidate.owned_categories.set(user.owned_categories.all())
                candidate.moderated_categories.set(user.mod_categories.all())
                if user.avatar:
                    avatar_files.append((user.avatar.storage, user.avatar.name))
                user.delete()
            for storage, name in avatar_files:
                transaction.on_commit(
                    lambda storage=storage, name=name: storage.delete(name)
                )

        self.stdout.write(self.style.SUCCESS(f"APPLIED: {summary}"))
