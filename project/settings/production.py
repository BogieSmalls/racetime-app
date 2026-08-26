"""Fail-closed production settings for Z1RR RaceTime."""

import base64
import binascii
import os
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from . import env
from .base import *  # noqa: F403


_VARIABLES = {
    "DJANGO_SECRET_KEY",
    "RT_SITE_URI",
    "ALLOWED_HOSTS",
    "CSRF_TRUSTED_ORIGINS",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "REDIS_URL",
    "INTERNAL_HEALTH_TOKEN",
    "RACETIME_THROTTLE_HMAC_KEY",
    "RACETIME_TRUSTED_PROXY_CIDRS",
    "DISCORD_CLIENT_ID",
    "DISCORD_CLIENT_SECRET",
    "DISCORD_REDIRECT_URI",
    "TWITCH_CLIENT_ID",
    "TWITCH_CLIENT_SECRET",
    "STATIC_ROOT",
    "MEDIA_ROOT",
    "LOG_LEVEL",
    "RACETIME_ACCESS_PHASE",
    "RACETIME_BUILD_COMMIT",
}
_PREFIXES = (
    "DJANGO_",
    "RT_",
    "DB_",
    "REDIS_",
    "INTERNAL_",
    "RACETIME_",
    "DISCORD_",
    "TWITCH_",
)
_ALLOWED_ENVIRONMENT = _VARIABLES | {"DJANGO_SETTINGS_MODULE"}


def _invalid(name):
    raise ImproperlyConfigured(f"Invalid production configuration: {name}")


for _name in os.environ:
    if _name.startswith(_PREFIXES) and _name not in _ALLOWED_ENVIRONMENT:
        _invalid(_name)


DEBUG = False
SECRET_KEY = env.secret("DJANGO_SECRET_KEY", minimum=32)

INSTALLED_APPS = [  # noqa: F405
    application for application in INSTALLED_APPS
    if application != "debug_toolbar"
]
MIDDLEWARE = [  # noqa: F405
    middleware for middleware in MIDDLEWARE
    if middleware != "debug_toolbar.middleware.DebugToolbarMiddleware"
]

RT_SITE_URI = env.https_origin("RT_SITE_URI")
_site_hostname = urlsplit(RT_SITE_URI).hostname
ALLOWED_HOSTS = env.csv("ALLOWED_HOSTS", required=True)
if ALLOWED_HOSTS != [_site_hostname] or any("*" in host for host in ALLOWED_HOSTS):
    _invalid("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = [env.https_origin("CSRF_TRUSTED_ORIGINS")]
if CSRF_TRUSTED_ORIGINS != [RT_SITE_URI]:
    _invalid("CSRF_TRUSTED_ORIGINS")

RACETIME_ACCESS_PHASE = env.required("RACETIME_ACCESS_PHASE").lower()
if RACETIME_ACCESS_PHASE not in {"restricted", "public"}:
    _invalid("RACETIME_ACCESS_PHASE")

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
# Race room JavaScript reads the CSRF cookie when posting race actions.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = (
    300 if RACETIME_ACCESS_PHASE == "restricted" else 31536000
)
# These are deliberate scope decisions, not omitted hardening: this service does
# not control every z1rracing.com subdomain and must not preload the parent domain.
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
USE_X_FORWARDED_HOST = False
SILENCED_SYSTEM_CHECKS = [  # noqa: F405
    *SILENCED_SYSTEM_CHECKS,  # noqa: F405
    # LiveSplit is an RFC 8252 native client with an exact loopback callback.
    "oauth2_provider.W008",
    # HSTS intentionally neither covers sibling subdomains nor opts into preload.
    "security.W005",
    "security.W021",
]

CORS_ORIGIN_ALLOW_ALL = False
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [RT_SITE_URI]
CORS_ALLOW_CREDENTIALS = False

DB_PASSWORD = env.secret("DB_PASSWORD", minimum=16)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": env.required("DB_NAME"),
        "USER": env.required("DB_USER"),
        "PASSWORD": DB_PASSWORD,
        "HOST": env.required("DB_HOST"),
        "PORT": str(env.integer("DB_PORT", minimum=1, maximum=65535)),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "charset": "utf8mb4",
            "connect_timeout": 5,
        },
    },
}

REDIS_URL = env.required("REDIS_URL")
try:
    _redis = urlsplit(REDIS_URL)
    _redis_port = _redis.port
except (TypeError, ValueError):
    _invalid("REDIS_URL")
if (
    _redis.scheme not in {"redis", "rediss"}
    or not _redis.hostname
    or not _redis.password
    or _redis.query
    or _redis.fragment
    or _redis.hostname.endswith(".invalid")
    or _redis.path not in {f"/{number}" for number in range(16)}
    or (_redis_port is not None and not 1 <= _redis_port <= 65535)
):
    _invalid("REDIS_URL")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "z1rr-racetime-production",
        "OPTIONS": {
            "socket_connect_timeout": 2,
            "socket_timeout": 2,
        },
    },
}
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "racetime.utils.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
            "prefix": "z1rr-racetime-production-channels",
            "capacity": 100,
            "expiry": 10,
        },
    },
}

INTERNAL_HEALTH_TOKEN = env.secret("INTERNAL_HEALTH_TOKEN", minimum=32)
RACETIME_THROTTLE_HMAC_KEY = env.secret(
    "RACETIME_THROTTLE_HMAC_KEY",
    minimum=32,
)
try:
    _decoded_throttle_key = base64.b64decode(
        RACETIME_THROTTLE_HMAC_KEY,
        validate=True,
    )
except (binascii.Error, ValueError):
    _invalid("RACETIME_THROTTLE_HMAC_KEY")
if len(_decoded_throttle_key) < 32 or RACETIME_THROTTLE_HMAC_KEY == SECRET_KEY:
    _invalid("RACETIME_THROTTLE_HMAC_KEY")

RACETIME_TRUSTED_PROXY_CIDRS = env.csv(
    "RACETIME_TRUSTED_PROXY_CIDRS",
    required=True,
)
if RACETIME_TRUSTED_PROXY_CIDRS != ["172.30.0.2/32"]:
    _invalid("RACETIME_TRUSTED_PROXY_CIDRS")
RACETIME_TRUSTED_PROXY_CIDR = RACETIME_TRUSTED_PROXY_CIDRS[0]
REAL_IP_HEADER = "HTTP_X_FORWARDED_FOR"
RT_THROTTLING_ENABLED = True
RT_THROTTLING_REQUIRE_REDIS = True

RT_PUBLIC_PASSWORD_AUTH = False
RT_PUBLIC_CATEGORY_REQUESTS = False
RT_PATREON_ENABLED = False
RT_DISCORD_AUTH_ENABLED = True
RT_ENABLE_LEGACY_LIVESPLIT_PKCE_BYPASS = False
OAUTH2_PROVIDER = {  # noqa: F405
    **OAUTH2_PROVIDER,
    "PKCE_REQUIRED": True,
    "COMPLIANT_BCP_RFC9700_PKCE_METHOD": True,
    "COMPLIANT_BCP_RFC9700_IMPLICIT_GRANT": True,
    "COMPLIANT_BCP_RFC9700_PASSWORD_GRANT": True,
    "COMPLIANT_BCP_RFC9700_ACCESS_TOKEN_TRANSPORT": True,
    "COMPLIANT_BCP_RFC9700_AUTHZ_RESPONSE_ISS": True,
    "COMPLIANT_BCP_RFC9700_TOKEN_STORAGE": True,
    "REFRESH_TOKEN_REUSE_PROTECTION": True,
    "COMPLIANT_BCP_RFC9700_REFRESH_TOKEN": True,
    "ALLOW_URI_WILDCARDS": False,
    "COMPLIANT_BCP_RFC9700_REDIRECT_URI_MATCHING": True,
    "COMPLIANT_BCP_RFC9700_PKCE_REQUIRED": True,
    # HTTPS is the default; HTTP exists solely for exact RFC 8252 loopback
    # callbacks such as LiveSplit's http://127.0.0.1:4888/ URI.
    "ALLOWED_REDIRECT_URI_SCHEMES": ["https", "http"],
}

DISCORD_CLIENT_ID = env.required("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = env.secret("DISCORD_CLIENT_SECRET", minimum=32)
DISCORD_REDIRECT_URI = env.required("DISCORD_REDIRECT_URI")
if DISCORD_REDIRECT_URI != RT_SITE_URI + "/account/discord/callback":
    _invalid("DISCORD_REDIRECT_URI")
TWITCH_CLIENT_ID = env.required("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = env.secret("TWITCH_CLIENT_SECRET", minimum=30)

STATIC_ROOT = env.required("STATIC_ROOT")
MEDIA_ROOT = env.required("MEDIA_ROOT")
_static_path = PurePosixPath(STATIC_ROOT)
_media_path = PurePosixPath(MEDIA_ROOT)
if (
    not _static_path.is_absolute()
    or not _media_path.is_absolute()
    or _static_path == _media_path
):
    _invalid("STATIC_ROOT")
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750

LOG_LEVEL = env.required("LOG_LEVEL").upper()
if LOG_LEVEL not in {"INFO", "WARNING", "ERROR"}:
    _invalid("LOG_LEVEL")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact": {"()": "project.logging.RedactionFilter"},
    },
    "formatters": {
        "json": {"()": "project.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["redact"],
            "formatter": "json",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django.server": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "racebot": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
