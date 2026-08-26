"""Fill blank Z1RR profile fields from linked public racetime.gg profiles."""

import io
import re
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from django.core.files.base import ContentFile
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from ...models import ExternalIdentity, User


_PROFILE_URL = "https://racetime.gg/user/{subject}"
_SUBJECT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_AVATAR_PATTERN = re.compile(r"background-image\s*:\s*url\((?:['\"])?(.+?)(?:['\"])?\)")
_MAX_DOWNLOAD = 5 * 1024 * 1024
_MAX_AVATAR = 100 * 1024
_PRONOUNS = {value for value, _label in User._meta.get_field("pronouns").choices}


def _rtgg_url(value, *, path_prefix):
    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError):
        raise CommandError("The RT.gg profile returned an invalid URL.") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "racetime.gg"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not parsed.path.startswith(path_prefix)
    ):
        raise CommandError("The RT.gg profile returned an invalid URL.")
    return value


def _parse_profile(html, profile_url):
    root = BeautifulSoup(html, "html.parser").select_one("div.user-profile")
    if root is None:
        raise CommandError("Unable to read an RT.gg public profile.")

    pronouns_node = root.select_one(".pronouns")
    pronouns = None
    if pronouns_node is not None:
        pronouns = re.sub(r"\s*/\s*", "/", pronouns_node.get_text(strip=True))
        if pronouns not in _PRONOUNS:
            raise CommandError("The RT.gg profile returned unsupported pronouns.")

    bio_node = root.select_one(".bio")
    bio = bio_node.get_text("\n", strip=True) if bio_node is not None else None
    if bio and len(bio) > User._meta.get_field("profile_bio").max_length:
        raise CommandError("The RT.gg profile bio is too long.")

    avatar_url = None
    avatar_node = root.select_one(".avatar")
    if avatar_node is not None:
        match = _AVATAR_PATTERN.search(avatar_node.get("style", ""))
        if match:
            avatar_url = _rtgg_url(
                urljoin(profile_url, match.group(1).strip()),
                path_prefix="/media/",
            )
    return {"avatar_url": avatar_url, "pronouns": pronouns, "bio": bio}


def _download_avatar(session, url):
    response = session.get(
        url,
        timeout=20,
        headers={"User-Agent": "Z1RR-RaceTime-profile-import/1"},
    )
    response.raise_for_status()
    _rtgg_url(response.url, path_prefix="/media/")
    if not response.headers.get("Content-Type", "").lower().startswith("image/"):
        raise CommandError("The RT.gg avatar response is not an image.")
    if len(response.content) > _MAX_DOWNLOAD:
        raise CommandError("The RT.gg avatar is too large to import.")
    try:
        with Image.open(io.BytesIO(response.content)) as source:
            if source.width * source.height > 25_000_000:
                raise CommandError("The RT.gg avatar dimensions are too large.")
            avatar = ImageOps.exif_transpose(source)
            avatar.thumbnail((100, 100), Image.Resampling.LANCZOS)
            if avatar.mode not in ("RGB", "RGBA"):
                avatar = avatar.convert("RGBA")
            output = io.BytesIO()
            avatar.save(output, format="PNG", optimize=True)
    except (OSError, UnidentifiedImageError):
        raise CommandError("The RT.gg avatar is not a valid image.") from None
    data = output.getvalue()
    if len(data) > _MAX_AVATAR:
        raise CommandError("The normalized RT.gg avatar exceeds 100kb.")
    return data


class Command(BaseCommand):
    help = "Fill blank avatar, pronouns, and bio fields from linked RT.gg profiles."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        identities = list(
            ExternalIdentity.objects.filter(
                provider="racetimegg",
                user__external_identities__provider="discord",
            )
            .select_related("user")
            .order_by("user_id")
        )
        session = requests.Session()
        prepared = []
        unchanged = 0
        counts = {"avatar": 0, "pronouns": 0, "bio": 0}

        for identity in identities:
            user = identity.user
            needed = {
                "avatar": not bool(user.avatar),
                "pronouns": not bool(user.pronouns),
                "bio": not bool(user.profile_bio),
            }
            if not any(needed.values()):
                unchanged += 1
                continue
            if not _SUBJECT_PATTERN.fullmatch(identity.subject):
                raise CommandError("An RT.gg identity has an invalid subject.")
            response = session.get(
                _PROFILE_URL.format(subject=identity.subject),
                timeout=20,
                headers={"User-Agent": "Z1RR-RaceTime-profile-import/1"},
            )
            response.raise_for_status()
            profile_url = _rtgg_url(response.url, path_prefix="/user/")
            profile = _parse_profile(response.text, profile_url)
            changes = {}
            if needed["avatar"] and profile["avatar_url"]:
                changes["avatar"] = (
                    _download_avatar(session, profile["avatar_url"])
                    if options["apply"]
                    else None
                )
            if needed["pronouns"] and profile["pronouns"]:
                changes["pronouns"] = profile["pronouns"]
            if needed["bio"] and profile["bio"]:
                changes["bio"] = profile["bio"]
            if not changes:
                unchanged += 1
                continue
            for field in changes:
                counts[field] += 1
            prepared.append((identity, changes))

        if options["apply"]:
            with transaction.atomic():
                for identity, changes in prepared:
                    user = identity.user
                    update_fields = []
                    if "avatar" in changes and not user.avatar:
                        user.avatar.save(
                            f"rtgg-{identity.subject}.png",
                            ContentFile(changes["avatar"]),
                            save=False,
                        )
                        update_fields.append("avatar")
                    if "pronouns" in changes and not user.pronouns:
                        user.pronouns = changes["pronouns"]
                        update_fields.append("pronouns")
                    if "bio" in changes and not user.profile_bio:
                        user.profile_bio = changes["bio"]
                        update_fields.append("profile_bio")
                    if update_fields:
                        user.save(update_fields=update_fields)

        prefix = "APPLIED" if options["apply"] else "DRY RUN"
        self.stdout.write(
            f"{prefix}: USERS={len(identities)} AVATARS={counts['avatar']} "
            f"PRONOUNS={counts['pronouns']} BIOS={counts['bio']} "
            f"UNCHANGED={unchanged}"
        )
