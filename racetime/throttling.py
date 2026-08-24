"""Application-level distributed throttling for public RaceTime endpoints."""

from dataclasses import dataclass
from functools import wraps
import hashlib
import hmac
import ipaddress
import logging
import secrets
import threading
import time

from django.conf import settings
from django.core.cache import cache
from django.core.checks import Error, Tags, register
from django.http import HttpResponse, JsonResponse
from django.utils.cache import patch_cache_control


logger = logging.getLogger(__name__)
SESSION_BUCKET_KEY = "racetime_throttle_session"
TRUSTED_CADDY_PROXY_CIDR = "172.30.0.2/32"
REDIS_CACHE_BACKEND = "django.core.cache.backends.redis.RedisCache"


@dataclass(frozen=True)
class RateLimit:
    dimension: str
    requests: int
    window_seconds: int


@dataclass(frozen=True)
class ThrottlePolicy:
    limits: tuple
    failure_mode: str = "closed"


@dataclass(frozen=True)
class ThrottleDecision:
    allowed: bool
    rate_limited: bool = False
    unavailable: bool = False
    degraded: bool = False
    retry_after: int = 0


POLICIES = {
    "discord_auth": ThrottlePolicy(
        limits=(
            RateLimit("ip", 10, 600),
            RateLimit("session", 10, 600),
        )
    ),
    "race_create": ThrottlePolicy(
        limits=(
            RateLimit("user", 5, 600),
            RateLimit("ip", 20, 3600),
        )
    ),
    "lookup": ThrottlePolicy(
        limits=(
            RateLimit("user", 60, 60),
            RateLimit("ip", 120, 60),
        )
    ),
    "profile_mutation": ThrottlePolicy(
        limits=(
            RateLimit("user", 10, 3600),
            RateLimit("ip", 30, 3600),
        )
    ),
    "admin_mutation": ThrottlePolicy(
        limits=(
            RateLimit("user", 60, 60),
            RateLimit("ip", 120, 60),
        )
    ),
    "chat_mutation": ThrottlePolicy(
        limits=(
            RateLimit("user", 60, 60),
            RateLimit("ip", 120, 60),
        )
    ),
    "oauth_decision": ThrottlePolicy(
        limits=(
            RateLimit("user", 30, 600),
            RateLimit("ip", 30, 600),
        )
    ),
    "in_race_transition": ThrottlePolicy(
        limits=(
            RateLimit("user", 120, 60),
            RateLimit("ip", 240, 60),
        ),
        failure_mode="emergency",
    ),
}


_emergency_counters = {}
_emergency_lock = threading.Lock()


def reset_emergency_throttles():
    with _emergency_lock:
        _emergency_counters.clear()


def _normalize_ip(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or "," in value:
        return None
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.compressed


def client_ip(request):
    """Resolve a client address while trusting only the rendered Caddy host."""
    remote = _normalize_ip(getattr(request, "META", {}).get("REMOTE_ADDR"))
    if remote is None:
        remote = "unavailable"
    trusted_proxy = getattr(settings, "RACETIME_TRUSTED_PROXY_CIDR", None)
    if trusted_proxy == TRUSTED_CADDY_PROXY_CIDR and remote == "172.30.0.2":
        forwarded = _normalize_ip(
            getattr(request, "META", {}).get("HTTP_X_FORWARDED_FOR")
        )
        if forwarded is not None:
            return forwarded
    return remote


def _session_identity(request):
    session = getattr(request, "session", None)
    if session is None:
        return "unavailable"
    marker = session.get(SESSION_BUCKET_KEY)
    if not isinstance(marker, str) or not marker:
        marker = secrets.token_urlsafe(24)
        session[SESSION_BUCKET_KEY] = marker
    return marker


def _user_identity(request):
    for attribute in ("resource_owner", "user"):
        user = getattr(request, attribute, None)
        if user is not None and getattr(user, "is_authenticated", False):
            user_id = getattr(user, "pk", None)
            if user_id is not None:
                return str(user_id)
    return "anonymous:" + _session_identity(request)


def _dimension_identity(request, dimension):
    if dimension == "ip":
        return client_ip(request)
    if dimension == "session":
        return _session_identity(request)
    if dimension == "user":
        return _user_identity(request)
    raise ValueError(f"Unsupported throttle dimension: {dimension}")


def _hmac_key():
    value = getattr(settings, "RACETIME_THROTTLE_HMAC_KEY", None)
    if not isinstance(value, (str, bytes)):
        raise ValueError("Dedicated throttle HMAC key is unavailable")
    key = value.encode("utf-8") if isinstance(value, str) else value
    if len(key) < 32:
        raise ValueError("Dedicated throttle HMAC key is invalid")
    return key


def _counter_key(policy_name, bucket, limit, identity, window):
    message = "\x00".join(
        (
            policy_name,
            str(bucket),
            limit.dimension,
            identity,
        )
    ).encode("utf-8")
    digest = hmac.new(_hmac_key(), message, hashlib.sha256).hexdigest()
    return (
        f"rt-throttle:{policy_name}:{limit.dimension}:"
        f"{digest}:{limit.window_seconds}:{window}"
    )


def _increment(backend, key, timeout):
    if backend.add(key, 1, timeout=timeout):
        return 1
    try:
        return backend.incr(key)
    except ValueError:
        if backend.add(key, 1, timeout=timeout):
            return 1
        return backend.incr(key)


def _retry_after(timestamp, window_seconds):
    remaining = window_seconds - (timestamp % window_seconds)
    return max(1, min(window_seconds, remaining))


def _evaluate_limits(request, policy_name, bucket, policy, backend, timestamp):
    exceeded = []
    for limit in policy.limits:
        window = timestamp // limit.window_seconds
        identity = _dimension_identity(request, limit.dimension)
        key = _counter_key(policy_name, bucket, limit, identity, window)
        count = _increment(backend, key, limit.window_seconds + 1)
        if count > limit.requests:
            exceeded.append(_retry_after(timestamp, limit.window_seconds))
    if exceeded:
        return ThrottleDecision(
            allowed=False,
            rate_limited=True,
            retry_after=max(exceeded),
        )
    return ThrottleDecision(allowed=True)


def _evaluate_emergency(request, policy_name, bucket, policy, timestamp):
    exceeded = []
    with _emergency_lock:
        for limit in policy.limits:
            window = timestamp // limit.window_seconds
            identity = _dimension_identity(request, limit.dimension)
            key = _counter_key(policy_name, bucket, limit, identity, window)
            counter_key = (key, limit.window_seconds, window)
            count = _emergency_counters.get(counter_key, 0) + 1
            _emergency_counters[counter_key] = count
            if count > limit.requests:
                exceeded.append(_retry_after(timestamp, limit.window_seconds))
    if exceeded:
        return ThrottleDecision(
            allowed=False,
            rate_limited=True,
            degraded=True,
            retry_after=max(exceeded),
        )
    return ThrottleDecision(allowed=True, degraded=True)


def evaluate_throttle(
    request,
    policy_name,
    *,
    bucket,
    backend=None,
    now=None,
):
    """Evaluate a named policy without exposing raw identity in cache keys."""
    if not getattr(settings, "RT_THROTTLING_ENABLED", False):
        return ThrottleDecision(allowed=True)
    try:
        policy = POLICIES[policy_name]
    except KeyError as error:
        raise ValueError(f"Unknown throttle policy: {policy_name}") from error
    backend = backend or cache
    timestamp = int(time.time() if now is None else now)
    try:
        return _evaluate_limits(
            request,
            policy_name,
            bucket,
            policy,
            backend,
            timestamp,
        )
    except Exception:
        logger.error(
            "Throttle backend unavailable for policy %s; applying %s mode",
            policy_name,
            policy.failure_mode,
        )
        if policy.failure_mode == "emergency":
            try:
                return _evaluate_emergency(
                    request,
                    policy_name,
                    bucket,
                    policy,
                    timestamp,
                )
            except Exception:
                logger.error(
                    "Emergency throttle unavailable for authoritative race action"
                )
                return ThrottleDecision(allowed=True, degraded=True)
        return ThrottleDecision(allowed=False, unavailable=True, retry_after=5)


def _wants_json(request):
    meta = getattr(request, "META", {})
    accept = meta.get("HTTP_ACCEPT", "")
    return (
        str(getattr(request, "path", "")).startswith("/o/")
        or "application/json" in accept
        or meta.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest"
    )


def throttle_response(request, decision):
    if decision.rate_limited:
        status = 429
        error = "rate_limited"
        message = "Too many requests. Please retry later."
    else:
        status = 503
        error = "temporarily_unavailable"
        message = "This action is temporarily unavailable. Please retry later."
    if _wants_json(request):
        response = JsonResponse({"error": error}, status=status)
    else:
        response = HttpResponse(message, status=status)
    response["Retry-After"] = str(max(1, decision.retry_after or 5))
    patch_cache_control(response, no_store=True, private=True)
    return response


def throttle_view(policy_name, *, bucket, methods=None):
    methods = frozenset(method.upper() for method in methods) if methods else None

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if methods is None or request.method.upper() in methods:
                decision = evaluate_throttle(
                    request,
                    policy_name,
                    bucket=bucket,
                )
                if not decision.allowed:
                    return throttle_response(request, decision)
                if decision.degraded:
                    request.racetime_throttle_degraded = True
            return view(request, *args, **kwargs)

        wrapped.racetime_throttle_policy = policy_name
        wrapped.racetime_throttle_bucket = bucket
        wrapped.racetime_throttle_methods = methods
        return wrapped

    return decorator


@register(Tags.security, deploy=True)
def check_throttle_configuration(app_configs, **kwargs):
    if not getattr(settings, "RT_THROTTLING_ENABLED", False):
        return []
    errors = []
    key = getattr(settings, "RACETIME_THROTTLE_HMAC_KEY", None)
    key_bytes = key.encode("utf-8") if isinstance(key, str) else key
    secret_key = getattr(settings, "SECRET_KEY", "")
    secret_bytes = (
        secret_key.encode("utf-8")
        if isinstance(secret_key, str)
        else secret_key
    )
    if (
        not isinstance(key_bytes, bytes)
        or len(key_bytes) < 32
        or (
            isinstance(secret_bytes, bytes)
            and hmac.compare_digest(key_bytes, secret_bytes)
        )
    ):
        errors.append(
            Error(
                "A dedicated throttle HMAC key of at least 32 bytes is required; "
                "it must not reuse SECRET_KEY.",
                id="racetime.E001",
            )
        )
    if getattr(settings, "RACETIME_TRUSTED_PROXY_CIDR", None) != TRUSTED_CADDY_PROXY_CIDR:
        errors.append(
            Error(
                "RACETIME_TRUSTED_PROXY_CIDR must be exactly 172.30.0.2/32.",
                id="racetime.E002",
            )
        )
    cache_backend = settings.CACHES.get("default", {}).get("BACKEND")
    if (
        getattr(settings, "RT_THROTTLING_REQUIRE_REDIS", False)
        and cache_backend != REDIS_CACHE_BACKEND
    ):
        errors.append(
            Error(
                "This profile requires django.core.cache.backends.redis.RedisCache.",
                id="racetime.E003",
            )
        )
    return errors
