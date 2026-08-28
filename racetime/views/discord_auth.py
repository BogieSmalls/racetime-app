"""Discord authentication and first-account creation views."""

import time

import requests

from django.conf import settings
from django.contrib.auth import login
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
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
from racetime.rtgg import RTGGImportError, RTGG_ORIGIN, download_avatar, load_profile


PENDING_IDENTITY_SESSION_KEY = "discord_pending_identity"
PENDING_IDENTITY_MAX_AGE_SECONDS = 600
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


def _candidate_profile(candidate):
    profile = load_profile(
        f"{RTGG_ORIGIN}/user/{candidate.racetimegg_subject}"
    )
    if (
        profile["subject"] != candidate.racetimegg_subject
        or not profile["twitch_login"]
    ):
        raise RTGGImportError(
            "The matched racetime.gg profile could not be verified."
        )
    return profile


def _create_or_find_account(
    request,
    subject,
    name,
    *,
    candidate_id=None,
    profile=None,
    avatar_data=None,
):
    try:
        with transaction.atomic():
            identity = _find_identity(subject, lock=True)
            if identity is not None:
                return identity.user

            email = f"{subject}@discord.invalid"
            if models.User.objects.select_for_update().filter(email=email).exists():
                raise SyntheticEmailCollision

            candidate = None
            if profile is not None:
                candidate = (
                    models.ProfileImportCandidate.objects.select_for_update()
                    .filter(pk=candidate_id, discord_subject=subject)
                    .first()
                )
                if (
                    candidate is None
                    or candidate.racetimegg_subject != profile["subject"]
                ):
                    raise RTGGImportError(
                        "The private import candidate is no longer available."
                    )

                if (
                    models.User.objects.select_for_update()
                    .filter(twitch_id=candidate.twitch_id)
                    .exists()
                ):
                    raise RTGGImportError(
                        "That Twitch account is already linked."
                    )
            user = models.User(email=email, name=name)
            if profile is not None:
                user.discriminator = profile["discriminator"]
                user.pronouns = profile["pronouns"]
                user.profile_bio = profile["bio"]
                user.twitch_id = candidate.twitch_id
                user.twitch_login = profile["twitch_login"]
                user.twitch_name = (
                    profile.get("twitch_name") or profile["twitch_login"]
                )
            user.set_unusable_password()
            user.save()
            if avatar_data:
                user.avatar.save(
                    f"rtgg-{profile['subject']}.png",
                    ContentFile(avatar_data),
                )
            role_candidate = candidate
            if role_candidate is None:
                role_candidate = (
                    models.ProfileImportCandidate.objects.select_for_update()
                    .filter(discord_subject=subject)
                    .first()
                )
            if role_candidate is not None:
                role_candidate.apply_category_roles(user)
            models.ExternalIdentity.objects.create(
                user=user,
                provider="discord",
                subject=subject,
                last_authenticated_at=timezone.now(),
            )
            if profile is not None:
                models.ExternalIdentity.objects.create(
                    user=user,
                    provider="racetimegg",
                    subject=profile["subject"],
                )
                candidate.delete()
                user.log_action("racetimegg_import", request)
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
    pending = _pending_identity(request)
    if pending is None:
        return _generic_error(request)

    candidate = models.ProfileImportCandidate.objects.filter(
        discord_subject=pending["subject"]
    ).first()
    choice = request.POST.get("profile_choice", "fresh")
    form = forms.DiscordDisplayNameForm(
        request.POST
        if request.method == "POST" and choice != "import"
        else None
    )
    candidate_profile = None
    import_error = None
    user = None

    if request.method == "POST" and choice == "import":
        if candidate is None:
            import_error = "The private import candidate is no longer available."
        else:
            try:
                candidate_profile = _candidate_profile(candidate)
                avatar_data = (
                    download_avatar(candidate_profile["avatar_url"])
                    if candidate_profile["avatar_url"]
                    else None
                )
                user = _create_or_find_account(
                    request,
                    pending["subject"],
                    candidate_profile["name"],
                    candidate_id=candidate.pk,
                    profile=candidate_profile,
                    avatar_data=avatar_data,
                )
            except (requests.RequestException, RTGGImportError, IntegrityError):
                import_error = (
                    "The matched racetime.gg profile could not be imported "
                    "right now. You can retry or create an account without it."
                )
    elif request.method == "POST" and choice == "fresh" and form.is_valid():
        try:
            user = _create_or_find_account(
                request,
                pending["subject"],
                form.cleaned_data["name"],
            )
        except (IntegrityError, SyntheticEmailCollision):
            return _generic_error(request)
    elif request.method == "POST" and choice not in {"fresh", "import"}:
        form.add_error(None, "Choose how to create your account.")

    if user is not None:
        request.session.pop(PENDING_IDENTITY_SESSION_KEY, None)
        if _login_discord_user(request, user) is None:
            return _generic_error(request)
        return HttpResponseRedirect(pending["next"])

    if request.method == "GET" and candidate is not None:
        try:
            candidate_profile = _candidate_profile(candidate)
        except (requests.RequestException, RTGGImportError):
            import_error = (
                "Your matched racetime.gg profile could not be loaded right "
                "now. You can still create an account without importing it."
            )

    return render(
        request,
        "racetime/user/discord_create_account.html",
        {
            "form": form,
            "candidate": candidate,
            "candidate_profile": candidate_profile,
            "import_error": import_error,
        },
    )
