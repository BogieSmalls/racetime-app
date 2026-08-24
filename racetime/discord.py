"""Minimal Discord OAuth client and consume-once callback state."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re
import secrets
import time
from urllib.parse import urlencode

from django.conf import settings
from django.utils.http import url_has_allowed_host_and_scheme
import requests


DISCORD_OAUTH_SESSION_KEY = "discord_oauth_pending"
DISCORD_OAUTH_STATE_MAX_AGE_SECONDS = 600
_DISCORD_SUBJECT_PATTERN = re.compile(r"^[0-9]+$")


class DiscordOAuthError(Exception):
    """A sanitized Discord OAuth failure safe to show or log."""


class DiscordOAuthStateError(DiscordOAuthError):
    """The callback state is absent, invalid, expired, or already consumed."""


class DiscordOAuthDenied(DiscordOAuthError):
    """The resource owner denied Discord authorization."""


@dataclass(frozen=True)
class DiscordIdentity:
    subject: str


class DiscordOAuthClientContract(ABC):
    @abstractmethod
    def authorization_url(self, state: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def exchange_code(self, code: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def fetch_identity(self, access_token: str) -> DiscordIdentity:
        raise NotImplementedError


def _now_timestamp(now):
    return int(time.time() if now is None else now)


def _safe_next(request, next_url):
    if not isinstance(next_url, str) or not next_url:
        return "/"
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=True,
    ):
        return "/"
    return next_url


def issue_discord_oauth_state(request, next_url="/", *, now=None):
    state = secrets.token_urlsafe(32)
    request.session[DISCORD_OAUTH_SESSION_KEY] = {
        "state": state,
        "issued_at": _now_timestamp(now),
        "next": _safe_next(request, next_url),
    }
    return state


def consume_discord_oauth_state(request, supplied_state, *, now=None):
    pending = request.session.pop(DISCORD_OAUTH_SESSION_KEY, None)
    if not isinstance(pending, dict):
        raise DiscordOAuthStateError("Discord authorization state is unavailable.")

    expected_state = pending.get("state")
    issued_at = pending.get("issued_at")
    next_url = pending.get("next")
    if not isinstance(expected_state, str) or not isinstance(supplied_state, str):
        raise DiscordOAuthStateError("Discord authorization state is invalid.")
    if not secrets.compare_digest(expected_state, supplied_state):
        raise DiscordOAuthStateError("Discord authorization state is invalid.")
    if not isinstance(issued_at, int):
        raise DiscordOAuthStateError("Discord authorization state is invalid.")
    age = _now_timestamp(now) - issued_at
    if age < 0 or age > DISCORD_OAUTH_STATE_MAX_AGE_SECONDS:
        raise DiscordOAuthStateError("Discord authorization state has expired.")
    if not isinstance(next_url, str):
        raise DiscordOAuthStateError("Discord authorization state is invalid.")
    return _safe_next(request, next_url)


def consume_discord_callback(request, *, now=None):
    next_url = consume_discord_oauth_state(
        request,
        request.GET.get("state"),
        now=now,
    )
    if request.GET.get("error"):
        raise DiscordOAuthDenied("Discord authorization was denied.")
    code = request.GET.get("code")
    if not isinstance(code, str) or not code:
        raise DiscordOAuthError("Discord authorization code is unavailable.")
    return code, next_url


class DiscordOAuthClient(DiscordOAuthClientContract):
    def __init__(self, session=None):
        self._session = session or requests.Session()

    @staticmethod
    def _required_setting(name):
        value = getattr(settings, name, None)
        if not isinstance(value, str) or not value:
            raise DiscordOAuthError("Discord OAuth is not configured.")
        return value

    @staticmethod
    def _timeout():
        timeout = getattr(settings, "DISCORD_HTTP_TIMEOUT", (3.05, 10.0))
        if (
            not isinstance(timeout, (tuple, list))
            or len(timeout) != 2
            or not all(isinstance(value, (int, float)) and value > 0 for value in timeout)
        ):
            raise DiscordOAuthError("Discord OAuth is not configured.")
        return tuple(timeout)

    def authorization_url(self, state: str) -> str:
        if not isinstance(state, str) or not state:
            raise DiscordOAuthError("Discord authorization state is invalid.")
        return self._required_setting("DISCORD_AUTHORIZE_URL") + "?" + urlencode(
            {
                "client_id": self._required_setting("DISCORD_CLIENT_ID"),
                "redirect_uri": self._required_setting("DISCORD_REDIRECT_URI"),
                "response_type": "code",
                "scope": "identify",
                "state": state,
            }
        )

    def exchange_code(self, code: str) -> str:
        if not isinstance(code, str) or not code:
            raise DiscordOAuthError("Discord authorization code is unavailable.")
        try:
            response = self._session.post(
                self._required_setting("DISCORD_TOKEN_URL"),
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._required_setting("DISCORD_REDIRECT_URI"),
                    "client_id": self._required_setting("DISCORD_CLIENT_ID"),
                    "client_secret": self._required_setting("DISCORD_CLIENT_SECRET"),
                },
                headers={"Accept": "application/json"},
                timeout=self._timeout(),
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise DiscordOAuthError("Discord token exchange failed.") from error
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise DiscordOAuthError("Discord token response was invalid.") from error
        access_token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(access_token, str) or not access_token:
            raise DiscordOAuthError("Discord token response was invalid.")
        return access_token

    def fetch_identity(self, access_token: str) -> DiscordIdentity:
        if not isinstance(access_token, str) or not access_token:
            raise DiscordOAuthError("Discord access token is unavailable.")
        try:
            response = self._session.get(
                self._required_setting("DISCORD_USER_URL"),
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
                timeout=self._timeout(),
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise DiscordOAuthError("Discord identity request failed.") from error
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise DiscordOAuthError("Discord identity response was invalid.") from error
        subject = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(subject, str) or not _DISCORD_SUBJECT_PATTERN.fullmatch(subject):
            raise DiscordOAuthError("Discord identity response was invalid.")
        return DiscordIdentity(subject=subject)
