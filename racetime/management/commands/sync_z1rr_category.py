"""Synchronize the Z1RR category image and Restream-derived role membership."""

from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import BaseCommand, CommandError
from django.db import transaction

from ...models import Category, ExternalIdentity


CATEGORY_SLUG = "z1rr"
CATEGORY_IMAGE_NAME = "category/dodongo_5horns_256x256.png"
CATEGORY_IMAGE_ASSET = (
    Path(settings.BASE_DIR)
    / "racetime"
    / "static"
    / "racetime"
    / "image"
    / "dodongo_5horns_256x256.png"
)


class Command(BaseCommand):
    help = "Set the Z1RR category image and exact Restream admin/operator roles."

    def add_arguments(self, parser):
        parser.add_argument("--owner-discord-id", action="append", default=[])
        parser.add_argument("--moderator-discord-id", action="append", default=[])
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        owner_subjects = self._subjects(options["owner_discord_id"], "owner")
        moderator_subjects = self._subjects(
            options["moderator_discord_id"], "moderator"
        )
        if not owner_subjects:
            raise CommandError("At least one --owner-discord-id is required.")
        if set(owner_subjects) & set(moderator_subjects):
            raise CommandError("An identity cannot be both owner and moderator.")

        category = Category.objects.get(slug=CATEGORY_SLUG)
        owners = self._users(owner_subjects, "owner")
        moderators = self._users(moderator_subjects, "moderator")
        if len(owners) > category.max_owners:
            raise CommandError("Restream admins exceed the category owner limit.")
        if len(moderators) > category.max_moderators:
            raise CommandError("Restream operators exceed the category moderator limit.")

        try:
            image_bytes = CATEGORY_IMAGE_ASSET.read_bytes()
        except OSError as error:
            raise CommandError("The bundled Z1RR category image is unavailable.") from error
        if len(image_bytes) > 100_000:
            raise CommandError("The bundled Z1RR category image exceeds 100 KB.")

        prefix = "APPLIED" if options["apply"] else "DRY RUN"
        if options["apply"]:
            with transaction.atomic():
                category.owners.set(owners)
                category.moderators.set(moderators)
                self._save_image(category, image_bytes)

        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}: OWNERS={len(owners)} MODERATORS={len(moderators)} "
                f"IMAGE={CATEGORY_IMAGE_NAME}"
            )
        )

    @staticmethod
    def _subjects(values, label):
        subjects = []
        seen = set()
        for value in values:
            try:
                _, subject = ExternalIdentity.objects.normalize("discord", value)
            except Exception as error:
                raise CommandError(f"Invalid {label} Discord ID.") from error
            if subject not in seen:
                seen.add(subject)
                subjects.append(subject)
        return subjects

    @staticmethod
    def _users(subjects, label):
        identities = {
            identity.subject: identity
            for identity in ExternalIdentity.objects.select_related("user").filter(
                provider="discord",
                subject__in=subjects,
            )
        }
        if set(identities) != set(subjects):
            raise CommandError(f"Every {label} Discord ID must match a RaceTime user.")
        users = [identities[subject].user for subject in subjects]
        if any(not user.active for user in users):
            raise CommandError(f"Every {label} must be an active RaceTime user.")
        return users

    @staticmethod
    def _save_image(category, image_bytes):
        current_bytes = None
        if category.image:
            try:
                with category.image.storage.open(category.image.name, "rb") as image:
                    current_bytes = image.read()
            except OSError:
                pass
        if category.image.name == CATEGORY_IMAGE_NAME and current_bytes == image_bytes:
            return

        storage = category.image.storage
        old_name = category.image.name
        if storage.exists(CATEGORY_IMAGE_NAME):
            storage.delete(CATEGORY_IMAGE_NAME)
        saved_name = storage.save(CATEGORY_IMAGE_NAME, ContentFile(image_bytes))
        if saved_name != CATEGORY_IMAGE_NAME:
            raise CommandError("Could not store the category image at its exact path.")
        category.image.name = saved_name
        category.save(update_fields=("image", "updated_at"))
        if old_name and old_name != saved_name and storage.exists(old_name):
            storage.delete(old_name)
