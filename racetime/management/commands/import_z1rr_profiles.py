"""Import claimable Z1RR racer profiles from a prepared exact-match file."""

import json

from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, CommandError
from django.db import transaction

from ...models import ExternalIdentity, ProfileImportCandidate, User


def _required_text(profile, field, *, maximum=None):
    value = profile.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"{field} must be a non-empty string.")
    value = value.strip()
    if maximum is not None and len(value) > maximum:
        raise CommandError(f"{field} exceeds {maximum} characters.")
    return value


def _normalize_profile(raw):
    if not isinstance(raw, dict):
        raise CommandError("Every profile must be a JSON object.")
    try:
        _, discord_id = ExternalIdentity.objects.normalize(
            "discord", _required_text(raw, "discord_id")
        )
        _, rtgg_id = ExternalIdentity.objects.normalize(
            "racetimegg", _required_text(raw, "rtgg_id")
        )
    except ValidationError as error:
        raise CommandError(" ".join(error.messages)) from None

    twitch_id = raw.get("twitch_id")
    if isinstance(twitch_id, bool) or not isinstance(twitch_id, int) or twitch_id <= 0:
        raise CommandError("twitch_id must be a positive integer.")
    aliases = raw.get("twitch_aliases")
    if not isinstance(aliases, list) or not aliases:
        raise CommandError("twitch_aliases must be a non-empty list.")
    normalized_aliases = []
    for alias in aliases:
        if not isinstance(alias, str) or not alias.strip():
            raise CommandError("Every Twitch alias must be a non-empty string.")
        normalized_aliases.append(alias.strip().lower())

    profile = {
        "discord_id": discord_id,
        "rtgg_id": rtgg_id,
        "name": _required_text(raw, "name", maximum=25),
        "discriminator": _required_text(raw, "discriminator", maximum=4),
        "pronouns": raw.get("pronouns") or None,
        "twitch_id": twitch_id,
        "twitch_login": _required_text(raw, "twitch_login", maximum=25).lower(),
        "twitch_name": _required_text(raw, "twitch_name", maximum=25),
        "twitch_aliases": sorted(set(normalized_aliases)),
    }
    if profile["twitch_login"] not in profile["twitch_aliases"]:
        raise CommandError("twitch_aliases must contain twitch_login.")

    candidate = User(
        email=f"{discord_id}@discord.invalid",
        name=profile["name"],
        discriminator=profile["discriminator"],
        pronouns=profile["pronouns"],
        twitch_id=profile["twitch_id"],
        twitch_login=profile["twitch_login"],
        twitch_name=profile["twitch_name"],
    )
    candidate.set_unusable_password()
    try:
        candidate.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as error:
        raise CommandError("Profile data is invalid.") from None
    return profile


def _load_profiles(path):
    try:
        with open(path, encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise CommandError("Unable to read the profile import file.") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
        raise CommandError("The import file must contain a profiles array.")
    profiles = [_normalize_profile(raw) for raw in payload["profiles"]]
    if not profiles:
        raise CommandError("The import file contains no profiles.")
    for field in ("discord_id", "rtgg_id", "twitch_id"):
        values = [profile[field] for profile in profiles]
        if len(values) != len(set(values)):
            raise CommandError(f"The import file contains duplicate {field} values.")
    return profiles


def _classify(profiles):
    classifications = []
    for profile in profiles:
        discord_identity = (
            ExternalIdentity.objects.select_related("user")
            .filter(provider="discord", subject=profile["discord_id"])
            .first()
        )
        if discord_identity is not None:
            user = discord_identity.user
            rtgg_identity = ExternalIdentity.objects.filter(
                user=user, provider="racetimegg"
            ).first()
            if (
                rtgg_identity is None
                or rtgg_identity.subject != profile["rtgg_id"]
                or user.twitch_id != profile["twitch_id"]
            ):
                raise CommandError("An existing Discord profile conflicts with the import.")
            classifications.append(("existing", profile))
            continue

        candidate = ProfileImportCandidate.objects.filter(
            discord_subject=profile["discord_id"],
        ).first()
        if candidate is not None:
            if (
                candidate.racetimegg_subject != profile["rtgg_id"]
                or candidate.twitch_id != profile["twitch_id"]
            ):
                raise CommandError(
                    "An existing private candidate conflicts with the import."
                )
            classifications.append(("existing", profile))
            continue

        if ProfileImportCandidate.objects.filter(
            racetimegg_subject=profile["rtgg_id"],
        ).exists() or ProfileImportCandidate.objects.filter(
            twitch_id=profile["twitch_id"],
        ).exists():
            raise CommandError("A private candidate conflicts with the import.")
        if ExternalIdentity.objects.filter(
            provider="racetimegg", subject=profile["rtgg_id"]
        ).exists():
            raise CommandError("An RT.gg identity is already linked to another profile.")
        if User.objects.filter(twitch_id=profile["twitch_id"]).exists():
            raise CommandError("A Twitch identity is already linked to another profile.")
        if User.objects.filter(
            email=f"{profile['discord_id']}@discord.invalid"
        ).exists():
            raise CommandError("A synthetic Discord email already exists without its identity.")
        classifications.append(("create", profile))
    return classifications


class Command(BaseCommand):
    help = "Import exact-matched Z1RR profiles; dry-run unless --apply is supplied."

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        profiles = _load_profiles(options["input"])
        classifications = _classify(profiles)
        created = sum(kind == "create" for kind, _ in classifications)
        existing = len(classifications) - created
        if not options["apply"]:
            self.stdout.write(
                f"DRY RUN: CREATED={created} EXISTING={existing} TOTAL={len(profiles)}"
            )
            return

        with transaction.atomic():
            classifications = _classify(profiles)
            for kind, profile in classifications:
                if kind == "existing":
                    continue
                ProfileImportCandidate.objects.create(
                    discord_subject=profile["discord_id"],
                    racetimegg_subject=profile["rtgg_id"],
                    twitch_id=profile["twitch_id"],
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"APPLIED: CREATED={created} EXISTING={existing} TOTAL={len(profiles)}"
            )
        )
