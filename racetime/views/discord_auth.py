"""Discord authentication and first-account creation views."""

import hashlib
import secrets
import time

from django.conf import settings
from django.contrib.auth import login
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import patch_cache_control
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from racetime import forms, models
from racetime.discord import (
    DiscordOAuthClient,
    DiscordOAuthError,
    consume_discord_callback,
    issue_discord_oauth_state,
)
from racetime.utils import determine_ip


PENDING_IDENTITY_SESSION_KEY = "discord_pending_identity"
PENDING_IDENTITY_MAX_AGE_SECONDS = 600
_RATE_SESSION_KEY = "discord_rate_session"
_RATE_LIMIT = 10
_RATE_WINDOW_SECONDS = 600
_AUTH_BACKEND = "django.contrib.auth.backends.ModelBackend"


class SyntheticEmailCollision(Exception):
    """A synthetic Discord address already belongs to an unrelated account."""


def _require_discord_auth():
    if not getattr(settings, "RT_DISCORD_AUTH_ENABLED", False):
        raise Http404


def _generic_error(request):
    return render(
        request,
        "racetime/user/discord_error.html",
        status=400,
    )


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


def _rate_counter(key, timeout):
    if cache.add(key, 1, timeout=timeout):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout)
        return 1


def _rate_limited(request, scope):
    session_marker = request.session.get(_RATE_SESSION_KEY)
    if not isinstance(session_marker, str) or not session_marker:
        session_marker = secrets.token_urlsafe(16)
        request.session[_RATE_SESSION_KEY] = session_marker

    window = int(time.time()) // _RATE_WINDOW_SECONDS
    timeout = _RATE_WINDOW_SECONDS + 1
    dimensions = (
        ("ip", determine_ip(request) or "unavailable"),
        ("session", session_marker),
    )
    blocked = False
    for dimension, value in dimensions:
        digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
        key = f"discord-auth:{scope}:{dimension}:{digest}:{window}"
        if _rate_counter(key, timeout) > _RATE_LIMIT:
            blocked = True
    return blocked


def _throttled_response():
    response = HttpResponse(
        "Too many authentication attempts. Please retry later.",
        status=429,
    )
    response["Retry-After"] = str(_RATE_WINDOW_SECONDS)
    patch_cache_control(response, no_store=True, private=True)
    return response


def _pending_identity(request):
    pending = request.session.get(PENDING_IDENTITY_SESSION_KEY)
    valid = isinstance(pending, dict)
    subject = pending.get("subject") if valid else None
    issued_at = pending.get("issued_at") if valid else None
    next_url = pending.get("next") if valid else None
    valid = (
        valid
        and isinstance(subject, str)
        and subject.isascii()
        and subject.isdecimal()
        and isinstance(issued_at, int)
        and isinstance(next_url, str)
    )
    if valid:
        age = int(time.time()) - issued_at
        valid = 0 <= age <= PENDING_IDENTITY_MAX_AGE_SECONDS
    if not valid:
        request.session.pop(PENDING_IDENTITY_SESSION_KEY, None)
        return None
    return {
        "subject": subject,
        "next": _safe_next(request, next_url),
    }


def _login_discord_user(request, user):
    if not user.is_active:
        return None
    login(request, user, backend=_AUTH_BACKEND)
    user.log_action("discord_login", request)
    return user


def _find_identity(subject, *, lock=False):
    identities = models.ExternalIdentity.objects.select_related("user")
    if lock:
        identities = identities.select_for_update()
    return identities.filter(provider="discord", subject=subject).first()


def _create_or_find_account(request, subject, name):
    try:
        with transaction.atomic():
            identity = _find_identity(subject, lock=True)
            if identity is not None:
                return identity.user

            email = f"{subject}@discord.invalid"
            if models.User.objects.select_for_update().filter(email=email).exists():
                raise SyntheticEmailCollision

            user = models.User(email=email, name=name)
            user.set_unusable_password()
            user.save()
            models.ExternalIdentity.objects.create(
                user=user,
                provider="discord",
                subject=subject,
                last_authenticated_at=timezone.now(),
            )
            user.log_action("create_account", request)
            return user
    except IntegrityError:
        identity = _find_identity(subject)
        if identity is not None:
            return identity.user
        raise


@never_cache
@require_GET
def discord_initiate(request):
    _require_discord_auth()
    if _rate_limited(request, "initiate"):
        return _throttled_response()
    try:
        state = issue_discord_oauth_state(request, request.GET.get("next", "/"))
        location = DiscordOAuthClient().authorization_url(state)
    except DiscordOAuthError:
        return _generic_error(request)
    return HttpResponseRedirect(location)


@never_cache
@require_GET
def discord_callback(request):
    _require_discord_auth()
    if _rate_limited(request, "callback"):
        return _throttled_response()
    try:
        code, next_url = consume_discord_callback(request)
        oauth_client = DiscordOAuthClient()
        access_token = oauth_client.exchange_code(code)
        discord_identity = oauth_client.fetch_identity(access_token)
    except DiscordOAuthError:
        return _generic_error(request)

    identity = _find_identity(discord_identity.subject)
    if identity is not None:
        if not identity.user.is_active:
            return _generic_error(request)
        models.ExternalIdentity.objects.filter(pk=identity.pk).update(
            last_authenticated_at=timezone.now()
        )
        _login_discord_user(request, identity.user)
        return HttpResponseRedirect(next_url)

    request.session[PENDING_IDENTITY_SESSION_KEY] = {
        "subject": discord_identity.subject,
        "issued_at": int(time.time()),
        "next": next_url,
    }
    return HttpResponseRedirect(reverse("discord_create_account"))


@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def discord_create_account(request):
    _require_discord_auth()
    if _rate_limited(request, "create"):
        return _throttled_response()
    pending = _pending_identity(request)
    if pending is None:
        return _generic_error(request)

    form = forms.DiscordDisplayNameForm(
        request.POST if request.method == "POST" else None
    )
    if request.method == "POST" and form.is_valid():
        request.session.pop(PENDING_IDENTITY_SESSION_KEY, None)
        try:
            user = _create_or_find_account(
                request,
                pending["subject"],
                form.cleaned_data["name"],
            )
        except (IntegrityError, SyntheticEmailCollision):
            return _generic_error(request)
        if _login_discord_user(request, user) is None:
            return _generic_error(request)
        return HttpResponseRedirect(pending["next"])

    return render(
        request,
        "racetime/user/discord_create_account.html",
        {"form": form},
    )
