"""Discover and read public racetime.gg profiles."""

import io
import re
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import User


RTGG_ORIGIN = "https://racetime.gg"
_HEADERS = {"User-Agent": "Z1RR-Raceroom-profile-import/1"}
_PROFILE_PATH = re.compile(r"^/user/(?P<subject>[A-Za-z0-9_-]{1,128})(?:/[^/]+)?$")
_AVATAR_PATTERN = re.compile(
    r"background-image\s*:\s*url\((?:['\"])?(.+?)(?:['\"])?\)"
)
_PRONOUNS = {value for value, _label in User._meta.get_field("pronouns").choices}
_MAX_DOWNLOAD = 5 * 1024 * 1024
_MAX_AVATAR = 100 * 1024


class RTGGImportError(Exception):
    """A public racetime.gg profile could not be verified safely."""


def _rtgg_url(value, *, path_prefix):
    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError):
        raise RTGGImportError("racetime.gg returned an invalid URL.") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "racetime.gg"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not parsed.path.startswith(path_prefix)
    ):
        raise RTGGImportError("racetime.gg returned an invalid URL.")
    return value


def _twitch_login(value):
    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"twitch.tv", "www.twitch.tv"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or len(parts) != 1
    ):
        return None
    return parts[0].lower()


def _parse_profile(html, profile_url):
    parsed_url = urlsplit(_rtgg_url(profile_url, path_prefix="/user/"))
    path_match = _PROFILE_PATH.fullmatch(parsed_url.path)
    if path_match is None:
        raise RTGGImportError("racetime.gg returned an invalid profile URL.")

    root = BeautifulSoup(html, "html.parser").select_one("div.user-profile")
    if root is None:
        raise RTGGImportError("Unable to read the public racetime.gg profile.")

    name_node = root.select_one(".name")
    scrim_node = root.select_one(".scrim")
    twitch_node = root.select_one("a.twitch-channel[href]")
    name = name_node.get_text(strip=True) if name_node is not None else ""
    discriminator = (
        scrim_node.get_text(strip=True).removeprefix("#")
        if scrim_node is not None
        else ""
    )
    twitch_login = (
        _twitch_login(twitch_node.get("href")) if twitch_node is not None else None
    )
    try:
        User._meta.get_field("name").clean(name, None)
        User._meta.get_field("discriminator").clean(discriminator, None)
    except ValidationError:
        raise RTGGImportError("racetime.gg returned an invalid display identity.")

    pronouns_node = root.select_one(".pronouns")
    pronouns = None
    if pronouns_node is not None:
        pronouns = re.sub(r"\s*/\s*", "/", pronouns_node.get_text(strip=True))
        if pronouns not in _PRONOUNS:
            raise RTGGImportError("racetime.gg returned unsupported pronouns.")

    bio_node = root.select_one(".bio")
    bio = bio_node.get_text("\n", strip=True) if bio_node is not None else None
    if bio and len(bio) > User._meta.get_field("profile_bio").max_length:
        raise RTGGImportError("The racetime.gg profile bio is too long.")

    avatar_url = None
    avatar_node = root.select_one(".avatar")
    if avatar_node is not None:
        match = _AVATAR_PATTERN.search(avatar_node.get("style", ""))
        if match:
            avatar_url = _rtgg_url(
                urljoin(profile_url, match.group(1).strip()),
                path_prefix="/media/",
            )

    return {
        "subject": path_match.group("subject"),
        "url": profile_url,
        "name": name,
        "discriminator": discriminator,
        "twitch_login": twitch_login,
        "avatar_url": avatar_url,
        "pronouns": pronouns,
        "bio": bio,
    }


def _load_profile(session, url):
    url = _rtgg_url(url, path_prefix="/user/")
    response = session.get(url, timeout=20, headers=_HEADERS)
    response.raise_for_status()
    profile_url = _rtgg_url(response.url, path_prefix="/user/")
    return _parse_profile(response.text, profile_url)


def load_profile(url, *, session=None):
    """Fetch and parse one public racetime.gg profile URL."""
    return _load_profile(session or requests.Session(), url)


def download_avatar(url, *, session=None):
    """Download and normalize a public racetime.gg avatar."""
    session = session or requests.Session()
    response = session.get(
        _rtgg_url(url, path_prefix="/media/"),
        timeout=20,
        headers=_HEADERS,
    )
    response.raise_for_status()
    _rtgg_url(response.url, path_prefix="/media/")
    if not response.headers.get("Content-Type", "").lower().startswith("image/"):
        raise RTGGImportError("The racetime.gg avatar response is not an image.")
    if len(response.content) > _MAX_DOWNLOAD:
        raise RTGGImportError("The racetime.gg avatar is too large to import.")
    try:
        with Image.open(io.BytesIO(response.content)) as source:
            if source.width * source.height > 25_000_000:
                raise RTGGImportError(
                    "The racetime.gg avatar dimensions are too large."
                )
            avatar = ImageOps.exif_transpose(source)
            avatar.thumbnail((100, 100), Image.Resampling.LANCZOS)
            if avatar.mode not in ("RGB", "RGBA"):
                avatar = avatar.convert("RGBA")
            output = io.BytesIO()
            avatar.save(output, format="PNG", optimize=True)
    except (OSError, UnidentifiedImageError):
        raise RTGGImportError(
            "The racetime.gg avatar is not a valid image."
        ) from None
    data = output.getvalue()
    if len(data) > _MAX_AVATAR:
        raise RTGGImportError(
            "The normalized racetime.gg avatar exceeds 100kb."
        )
    return data


def discover_profile(*, twitch_login, twitch_name=None, session=None):
    """Return the one public profile linked to the verified Twitch login."""
    verified_login = str(twitch_login or "").strip().lower()
    if not verified_login:
        raise RTGGImportError("Connect Twitch before importing a profile.")

    session = session or requests.Session()
    terms = []
    seen_terms = set()
    for value in (twitch_login, twitch_name):
        term = str(value or "").strip()
        if term and term.casefold() not in seen_terms:
            terms.append(term)
            seen_terms.add(term.casefold())

    candidate_urls = []
    seen_urls = set()
    for term in terms:
        response = session.get(
            RTGG_ORIGIN + "/search",
            params={"q": term},
            timeout=20,
            headers=_HEADERS,
        )
        response.raise_for_status()
        _rtgg_url(response.url, path_prefix="/search")
        for node in BeautifulSoup(response.text, "html.parser").select(
            "a.user-pop[href]"
        ):
            url = _rtgg_url(
                urljoin(RTGG_ORIGIN, node.get("href")),
                path_prefix="/user/",
            )
            if url not in seen_urls:
                candidate_urls.append(url)
                seen_urls.add(url)
            if len(candidate_urls) >= 10:
                break
        if len(candidate_urls) >= 10:
            break

    matches = {}
    for url in candidate_urls:
        profile = _load_profile(session, url)
        if profile["twitch_login"] == verified_login:
            matches[profile["subject"]] = profile
    if len(matches) > 1:
        raise RTGGImportError(
            "More than one racetime.gg profile links to this Twitch account."
        )
    return next(iter(matches.values()), None)
